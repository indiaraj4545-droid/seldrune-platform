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
from backend.app.models.membership import Membership


@pytest.fixture
def budget_client():
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
            "email": "budget-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Budget Founder",
            "organization_name": "Seldrune Budget",
            "organization_slug": "seldrune-budget",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id, profile["user"]["id"]


def set_role(testing_session, organization_id: str, user_id: str, role: str) -> None:
    with testing_session() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == UUID(organization_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert membership is not None
        membership.role = role
        session.commit()


def test_billing_manage_is_owner_only() -> None:
    assert has_permission(Role.OWNER, Permission.BILLING_MANAGE)
    assert not has_permission(Role.ADMIN, Permission.BILLING_MANAGE)
    assert not has_permission(Role.MEMBER, Permission.BILLING_MANAGE)
    assert not has_permission(Role.AUDITOR, Permission.BILLING_MANAGE)


def test_admin_keeps_operations_but_cannot_change_budget_accounting(budget_client) -> None:
    client, testing_session = budget_client
    headers, organization_id, user_id = register_owner(client)
    base = f"/api/v1/organizations/{organization_id}"

    department = client.post(
        f"{base}/departments",
        headers=headers,
        json={
            "name": "Delivery",
            "slug": "delivery",
            "budget_limit_usd": 200,
            "resource_limit_units": 50,
        },
    )
    assert department.status_code == 201
    department_id = department.json()["id"]

    project = client.post(
        f"{base}/projects",
        headers=headers,
        json={
            "name": "Governed budget project",
            "slug": "governed-budget-project",
            "department_id": department_id,
            "budget_limit_usd": 500,
            "budget_spent_usd": 25,
            "resource_limit_units": 100,
            "resource_used_units": 10,
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    set_role(testing_session, organization_id, user_id, "admin")

    operational_update = client.patch(
        f"{base}/projects/{project_id}",
        headers=headers,
        json={"priority": 88, "resource_limit_units": 120},
    )
    assert operational_update.status_code == 200
    assert operational_update.json()["priority"] == 88
    assert operational_update.json()["resource_limit_units"] == 120

    for payload in (
        {"budget_limit_usd": 600},
        {"budget_spent_usd": 30},
        {"resource_used_units": 12},
    ):
        denied = client.patch(
            f"{base}/projects/{project_id}",
            headers=headers,
            json=payload,
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Missing permission: billing:manage"

    capacity_only = client.post(
        f"{base}/projects/{project_id}/resources",
        headers=headers,
        json={"resource_limit_units": 150, "reason": "Increase delivery capacity"},
    )
    assert capacity_only.status_code == 200
    assert capacity_only.json()["resource_limit_units"] == 150
    assert capacity_only.json()["budget_limit_usd"] == 500

    budget_allocation = client.post(
        f"{base}/projects/{project_id}/resources",
        headers=headers,
        json={"budget_limit_usd": 650, "reason": "Increase delivery budget"},
    )
    assert budget_allocation.status_code == 403

    department_budget = client.patch(
        f"{base}/departments/{department_id}",
        headers=headers,
        json={"budget_limit_usd": 250},
    )
    assert department_budget.status_code == 403

    department_operational = client.patch(
        f"{base}/departments/{department_id}",
        headers=headers,
        json={"mission": "Operate governed delivery capacity"},
    )
    assert department_operational.status_code == 200

    admin_budget_project = client.post(
        f"{base}/projects",
        headers=headers,
        json={
            "name": "Admin funded project",
            "slug": "admin-funded-project",
            "budget_limit_usd": 1,
        },
    )
    assert admin_budget_project.status_code == 403

    admin_zero_budget_project = client.post(
        f"{base}/projects",
        headers=headers,
        json={
            "name": "Admin operational project",
            "slug": "admin-operational-project",
            "resource_limit_units": 25,
        },
    )
    assert admin_zero_budget_project.status_code == 201

    set_role(testing_session, organization_id, user_id, "owner")

    owner_correction = client.patch(
        f"{base}/projects/{project_id}",
        headers=headers,
        json={
            "budget_limit_usd": 650,
            "budget_spent_usd": 30,
            "resource_used_units": 12,
        },
    )
    assert owner_correction.status_code == 200
    assert owner_correction.json()["budget_limit_usd"] == 650
    assert owner_correction.json()["budget_spent_usd"] == 30
    assert owner_correction.json()["resource_used_units"] == 12

    audit = client.get(
        f"{base}/audit/resources/organization_project/{project_id}",
        headers=headers,
        params={"action": "organization_project.updated"},
    )
    assert audit.status_code == 200
    accounting = audit.json()["items"][0]["details"]["accounting"]
    assert accounting["budget_limit_usd"] == {"before": 500.0, "after": 650.0}
    assert accounting["budget_spent_usd"] == {"before": 25.0, "after": 30.0}
    assert accounting["resource_used_units"] == {"before": 10, "after": 12}
