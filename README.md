# running-proxy

Bridges the [Health Auto Export](https://www.healthyapps.dev) iOS app to a Google Sheets exercise log. Receives Apple Health workout data via webhook, deduplicates it in SQLite, and appends a row to the **Running** tab of a target spreadsheet.

## How it works

1. Health Auto Export pushes a JSON payload to the `/webhook` endpoint after each workout
2. The service filters for outdoor/indoor runs, processes the data, and writes a row to Google Sheets
3. Each workout is tracked in SQLite (PENDING → HYDRATED → SYNCED) to prevent duplicates

## Spreadsheet columns

| Col | Field | Notes |
|-----|-------|-------|
| A | Date | YYYY-MM-DD |
| B | Time | HH:MM (local time) |
| C | Temp (°C) | From Apple Watch weather |
| D | Humidity | % |
| E | Dew Point (°C) | Magnus-Tetens formula |
| F | Distance | Miles |
| G | Elapsed | HH:MM:SS |
| H | Avg Pace | min/mile |
| I | Splits | Pipe-separated per-mile paces, or elapsed if <1 mile |
| J | Elev (ft) | GPS elevation gain |
| K | Avg HR | bpm |
| L | HR Range | min-max bpm |
| M | AWL | Easy / Moderate / Hard (from workout intensity) |
| N | CR | Heart rate recovery — 1-min drop in bpm |
| O | VO2 Max | From daily Apple Watch estimate |

Splits are calculated from the GPS route embedded in the HAE payload using the Haversine formula — not from the `.gpx` files and not from the `walkingAndRunningDistance` time series (which under-reports distance).

## Running locally

```bash
SPREADSHEET_ID=<id> \
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json \
uvicorn main:app --host 0.0.0.0 --port 8000
```

Send a test payload:
```bash
python3 test_actual_payload.py
```

Run tests:
```bash
pytest tests/
```

## Deployment (Kubernetes)

K8s manifests live in a separate repo. The service requires two secrets:

```bash
kubectl create secret generic running-proxy-secrets \
  --from-literal=spreadsheet-id=<spreadsheet-id>

kubectl create secret generic google-service-account-json \
  --from-file=service-account.json=/path/to/sa.json
```

The service account needs **Editor** access to the target spreadsheet.

SQLite is stored on an NFS-backed PVC. The deployment uses `strategy: Recreate` to ensure only one pod writes to it at a time.

## Health Auto Export setup

Point the app's automation webhook at:
```
http://<loadbalancer-ip>/webhook
```
