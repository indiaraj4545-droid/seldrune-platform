def test_owner_console_serves_action_inbox_assets(client) -> None:
    page = client.get("/console")
    assert page.status_code == 200
    assert 'id="action-inbox"' in page.text
    assert 'href="#action-inbox"' in page.text
    assert "/console-assets/console-action-inbox.css" in page.text
    assert "/console-assets/console-action-inbox.js" in page.text
    assert "Complete governed command history" in page.text

    stylesheet = client.get("/console-assets/console-action-inbox.css")
    assert stylesheet.status_code == 200
    assert ".action-inbox-item" in stylesheet.text
    assert ".action-inbox-critical" in stylesheet.text
    assert ".action-inbox-review" in stylesheet.text
    assert ".action-inbox-approval" in stylesheet.text
    assert "prefers-reduced-motion:reduce" in stylesheet.text


def test_action_inbox_uses_server_ranked_attention(client) -> None:
    script = client.get("/console-assets/console-action-inbox.js")
    assert script.status_code == 200
    assert "/owner-attention" in script.text
    assert "/owner-commands" in script.text
    assert "/owner-dashboard" not in script.text
    assert "/executive-brief" not in script.text
    assert "attention.items" in script.text
    assert "renderAllCommands" in script.text
    assert "commandListMatches" in script.text
    assert "dataset.action" in script.text


def test_action_inbox_is_navigation_and_review_surface(client) -> None:
    page = client.get("/console")
    script = client.get("/console-assets/console-action-inbox.js")

    assert "Seldrune never acts from this inbox without the existing owner controls." in page.text
    assert "review_command" in script.text
    assert "action.kind==='navigate'" in script.text
    assert "method:'POST'" not in script.text
    assert 'method:"POST"' not in script.text
