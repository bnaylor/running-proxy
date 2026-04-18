import os
import json
import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Request, BackgroundTasks, Depends
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from models import Base, WorkoutRecord, WebhookPayload, Workout, WorkoutMetric
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./workouts.db")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/secrets/google/service-account.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID") # Must be provided via env or secret

logging.basicConfig(level=logging.INFO)
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
    service = build('sheets', 'v4', credentials=creds)
    return service

# --- Logic & Transformations ---

def parse_hk_value(val_str: str) -> float:
    """Parses strings like '62 degF' or '75 %' into floats."""
    if not val_str:
        return 0.0
    return float(val_str.split()[0])

def f_to_c(f: float) -> float:
    return (f - 32) * 5/9

def calculate_dew_point(temp_f: float, humidity_pct: float) -> float:
    """Magnus-Tetens formula for dew point."""
    if temp_f == 0 or humidity_pct == 0:
        return 0.0
    
    T = f_to_c(temp_f)
    RH = humidity_pct
    
    a = 17.625
    b = 243.04
    
    alpha = ((a * T) / (b + T)) + math.log(RH/100.0)
    Td = (b * alpha) / (a - alpha)
    
    # Convert back to Fahrenheit for the spreadsheet if needed, or leave in Celsius?
    # Usually spreadsheet is in Fahrenheit for US users.
    Td_f = (Td * 9/5) + 32
    return round(Td_f, 1)

def format_duration(seconds: float) -> str:
    return str(timedelta(seconds=round(seconds)))

def calculate_pace(duration_sec: float, distance_m: float) -> str:
    """Calculates min/mile pace."""
    if distance_m == 0:
        return "0:00"
    distance_miles = distance_m * 0.000621371
    pace_min_per_mile = (duration_sec / 60) / distance_miles
    minutes = int(pace_min_per_mile)
    seconds = int((pace_min_per_mile - minutes) * 60)
    return f"{minutes}:{seconds:02d}"

def process_workout(workout: Workout, db: Session):
    logger.info(f"Processing workout: {workout.id} ({workout.name})")
    
    # Check for existing record
    existing = db.query(WorkoutRecord).filter(WorkoutRecord.id == workout.id).first()
    if existing and existing.state == "SYNCED":
        logger.info(f"Workout {workout.id} already synced. Skipping.")
        return

    # Basic fields
    temp = 0.0
    humidity = 0.0
    avg_hr = 0.0
    recovery_hr = 0.0
    
    if workout.metadata:
        temp = parse_hk_value(workout.metadata.HKWeatherTemperature or "")
        humidity = parse_hk_value(workout.metadata.HKWeatherHumidity or "")
        avg_hr = parse_hk_value(workout.metadata.HKAverageHeartRate or "")
        recovery_hr = parse_hk_value(workout.metadata.HKHeartRateRecoveryOneMinute or "")

    dew_point = calculate_dew_point(temp, humidity)
    distance_miles = workout.totalDistance * 0.000621371
    elapsed = format_duration(workout.duration)
    avg_pace = calculate_pace(workout.duration, workout.totalDistance)
    
    # Heart Rate Range
    hr_min, hr_max = 0, 0
    if workout.metrics:
        for m in workout.metrics:
            if m.name == "heart_rate" and m.data:
                hr_values = [d.value for d in m.data]
                hr_min = min(hr_values)
                hr_max = max(hr_values)
    
    hr_range = f"{int(hr_min)}-{int(hr_max)}" if hr_min and hr_max else ""

    # Splits - Process events of type 'segment' or 'lap'
    splits_list = []
    if workout.workoutEvents:
        for e in workout.workoutEvents:
            if e.type in ["segment", "lap"] and e.duration and e.distance:
                split_pace = calculate_pace(e.duration, e.distance)
                splits_list.append(split_pace)
    
    splits_str = " | ".join(splits_list)
    
    # Prepare row data
    # | Date | Temp | Hum | DewPt | Distance | Elapsed | Pace | Splits | Avg HR | HR Range | AWL | CR | VO2 |
    row_data = [
        workout.start,          # Date / Time
        temp,                  # Temp
        humidity,              # Hum
        dew_point,             # DewPt
        round(distance_miles, 2), # Distance
        elapsed,               # Elapsed
        avg_pace,              # Avg Pace
        splits_str,            # Splits
        int(avg_hr) if avg_hr else "", # Avg HR
        hr_range,              # HR Range
        "",                    # AWL (Apple Watch Load / Effort) - might need extra mapping
        int(recovery_hr) if recovery_hr else "", # CR (Cardio Recovery)
        ""                     # VO2 (Needs lookup)
    ]

    # Sync to Sheets
    if sync_to_sheets(row_data):
        state = "SYNCED"
    else:
        state = "HYDRATED" # Failed to sync, keep for retry

    if not existing:
        new_record = WorkoutRecord(
            id=workout.id,
            name=workout.name,
            start_date=datetime.fromisoformat(workout.start.replace("Z", "+00:00")),
            end_date=datetime.fromisoformat(workout.end.replace("Z", "+00:00")),
            duration=workout.duration,
            distance=workout.totalDistance,
            state=state,
            payload=workout.dict()
        )
        db.add(new_record)
    else:
        existing.state = state
        existing.payload = workout.dict()
    
    db.commit()

def sync_to_sheets(row_data: List) -> bool:
    if not SPREADSHEET_ID:
        logger.error("SPREADSHEET_ID not set")
        return False
    
    service = get_sheets_service()
    if not service:
        return False
    
    try:
        body = {
            'values': [row_data]
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Running!A:A',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        logger.info(f"Appended row to Google Sheets: {result.get('updates').get('updatedRange')}")
        return True
    except Exception as e:
        logger.error(f"Error syncing to Google Sheets: {e}")
        return False

# --- FastAPI App ---

app = FastAPI(title="Running Proxy")

@app.on_event("startup")
def startup_event():
    init_db()

@app.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    logger.info(f"Received webhook with {len(payload.data.workouts)} workouts")
    for workout in payload.data.workouts:
        if workout.name == "Running":
            background_tasks.add_task(process_workout, workout, db)
    return {"status": "ok", "message": "Workouts queued for processing"}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
