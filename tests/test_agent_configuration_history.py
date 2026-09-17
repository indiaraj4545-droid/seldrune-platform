from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.agent import Agent
from backend.app.models.agent_revision import AgentConfigurationRevision


@pytest.fixture
def client_and_session():
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
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_owner(client: TestClient) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "agent-history-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Agent History Owner",
            "organization_name": "Agent History",
            "organization_slug": "agent-history",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id


def create_agent(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    *,
    slug: str = "history-agent",
    runtime_config: dict | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "History Agent",
            "slug": slug,
            "capabilities": ["research"],
            "runtime_config": runtime_config or {"provider": "mock", "model": "mock-v1"},
            "allowed_model_providers": ["mock"],
            "allowed_models": ["mock-v1"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_history_restore_is_monotonic_and_status_neutral(client_and_session) -> None:
    client, _testing_session = client_and_session
    headers, organization_id = register_owner(client)
    agent = create_agent(client, headers, organization_id)

    revisions = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions",
        headers=headers,
    )
    assert revisions.status_code == 200
    history = revisions.json()
    assert [item["version"] for item in history] == [1]
    assert history[0]["change_kind"] == "created"
    assert history[0]["snapshot"]["name"] == "History Agent"

    updated = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={
            "name": "History Agent v2",
            "capabilities": ["research", "analysis"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    disabled = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/status",
        headers=headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["version"] == 2

    history = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions",
        headers=headers,
    ).json()
    assert [item["version"] for item in history] == [1, 2]
    assert [item["change_kind"] for item in history] == ["created", "updated"]

    restored = client.post(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions/"
        f"{history[0]['id']}/restore",
        headers=headers,
    )
    assert restored.status_code == 200
    restored_agent = restored.json()
    assert restored_agent["version"] == 3
    assert restored_agent["name"] == "History Agent"
    assert restored_agent["capabilities"] == ["research"]
    assert restored_agent["status"] == "disabled"

    history = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions",
        headers=headers,
    ).json()
    assert [item["version"] for item in history] == [1, 2, 3]
    assert history[-1]["change_kind"] == "restored"

    no_op_restore = client.post(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions/"
        f"{history[0]['id']}/restore",
        headers=headers,
    )
    assert no_op_restore.status_code == 200
    assert no_op_restore.json()["version"] == 3

    foreign_org = client.get(
        f"/api/v1/organizations/{uuid4()}/agents/{agent['id']}/revisions",
        headers=headers,
    )
    assert foreign_org.status_code == 403


def test_secret_like_runtime_keys_are_rejected_recursively(client_and_session) -> None:
    client, _testing_session = client_and_session
    headers, organization_id = register_owner(client)

    rejected_create = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "Unsafe Agent",
            "slug": "unsafe-agent",
            "runtime_config": {"provider": "mock", "auth": {"api_key": "do-not-store"}},
        },
    )
    assert rejected_create.status_code == 422
    assert rejected_create.json()["detail"] == {
        "secret_like_runtime_config_keys": ["runtime_config.auth.api_key"]
    }

    agent = create_agent(client, headers, organization_id, slug="safe-agent")
    rejected_update = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"runtime_config": {"nested": [{"password": "do-not-store"}]}},
    )
    assert rejected_update.status_code == 422
    assert rejected_update.json()["detail"] == {
        "secret_like_runtime_config_keys": ["runtime_config.nested[0].password"]
    }

    current = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
    )
    assert current.status_code == 200
    assert current.json()["version"] == 1

    history = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions",
        headers=headers,
    )
    assert [item["version"] for item in history.json()] == [1]


def test_legacy_agent_gets_baseline_before_first_v086_update(client_and_session) -> None:
    client, testing_session = client_and_session
    headers, organization_id = register_owner(client)
    agent = create_agent(client, headers, organization_id, slug="legacy-agent")

    with testing_session() as session:
        session.execute(
            delete(AgentConfigurationRevision).where(
                AgentConfigurationRevision.agent_id == agent["id"]
            )
        )
        stored_agent = session.scalar(select(Agent).where(Agent.id == agent["id"]))
        assert stored_agent is not None
        stored_agent.version = 5
        session.commit()

    updated = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}",
        headers=headers,
        json={"name": "Legacy Agent Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 6

    history = client.get(
        f"/api/v1/organizations/{organization_id}/agents/{agent['id']}/revisions",
        headers=headers,
    )
    assert history.status_code == 200
    body = history.json()
    assert [item["version"] for item in body] == [5, 6]
    assert [item["change_kind"] for item in body] == ["baseline", "updated"]
    assert body[0]["snapshot"]["name"] == "History Agent"
    assert body[1]["snapshot"]["name"] == "Legacy Agent Updated"
