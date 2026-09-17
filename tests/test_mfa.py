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
from backend.app.models.organization import Organization
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
            "email": "mfa-founder@example.com",
            "password": PASSWORD,
            "display_name": "MFA Founder",
            "organization_name": "MFA Organization",
            "organization_slug": "mfa-organization",
        },
    )
    assert response.status_code == 201
    auth = response.json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return auth, headers, organization_id


def _setup_and_enable(client: TestClient, headers: dict[str, str]) -> str:
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


def test_mfa_setup_rotation_login_disable_and_non_disclosure(client: TestClient) -> None:
    registration, headers, _ = _register_owner(client)
    original_refresh = registration["refresh_token"]

    status_before = client.get("/api/v1/auth/mfa", headers=headers)
    assert status_before.status_code == 200
    assert status_before.json() == {"enabled": False, "setup_pending": False}

    wrong_password = client.post(
        "/api/v1/auth/mfa/setup",
        headers=headers,
        json={"password": "wrong-password"},
    )
    assert wrong_password.status_code == 401

    first_setup = client.post(
        "/api/v1/auth/mfa/setup",
        headers=headers,
        json={"password": PASSWORD},
    )
    assert first_setup.status_code == 200
    first_secret = first_setup.json()["secret"]
    assert first_secret in first_setup.json()["otpauth_uri"]

    second_setup = client.post(
        "/api/v1/auth/mfa/setup",
        headers=headers,
        json={"password": PASSWORD},
    )
    assert second_setup.status_code == 200
    second_secret = second_setup.json()["secret"]
    assert second_secret != first_secret

    old_code = client.post(
        "/api/v1/auth/mfa/enable",
        headers=headers,
        json={"code": totp_code(first_secret)},
    )
    assert old_code.status_code == 400

    enable_code = totp_code(second_secret)
    enabled = client.post(
        "/api/v1/auth/mfa/enable",
        headers=headers,
        json={"code": enable_code},
    )
    assert enabled.status_code == 200

    revoked_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert revoked_refresh.status_code == 401

    missing_mfa = client.post(
        "/api/v1/auth/login",
        json={"email": "mfa-founder@example.com", "password": PASSWORD},
    )
    assert missing_mfa.status_code == 401

    bad_mfa = client.post(
        "/api/v1/auth/login",
        json={
            "email": "mfa-founder@example.com",
            "password": PASSWORD,
            "mfa_code": "000000" if enable_code != "000000" else "000001",
        },
    )
    assert bad_mfa.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "mfa-founder@example.com",
            "password": PASSWORD,
            "mfa_code": totp_code(second_secret),
        },
    )
    assert login.status_code == 200
    login_auth = login.json()
    login_headers = {"Authorization": f"Bearer {login_auth['access_token']}"}

    with client.app.state.testing_session() as session:
        user = session.scalar(select(User).where(User.email == "mfa-founder@example.com"))
        assert user is not None
        assert user.mfa_enabled is True
        assert user.mfa_nonce is not None
        assert user.mfa_nonce != second_secret

    bad_disable = client.post(
        "/api/v1/auth/mfa/disable",
        headers=login_headers,
        json={"password": "wrong-password", "code": totp_code(second_secret)},
    )
    assert bad_disable.status_code == 401

    disabled = client.post(
        "/api/v1/auth/mfa/disable",
        headers=login_headers,
        json={"password": PASSWORD, "code": totp_code(second_secret)},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False, "setup_pending": False}

    revoked_after_disable = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_auth["refresh_token"]},
    )
    assert revoked_after_disable.status_code == 401

    password_only_login = client.post(
        "/api/v1/auth/login",
        json={"email": "mfa-founder@example.com", "password": PASSWORD},
    )
    assert password_only_login.status_code == 200

    with client.app.state.testing_session() as session:
        user = session.scalar(select(User).where(User.email == "mfa-founder@example.com"))
        assert user is not None
        assert user.mfa_enabled is False
        assert user.mfa_nonce is None
        audits = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(["auth.mfa_enabled", "auth.mfa_disabled"])
                )
            )
        )
        assert {audit.action for audit in audits} == {"auth.mfa_enabled", "auth.mfa_disabled"}
        assert all(audit.details == {} for audit in audits)
        audit_text = str([audit.details for audit in audits])
        assert first_secret not in audit_text
        assert second_secret not in audit_text
        assert enable_code not in audit_text


def test_invalid_mfa_codes_share_login_throttle(client: TestClient) -> None:
    _, headers, _ = _register_owner(client)
    secret = _setup_and_enable(client, headers)
    valid_code = totp_code(secret)
    wrong_code = "000000" if valid_code != "000000" else "000001"

    for _ in range(4):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "mfa-founder@example.com",
                "password": PASSWORD,
                "mfa_code": wrong_code,
            },
        )
        assert response.status_code == 401

    limited = client.post(
        "/api/v1/auth/login",
        json={
            "email": "mfa-founder@example.com",
            "password": PASSWORD,
            "mfa_code": wrong_code,
        },
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1

    correct_but_limited = client.post(
        "/api/v1/auth/login",
        json={
            "email": "mfa-founder@example.com",
            "password": PASSWORD,
            "mfa_code": totp_code(secret),
        },
    )
    assert correct_but_limited.status_code == 429


def test_existing_user_invitation_requires_mfa(client: TestClient) -> None:
    _, owner_headers, first_organization_id = _register_owner(client)

    first_invitation = client.post(
        f"/api/v1/organizations/{first_organization_id}/invitations",
        headers=owner_headers,
        json={"email": "mfa-member@example.com", "role": "member"},
    )
    assert first_invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": first_invitation.json()["token"],
            "display_name": "MFA Member",
            "password": PASSWORD,
        },
    )
    assert accepted.status_code == 201
    member_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    member_secret = _setup_and_enable(client, member_headers)

    owner_profile = client.get("/api/v1/auth/me", headers=owner_headers).json()
    owner_user_id = owner_profile["user"]["id"]
    with client.app.state.testing_session() as session:
        second = Organization(name="Second MFA Org", slug="second-mfa-org")
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
        json={"email": "mfa-member@example.com", "role": "auditor"},
    )
    assert second_invitation.status_code == 201
    token = second_invitation.json()["token"]

    missing_code = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "display_name": "MFA Member",
            "password": PASSWORD,
        },
    )
    assert missing_code.status_code == 401

    wrong_code = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "display_name": "MFA Member",
            "password": PASSWORD,
            "mfa_code": "000000" if totp_code(member_secret) != "000000" else "000001",
        },
    )
    assert wrong_code.status_code == 401

    success = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "display_name": "MFA Member",
            "password": PASSWORD,
            "mfa_code": totp_code(member_secret),
        },
    )
    assert success.status_code == 201
