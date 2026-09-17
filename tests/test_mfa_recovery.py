from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.core.mfa import totp_code
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.audit import AuditLog
from backend.app.models.membership import Membership
from backend.app.models.mfa_recovery_code import MfaRecoveryCode
from backend.app.models.organization import Organization
from backend.app.models.security_event import SecurityEvent
from backend.app.models.user import User

PASSWORD = "correct horse battery staple"


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


def _register_owner(client: TestClient) -> tuple[dict, dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "display_name": "Recovery Founder",
            "organization_name": "Recovery Organization",
            "organization_slug": "recovery-organization",
        },
    )
    assert response.status_code == 201
    auth = response.json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return auth, headers, organization_id


def _enable_mfa(client: TestClient, headers: dict[str, str]) -> str:
    setup = client.post(
        "/api/v1/auth/mfa/setup",
        headers=headers,
        json={"password": PASSWORD},
    )
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    enabled = client.post(
        "/api/v1/auth/mfa/enable",
        headers=headers,
        json={"code": totp_code(secret)},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True, "setup_pending": False}
    return secret


def _generate_codes(
    client: TestClient,
    headers: dict[str, str],
    secret: str,
) -> list[str]:
    response = client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers=headers,
        json={"password": PASSWORD, "code": totp_code(secret)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recovery_codes_remaining"] == 10
    assert len(body["recovery_codes"]) == 10
    assert len(set(body["recovery_codes"])) == 10
    return body["recovery_codes"]


def test_recovery_codes_are_one_time_hashed_and_regenerable(client: TestClient) -> None:
    _, headers, _ = _register_owner(client)
    secret = _enable_mfa(client, headers)

    status_before = client.get(
        "/api/v1/auth/mfa/recovery-codes/status",
        headers=headers,
    )
    assert status_before.status_code == 200
    assert status_before.json() == {"recovery_codes_remaining": 0}

    codes = _generate_codes(client, headers, secret)
    first_code = codes[0]
    second_code = codes[1]

    with client.app.state.testing_session() as session:
        user = session.scalar(select(User).where(User.email == "recovery-founder@example.com"))
        assert user is not None
        rows = list(
            session.scalars(
                select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id)
            )
        )
        assert len(rows) == 10
        assert all(len(row.code_digest) == 64 for row in rows)
        assert all(row.code_digest not in codes for row in rows)

    recovered_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "recovery_code": first_code,
        },
    )
    assert recovered_login.status_code == 200

    status_after_use = client.get(
        "/api/v1/auth/mfa/recovery-codes/status",
        headers=headers,
    )
    assert status_after_use.status_code == 200
    assert status_after_use.json() == {"recovery_codes_remaining": 9}

    reused = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "recovery_code": first_code,
        },
    )
    assert reused.status_code == 401

    replacement_codes = _generate_codes(client, headers, secret)
    assert set(replacement_codes).isdisjoint(codes)

    invalidated_old_code = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "recovery_code": second_code,
        },
    )
    assert invalidated_old_code.status_code == 401

    replacement_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "recovery_code": replacement_codes[0],
        },
    )
    assert replacement_login.status_code == 200

    with client.app.state.testing_session() as session:
        audits = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        [
                            "auth.mfa_recovery_code_used",
                            "auth.mfa_recovery_codes_regenerated",
                        ]
                    )
                )
            )
        )
        events = list(
            session.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.event_type.in_(
                        [
                            "mfa_recovery_code_used",
                            "mfa_recovery_codes_regenerated",
                        ]
                    )
                )
            )
        )
        assert audits
        assert events
        disclosure_text = str(
            [audit.details for audit in audits] + [event.details for event in events]
        )
        for code in codes + replacement_codes:
            assert code not in disclosure_text


def test_recovery_code_can_disable_mfa_and_revokes_refresh(client: TestClient) -> None:
    _, headers, _ = _register_owner(client)
    secret = _enable_mfa(client, headers)
    codes = _generate_codes(client, headers, secret)

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-founder@example.com",
            "password": PASSWORD,
            "mfa_code": totp_code(secret),
        },
    )
    assert login.status_code == 200
    login_auth = login.json()
    login_headers = {"Authorization": f"Bearer {login_auth['access_token']}"}

    disabled = client.post(
        "/api/v1/auth/mfa/disable",
        headers=login_headers,
        json={"password": PASSWORD, "recovery_code": codes[0]},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False, "setup_pending": False}

    revoked_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_auth["refresh_token"]},
    )
    assert revoked_refresh.status_code == 401

    status = client.get(
        "/api/v1/auth/mfa/recovery-codes/status",
        headers=login_headers,
    )
    assert status.status_code == 200
    assert status.json() == {"recovery_codes_remaining": 0}


def test_existing_user_invitation_accepts_one_recovery_code(client: TestClient) -> None:
    _, owner_headers, first_organization_id = _register_owner(client)

    first_invitation = client.post(
        f"/api/v1/organizations/{first_organization_id}/invitations",
        headers=owner_headers,
        json={"email": "recovery-member@example.com", "role": "member"},
    )
    assert first_invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": first_invitation.json()["token"],
            "display_name": "Recovery Member",
            "password": PASSWORD,
        },
    )
    assert accepted.status_code == 201
    member_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    member_secret = _enable_mfa(client, member_headers)
    recovery_codes = _generate_codes(client, member_headers, member_secret)

    owner_profile = client.get("/api/v1/auth/me", headers=owner_headers).json()
    owner_user_id = owner_profile["user"]["id"]
    with client.app.state.testing_session() as session:
        second = Organization(name="Second Recovery Org", slug="second-recovery-org")
        session.add(second)
        session.flush()
        session.add(
            Membership(
                organization_id=second.id,
                user_id=UUID(owner_user_id),
                role="owner",
            )
        )
        session.commit()
        second_organization_id = str(second.id)

    second_invitation = client.post(
        f"/api/v1/organizations/{second_organization_id}/invitations",
        headers=owner_headers,
        json={"email": "recovery-member@example.com", "role": "auditor"},
    )
    assert second_invitation.status_code == 201

    success = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": second_invitation.json()["token"],
            "display_name": "Recovery Member",
            "password": PASSWORD,
            "recovery_code": recovery_codes[0],
        },
    )
    assert success.status_code == 201

    reused = client.post(
        "/api/v1/auth/login",
        json={
            "email": "recovery-member@example.com",
            "password": PASSWORD,
            "recovery_code": recovery_codes[0],
        },
    )
    assert reused.status_code == 401
