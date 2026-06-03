import os
import json
import re
import logging
import traceback
from typing import List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from models import Base, WorkoutRecord, WebhookPayload, Workout, Metric
from transformations import (
    parse_workout_datetime,
    calculate_splits_from_route,
    calculate_hr_recovery,
    calculate_dew_point,
    format_duration,
    convert_to_miles,
    convert_to_feet,
    calculate_pace,
    get_metric_for_date,
    map_effort,
)
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./workouts.db")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/secrets/google/service-account.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Database Setup ---

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Google Sheets Service ---

def get_sheets_service():
    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        logger.error(f"Service account file not found: {GOOGLE_SERVICE_ACCOUNT_FILE}")
        return None

    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    return build('sheets', 'v4', credentials=creds)


# --- Processing ---

def process_workout(workout: Workout, all_metrics: List[Metric], db: Session):
    logger.info(f"Processing workout: {workout.id} ({workout.name})")

    existing = db.query(WorkoutRecord).filter(WorkoutRecord.id == workout.id).first()
    if existing and existing.state == "SYNCED":
        logger.info(f"Workout {workout.id} already synced. Skipping.")
        return

    # Parse timestamps with full timezone awareness
    start_dt = parse_workout_datetime(workout.start)
    end_dt = parse_workout_datetime(workout.end)

    temp_c = workout.temperature.qty if workout.temperature else 0.0
    humidity = workout.humidity.qty if workout.humidity else 0.0
    avg_hr = workout.avgHeartRate.qty if workout.avgHeartRate else 0.0

    # CR: drop from first recovery reading to reading closest to 1 min post-workout
    recovery_val = calculate_hr_recovery(workout.heartRateRecovery or [], end_dt)

    dew_point = calculate_dew_point(temp_c, humidity)
    distance_miles = convert_to_miles(workout.distance.qty, workout.distance.units) if workout.distance else 0.0
    elevation_feet = convert_to_feet(workout.elevationUp.qty, workout.elevationUp.units) if workout.elevationUp else 0.0
    elapsed = format_duration(workout.duration)
    avg_pace = calculate_pace(workout.duration, distance_miles)

    hr_min = workout.heartRate.min.qty if workout.heartRate and workout.heartRate.min else 0
    hr_max = workout.heartRate.max.qty if workout.heartRate and workout.heartRate.max else 0
    hr_range = f"{int(hr_min)}-{int(hr_max)}" if hr_min and hr_max else ""

    # GPS-based splits (more accurate than walkingAndRunningDistance)
    splits_list = calculate_splits_from_route(workout.route or [])
    # If run was <1 mile (no full splits), record elapsed as a fallback
    splits_str = " | ".join(splits_list) if splits_list else elapsed

    date_str = start_dt.strftime("%Y-%m-%d")
    time_str = start_dt.strftime("%H:%M")

    # AWL: prefer the workout's own intensity value over the daily aggregate metric
    if workout.intensity and workout.intensity.qty is not None:
        awl = map_effort(workout.intensity.qty)
    else:
        effort_val = get_metric_for_date(all_metrics, "physical_effort", start_dt)
        awl = map_effort(effort_val)

    vo2 = get_metric_for_date(all_metrics, "vo2_max", start_dt)

    # | Date | Time | Temp(C) | Hum | DewPt | Distance | Elapsed | Pace | Splits | Elev | Avg HR | HR Range | AWL | CR | VO2 |
    # Pace, splits, and elevation are prefixed with ' to prevent Google Sheets
    # from misinterpreting them as time values in time-formatted cells.
    row_data = [
        date_str,
        time_str,
        round(temp_c, 1) if temp_c else "",
        humidity if humidity else "",
        dew_point if dew_point else "",
        round(distance_miles, 2),
        elapsed,
        f"'{avg_pace}",
        f"'{splits_str}",
        f"'{int(elevation_feet)}" if elevation_feet > 0 else "",
        int(avg_hr) if avg_hr else "",
        hr_range,
        awl,
        int(recovery_val) if recovery_val > 0 else "",
        round(vo2, 1) if vo2 else "",
    ]

    if sync_to_sheets(row_data):
        state = "SYNCED"
    else:
        state = "HYDRATED"

    if not existing:
        new_record = WorkoutRecord(
            id=workout.id,
            name=workout.name,
            start_date=start_dt,
            end_date=end_dt,
            duration=workout.duration,
            distance=distance_miles,
            state=state,
            payload=workout.model_dump(),
        )
        db.add(new_record)
    else:
        existing.state = state
        existing.payload = workout.model_dump()

    db.commit()


def process_workout_bg(workout: Workout, all_metrics: List[Metric]):
    """Background task wrapper that owns its own DB session."""
    db = SessionLocal()
    try:
        process_workout(workout, all_metrics, db)
    except Exception as e:
        logger.error(f"Error processing workout {workout.id}: {e}\n{traceback.format_exc()}")
    finally:
        db.close()


def sync_to_sheets(row_data: List) -> bool:
    if not SPREADSHEET_ID:
        logger.error("SPREADSHEET_ID not set")
        return False

    service = get_sheets_service()
    if not service:
        return False

    try:
        body = {'values': [row_data]}
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Running!A:A',
            valueInputOption='USER_ENTERED',
            body=body,
        ).execute()
        logger.info(f"Appended row to Google Sheets: {result.get('updates').get('updatedRange')}")
        return True
    except Exception as e:
        logger.error(f"Error syncing to Google Sheets: {e}")
        return False


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Running Proxy", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    text = raw_body.decode("utf-8", errors="replace")
    logger.info(f"Raw payload hex: {raw_body.hex()}")
    # Health Auto Export sometimes embeds raw control characters in string fields
    # (workoutName, notes, route metadata, etc.). Python's json.loads() rejects
    # these, so strip all control chars (0x00-0x1F) before parsing.
    cleaned = re.sub(r"[\x00-\x1f]", "", text)
    try:
        payload_data = json.loads(cleaned)
    except Exception as e:
        logger.error(f"JSON parse error even after sanitization: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    try:
        payload = WebhookPayload(**payload_data)
    except Exception as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    logger.info(f"Received webhook with {len(payload.data.workouts)} workouts and {len(payload.data.metrics)} metrics")
    ACCEPTED_WORKOUT_TYPES = {"Running", "Outdoor Run", "Outdoor Walk", "Indoor Walk", "Indoor Run"}
    queued = []
    rejected = []
    for workout in payload.data.workouts:
        if workout.name in ACCEPTED_WORKOUT_TYPES:
            background_tasks.add_task(process_workout_bg, workout, payload.data.metrics)
            queued.append(workout.name)
        else:
            rejected.append(workout.name)
            logger.info(f"Skipping workout {workout.id}: unsupported type {workout.name!r}")

    return {"status": "ok", "queued": queued, "rejected": rejected}


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
