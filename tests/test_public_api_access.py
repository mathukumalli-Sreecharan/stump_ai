from fastapi.testclient import TestClient

from backend.main import app


def test_api_health_is_available_without_credentials():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_endpoint_is_not_registered():
    response = TestClient(app).post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert response.status_code == 404
