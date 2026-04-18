"""Tests for FastAPI webhook endpoint error handling."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_webhook_returns_422_on_empty_payload():
    """An empty body is not a valid WebhookPayload — must return 4xx, not 200."""
    response = client.post("/webhook", json={})
    assert response.status_code == 422


def test_webhook_returns_422_on_missing_data_key():
    """Payload missing the required 'data' key must return 4xx."""
    response = client.post("/webhook", json={"workouts": []})
    assert response.status_code == 422


def test_health_endpoint_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
