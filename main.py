import os
import json
import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks, Depends
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from models import Base, WorkoutRecord, WebhookPayload, Workout, Metric, DatedQuantityValue, MetricDataPoint
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./workouts.db")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/secrets/google/service-account.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID") 

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

def f_to_c(f: float) -> float:
    return (f - 32) * 5/9

def c_to_f(c: float) -> float:
    return (c * 9/5) + 32

def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    """Magnus-Tetens formula for dew point."""
    if temp_c == 0 or humidity_pct == 0:
        return 0.0
    
    T = temp_c
    RH = humidity_pct
    
    a = 17.625
    b = 243.04
    
    alpha = ((a * T) / (b + T)) + math.log(RH/100.0)
    Td = (b * alpha) / (a - alpha)
    
    return round(c_to_f(Td), 1)

def format_duration(seconds: float) -> str:
    return str(timedelta(seconds=round(seconds)))

def convert_to_miles(qty: float, unit: Optional[str]) -> float:
    if not unit:
        return qty
    if unit == "km":
        return qty * 0.621371
    elif unit == "m":
        return qty * 0.000621371
    elif unit == "mi":
        return qty
    return qty

def convert_to_feet(qty: float, unit: Optional[str]) -> float:
    if not unit:
        return qty
    if unit == "m":
        return qty * 3.28084
    elif unit == "km":
        return qty * 3280.84
    elif unit == "ft":
        return qty
    return qty

def calculate_pace(duration_sec: float, distance_miles: float) -> str:
    """Calculates min/mile pace."""
    if distance_miles == 0:
        return "0:00"
    pace_min_per_mile = (duration_sec / 60) / distance_miles
    minutes = int(pace_min_per_mile)
    seconds = int((pace_min_per_mile - minutes) * 60)
    return f"{minutes}:{seconds:02d}"

def get_metric_for_date(metrics: List[Metric], name: str, target_date: datetime) -> Optional[float]:
    """Finds the metric value closest to the target date."""
    best_val = None
    min_diff = timedelta(days=1)
    
    for m in metrics:
        if m.name == name:
            for d in m.data:
                try:
                    date_val = datetime.strptime(d.date[:19], "%Y-%m-%d %H:%M:%S")
                    diff = abs(target_date.replace(hour=0, minute=0, second=0, microsecond=0) - date_val)
                    if diff <= min_diff:
                        min_diff = diff
                        best_val = d.qty
                except Exception as e:
                    logger.error(f"Error parsing metric date {d.date}: {e}")
    return best_val

def map_effort(physical_effort: Optional[float]) -> str:
    """Maps physical_effort (kcal/hr/kg) to AWL labels."""
    if physical_effort is None:
        return ""
    if physical_effort < 4.0:
        return "Easy"
    elif physical_effort < 8.0:
        return "Moderate"
    else:
        return "Hard"

def process_workout(workout: Workout, all_metrics: List[Metric], db: Session):
    logger.info(f"Processing workout: {workout.id} ({workout.name})")
    
    existing = db.query(WorkoutRecord).filter(WorkoutRecord.id == workout.id).first()
    if existing and existing.state == "SYNCED":
        logger.info(f"Workout {workout.id} already synced. Skipping.")
        return

    temp_c = workout.temperature.qty if workout.temperature else 0.0
    humidity = workout.humidity.qty if workout.humidity else 0.0
    avg_hr = workout.avgHeartRate.qty if workout.avgHeartRate else 0.0
    
    recovery_val = 0
    if workout.heartRateRecovery and len(workout.heartRateRecovery) > 1:
        start_hr = workout.heartRateRecovery[0].Avg
        end_hr = workout.heartRateRecovery[-1].Avg
        recovery_val = start_hr - end_hr

    dew_point = calculate_dew_point(temp_c, humidity)
    distance_miles = convert_to_miles(workout.distance.qty, workout.distance.units) if workout.distance else 0.0
    elevation_feet = convert_to_feet(workout.elevationUp.qty, workout.elevationUp.units) if workout.elevationUp else 0.0
    elapsed = format_duration(workout.duration)
    avg_pace = calculate_pace(workout.duration, distance_miles)
    
    hr_min = workout.heartRate.min.qty if workout.heartRate and workout.heartRate.min else 0
    hr_max = workout.heartRate.max.qty if workout.heartRate and workout.heartRate.max else 0
    hr_range = f"{int(hr_min)}-{int(hr_max)}" if hr_min and hr_max else ""

    splits_list = []
    if workout.walkingAndRunningDistance:
        current_split_dist = 0.0
        current_split_time = 0.0
        for i in range(len(workout.walkingAndRunningDistance)):
            d = workout.walkingAndRunningDistance[i]
            dist_mi = convert_to_miles(d.qty, d.units)
            current_split_dist += dist_mi
            current_split_time += 60 
            if current_split_dist >= 1.0:
                splits_list.append(calculate_pace(current_split_time, current_split_dist))
                current_split_dist = 0.0
                current_split_time = 0.0
        if current_split_dist > 0.1:
            splits_list.append(calculate_pace(current_split_time, current_split_dist))
    
    splits_str = " | ".join(splits_list)
    
    start_dt = datetime.strptime(workout.start[:19], "%Y-%m-%d %H:%M:%S")
    date_str = start_dt.strftime("%Y-%m-%d")
    time_str = start_dt.strftime("%H:%M")
    
    vo2 = get_metric_for_date(all_metrics, "vo2_max", start_dt)
    effort_val = get_metric_for_date(all_metrics, "physical_effort", start_dt)
    awl = map_effort(effort_val)

    # Prepare row data
    # | Date | Time | Temp | Hum | DewPt | Distance | Elapsed | Pace | Splits | Elev | Avg HR | HR Range | AWL | CR | VO2 |
    row_data = [
        date_str,
        time_str,
        round(c_to_f(temp_c), 1) if temp_c else "",
        humidity if humidity else "",
        dew_point if dew_point else "",
        round(distance_miles, 2),
        elapsed,
        avg_pace,
        splits_str,
        int(elevation_feet) if elevation_feet > 0 else "",
        int(avg_hr) if avg_hr else "",
        hr_range,
        awl,
        int(recovery_val) if recovery_val > 0 else "",
        round(vo2, 1) if vo2 else ""
    ]

    if sync_to_sheets(row_data):
        state = "SYNCED"
    else:
        state = "HYDRATED"

    end_dt = datetime.strptime(workout.end[:19], "%Y-%m-%d %H:%M:%S")
    
    if not existing:
        new_record = WorkoutRecord(
            id=workout.id,
            name=workout.name,
            start_date=start_dt,
            end_date=end_dt,
            duration=workout.duration,
            distance=distance_miles,
            state=state,
            payload=workout.model_dump()
        )
        db.add(new_record)
    else:
        existing.state = state
        existing.payload = workout.model_dump()
    
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Running Proxy", lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    payload_data = await request.json()
    try:
        payload = WebhookPayload(**payload_data)
        logger.info(f"Received webhook with {len(payload.data.workouts)} workouts and {len(payload.data.metrics)} metrics")
        for workout in payload.data.workouts:
            if workout.name in ["Running", "Outdoor Run"]:
                background_tasks.add_task(process_workout, workout, payload.data.metrics, db)
        return {"status": "ok", "message": "Workouts queued for processing"}
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
