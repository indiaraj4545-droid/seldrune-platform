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


def register_owner(client: TestClient) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "policy-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Policy Owner",
            "organization_name": "Policy Organization",
            "organization_slug": "policy-organization",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id


def test_agent_model_policy_versioning_and_status_are_separate(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    created = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "Governed Runtime Agent",
            "slug": "governed-runtime-agent",
            "runtime_config": {"provider": "mock", "model": "mock-v1"},
        },
    )
    assert created.status_code == 201
    agent = created.json()
    agent_id = agent["id"]
    assert agent["version"] == 1
    assert agent["allowed_model_providers"] is None
    assert agent["allowed_models"] is None

    policy_payload = {
        "allowed_model_providers": ["mock"],
        "allowed_models": ["mock-v1"],
    }
    updated = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent_id}",
        headers=headers,
        json=policy_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["allowed_model_providers"] == ["mock"]
    assert updated.json()["allowed_models"] == ["mock-v1"]

    unchanged = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent_id}",
        headers=headers,
        json=policy_payload,
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["version"] == 2

    disabled = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent_id}/status",
        headers=headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["version"] == 2

    cleared = client.patch(
        f"/api/v1/organizations/{organization_id}/agents/{agent_id}",
        headers=headers,
        json={"allowed_model_providers": None, "allowed_models": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["version"] == 3
    assert cleared.json()["allowed_model_providers"] is None
    assert cleared.json()["allowed_models"] is None

    audit = client.get(
        f"/api/v1/organizations/{organization_id}/audit-log?action=agent.updated",
        headers=headers,
    )
    assert audit.status_code == 200
    version_changes = {
        (event["details"]["from_version"], event["details"]["to_version"])
        for event in audit.json()["events"]
    }
    assert version_changes == {(1, 2), (2, 3)}
