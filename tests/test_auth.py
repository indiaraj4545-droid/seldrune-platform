from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.config import settings
from backend.app.core.security import ALGORITHM
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.audit import AuditLog
from backend.app.models.revoked_access_token import RevokedAccessToken


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
    app.state.testing_session = testing_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def registration_payload() -> dict[str, str]:
    return {
        "email": "founder@example.com",
        "password": "correct horse battery staple",
        "display_name": "Founder",
        "organization_name": "Seldrune",
        "organization_slug": "seldrune",
    }


def test_register_login_and_protected_routes(client: TestClient) -> None:
    status_before = client.get("/api/v1/auth/bootstrap-status")
    assert status_before.status_code == 200
    assert status_before.json() == {"required": True}

    register = client.post("/api/v1/auth/register", json=registration_payload())
    assert register.status_code == 201
    registration = register.json()
    assert registration["token_type"] == "bearer"

    status_after = client.get("/api/v1/auth/bootstrap-status")
    assert status_after.status_code == 200
    assert status_after.json() == {"required": False}

    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    profile = me.json()
    assert profile["user"]["email"] == "founder@example.com"
    assert profile["memberships"][0]["role"] == "owner"
    assert "members:read" in profile["memberships"][0]["permissions"]

    organization_id = profile["memberships"][0]["organization"]["id"]
    members = client.get(
        f"/api/v1/organizations/{organization_id}/members",
        headers=headers,
    )
    assert members.status_code == 200
    assert len(members.json()) == 1

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert login.json()["access_token"] != token


def test_logout_revokes_only_the_current_session(client: TestClient) -> None:
    register = client.post("/api/v1/auth/register", json=registration_payload())
    assert register.status_code == 201
    first_token = register.json()["access_token"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    second_token = login.json()["access_token"]
    assert second_token != first_token

    first_headers = {"Authorization": f"Bearer {first_token}"}
    second_headers = {"Authorization": f"Bearer {second_token}"}

    logout = client.post("/api/v1/auth/logout", headers=first_headers)
    assert logout.status_code == 204
    repeated = client.post("/api/v1/auth/logout", headers=first_headers)
    assert repeated.status_code == 204

    assert client.get("/api/v1/auth/me", headers=first_headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=second_headers).status_code == 200

    with client.app.state.testing_session() as session:
        revoked = list(session.scalars(select(RevokedAccessToken)))
        assert len(revoked) == 1
        assert len(revoked[0].token_sha256) == 64
        assert revoked[0].token_sha256 != first_token

        logout_audit = session.scalar(select(AuditLog).where(AuditLog.action == "auth.logout"))
        assert logout_audit is not None
        assert set(logout_audit.details) <= {"family_id"}
        assert first_token not in str(logout_audit.details)
        assert revoked[0].token_sha256 not in str(logout_audit.details)


def test_legacy_access_token_without_jti_remains_valid(client: TestClient) -> None:
    register = client.post("/api/v1/auth/register", json=registration_payload())
    assert register.status_code == 201
    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {register.json()['access_token']}"},
    ).json()
    user_id = profile["user"]["id"]

    now = datetime.now(UTC)
    legacy_token = jwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.auth_secret_key,
        algorithm=ALGORITHM,
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert response.status_code == 200


def test_invalid_logout_token_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 401


def test_unauthenticated_me_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_registration_is_locked_after_first_owner(client: TestClient) -> None:
    first = client.post("/api/v1/auth/register", json=registration_payload())
    assert first.status_code == 201

    second_payload = {
        **registration_payload(),
        "email": "attacker@example.com",
        "organization_name": "Other",
        "organization_slug": "other",
    }
    second = client.post("/api/v1/auth/register", json=second_payload)
    assert second.status_code == 403
    assert second.json()["detail"] == "Owner onboarding is already complete"


def test_wrong_password_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "definitely-wrong"},
    )
    assert response.status_code == 401
