Your collaborator-grade blueprint is ready. This summary captures the infrastructure, data mapping, and logic we've defined for your **Apple Health ⮕ Exercise Spreadsheet** bridge.

Your `gemini-cli` setup can use this as a system prompt or context file to generate the specific Python code or K8s manifests.

***

# Technical Spec: Apple Health to Google Sheets Proxy

## 1. Project Overview
A production-grade ingestion service running in a Kubernetes cluster (**{kates, nuclhed, nuclular}**) that receives Apple Health workout data via a REST endpoint, caches and deduplicates it using an NFS-backed SQLite database, and synchronizes specific running metrics to the "Running" tab of the **Exercise** Google Sheet.

## 2. Infrastructure & Environment
* **Host:** K8s Cluster (Toronto Home Lab).
* **Execution:** FastAPI (Python) containerized service.
* **Storage:** SQLite database on an NFS-backed Persistent Volume (PV) for persistence and cross-node availability.
* **Auth:** Google Service Account with Editor access to the "Exercise" spreadsheet.
* **Network:** K8s LoadBalancer service providing a static internal IP for iPhone "Pusher" apps (e.g., Health Auto Export).

## 3. Data Mapping (Running Tab)
The proxy will map `HKWorkout` and associated `HKQuantityType` samples to the following spreadsheet columns. Columns not listed are to be left blank for manual input (e.g., Pal, Notes, Intent).

| Spreadsheet Column | Data Source / Logic |
| :--- | :--- |
| **Date / Time** | `startDate` from `HKWorkout` |
| **Temp / Hum** | `HKWorkout` metadata (Apple Watch) or External Weather API |
| **DewPt** | Derived via Magnus-Tetens formula: `f(Temp, Hum)` |
| **Distance** | `totalDistance` (converted to Miles) |
| **Elapsed** | `duration` (formatted as HH:MM:SS) |
| **Avg Pace** | Calculated: `duration / totalDistance` (min/mile) |
| **Splits (pace)** | Flattened string of per-mile segments from the JSON payload |
| **Avg HR** | `HKAverageHeartRate` metadata |
| **HR Range** | `min` and `max` values from the `heartRate` sample list |
| **AWL** | Apple "Effort" metric (Easy/Moderate/Hard) |
| **CR** | `heartRateRecoveryOneMinute` (60s post-workout sample) |
| **VO2** | `vo2Max` quantity type sample associated with workout date |

## 4. Engineering Logic
### Deduplication & State Management
To prevent "rot" and double-entries, the service uses a three-state SQLite machine:
1. **PENDING:** Payload received; UUID stored; awaiting late-arrival samples (like Cardio Recovery).
2. **HYDRATED:** Calculations for Pace and Dew Point completed; splits flattened.
3. **SYNCED:** Row successfully appended to Google Sheets.

### Key Transformation Functions
* **Magnus-Tetens:** Required for calculating Dew Point from temperature and humidity.
* **Pace Conversion:** Meters-per-second to minutes-per-mile.
* **Split Processing:** Mapping the Apple Health `segments` array into a single-cell string for the spreadsheet.

## 5. Deployment Constraints
* **Single Writer:** The Deployment should use `strategy: type: Recreate` or be a `StatefulSet` to ensure only one Pod accesses the SQLite file on the NFS share at a time.
* **Webhook Endpoint:** Must accept `POST` requests in JSON format containing a list of workout and quantity samples.
* **Secrets:** Google Service Account JSON must be mounted as a volume, not injected as an environment variable, for better security.

***

**Suggested Next Step for gemini-cli:** *"Based on this spec, generate a FastAPI application that handles the SQLite deduplication logic and a Kubernetes manifest for a single-replica Deployment using an NFS-backed PVC."*
