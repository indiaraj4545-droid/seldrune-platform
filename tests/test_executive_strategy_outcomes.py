from tests.test_autonomous_execution import register_owner
from tests.test_executive_brief import _blocked_project, _project_priority

pytest_plugins = ["tests.test_autonomous_execution"]


def test_strategy_outcomes_start_empty(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    brief = client.get(f"{base}/executive-brief", headers=headers)
    assert brief.status_code == 200
    body = brief.json()
    assert body["strategy_outcomes"] == {
        "scored_attempts": 0,
        "verified_resolution_associations": 0,
        "persisted_after_success": 0,
        "unsuccessful_attempts": 0,
        "scored_families": 0,
    }
    assert body["strategy_scorecards"] == []
    assert body["strategy_outcome_history"] == []


def test_strategy_outcomes_score_resolution_and_inform_future_context(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    first_project = _blocked_project(
        client,
        base,
        headers,
        name="Blocked Strategy Alpha",
        slug="blocked-strategy-alpha",
    )
    first_priority = _project_priority(client, base, headers, first_project["id"])
    first_endpoint = f"{base}/executive-brief/actions/{first_priority['key']}"
    first_command = client.post(first_endpoint, headers=headers)
    assert first_command.status_code == 201
    command = first_command.json()
    assert command["context"]["executive_strategy"]["mode"] == "baseline"
    assert command["context"]["executive_strategy"]["outcome_score"]["family_attempts"] == 0

    approved = client.post(
        f"{base}/owner-commands/{command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    executed = client.post(
        f"{base}/owner-commands/{command['id']}/execute",
        headers=headers,
        json={"max_steps": 50},
    )
    assert executed.status_code == 200
    assert executed.json()["run"]["status"] == "succeeded"

    persistent = client.get(f"{base}/executive-brief", headers=headers).json()
    assert persistent["strategy_outcomes"]["scored_attempts"] == 1
    assert persistent["strategy_outcomes"]["verified_resolution_associations"] == 0
    assert persistent["strategy_outcomes"]["persisted_after_success"] == 1
    card = next(
        item
        for item in persistent["strategy_scorecards"]
        if item["family"] == "blocked-project" and item["mode"] == "baseline"
    )
    assert card["attempts"] == 1
    assert card["execution_succeeded"] == 1
    assert card["resolution_associations"] == 0
    assert card["persisted_after_success"] == 1
    assert card["resolution_rate"] == 0.0
    assert card["causal_claim"] is False

    unblocked = client.patch(
        f"{base}/projects/{first_project['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert unblocked.status_code == 200

    resolved = client.get(f"{base}/executive-brief", headers=headers).json()
    assert resolved["strategy_outcomes"]["scored_attempts"] == 1
    assert resolved["strategy_outcomes"]["verified_resolution_associations"] == 1
    assert resolved["strategy_outcomes"]["persisted_after_success"] == 0
    card = next(
        item
        for item in resolved["strategy_scorecards"]
        if item["family"] == "blocked-project" and item["mode"] == "baseline"
    )
    assert card["resolution_associations"] == 1
    assert card["resolution_rate"] == 1.0
    assert card["evidence_strength"] == "low"
    history = resolved["strategy_outcome_history"][0]
    assert history["command_id"] == command["id"]
    assert history["outcome"] == "resolution_associated"
    assert history["causal_claim"] is False

    second_project = _blocked_project(
        client,
        base,
        headers,
        name="Blocked Strategy Beta",
        slug="blocked-strategy-beta",
    )
    second_priority = _project_priority(client, base, headers, second_project["id"])
    family_history = second_priority["strategy_outcomes"]
    assert family_history["family"] == "blocked-project"
    assert family_history["total_attempts"] == 1
    assert family_history["resolution_associations"] == 1
    assert family_history["modes"]["baseline"]["resolution_rate"] == 1.0
    assert second_priority["strategy"]["mode"] == "reuse"
    assert second_priority["strategy"]["outcome_score"]["family_attempts"] == 1
    assert second_priority["strategy"]["outcome_score"]["attempts"] == 0

    second_endpoint = f"{base}/executive-brief/actions/{second_priority['key']}"
    second_command = client.post(second_endpoint, headers=headers)
    assert second_command.status_code == 201
    strategy_context = second_command.json()["context"]["executive_strategy"]
    assert strategy_context["mode"] == "reuse"
    assert strategy_context["outcome_score"]["family"] == "blocked-project"
    assert strategy_context["outcome_score"]["family_attempts"] == 1
    assert strategy_context["outcome_score"]["attempts"] == 0
    assert strategy_context["outcome_score"]["causal_claim"] is False
