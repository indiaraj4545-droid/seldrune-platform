import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_owner(client: TestClient, suffix: str = "primary") -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"tool-grants-{suffix}@example.com",
            "password": "correct horse battery staple",
            "display_name": f"Tool Grants {suffix}",
            "organization_name": f"Tool Grants {suffix}",
            "organization_slug": f"tool-grants-{suffix}",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id


def create_tool(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    *,
    slug: str,
    action_name: str,
    risk_level: str = "low",
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/tools",
        headers=headers,
        json={
            "name": slug.replace("-", " ").title(),
            "slug": slug,
            "action_name": action_name,
            "risk_level": risk_level,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_agent(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    *,
    slug: str,
    allowed_tool_slugs: list[str] | None = None,
    include_policy: bool = True,
) -> dict:
    payload = {"name": slug.replace("-", " ").title(), "slug": slug}
    if include_policy:
        payload["allowed_tool_slugs"] = allowed_tool_slugs
    response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def create_task(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    agent_id: str,
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/tasks",
        headers=headers,
        json={
            "title": "Agent tool task",
            "objective": "Exercise the assigned agent tool policy safely.",
            "assigned_agent_id": agent_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_tool_allowlist_blocks_before_tool_run_creation(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    echo = create_tool(
        client,
        headers,
        organization_id,
        slug="echo-tool",
        action_name="echo",
    )
    stats = create_tool(
        client,
        headers,
        organization_id,
        slug="stats-tool",
        action_name="text-stats",
    )
    agent = create_agent(
        client,
        headers,
        organization_id,
        slug="restricted-agent",
        allowed_tool_slugs=["echo-tool"],
    )
    task = create_task(client, headers, organization_id, agent["id"])

    allowed = client.post(
        f"/api/v1/organizations/{organization_id}/tool-runs",
        headers=headers,
        json={
            "tool_id": echo["id"],
            "task_id": task["id"],
            "input_data": {"message": "allowed"},
        },
    )
    assert allowed.status_code == 201
    assert allowed.json()["status"] == "succeeded"
    assert allowed.json()["agent_id"] == agent["id"]

    blocked = client.post(
        f"/api/v1/organizations/{organization_id}/tool-runs",
        headers=headers,
        json={
            "tool_id": stats["id"],
            "task_id": task["id"],
            "input_data": {"text": "must not execute"},
        },
    )
    assert blocked.status_code == 409

    runs = client.get(
        f"/api/v1/organizations/{organization_id}/tool-runs",
        headers=headers,
    )
    assert runs.status_code == 200
    assert len(runs.json()) == 1

    audit = client.get(
        f"/api/v1/organizations/{organization_id}/audit-log?action=agent.tool_access_denied",
        headers=headers,
    )
    assert audit.status_code == 200
    events = audit.json()["events"]
    assert len(events) == 1
    assert events[0]["resource_id"] == agent["id"]
    assert events[0]["details"]["tool_slug"] == "stats-tool"


def test_empty_tool_allowlist_denies_all_task_linked_tools(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    tool = create_tool(
        client,
        headers,
        organization_id,
        slug="echo-tool",
        action_name="echo",
    )
    agent = create_agent(
        client,
        headers,
        organization_id,
        slug="deny-all-agent",
        allowed_tool_slugs=[],
    )
    task = create_task(client, headers, organization_id, agent["id"])

    blocked = client.post(
        f"/api/v1/organizations/{organization_id}/tool-runs",
        headers=headers,
        json={"tool_id": tool["id"], "task_id": task["id"], "input_data": {}},
    )
    assert blocked.status_code == 409


def test_legacy_unrestricted_agent_preserves_high_risk_approval(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    tool = create_tool(
        client,
        headers,
        organization_id,
        slug="reviewed-stats",
        action_name="text-stats",
        risk_level="high",
    )
    agent = create_agent(
        client,
        headers,
        organization_id,
        slug="legacy-agent",
        include_policy=False,
    )
    assert agent["allowed_tool_slugs"] is None
    task = create_task(client, headers, organization_id, agent["id"])

    requested = client.post(
        f"/api/v1/organizations/{organization_id}/tool-runs",
        headers=headers,
        json={
            "tool_id": tool["id"],
            "task_id": task["id"],
            "input_data": {"text": "one two three"},
        },
    )
    assert requested.status_code == 201
    pending = requested.json()
    assert pending["status"] == "pending_approval"
    assert pending["agent_id"] == agent["id"]

    approved = client.post(
        f"/api/v1/organizations/{organization_id}/tool-runs/{pending['id']}/approve",
        headers=headers,
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "succeeded"


def test_tool_policy_changes_increment_version_and_are_org_scoped(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    tool = create_tool(
        client,
        headers,
        organization_id,
        slug="echo-tool",
        action_name="echo",
    )
    agent = create_agent(
        client,
        headers,
        organization_id,
        slug="versioned-agent",
        include_policy=False,
    )
    assert agent["version"] == 1

    policy = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"allowed_tool_slugs": [tool["slug"]]},
    )
    assert policy.status_code == 200
    assert policy.json()["version"] == 2

    unchanged = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"allowed_tool_slugs": [tool["slug"]]},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["version"] == 2

    disabled = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/status",
        headers=headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["version"] == 2

    cleared = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"allowed_tool_slugs": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["version"] == 3

    foreign_headers, foreign_org_id = register_owner(client, "foreign")
    create_tool(
        client,
        foreign_headers,
        foreign_org_id,
        slug="foreign-only-tool",
        action_name="echo",
    )
    rejected = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"allowed_tool_slugs": ["foreign-only-tool"]},
    )
    assert rejected.status_code == 422

    fetched = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["version"] == 3
    assert fetched.json()["allowed_tool_slugs"] is None
