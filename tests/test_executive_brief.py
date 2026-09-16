from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


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
    assert body["executive_actions"]["tracked_priorities"] == 0
    assert body["resolved_actions"] == []

    project = client.post(
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
    assert project.status_code == 201

    degraded = client.get(f"{base}/executive-brief", headers=headers)
    assert degraded.status_code == 200
    result = degraded.json()
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


def test_executive_priority_action_lifecycle_closes_when_evidence_clears(client) -> None:
    token, organization_id = register_owner(client)
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/organizations/{organization_id}"

    project = client.post(
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
    assert project.status_code == 201
    project_id = project.json()["id"]

    brief = client.get(f"{base}/executive-brief", headers=headers).json()
    priority = next(item for item in brief["priorities"] if item["source"] == "project")
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

    commands = client.get(f"{base}/owner-commands", headers=headers)
    assert commands.status_code == 200
    matching = [
        item
        for item in commands.json()
        if (item["context"].get("executive_priority") or {}).get("key") == priority["key"]
    ]
    assert len(matching) == 1

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
    assert "EXECUTIVE ACTION LIFECYCLE" in page.text
    assert "resolved-actions" in page.text
    assert "/console-assets/executive-brief.js" in page.text

    script = client.get("/console-assets/executive-brief.js")
    assert script.status_code == 200
    assert "/executive-brief/actions/" in script.text
    assert "Create follow-up governed command" in script.text
    assert "succeeded_unresolved" in script.text

    board = client.get("/console-assets/organization-board.html")
    assert board.status_code == 200
    assert "/console-assets/executive-brief.html" in board.text
