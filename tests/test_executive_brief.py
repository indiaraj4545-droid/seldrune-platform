from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def _blocked_project(client, base: str, headers: dict[str, str]) -> dict:
    response = client.post(
        f"{base}/projects",
        headers=headers,
        json={
            "name": "Blocked Delivery",
            "slug": "blocked-delivery",
            "status": "blocked",
            "priority": 95,
            "budget_limit_usd": 50,
            "resource_limit_units": 100,
        },
    )
    assert response.status_code == 201
    return response.json()


def _project_priority(client, base: str, headers: dict[str, str]) -> dict:
    brief = client.get(f"{base}/executive-brief", headers=headers)
    assert brief.status_code == 200
    return next(item for item in brief.json()["priorities"] if item["source"] == "project")


def test_executive_brief_reports_owner_priorities(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    initial = client.get(f"{base}/executive-brief", headers=headers)
    assert initial.status_code == 200
    body = initial.json()
    assert body["health"]["score"] == 100
    assert body["health"]["posture"] == "stable"
    assert body["governance"] == {
        "max_steps_per_command": 25,
        "max_project_budget_usd": 100.0,
        "allow_autonomous_execution": True,
    }
    assert body["operating_snapshot"]["open_goals"] == 0
    assert body["priorities"][0]["source"] == "goals"
    assert body["priorities"][0]["key"] == "no-open-goals"
    assert body["priorities"][0]["action"]["kind"] == "navigate"
    assert body["priorities"][0]["lifecycle"]["state"] == "unassigned"
    assert body["priorities"][0]["escalation"]["level"] == 0
    assert body["executive_actions"]["tracked_priorities"] == 0
    assert body["executive_actions"]["escalated_priorities"] == 0
    assert body["resolved_actions"] == []

    _blocked_project(client, base, headers)
    result = client.get(f"{base}/executive-brief", headers=headers).json()
    assert result["health"]["score"] < 100
    assert result["health"]["blocked_projects"] == 1
    assert result["health"]["warning_incidents"] >= 1
    project_priority = next(
        item for item in result["priorities"] if item["source"] == "project"
    )
    assert project_priority["severity"] == "high"
    assert project_priority["key"].startswith("blocked-project:")
    assert project_priority["action"]["kind"] == "owner_command"
    assert project_priority["lifecycle"]["state"] == "unassigned"
    assert project_priority["escalation"]["level"] == 0


def test_executive_priority_action_lifecycle_closes_when_evidence_clears(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    project = _blocked_project(client, base, headers)
    project_id = project["id"]
    priority = _project_priority(client, base, headers)
    endpoint = f"{base}/executive-brief/actions/{priority['key']}"

    created = client.post(endpoint, headers=headers)
    assert created.status_code == 201
    command = created.json()
    assert command["context"]["owner_command"]["approval_status"] == "awaiting_approval"
    assert command["context"]["executive_priority"]["key"] == priority["key"]
    assert command["context"]["executive_priority"]["resource_id"] == project_id

    active_brief = client.get(f"{base}/executive-brief", headers=headers).json()
    active_priority = next(
        item for item in active_brief["priorities"] if item["key"] == priority["key"]
    )
    assert active_priority["lifecycle"]["state"] == "awaiting_approval"
    assert active_priority["lifecycle"]["command_id"] == command["id"]
    assert active_priority["lifecycle"]["attempts"] == 1
    assert active_brief["executive_actions"]["tracked_priorities"] == 1

    repeated = client.post(endpoint, headers=headers)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == command["id"]

    unblocked = client.patch(
        f"{base}/projects/{project_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert unblocked.status_code == 200

    resolved_brief = client.get(f"{base}/executive-brief", headers=headers).json()
    assert all(item["key"] != priority["key"] for item in resolved_brief["priorities"])
    resolved = next(
        item for item in resolved_brief["resolved_actions"] if item["key"] == priority["key"]
    )
    assert resolved["state"] == "resolved"
    assert resolved["latest_command_id"] == command["id"]
    assert resolved["latest_command_status"] == command["status"]
    assert resolved["attempts"] == 1
    assert resolved_brief["executive_actions"]["resolved_priorities"] == 1


def test_persistent_priority_escalates_after_completed_action(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    _blocked_project(client, base, headers)
    priority = _project_priority(client, base, headers)
    endpoint = f"{base}/executive-brief/actions/{priority['key']}"

    first = client.post(endpoint, headers=headers)
    assert first.status_code == 201
    first_command = first.json()

    approved = client.post(
        f"{base}/owner-commands/{first_command['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200

    executed = client.post(
        f"{base}/owner-commands/{first_command['id']}/execute",
        headers=headers,
        json={"max_steps": 50},
    )
    assert executed.status_code == 200
    assert executed.json()["run"]["status"] in {"succeeded", "partial", "failed"}

    escalated_brief = client.get(f"{base}/executive-brief", headers=headers).json()
    escalated = next(
        item for item in escalated_brief["priorities"] if item["key"] == priority["key"]
    )
    assert escalated["escalation"]["level"] == 1
    assert escalated["escalation"]["completed_attempts"] == 1
    assert escalated["escalation"]["effective_severity"] == "critical"
    assert escalated["escalation"]["alternate_strategy_required"] is True
    assert escalated_brief["executive_actions"]["escalated_priorities"] == 1

    follow_up = client.post(endpoint, headers=headers)
    assert follow_up.status_code == 201
    second_command = follow_up.json()
    assert second_command["id"] != first_command["id"]
    assert second_command["objective"].startswith("Executive escalation level 1:")
    context = second_command["context"]["executive_priority"]
    assert context["escalation_level"] == 1
    assert context["completed_attempts"] == 1
    assert context["effective_severity"] == "critical"


def test_executive_priority_action_rejects_navigation_and_stale_keys(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    navigation = client.post(
        f"{base}/executive-brief/actions/no-open-goals",
        headers=headers,
    )
    assert navigation.status_code == 409

    stale = client.post(
        f"{base}/executive-brief/actions/not-a-current-priority",
        headers=headers,
    )
    assert stale.status_code == 409


def test_executive_brief_assets_are_served(client) -> None:
    page = client.get("/console-assets/executive-brief.html")
    assert page.status_code == 200
    assert "Executive Brief" in page.text
    assert "EXECUTIVE ESCALATION ENGINE" in page.text
    assert "resolved-actions" in page.text
    assert "/console-assets/executive-brief.js" in page.text

    script = client.get("/console-assets/executive-brief.js")
    assert script.status_code == 200
    assert "/executive-brief/actions/" in script.text
    assert "Create escalated follow-up" in script.text
    assert "Escalation level" in script.text

    board = client.get("/console-assets/organization-board.html")
    assert board.status_code == 200
    assert "/console-assets/executive-brief.html" in board.text
