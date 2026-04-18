# Project Summary: Running Proxy

This service acts as a bridge between the **Health Auto Export** iOS app and a **Google Sheets** exercise log. It receives Apple Health workout data via a webhook, processes it, deduplicates entries using a local SQLite database, and synchronizes the results to a "Running" tab in a specified spreadsheet.

## 🛠️ Components Implemented

### 1. Application Core
- **FastAPI Service (`main.py`)**: Handles incoming JSON webhooks using an `async` lifespan handler and background tasks.
- **Data Models (`models.py`)**: 
  - **Pydantic V2**: Validates actual nested JSON payloads from Health Auto Export. Supports the `{qty, units}` object structure and uses `extra='allow'` to handle varied metric types gracefully.
  - **SQLAlchemy**: Manages a SQLite database for deduplication and state tracking (PENDING, HYDRATED, SYNCED).
- **Transformation Engine**:
  - **Temporal Splitting**: Separates workout start timestamps into individual **Date** (YYYY-MM-DD) and **Time** (HH:MM) columns.
  - **Unit Conversion**: Robust handling of `km`, `m`, and `mi` for distance and `degC` for temperature.
  - **Magnus-Tetens Formula**: Calculates Dew Point from Temperature and Humidity.
  - **Derived Splits**: Aggregates `walkingAndRunningDistance` time-series data into 1-mile buckets when native laps/segments are unavailable.
  - **Elevation Tracking**: Extracts and converts `elevationUp` data to Feet.
  - **Cross-Metric Lookup**: Correlates workouts with top-level `vo2_max` and `physical_effort` samples based on date proximity.
  - **Effort Mapping**: Converts `kcal/hr/kg` intensity into descriptive AWL labels (Easy/Moderate/Hard).

### 2. Infrastructure & Deployment
- **Dockerfile**: A lightweight Python 3.11-slim image configured for K8s deployment.
- **Kubernetes Manifests (`k8s/`)**:
  - **`pvc.yaml`**: Persistent volume claim for the SQLite database.
  - **`deployment.yaml`**: Single-replica deployment using the `Recreate` strategy to ensure database integrity on NFS.
  - **`service.yaml`**: LoadBalancer service for an internal static IP.

### 3. Integration & Testing
- **Google Sheets Integration**: 15-column row mapping (A-O) including Pace, Splits, Elevation, Heart Rate, AWL, and VO2. Manual columns (Tgt Pace, Intent, Notes, etc.) should be moved to Column P and beyond.
- **Test Scripts**:
  - **`test_actual_payload.py`**: Validates processing logic using real production JSON export files.

## 📊 Spreadsheet Column Mapping (1-15)

| Index | Letter | Header | Description |
| :--- | :--- | :--- | :--- |
| 0 | A | Date | Workout date (YYYY-MM-DD) |
| 1 | B | Time | Workout start time (HH:MM) |
| 2 | C | Temp (F) | Weather temperature |
| 3 | D | Humidity | Relative humidity % |
| 4 | E | Dew Point | Calculated dew point (F) |
| 5 | F | Distance | Total distance in miles |
| 6 | G | Elapsed | Formatted duration (HH:MM:SS) |
| 7 | H | Avg Pace | Summary min/mile pace |
| 8 | I | Splits | Pipe-separated mile splits |
| 9 | J | Elev (ft) | Total elevation gain |
| 10 | K | Avg HR | Summary heart rate |
| 11 | L | HR Range | Min-Max heart rate |
| 12 | M | AWL | Effort label (Easy/Mod/Hard) |
| 13 | N | CR | Heart Rate Recovery (1-min drop) |
| 14 | O | VO2 Max | Daily VO2 max estimate |

## 🧪 Decision Log

- **GPX Files**: Export of `.gpx` files was evaluated and disabled. Summary metrics are directly calculated from the JSON payload.
- **Manual Columns**: To maintain a clean automation boundary, manual columns (Tgt Pace, Music, etc.) are moved to the right of Column O.

## 🚀 Next Steps

1. **Security**: Configure an API Key or Bearer Token for the `/webhook` endpoint.
2. **Dashboard**: A simple `/workouts` GET endpoint to view recent sync status.
3. **Error Retries**: Background task to retry "HYDRATED" status workouts.
