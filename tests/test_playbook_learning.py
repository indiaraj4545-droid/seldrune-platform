from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def _run_owner_command(client, organization_id: str, headers: dict[str, str], objective: str):
    created = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": objective},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    approved = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/approve",
        headers=headers,
    )
    assert approved.status_code == 200
    executed = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands/{run_id}/execute",
        headers=headers,
        json={},
    )
    assert executed.status_code == 200
    return executed.json()["run"]


def test_repeated_reflections_promote_playbook_for_future_planning(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    objective = "Analyze payment automation workflow improvements"

    first = _run_owner_command(client, organization_id, headers, objective)
    assert first["summary"]["reflection"]["status"] == "succeeded"
    second = _run_owner_command(client, organization_id, headers, objective)
    assert second["summary"]["reflection"]["status"] == "succeeded"

    third = client.post(
        f"/api/v1/organizations/{organization_id}/owner-commands",
        headers=headers,
        json={"objective": objective},
    )
    assert third.status_code == 201
    command = third.json()
    playbook = command["context"]["operational_playbook"]
    assert playbook["applied"] is True
    assert playbook["playbook_count"] >= 1
    assert any(item["code"] == "narrow_steps" for item in playbook["playbooks"])
    assert command["context"]["planner"]["adaptive_planning"]["applied"] is True
