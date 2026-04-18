import requests
import json
import os

# Local FastAPI endpoint
URL = "http://localhost:8000/webhook"
SAMPLE_FILE = "example/HealthAutoExport_20260418105420/HealthAutoExport-2026-03-19-2026-04-18.json"

def send_real_sample():
    if not os.path.exists(SAMPLE_FILE):
        print(f"Sample file not found: {SAMPLE_FILE}")
        return

    with open(SAMPLE_FILE, 'r') as f:
        full_data = json.load(f)

    # We'll send a subset: 1st Outdoor Run + related metrics
    all_workouts = full_data['data']['workouts']
    outdoor_runs = [w for w in all_workouts if w['name'] == "Outdoor Run"]
    
    if not outdoor_runs:
        print("No Outdoor Run found in sample.")
        return

    # Just take the first run
    test_workouts = [outdoor_runs[0]]
    
    # Take some metrics too
    test_metrics = full_data['data']['metrics']

    payload = {
        "data": {
            "workouts": test_workouts,
            "metrics": test_metrics
        }
    }

    print(f"Sending real sample with workout ID: {test_workouts[0]['id']}")
    try:
        response = requests.post(URL, json=payload)
        print(f"Response: {response.status_code}")
        print(response.json())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    send_real_sample()
