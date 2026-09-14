from backend.app.core.orchestration import PlannedStep
from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def test_sense_endpoint_reports_go_for_live_well_matched_plan(client, monkeypatch) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    class LivePlan:
        planner_version = "live-model-v2"
        metadata = {"mode": "live", "provider": "openai", "model": "test-live-model"}
        steps = [PlannedStep("Analyze", "Analyze objective", ["analysis"], 80)]

    monkeypatch.setattr(
        "backend.app.api.routes.owner_commands.build_live_plan",
        lambda objective: LivePlan,
    )
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze this opportunity"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    sense = client.get(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/sense",
        headers=headers,
    )
    assert sense.status_code == 200
    assert sense.json()["decision"] == "GO"
    assert sense.json()["score"] >= 65


def test_sense_review_requires_owner_override(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze a simple opportunity"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    approved = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/approve",
        headers=headers,
    )
    assert approved.status_code == 200

    blocked = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/execute",
        headers=headers,
        json={},
    )
    assert blocked.status_code == 409
    assert "Sense Layer REVIEW" in blocked.json()["detail"]

    override = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/sense/override",
        headers=headers,
    )
    assert override.status_code == 200
    assert override.json()["status"] == "approved"

    executed = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200
