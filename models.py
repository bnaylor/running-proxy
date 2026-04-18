from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# --- SQLite Models ---

class WorkoutRecord(Base):
    __tablename__ = "workouts"
    
    id = Column(String, primary_key=True) # UUID from Health Auto Export
    name = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    duration = Column(Float)
    distance = Column(Float)
    state = Column(String, default="PENDING") # PENDING, HYDRATED, SYNCED
    payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# --- Pydantic Models for Webhook ---

class WorkoutMetadata(BaseModel):
    HKTimeZone: Optional[str] = None
    HKWeatherTemperature: Optional[str] = None
    HKWeatherHumidity: Optional[str] = None
    HKIndoorWorkout: Optional[int] = None
    HKAverageHeartRate: Optional[str] = None
    HKHeartRateRecoveryOneMinute: Optional[str] = None

class WorkoutMetricData(BaseModel):
    date: str
    value: float

class WorkoutMetric(BaseModel):
    name: str
    units: str
    data: List[WorkoutMetricData]

class WorkoutRoutePoint(BaseModel):
    lat: float
    lon: float
    altitude: float
    timestamp: str
    speed: float

class WorkoutEvent(BaseModel):
    type: str
    date: str
    duration: Optional[float] = None
    distance: Optional[float] = None
    metadata: Optional[Dict] = None

class Workout(BaseModel):
    id: str = Field(..., alias="id") # UUID
    name: str
    start: str
    end: str
    duration: float
    durationUnit: str
    totalDistance: float
    distanceUnit: str
    totalEnergyBurned: float
    energyBurnedUnit: str
    sourceName: str
    sourceVersion: str
    device: str
    metadata: Optional[WorkoutMetadata] = None
    metrics: Optional[List[WorkoutMetric]] = None
    route: Optional[List[WorkoutRoutePoint]] = None
    workoutEvents: Optional[List[WorkoutEvent]] = None

class WebhookPayloadData(BaseModel):
    workouts: List[Workout] = []
    # Could also have metrics, etc. at top level but we focus on workouts

class WebhookPayload(BaseModel):
    data: WebhookPayloadData
    metadata: Dict
