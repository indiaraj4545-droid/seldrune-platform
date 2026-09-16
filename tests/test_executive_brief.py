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
    assert any(
        item["source"] == "project" and item["severity"] == "high"
        for item in result["priorities"]
    )


def test_executive_brief_assets_are_served(client) -> None:
    page = client.get("/console-assets/executive-brief.html")
    assert page.status_code == 200
    assert "Executive Brief" in page.text
    assert "/console-assets/executive-brief.js" in page.text

    script = client.get("/console-assets/executive-brief.js")
    assert script.status_code == 200
    assert "/executive-brief" in script.text
    assert "Organization health" not in script.text

    board = client.get("/console-assets/organization-board.html")
    assert board.status_code == 200
    assert "/console-assets/executive-brief.html" in board.text
