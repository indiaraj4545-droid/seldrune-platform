from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_status_endpoint() -> None:
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["ready"] is True
    assert body["service"] == "seldrune-platform"
    assert body["version"] == "0.40.0"
    assert body["environment"] == "development"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["model_provider"] == {
        "status": "ok",
        "provider": "mock",
        "model": "mock-v1",
        "live_ai": False,
    }
    assert body["checked_at"]
