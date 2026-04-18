# Code Review: Running Proxy

**Reviewed:** 2026-04-18
**Scope:** Full assessment — requirements alignment, design, implementation correctness, gaps before real-data use

---

## TL;DR

The skeleton is solid. The data models, state machine concept, deployment manifests, and overall flow are all reasonable. But there are **three bugs that will silently produce wrong data**, one **session lifecycle issue that will cause crashes under load**, and several missing pieces the spec called out as needed before real use. None of these is a disaster, but you should fix the data-corruption bugs before pointing this at your real spreadsheet.

---

## Requirements Alignment

The spec (gemini_web_blueprint.md) called for:

| Requirement | Status |
|:---|:---|
| Receive POST webhook with Apple Health payload | ✅ Done |
| Deduplicate via SQLite (UUID check) | ✅ Done |
| Three-state machine (PENDING → HYDRATED → SYNCED) | ⚠️ Partial — see below |
| Append row to Google Sheets "Running" tab | ✅ Done |
| All 15 column mappings | ✅ Done |
| Magnus-Tetens dew point | ✅ Done |
| Retry HYDRATED workouts | ❌ Not implemented |
| Webhook auth (API key / bearer token) | ❌ Not implemented |
| `/workouts` status dashboard endpoint | ❌ Not implemented |
| Single-writer K8s deployment | ✅ Done (Recreate strategy) |
| Secrets as mounted volume | ✅ Done |

---

## Bugs — Will Produce Wrong Data

### 1. Splits calculation is almost certainly wrong (`main.py:172-183`)

```python
current_split_time += 60   # ← assumes each data point = exactly 60 seconds
```

`walkingAndRunningDistance` is a time-series of individual samples, each with a `date` field. The code ignores those dates and assumes every sample is exactly one minute long. In practice, Apple Health emits these at irregular intervals (sometimes per second, sometimes per minute depending on the watch model and export settings).

**Fix:** Use the `date` field of consecutive `DatedQuantityValue` / `MetricDataPoint` entries to compute elapsed time between samples, rather than hardcoding 60 seconds.

---

### 2. Heart Rate Recovery calculation may be wrong (`main.py:153-157`)

```python
if workout.heartRateRecovery and len(workout.heartRateRecovery) > 1:
    start_hr = workout.heartRateRecovery[0].Avg
    end_hr = workout.heartRateRecovery[-1].Avg
    recovery_val = start_hr - end_hr
```

The spec says CR = "60s post-workout sample" (a drop value). But `heartRateRecovery` is a time series starting *at workout end*, and the code takes `[0]` minus `[-1]` — which is HR at the first sample minus the last sample in that series, not necessarily a 1-minute window. If the series has more than two entries (e.g., multi-minute recovery tracking), this averages over the wrong window.

Also, if Apple Watch doesn't measure recovery on a given run, this silently returns 0, which is valid-looking data but misleading.

**Fix:** Instead of first-minus-last, find the sample closest to `workout.end + 60s` and compute `heartRateRecovery[0].Avg - that_sample.Avg`. Or simply look for the single `heartRateRecoveryOneMinute` value if it's provided directly.

---

### 3. Timezone is silently dropped (`main.py:187-189`)

```python
start_dt = datetime.strptime(workout.start[:19], "%Y-%m-%d %H:%M:%S")
```

The `start` field from Health Auto Export is `"2026-03-30 12:24:54 +0000"` (UTC). The `[:19]` slice strips the timezone offset silently. Since Apple Watch records in UTC, the Date and Time columns in your spreadsheet will be in UTC, not your local Toronto time (UTC-4/5). A run at 12:24 PM local will appear as 12:24 PM UTC in the sheet.

**Fix:** Parse the full timestamp including offset using `datetime.fromisoformat()` or `strptime` with `%z`, then convert to your local timezone before formatting `date_str` and `time_str`.

---

## Crash-Under-Load: DB Session Passed to Background Task (`main.py:282`)

```python
background_tasks.add_task(process_workout, workout, payload.data.metrics, db)
```

`db` is a request-scoped SQLAlchemy session. FastAPI's `Depends(get_db)` will close this session when the request completes — which may happen *before* the background task runs. This leads to `DetachedInstanceError` or `Session closed` errors under any real load.

**Fix:** Don't pass the session to background tasks. Instead, create a fresh session inside `process_workout`:

```python
async def process_workout_bg(workout, all_metrics):
    db = SessionLocal()
    try:
        process_workout(workout, all_metrics, db)
    finally:
        db.close()

background_tasks.add_task(process_workout_bg, workout, payload.data.metrics)
```

---

## Design Issues

### PENDING state is never used

The three-state machine is described as: PENDING (received, waiting for late samples) → HYDRATED (calculations done) → SYNCED. But the code goes directly from nothing to HYDRATED-or-SYNCED in a single pass. The record is never saved with state=PENDING first.

This matters if you ever want to handle late-arriving samples (e.g., VO2 or HR recovery that arrives in a later export). Right now, if the first payload is missing VO2, you'll just get a blank cell and the record will be SYNCED with no chance to update it.

Consider: save as PENDING immediately upon receipt, then hydrate/sync in the background task. This also gives you a meaningful "received but not yet processed" state visible in the DB.

### Sheets `append` + deduplication mismatch

