import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.security import decode_access_token_claims
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.audit import AuditLog
from backend.app.models.refresh_token import RefreshToken


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


def register(client: TestClient) -> dict:
    response = client.post("/api/v1/auth/register", json=registration_payload())
    assert response.status_code == 201
    return response.json()


def login(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "founder@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_auth_responses_issue_hashed_refresh_session(client: TestClient) -> None:
    auth = register(client)

    assert auth["refresh_token"]
    assert auth["refresh_expires_in"] > 0
    claims = decode_access_token_claims(auth["access_token"])
    assert claims.session_id is not None

    expected_hash = hashlib.sha256(auth["refresh_token"].encode("utf-8")).hexdigest()
    with client.app.state.testing_session() as session:
        row = session.scalar(
            select(RefreshToken).where(RefreshToken.family_id == claims.session_id)
        )
        assert row is not None
        assert row.token_sha256 == expected_hash
        assert row.token_sha256 != auth["refresh_token"]
        assert len(row.token_sha256) == 64
        assert row.used_at is None
        assert row.revoked_at is None


def test_refresh_rotates_once_and_replay_revokes_family(client: TestClient) -> None:
    auth = register(client)
    original_refresh = auth["refresh_token"]
    family_id = decode_access_token_claims(auth["access_token"]).session_id
    assert family_id is not None

    rotated = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert rotated.status_code == 200
    rotated_auth = rotated.json()
    assert rotated_auth["refresh_token"] != original_refresh
    assert decode_access_token_claims(rotated_auth["access_token"]).session_id == family_id

    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert replay.status_code == 401

    family_after_replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated_auth["refresh_token"]},
    )
    assert family_after_replay.status_code == 401

    with client.app.state.testing_session() as session:
        rows = list(
            session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == family_id)
            )
        )
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)
        reuse_audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "auth.refresh_reuse_detected")
        )
        assert reuse_audit is not None
        assert original_refresh not in str(reuse_audit.details)
        assert hashlib.sha256(original_refresh.encode()).hexdigest() not in str(
            reuse_audit.details
        )


def test_refresh_replay_isolated_from_second_login(client: TestClient) -> None:
    first = register(client)
    second = login(client)
    first_family = decode_access_token_claims(first["access_token"]).session_id
    second_family = decode_access_token_claims(second["access_token"]).session_id
    assert first_family is not None
    assert second_family is not None
    assert first_family != second_family

    first_rotation = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert first_rotation.status_code == 200
    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert replay.status_code == 401

    second_rotation = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second["refresh_token"]},
    )
    assert second_rotation.status_code == 200
    assert (
        decode_access_token_claims(second_rotation.json()["access_token"]).session_id
        == second_family
    )


def test_logout_revokes_associated_refresh_family(client: TestClient) -> None:
    first = register(client)
    second = login(client)

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert logout.status_code == 204

    revoked_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second["refresh_token"]},
    )
    assert revoked_refresh.status_code == 401

    independent_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert independent_refresh.status_code == 200


def test_invitation_acceptance_issues_refresh_session(client: TestClient) -> None:
    owner = register(client)
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=owner_headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]

    invitation = client.post(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": "member@example.com", "role": "member", "expires_in_hours": 24},
    )
    assert invitation.status_code == 201

    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invitation.json()["token"],
            "display_name": "Member",
            "password": "another correct horse password",
        },
    )
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["refresh_token"]
    assert body["refresh_expires_in"] > 0
    assert decode_access_token_claims(body["access_token"]).session_id is not None
