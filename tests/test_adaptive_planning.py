from backend.app.services import live_planner
from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def test_owner_command_planning_reuses_prior_reflection(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze payment automation workflow"},
    )
    assert first.status_code == 201
    first_id = first.json()["id"]
    assert client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{first_id}/approve",
        headers=headers,
    ).status_code == 200
    executed = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{first_id}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200
    assert executed.json()["run"]["summary"]["reflection"]["recommendations"]

    second = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": "Analyze payment automation workflow improvements"},
    )
    assert second.status_code == 201
    command = second.json()
    adaptive = command["context"]["planner"]["adaptive_planning"]
    assert adaptive["applied"] is True
    assert adaptive["sample_count"] >= 1
    assert adaptive["historical_success_rate"] == 1.0
    assert adaptive["preferred_capabilities"]
    assert "preferred_capability_priority_boost" in adaptive["adaptations"]
    assert "adaptive" in command["planner_version"]


def test_explicit_owner_step_count_wins_over_adaptive_history(monkeypatch) -> None:
    monkeypatch.setattr(live_planner.settings, "model_provider", "mock")
    guidance = {
        "version": "adaptive-planning-v1",
        "applied": True,
        "sample_count": 3,
        "reflection_sample_count": 3,
        "outcome_sample_count": 3,
        "historical_success_rate": 0.0,
        "confidence": 1.0,
        "preferred_capabilities": [],
        "caution_capabilities": ["analysis"],
        "recommendations": ["review_failed_capabilities_before_repeating_similar_work"],
        "recurring_cautions": ["task_failures_were_observed"],
        "advisories": ["Add a validation checkpoint."],
    }
    result = live_planner.build_live_plan(
        "Create exactly three planning steps for an automation.",
        adaptive_guidance=guidance,
    )
    assert len(result.steps) == 3
    adaptive = result.metadata["adaptive_planning"]
    assert adaptive["applied"] is True
    assert "owner_step_count_preserved_over_history" in adaptive["adaptations"]
