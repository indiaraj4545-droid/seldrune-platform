from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.rbac import Permission, Role, has_permission
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
            "email": "approval-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Approval Owner",
            "organization_name": "Approval Lab",
            "organization_slug": "approval-lab",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id


def create_research_agent(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
) -> None:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/agents",
        headers=headers,
        json={
            "name": "Approval Research Agent",
            "slug": "approval-research-agent",
            "capabilities": ["research"],
            "runtime_config": {"provider": "mock", "model": "mock-v1"},
        },
    )
    assert response.status_code == 201


def create_run(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    *,
    requires_approval: bool,
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations",
        headers=headers,
        json={
            "objective": "Research approval checkpoint behavior",
            "plan": [
                {
                    "title": "Research approval controls",
                    "description": "Produce a concise research result.",
                    "capabilities": ["research"],
                    "requires_approval": requires_approval,
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def list_approvals(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    run_id: str,
):
    return client.get(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run_id}/approvals",
        headers=headers,
    )


def decide(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    run_id: str,
    approval_id: str,
    decision: str,
):
    return client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run_id}/approvals/"
        f"{approval_id}/decision",
        headers=headers,
        json={"decision": decision, "decision_note": "Reviewed by a human owner."},
    )


def execute(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    run_id: str,
):
    return client.post(
        f"/api/v1/organizations/{organization_id}/orchestrations/{run_id}/execute",
        headers=headers,
        json={},
    )


def test_pending_approval_blocks_then_approved_run_resumes(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    create_research_agent(client, headers, organization_id)
    run = create_run(client, headers, organization_id, requires_approval=True)

    assert run["steps"][0]["requires_approval"] is True
    approvals_response = list_approvals(client, headers, organization_id, run["id"])
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"

    blocked = execute(client, headers, organization_id, run["id"])
    assert blocked.status_code == 200
    blocked_report = blocked.json()["execution"]
    assert blocked_report["executed_steps"] == 0
    assert blocked_report["blocked_steps"] == 1
    assert blocked_report["approval_blocked_steps"] == 1
    assert blocked_report["halted_reason"] == "approval_required"

    task_id = run["steps"][0]["task_id"]
    task = client.get(
        f"/api/v1/organizations/{organization_id}/tasks/{task_id}",
        headers=headers,
    )
    assert task.status_code == 200
    assert task.json()["status"] == "assigned"
    assert task.json()["output_data"] is None

    approved = decide(
        client,
        headers,
        organization_id,
        run["id"],
        approvals[0]["id"],
        "approved",
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_by_user_id"] is not None

    second_decision = decide(
        client,
        headers,
        organization_id,
        run["id"],
        approvals[0]["id"],
        "rejected",
    )
    assert second_decision.status_code == 409

    resumed = execute(client, headers, organization_id, run["id"])
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["execution"]["executed_steps"] == 1
    assert body["execution"]["approval_blocked_steps"] == 0
    assert body["execution"]["halted_reason"] is None
    assert body["run"]["status"] == "succeeded"

    foreign = list_approvals(client, headers, str(uuid4()), run["id"])
    assert foreign.status_code == 403


def test_rejected_approval_blocks_execution(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    create_research_agent(client, headers, organization_id)
    run = create_run(client, headers, organization_id, requires_approval=True)
    approval = list_approvals(client, headers, organization_id, run["id"]).json()[0]

    rejected = decide(
        client,
        headers,
        organization_id,
        run["id"],
        approval["id"],
        "rejected",
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    blocked = execute(client, headers, organization_id, run["id"])
    assert blocked.status_code == 200
    report = blocked.json()["execution"]
    assert report["executed_steps"] == 0
    assert report["approval_blocked_steps"] == 1
    assert report["halted_reason"] == "approval_rejected"


def test_ordinary_steps_remain_backward_compatible(client: TestClient) -> None:
    headers, organization_id = register_owner(client)
    create_research_agent(client, headers, organization_id)
    run = create_run(client, headers, organization_id, requires_approval=False)

    assert run["steps"][0]["requires_approval"] is False
    approvals = list_approvals(client, headers, organization_id, run["id"])
    assert approvals.status_code == 200
    assert approvals.json() == []

    result = execute(client, headers, organization_id, run["id"])
    assert result.status_code == 200
    report = result.json()["execution"]
    assert report["executed_steps"] == 1
    assert report["blocked_steps"] == 0
    assert report["approval_blocked_steps"] == 0


def test_approval_permission_is_separate_from_run_permission() -> None:
    assert has_permission(Role.OWNER, Permission.AGENTS_APPROVE)
    assert has_permission(Role.ADMIN, Permission.AGENTS_APPROVE)
    assert not has_permission(Role.MEMBER, Permission.AGENTS_APPROVE)
    assert not has_permission(Role.AUDITOR, Permission.AGENTS_APPROVE)
    assert has_permission(Role.MEMBER, Permission.AGENTS_RUN)
