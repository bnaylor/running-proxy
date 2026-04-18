import requests
import json
import uuid
from datetime import datetime, timedelta

# Local FastAPI endpoint
URL = "http://localhost:8000/webhook"

def generate_mock_workout():
    workout_id = str(uuid.uuid4())
    start_time = datetime.now() - timedelta(hours=1)
    end_time = start_time + timedelta(minutes=45)
    
    # Mock data following the Health Auto Export format
    payload = {
        "data": {
            "workouts": [
                {
                    "id": workout_id,
                    "name": "Running",
                    "start": start_time.strftime("%Y-%m-%d %H:%M:%S +0000"),
                    "end": end_time.strftime("%Y-%m-%d %H:%M:%S +0000"),
                    "duration": 2700, # 45 mins
                    "durationUnit": "s",
                    "totalDistance": 8046.72, # 5 miles
                    "distanceUnit": "m",
                    "totalEnergyBurned": 500,
                    "energyBurnedUnit": "kcal",
                    "sourceName": "Apple Watch",
                    "sourceVersion": "10.0.1",
                    "device": "Apple Watch Series 8",
                    "metadata": {
                        "HKTimeZone": "America/New_York",
                        "HKWeatherTemperature": "72 degF",
                        "HKWeatherHumidity": "60 %",
                        "HKAverageHeartRate": "150 count/min",
                        "HKHeartRateRecoveryOneMinute": "30 count/min"
                    },
                    "workoutEvents": [
                        {
                            "type": "segment",
                            "date": (start_time + timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M:%S +0000"),
                            "duration": 540,
                            "distance": 1609.34
                        },
                        {
                            "type": "segment",
                            "date": (start_time + timedelta(minutes=18)).strftime("%Y-%m-%d %H:%M:%S +0000"),
                            "duration": 540,
                            "distance": 1609.34
                        }
                    ],
                    "metrics": [
                        {
                            "name": "heart_rate",
                            "units": "count/min",
                            "data": [
                                {"date": start_time.strftime("%Y-%m-%d %H:%M:%S +0000"), "value": 140},
                                {"date": end_time.strftime("%Y-%m-%d %H:%M:%S +0000"), "value": 160}
                            ]
                        }
                    ]
                }
            ]
        },
        "metadata": {
            "app_version": "9.0.0",
            "export_date": datetime.now().isoformat()
        }
    }
    return payload

def send_test_webhook():
    payload = generate_mock_workout()
    print(f"Sending mock workout ID: {payload['data']['workouts'][0]['id']}")
    try:
        response = requests.post(URL, json=payload)
        print(f"Response: {response.status_code}")
        print(response.json())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    send_test_webhook()
