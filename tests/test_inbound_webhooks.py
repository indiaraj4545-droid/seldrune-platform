import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

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
from backend.app.models.membership import Membership
from backend.app.models.organization import Organization
from backend.app.models.secret_reference import SecretReference

WEBHOOK_SECRET = "seldrune-test-webhook-secret"
WEBHOOK_SECRET_ENV = "SELDRUNE_TEST_WEBHOOK_SECRET"


@pytest.fixture
def webhook_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(WEBHOOK_SECRET_ENV, WEBHOOK_SECRET)
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
            "email": "webhook-founder@example.com",
            "password": "correct horse battery staple",
            "display_name": "Webhook Founder",
            "organization_name": "Seldrune Webhooks",
            "organization_slug": "seldrune-webhooks",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers).json()
    organization_id = profile["memberships"][0]["organization"]["id"]
    return headers, organization_id, profile["user"]["id"]


def create_secret_reference(testing_session, organization_id: str, *, slug: str) -> str:
    with testing_session() as session:
        reference = SecretReference(
            organization_id=UUID(organization_id),
            name=f"Webhook secret {slug}",
            slug=slug,
            provider="env",
            locator=WEBHOOK_SECRET_ENV,
            status="active",
        )
        session.add(reference)
        session.commit()
        session.refresh(reference)
        return str(reference.id)


def create_endpoint(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
    secret_reference_id: str,
    *,
    slug: str = "crm-events",
    max_payload_bytes: int = 4096,
) -> dict:
    response = client.post(
        f"/api/v1/organizations/{organization_id}/webhooks",
        headers=headers,
        json={
            "name": "CRM Events",
            "slug": slug,
            "secret_reference_id": secret_reference_id,
            "allowed_event_types": ["crm.contact.updated"],
            "max_payload_bytes": max_payload_bytes,
        },
    )
    assert response.status_code == 201
    return response.json()


def signed_headers(
    body: bytes,
    *,
    delivery_id: str = "delivery-1",
    event_type: str = "crm.contact.updated",
    timestamp: str | None = None,
    secret: str = WEBHOOK_SECRET,
) -> dict[str, str]:
    timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    signed = timestamp.encode("utf-8") + b"." + body
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Seldrune-Delivery": delivery_id,
        "X-Seldrune-Event": event_type,
        "X-Seldrune-Timestamp": timestamp,
        "X-Seldrune-Signature": f"sha256={signature}",
    }


def test_signed_webhook_accepts_deduplicates_and_lists_event(webhook_client) -> None:
    client, testing_session = webhook_client
    headers, organization_id, _ = register_owner(client)
    secret_id = create_secret_reference(testing_session, organization_id, slug="crm-secret")
    endpoint = create_endpoint(client, headers, organization_id, secret_id)
    body = json.dumps(
        {"contact_id": "c-1", "status": "active"},
        separators=(",", ":"),
    ).encode("utf-8")
    receiver = f"/api/v1/webhooks/{endpoint['id']}"
    inbound_headers = signed_headers(body)

    accepted = client.post(receiver, content=body, headers=inbound_headers)
    assert accepted.status_code == 202
    receipt = accepted.json()
    assert receipt["duplicate"] is False

    duplicate = client.post(receiver, content=body, headers=inbound_headers)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["event_id"] == receipt["event_id"]

    events = client.get(
        f"/api/v1/organizations/{organization_id}/webhook-events",
        headers=headers,
    )
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["payload_json"] == {"contact_id": "c-1", "status": "active"}

    changed_body = b'{"contact_id":"c-1","status":"inactive"}'
    conflict = client.post(
        receiver,
        content=changed_body,
        headers=signed_headers(changed_body),
    )
    assert conflict.status_code == 409


