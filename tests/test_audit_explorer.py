from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.rbac import Permission, Role, has_permission
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.audit import AuditLog
from backend.app.models.membership import Membership
from backend.app.models.organization import Organization


@pytest.fixture
def audit_client():
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


def register_owner(client: TestClient) -> tuple[dict[str, str], str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "audit-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Audit Founder",
            "organization_name": "Seldrune Audit",
            "organization_slug": "seldrune-audit",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id, profile["user"]["id"]


def seed_audit_rows(testing_session, organization_id: str, user_id: str) -> dict[str, str]:
    base_time = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
    with testing_session() as session:
        other = Organization(name="Other Audit Org", slug="other-audit-org")
        session.add(other)
        session.flush()

        task_created = AuditLog(
            organization_id=UUID(organization_id),
            actor_user_id=UUID(user_id),
            action="task.created",
            resource_type="task",
            resource_id="task-1",
            details={"source": "owner"},
            occurred_at=base_time,
        )
        system_update = AuditLog(
            organization_id=UUID(organization_id),
            actor_user_id=None,
            action="task.updated",
            resource_type="task",
            resource_id="task-1",
            details={"source": "system"},
            occurred_at=base_time + timedelta(minutes=1),
        )
        tool_run = AuditLog(
            organization_id=UUID(organization_id),
            actor_user_id=UUID(user_id),
            action="tool.run.created",
            resource_type="tool_run",
            resource_id="tool-run-1",
            details={"risk": "low"},
            occurred_at=base_time + timedelta(minutes=2),
        )
        other_row = AuditLog(
            organization_id=other.id,
            actor_user_id=UUID(user_id),
            action="task.updated",
            resource_type="task",
            resource_id="task-1",
            details={"source": "other-tenant"},
            occurred_at=base_time + timedelta(minutes=3),
        )
        session.add_all([task_created, system_update, tool_run, other_row])
        session.commit()
        return {
            "task_created": str(task_created.id),
            "system_update": str(system_update.id),
            "tool_run": str(tool_run.id),
            "other": str(other_row.id),
            "base_time": base_time.isoformat(),
        }


def test_audit_list_filters_pagination_and_resource_history(audit_client) -> None:
    client, testing_session = audit_client
    headers, organization_id, user_id = register_owner(client)
    seeded = seed_audit_rows(testing_session, organization_id, user_id)

    first_page = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"resource_type": "task", "limit": 1},
    )
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["returned"] == 1
    assert [item["id"] for item in payload["items"]] == [seeded["system_update"]]

    second_page = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"resource_type": "task", "limit": 1, "offset": 1},
    )
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [seeded["task_created"]]

    task_history = client.get(
        f"/api/v1/organizations/{organization_id}/audit/resources/task/task-1",
        headers=headers,
    )
    assert task_history.status_code == 200
    assert [item["id"] for item in task_history.json()["items"]] == [
        seeded["system_update"],
        seeded["task_created"],
    ]
    assert task_history.json()["items"][0]["actor_user_id"] is None

    created_only = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"action": "task.created", "resource_type": "task"},
    )
    assert created_only.status_code == 200
    assert [item["id"] for item in created_only.json()["items"]] == [seeded["task_created"]]

    owner_only = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"actor_user_id": user_id, "resource_type": "tool_run"},
    )
    assert owner_only.status_code == 200
    assert [item["id"] for item in owner_only.json()["items"]] == [seeded["tool_run"]]

    from_time = datetime.fromisoformat(seeded["base_time"]) + timedelta(minutes=1)
    time_filtered = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"resource_type": "task", "occurred_from": from_time.isoformat()},
    )
    assert time_filtered.status_code == 200
    assert [item["id"] for item in time_filtered.json()["items"]] == [seeded["system_update"]]

    invalid_window = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={
            "occurred_from": (from_time + timedelta(minutes=5)).isoformat(),
            "occurred_to": from_time.isoformat(),
        },
    )
    assert invalid_window.status_code == 400

    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/audit?limit=501",
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/audit?offset=-1",
            headers=headers,
        ).status_code
        == 422
    )


def test_audit_detail_tenant_isolation_and_rbac(audit_client) -> None:
    assert has_permission(Role.OWNER, Permission.AUDIT_READ)
    assert has_permission(Role.ADMIN, Permission.AUDIT_READ)
    assert has_permission(Role.AUDITOR, Permission.AUDIT_READ)
    assert not has_permission(Role.MEMBER, Permission.AUDIT_READ)

    client, testing_session = audit_client
    headers, organization_id, user_id = register_owner(client)
    seeded = seed_audit_rows(testing_session, organization_id, user_id)

    detail = client.get(
        f"/api/v1/organizations/{organization_id}/audit/{seeded['system_update']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["details"] == {"source": "system"}
    assert detail.json()["actor_user_id"] is None

    cross_tenant = client.get(
        f"/api/v1/organizations/{organization_id}/audit/{seeded['other']}",
        headers=headers,
    )
    assert cross_tenant.status_code == 404

    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = "member"
        session.commit()

    denied = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
    )
    assert denied.status_code == 403

    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = "auditor"
        session.commit()

    allowed = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=headers,
        params={"resource_type": "task"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["returned"] == 2
