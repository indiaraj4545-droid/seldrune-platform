import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.login_failure import LoginFailure
from backend.app.services.login_throttle import login_throttle_key


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


def _registration_payload() -> dict[str, str]:
    return {
        "email": "founder@example.com",
        "password": "correct horse battery staple",
        "display_name": "Founder",
        "organization_name": "Seldrune",
        "organization_slug": "seldrune",
    }


def _login(client: TestClient, email: str, password: str, **kwargs):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        **kwargs,
    )


def test_known_and_unknown_logins_share_throttle_behavior(client_and_session) -> None:
    client, testing_session = client_and_session
    assert client.post("/api/v1/auth/register", json=_registration_payload()).status_code == 201

    for email in ("founder@example.com", "missing@example.com"):
        for _ in range(4):
            response = _login(client, email, "wrong-password")
            assert response.status_code == 401
            assert response.json()["detail"] == "Invalid email or password"

        limited = _login(client, email, "wrong-password")
        assert limited.status_code == 429
        assert limited.json()["detail"] == "Too many login attempts. Try again later."
        assert int(limited.headers["Retry-After"]) >= 1

    with testing_session() as session:
        rows = list(session.scalars(select(LoginFailure)))
        assert len(rows) == 10
        for row in rows:
            assert len(row.throttle_key_sha256) == 64
            assert "founder@example.com" not in row.throttle_key_sha256
            assert "missing@example.com" not in row.throttle_key_sha256
            assert "testclient" not in row.throttle_key_sha256


def test_successful_login_clears_failures_for_that_pair(client_and_session) -> None:
    client, testing_session = client_and_session
    assert client.post("/api/v1/auth/register", json=_registration_payload()).status_code == 201

    for _ in range(3):
        assert _login(client, "founder@example.com", "wrong-password").status_code == 401

    success = _login(
        client,
        "founder@example.com",
        "correct horse battery staple",
    )
    assert success.status_code == 200

    key = login_throttle_key("founder@example.com", "testclient")
    with testing_session() as session:
        remaining = list(
            session.scalars(
                select(LoginFailure).where(LoginFailure.throttle_key_sha256 == key)
            )
        )
        assert remaining == []

    for _ in range(4):
        assert _login(client, "founder@example.com", "wrong-password").status_code == 401
    assert _login(client, "founder@example.com", "wrong-password").status_code == 429


def test_throttle_is_source_scoped_and_ignores_forwarded_header(client_and_session) -> None:
    client, _testing_session = client_and_session
    assert client.post("/api/v1/auth/register", json=_registration_payload()).status_code == 201

    for attempt in range(5):
        response = _login(
            client,
            "founder@example.com",
            "wrong-password",
            headers={"X-Forwarded-For": f"203.0.113.{attempt + 1}"},
        )
    assert response.status_code == 429

    with TestClient(app, client=("different-source", 50000)) as second_source:
        success = _login(
            second_source,
            "founder@example.com",
            "correct horse battery staple",
        )
        assert success.status_code == 200


def test_throttle_key_changes_with_credential_or_source() -> None:
    first = login_throttle_key("founder@example.com", "source-a")
    different_source = login_throttle_key("founder@example.com", "source-b")
    different_credential = login_throttle_key("other@example.com", "source-a")

    assert len(first) == 64
    assert first != different_source
    assert first != different_credential