def test_webhook_rejects_invalid_replayed_disallowed_and_disabled(webhook_client) -> None:
    client, testing_session = webhook_client
    headers, organization_id, _ = register_owner(client)
    secret_id = create_secret_reference(testing_session, organization_id, slug="guard-secret")
    endpoint = create_endpoint(client, headers, organization_id, secret_id, slug="guarded")
    receiver = f"/api/v1/webhooks/{endpoint['id']}"
    body = b'{"message":"hello"}'

    invalid = signed_headers(body, delivery_id="invalid-1")
    invalid["X-Seldrune-Signature"] = "sha256=" + ("0" * 64)
    assert client.post(receiver, content=body, headers=invalid).status_code == 401

    stale_timestamp = str(int(datetime.now(UTC).timestamp()) - 600)
    stale = signed_headers(body, delivery_id="stale-1", timestamp=stale_timestamp)
    assert client.post(receiver, content=body, headers=stale).status_code == 400

    disallowed = signed_headers(
        body,
        delivery_id="disallowed-1",
        event_type="crm.contact.deleted",
    )
    assert client.post(receiver, content=body, headers=disallowed).status_code == 403

    disabled = client.patch(
        f"/api/v1/organizations/{organization_id}/webhooks/{endpoint['id']}",
        headers=headers,
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    allowed = signed_headers(body, delivery_id="disabled-1")
    assert client.post(receiver, content=body, headers=allowed).status_code == 404


def test_webhook_enforces_payload_bound_and_runtime_secret(webhook_client, monkeypatch) -> None:
    client, testing_session = webhook_client
    headers, organization_id, _ = register_owner(client)
    secret_id = create_secret_reference(testing_session, organization_id, slug="bounded-secret")
    endpoint = create_endpoint(
        client,
        headers,
        organization_id,
        secret_id,
        slug="bounded",
        max_payload_bytes=1024,
    )
    receiver = f"/api/v1/webhooks/{endpoint['id']}"

    oversized = json.dumps({"data": "x" * 1100}).encode("utf-8")
    response = client.post(receiver, content=oversized, headers=signed_headers(oversized))
    assert response.status_code == 413

    monkeypatch.delenv(WEBHOOK_SECRET_ENV)
    body = b'{"data":"small"}'
    unavailable = client.post(
        receiver,
        content=body,
        headers=signed_headers(body, delivery_id="missing-secret-1"),
    )
    assert unavailable.status_code == 503


def test_webhook_permissions_and_tenant_secret_isolation(webhook_client) -> None:
    assert has_permission(Role.OWNER, Permission.WEBHOOKS_MANAGE)
    assert has_permission(Role.ADMIN, Permission.WEBHOOKS_MANAGE)
    assert has_permission(Role.ADMIN, Permission.WEBHOOKS_READ)
    assert has_permission(Role.AUDITOR, Permission.WEBHOOKS_READ)
    assert not has_permission(Role.AUDITOR, Permission.WEBHOOKS_MANAGE)
    assert not has_permission(Role.MEMBER, Permission.WEBHOOKS_READ)
    assert not has_permission(Role.MEMBER, Permission.WEBHOOKS_MANAGE)

    client, testing_session = webhook_client
    headers, organization_id, user_id = register_owner(client)
    first_secret_id = create_secret_reference(
        testing_session,
        organization_id,
        slug="first-org-secret",
    )

    with testing_session() as session:
        second = Organization(name="Second Webhook Org", slug="second-webhook-org")
        session.add(second)
        session.flush()
        session.add(
            Membership(
                organization_id=second.id,
                user_id=UUID(user_id),
                role="owner",
            )
        )
        session.commit()
        second_id = str(second.id)

    cross_secret = client.post(
        f"/api/v1/organizations/{second_id}/webhooks",
        headers=headers,
        json={
            "name": "Cross Tenant",
            "slug": "cross-tenant",
            "secret_reference_id": first_secret_id,
            "allowed_event_types": ["crm.contact.updated"],
        },
    )
    assert cross_secret.status_code == 400

    endpoint = create_endpoint(client, headers, organization_id, first_secret_id)
    second_list = client.get(
        f"/api/v1/organizations/{second_id}/webhooks",
        headers=headers,
    )
    assert second_list.status_code == 200
    assert second_list.json() == []

    body = b'{"contact_id":"tenant-a"}'
    accepted = client.post(
        f"/api/v1/webhooks/{endpoint['id']}",
        content=body,
        headers=signed_headers(body, delivery_id="tenant-a-1"),
    )
    assert accepted.status_code == 202
    second_events = client.get(
        f"/api/v1/organizations/{second_id}/webhook-events",
        headers=headers,
    )
    assert second_events.status_code == 200
    assert second_events.json() == []
