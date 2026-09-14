from backend.app.services.sense_engine import SENSE_VERSION, assess_orchestration
from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def test_sense_layer_go_for_healthy_live_command(client, monkeypatch) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    class FakePlan:
        planner_version = "live-model-v2"
        metadata = {"mode": "live", "provider": "openai", "model": "test-live-model"}
        steps = []

    from backend.app.core.orchestration import PlannedStep

    FakePlan.steps = [
        PlannedStep("Analyze objective", "Analyze the objective", ["analysis"], 80)
    ]
    monkeypatch.setattr(
        "backend.app.api.routes.owner_commands.build_live_plan",
        lambda objective: FakePlan,
    )
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze this objective safely"},
    )
    assert created.status_code == 201
    run = created.json()

    from backend.app.db.session import SessionLocal
    from backend.app.models.orchestration import OrchestrationRun

    with SessionLocal() as session:
        db_run = session.get(OrchestrationRun, run["id"])
        assessment = assess_orchestration(session, run=db_run)

    assert assessment.version == SENSE_VERSION
    assert assessment.decision == "GO"
    assert assessment.score >= 65
    assert assessment.signals["assignment_ratio"] == 1.0


def test_sense_layer_holds_unassigned_steps(client, monkeypatch) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    class FakePlan:
        planner_version = "live-model-v2"
        metadata = {"mode": "live", "provider": "openai", "model": "test-live-model"}
        steps = []

    from backend.app.core.orchestration import PlannedStep

    FakePlan.steps = [
        PlannedStep("Unknown work", "Needs an unavailable skill", ["nonexistent-skill"], 80)
    ]
    monkeypatch.setattr(
        "backend.app.api.routes.owner_commands.build_live_plan",
        lambda objective: FakePlan,
    )
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Perform unknown specialist work"},
    )
    assert created.status_code == 201
    run = created.json()

    from backend.app.db.session import SessionLocal
    from backend.app.models.orchestration import OrchestrationRun

    with SessionLocal() as session:
        db_run = session.get(OrchestrationRun, run["id"])
        assessment = assess_orchestration(session, run=db_run)

    assert assessment.decision == "HOLD"
    assert "unassigned_steps" in assessment.blockers
