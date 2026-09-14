from fastapi.testclient import TestClient

from backend.app.main import app


def test_organization_board_assets_are_served() -> None:
    with TestClient(app) as client:
        page = client.get("/console-assets/organization-board.html")
        assert page.status_code == 200
        assert "Seldrune Organization Board" in page.text
        assert "ORGANIZATION KERNEL" in page.text
        assert "/console-assets/organization-board.js" in page.text

        script = client.get("/console-assets/organization-board.js")
        assert script.status_code == 200
        assert "organization-kernel" in script.text
        assert "departments" in script.text
        assert "goals" in script.text
        assert "projects" in script.text
        assert "delegations" in script.text
