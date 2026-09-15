from fastapi.testclient import TestClient

from backend.app.main import app


def test_owner_console_is_served() -> None:
    with TestClient(app) as client:
        response = client.get("/console")
        assert response.status_code == 200
        assert "Seldrune Owner Console" in response.text
        assert "/console-assets/console.css" in response.text
        assert "Command monitor" in response.text
        assert "Organization board" in response.text
        assert "ORGANIZATION TREASURY" in response.text
        assert "treasury-allocated" in response.text
        assert "treasury-available" in response.text


def test_owner_console_assets_are_served() -> None:
    with TestClient(app) as client:
        assert client.get("/console-assets/console.css").status_code == 200
        script = client.get("/console-assets/console.js")
        assert script.status_code == 200
        assert "owner-dashboard" in script.text
        assert "Download report" in script.text
        assert "Total tokens" in script.text
        assert "Recorded cost" in script.text
        assert "Execution time" in script.text
        assert "result-step" in script.text
        assert "Promote to organization" in script.text
        assert "/promote" in script.text
        assert "Open Organization Board" in script.text
        assert "Revoke approval" in script.text
        assert "/revoke" in script.text
        assert "Governed project budget" in script.text
        assert "Circuit breaker stopped execution" in script.text
        assert "treasury-utilization" in script.text
        assert "allocated_budget_usd" in script.text
        assert "reserved_budget_usd" in script.text
