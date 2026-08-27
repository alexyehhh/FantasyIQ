"""Tests for the health check endpoint.

This is intentionally the first test in the project: it verifies the
app can be imported, assembled, and can serve a request end-to-end
through the FastAPI TestClient (no real network, no external services).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_returns_expected_shape():
    response = client.get("/api/v1/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "environment" in body
