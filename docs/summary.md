# Project Summary: Running Proxy

This service acts as a bridge between the **Health Auto Export** iOS app and a **Google Sheets** exercise log. It receives Apple Health workout data via a webhook, processes it, deduplicates entries using a local SQLite database, and synchronizes the results to a "Running" tab in a specified spreadsheet.

## 🛠️ Components Implemented

### 1. Application Core
- **FastAPI Service (`main.py`)**: Handles incoming JSON webhooks and coordinates data processing.
- **Data Models (`models.py`)**: 
  - **Pydantic**: Validates complex nested JSON payloads from Health Auto Export (Workouts, Metrics, Events).
  - **SQLAlchemy**: Manages a SQLite database for deduplication and state tracking (PENDING, HYDRATED, SYNCED).
- **Transformations**:
  - **Magnus-Tetens Formula**: Calculates Dew Point from Temperature and Humidity metadata.
  - **Pace Conversion**: Converts meters-per-second to `min/mile` format.
  - **Split Flattening**: Processes `segment` or `lap` events into a single pipe-separated string (e.g., `8:45 | 8:30 | 8:50`).

### 2. Infrastructure & Deployment
- **Dockerfile**: A lightweight Python 3.11-slim image configured for K8s deployment.
- **Kubernetes Manifests (`k8s/`)**:
  - **`pvc.yaml`**: Persistent volume claim for the SQLite database.
  - **`deployment.yaml`**: Single-replica deployment using the `Recreate` strategy to ensure database integrity on NFS.
  - **`service.yaml`**: LoadBalancer service for an internal static IP.

### 3. Integration & Testing
- **Google Sheets Integration**: Uses `google-api-python-client` with Service Account authentication.
- **Testing Utility (`test_webhook.py`)**: A script to simulate a full workout payload for local validation.

## 🧪 Testing Strategies

### Local Development
1. **Environment**: Install dependencies from `requirements.txt`.
2. **Execution**: Run `uvicorn main:app --reload`.
3. **Validation**: Use `python test_webhook.py` to send a mock workout and verify SQLite entries and console logs.
4. **Sheets Mock**: For offline testing, the `sync_to_sheets` function can be mocked to return `True`.

### Kubernetes Validation
- **Health Checks**: The `/health` endpoint is available for Liveness/Readiness probes.
- **Log Inspection**: Use `kubectl logs` to monitor the background processing of workouts.
- **Database Persistence**: Verify the SQLite file persists across pod restarts by checking the mounted PVC.

## 🚀 Potential Next Steps

1. **VO2 Max Integration**: Add a secondary lookup for `vo2Max` samples that may arrive separately from the workout payload.
2. **Apple "Effort" Mapping (AWL)**: Map the Apple Watch "Effort" metadata (0-10 scale) to the "AWL" column (Easy/Moderate/Hard).
3. **Error Retries**: Implement a background task to periodically retry syncing "HYDRATED" but un-synced workouts if the Google API is temporarily unavailable.
4. **Security**: Configure an API Key or Bearer Token for the `/webhook` endpoint to prevent unauthorized submissions.
5. **Dashboard**: A simple `/workouts` GET endpoint to view the status of recently processed runs.
