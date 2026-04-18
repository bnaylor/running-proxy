from pydantic import BaseModel, Field, ConfigDict
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

class BaseHaeModel(BaseModel):
    model_config = ConfigDict(extra='allow', protected_namespaces=())

class QuantityValue(BaseHaeModel):
    qty: Optional[float] = None
    units: Optional[str] = None

class DatedQuantityValue(BaseHaeModel):
    qty: Optional[float] = None
    units: Optional[str] = None
    date: str
    source: Optional[str] = None

class MetricDataPoint(BaseHaeModel):
    qty: Optional[float] = None
    date: str
    source: Optional[str] = None
    units: Optional[str] = None

class HeartRateDataPoint(BaseHaeModel):
    Avg: Optional[float] = None
    Min: Optional[float] = None
    Max: Optional[float] = None
    date: str
    units: Optional[str] = None
    source: Optional[str] = None

class HeartRateSummary(BaseHaeModel):
    min: Optional[QuantityValue] = None
    avg: Optional[QuantityValue] = None
    max: Optional[QuantityValue] = None

class WorkoutRoutePoint(BaseHaeModel):
    latitude: float
    longitude: float
    altitude: float
    timestamp: str
    speed: float
    course: Optional[float] = None
    horizontalAccuracy: Optional[float] = None
    verticalAccuracy: Optional[float] = None

class Workout(BaseHaeModel):
    id: str = Field(..., alias="id")
    name: str
    start: str
    end: str
    duration: float
    location: Optional[str] = None
    isIndoor: Optional[bool] = None
    
    # Nested Objects
    distance: Optional[QuantityValue] = None
    avgHeartRate: Optional[QuantityValue] = None
    maxHeartRate: Optional[QuantityValue] = None
    temperature: Optional[QuantityValue] = None
    humidity: Optional[QuantityValue] = None
    activeEnergyBurned: Optional[QuantityValue] = None
    stepCadence: Optional[QuantityValue] = None
    elevationUp: Optional[QuantityValue] = None
    intensity: Optional[QuantityValue] = None  # kcal/hr·kg, used for AWL effort label
    
    # Summaries
    heartRate: Optional[HeartRateSummary] = None
    
    # Time Series
    heartRateData: Optional[List[HeartRateDataPoint]] = []
    heartRateRecovery: Optional[List[HeartRateDataPoint]] = []
    stepCount: Optional[List[MetricDataPoint]] = []
    activeEnergy: Optional[List[MetricDataPoint]] = []
    walkingAndRunningDistance: Optional[List[MetricDataPoint]] = []
    
    route: Optional[List[WorkoutRoutePoint]] = None
    metadata: Optional[Dict] = {}

class Metric(BaseHaeModel):
    name: str
    units: Optional[str] = None
    data: List[MetricDataPoint]

class WebhookPayloadData(BaseHaeModel):
    workouts: List[Workout] = []
    metrics: List[Metric] = []

class WebhookPayload(BaseHaeModel):
    data: WebhookPayloadData