The deduplication check is only in SQLite. But `sync_to_sheets` always calls `values().append()`, which adds a new row every time. If the service crashes between the Sheets write and the `db.commit()`, the workout will appear in the sheet twice on retry (SYNCED state was never saved, so it will be re-processed).

**Fix:** Either (a) check `existing.state == "SYNCED"` before calling `sync_to_sheets`, or (b) use `values().update()` to write to a specific row keyed to the workout date, or (c) accept the risk for now but document it.

### `get_sheets_service()` rebuilds credentials on every sync

The Google API client and credentials are reconstructed from disk on every call to `sync_to_sheets`. This works but is wasteful and could hit filesystem/auth latency.

**Fix:** Build the service once at startup (in `lifespan`) and store it in app state.

### `physical_effort` lookup may not find anything

`get_metric_for_date` searches the top-level `metrics` array for a metric named `"physical_effort"`. Looking at the actual HAE payload structure, `physical_effort` may be a per-workout field (like `avgHeartRate`) rather than a top-level metric. The `get_metric_for_date` function would silently return `None`, giving empty AWL for every workout. This needs verification against your real export.

---

## Code Quality Issues

### `test_webhook.py` uses the wrong payload format

`test_webhook.py` sends `totalDistance`, `distanceUnit`, `workoutEvents`, etc. — these match an older HAE format, not the `{qty, units}` Pydantic model the real code expects. Running this test will succeed (200 OK) because Pydantic just ignores the unrecognized fields (`extra='allow'`), but it won't actually exercise the transformation logic. The test is effectively a no-op for validating correctness.

**Fix:** Update `test_webhook.py` to use the same `{qty, units}` structure as the real payload, or better yet, make it use the same `example/` file that `test_actual_payload.py` uses.

### `datetime.utcnow` is deprecated (`models.py:22-23`)

```python
created_at = Column(DateTime, default=datetime.utcnow)
updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

`datetime.utcnow` is deprecated since Python 3.12. Use `lambda: datetime.now(timezone.utc)`.

### Redundant alias on `Workout.id` (`models.py:70`)

```python
id: str = Field(..., alias="id")
```

Alias equals the field name — this is a no-op. Can be `id: str`.

### Webhook returns 200 on validation failure (`main.py:285-286`)

```python
except Exception as e:
    logger.error(f"Validation error: {e}")
    return {"status": "error", "message": str(e)}
```

A bare `return` with no status code defaults to HTTP 200. Validation errors and 5xx crashes should return 4xx/5xx so the client (Health Auto Export) knows to retry. Use `raise HTTPException(status_code=422, ...)` or return a `JSONResponse(status_code=422, ...)`.

---

## Infrastructure Issues

### No `.dockerignore`

`COPY . .` will include `workouts.db`, `__pycache__/`, `.git/`, `example/` (your real workout data!) and `docs/` in the image. This is a data leak risk and bloats the image unnecessarily.

**Fix:** Add a `.dockerignore` with at minimum:
```
.git/
__pycache__/
*.db
example/
*.pyc
```

### `requirements.txt` has no version pins

All packages are unpinned (`fastapi`, `uvicorn`, etc.). This means a rebuild 6 months from now may get a breaking version.

**Fix:** After verifying things work, run `pip freeze > requirements.txt` to lock exact versions.

### PVC uses `ReadWriteOnce` with NFS

The spec says NFS-backed storage, but `ReadWriteOnce` is a block-storage access mode. NFS volumes are typically `ReadWriteMany`. With single-replica + Recreate this works fine in practice (only one pod ever exists), but if you configure it against a real NFS StorageClass, you may need `ReadWriteMany` depending on the provisioner.

The `storageClassName` is commented out — that's fine for now but needs to be set before deploying.

### No resource limits in deployment

No `resources.requests` or `resources.limits` defined. The scheduler can't make good placement decisions, and a memory leak could OOM the node.

---

## What to Fix Before Touching Real Data

Priority order:

1. **Timezone bug** — Your timestamps will be wrong. Easy fix, high impact.
2. **Background task DB session** — Will crash on real workouts. Needs a fresh session inside the task.
3. **Add `.dockerignore`** — Your example data (real workouts) will be baked into the container image.
4. **Splits time calculation** — Will produce wrong pace splits. Needs date-based time delta.
5. **HR Recovery window** — May be wrong. At minimum, verify against a real export.
6. **Webhook returns 200 on error** — Health Auto Export won't know to retry failed deliveries.

---

## What Can Wait

- PENDING state as a true "received but not processed" stage
- Retry worker for HYDRATED workouts
- `/workouts` status endpoint
- Sheets deduplication (vs SQLite-only dedup)
- Webhook auth (fine for home lab for now, but add before exposing to internet)
- Resource limits in K8s manifests
- Version-pinned requirements
- Caching the Sheets service client

---

## What's Actually Good

- Pydantic V2 models with `extra='allow'` is the right call for an external API you don't fully control
- The `get_metric_for_date` date-proximity lookup is a solid approach for VO2/effort correlation
- `Recreate` strategy with single replica is exactly right for SQLite on NFS
- Mounting the service account as a volume (not env var) is correct
- The `convert_to_miles` / `convert_to_feet` unit-handling is thorough
- `test_actual_payload.py` using a real export file is the right testing approach
