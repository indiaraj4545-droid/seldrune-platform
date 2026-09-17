from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.rbac import Permission, Role, has_permission
from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invite_user(
    client,
    organization_id: str,
    owner_headers: dict[str, str],
    *,
    email: str,
    role: str,
) -> dict[str, str]:
    invitation = client.post(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=owner_headers,
        json={"email": email, "role": role, "expires_in_hours": 24},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invitation.json()["token"],
            "display_name": f"{role.title()} Security User",
            "password": f"{role}-security-password-123",
        },
    )
    assert accepted.status_code == 201
    return _headers(accepted.json()["access_token"])


def _produce_refresh_reuse(client) -> tuple[str, dict[str, str]]:
    owner_token, organization_id = register_owner(client)
    owner_headers = _headers(owner_token)
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "autonomy-founder@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert login.status_code == 200
    original_refresh = login.json()["refresh_token"]

    rotated = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert rotated.status_code == 200
    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert replay.status_code == 401
    return organization_id, owner_headers


def test_security_permissions() -> None:
    assert has_permission(Role.OWNER, Permission.SECURITY_READ)
    assert has_permission(Role.OWNER, Permission.SECURITY_MANAGE)
    assert has_permission(Role.ADMIN, Permission.SECURITY_READ)
    assert has_permission(Role.ADMIN, Permission.SECURITY_MANAGE)
    assert has_permission(Role.AUDITOR, Permission.SECURITY_READ)
    assert not has_permission(Role.AUDITOR, Permission.SECURITY_MANAGE)
    assert not has_permission(Role.MEMBER, Permission.SECURITY_READ)
    assert not has_permission(Role.MEMBER, Permission.SECURITY_MANAGE)


def test_refresh_reuse_security_event_lifecycle_and_owner_attention(client) -> None:
    organization_id, owner_headers = _produce_refresh_reuse(client)

    listed = client.get(
        f"/api/v1/organizations/{organization_id}/security-events",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    assert page["limit"] == 100
    assert page["offset"] == 0
    event = page["items"][0]
    assert event["event_type"] == "refresh_token_reuse"
    assert event["severity"] == "critical"
    assert event["status"] == "open"
    assert event["resource_type"] == "user"
    assert event["details"] == {}
    event_id = event["id"]

    detail = client.get(
        f"/api/v1/organizations/{organization_id}/security-events/{event_id}",
        headers=owner_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == event_id

    filtered = client.get(
        f"/api/v1/organizations/{organization_id}/security-events",
        headers=owner_headers,
        params={
            "severity": "critical",
            "status": "open",
            "event_type": "refresh_token_reuse",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1

    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/security-events",
            headers=owner_headers,
            params={"limit": 501},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/security-events",
            headers=owner_headers,
            params={"offset": -1},
        ).status_code
        == 422
    )

    attention = client.get(
        f"/api/v1/organizations/{organization_id}/owner-attention",
        headers=owner_headers,
    )
    assert attention.status_code == 200
    attention_payload = attention.json()
    security_items = [
        item for item in attention_payload["items"] if item["category"] == "security"
    ]
    assert len(security_items) == 1
    assert security_items[0]["kind"] == "critical_security_event"
    assert security_items[0]["resource_id"] == event_id
    assert attention_payload["summary"]["critical"] >= 1

    envelope = client.get(
        f"/api/v1/organizations/{organization_id}/owner-attention/notification-envelope",
        headers=owner_headers,
    )
    assert envelope.status_code == 200
    notification = envelope.json()
    assert notification["privacy"]["detail_level"] == "counts_only"
    assert notification["privacy"]["contains_resource_ids"] is False
    assert notification["summary"]["critical"] >= 1
    assert event_id not in str(notification)

    admin_headers = _invite_user(
        client,
        organization_id,
        owner_headers,
        email="security-admin@example.com",
        role="admin",
    )
    member_headers = _invite_user(
        client,
        organization_id,
        owner_headers,
        email="security-member@example.com",
        role="member",
    )
    auditor_headers = _invite_user(
        client,
        organization_id,
        owner_headers,
        email="security-auditor@example.com",
        role="auditor",
    )

    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/security-events",
            headers=admin_headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/security-events",
            headers=auditor_headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/organizations/{organization_id}/security-events",
            headers=member_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/organizations/{organization_id}/security-events/{event_id}/acknowledge",
            headers=auditor_headers,
        ).status_code
        == 403
    )

    acknowledged = client.post(
        f"/api/v1/organizations/{organization_id}/security-events/{event_id}/acknowledge",
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200
    acknowledged_payload = acknowledged.json()
    assert acknowledged_payload["status"] == "acknowledged"
    assert acknowledged_payload["acknowledged_at"] is not None
    first_acknowledged_at = acknowledged_payload["acknowledged_at"]

    repeated = client.post(
        f"/api/v1/organizations/{organization_id}/security-events/{event_id}/acknowledge",
        headers=admin_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["acknowledged_at"] == first_acknowledged_at

    after_attention = client.get(
        f"/api/v1/organizations/{organization_id}/owner-attention",
        headers=owner_headers,
    )
    assert after_attention.status_code == 200
    assert all(
        item["resource_id"] != event_id
        for item in after_attention.json()["items"]
        if item["category"] == "security"
    )

    acknowledged_list = client.get(
        f"/api/v1/organizations/{organization_id}/security-events",
        headers=owner_headers,
        params={"status": "acknowledged"},
    )
    assert acknowledged_list.status_code == 200
    assert acknowledged_list.json()["total"] == 1

    foreign_org = uuid4()
    assert (
        client.get(
            f"/api/v1/organizations/{foreign_org}/security-events/{event_id}",
            headers=owner_headers,
        ).status_code
        == 403
    )

    audit = client.get(
        f"/api/v1/organizations/{organization_id}/audit",
        headers=owner_headers,
        params={"resource_type": "security_event"},
    )
    assert audit.status_code == 200
    audit_items = audit.json()["items"]
    assert len(audit_items) == 1
    assert audit_items[0]["action"] == "security_event.acknowledged"
    assert set(audit_items[0]["details"]) == {"event_type", "severity"}


def test_webhook_authentication_rejection_creates_privacy_safe_warning(
    client,
    monkeypatch,
) -> None:
    owner_token, organization_id = register_owner(client)
    owner_headers = _headers(owner_token)
    secret_value = "security-webhook-test-secret"
    monkeypatch.setenv("SECURITY_WEBHOOK_SECRET", secret_value)

    reference = client.post(
        f"/api/v1/organizations/{organization_id}/secret-references",
        headers=owner_headers,
        json={
            "name": "Security Webhook Secret",
            "slug": "security-webhook-secret",
            "provider": "env",
            "locator": "SECURITY_WEBHOOK_SECRET",
        },
    )
    assert reference.status_code == 201

    endpoint = client.post(
        f"/api/v1/organizations/{organization_id}/webhooks",
        headers=owner_headers,
        json={
            "name": "Security Events",
            "slug": "security-events",
            "secret_reference_id": reference.json()["id"],
            "allowed_event_types": ["security.fixture"],
        },
    )
    assert endpoint.status_code == 201

    body = b'{"private":"payload-marker"}'
    signature = "sha256=" + ("0" * 64)
    rejected = client.post(
        f"/api/v1/webhooks/{endpoint.json()['id']}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Seldrune-Delivery": "security-rejected-1",
            "X-Seldrune-Event": "security.fixture",
            "X-Seldrune-Timestamp": str(int(datetime.now(UTC).timestamp())),
            "X-Seldrune-Signature": signature,
        },
    )
    assert rejected.status_code == 401

    listed = client.get(
        f"/api/v1/organizations/{organization_id}/security-events",
        headers=owner_headers,
        params={"event_type": "webhook_authentication_rejected"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    event = listed.json()["items"][0]
    assert event["severity"] == "warning"
    assert event["status"] == "open"
    assert event["resource_type"] == "webhook_endpoint"
    assert event["resource_id"] == endpoint.json()["id"]
    assert event["details"] == {}
    serialized = str(event)
    assert secret_value not in serialized
    assert signature not in serialized
    assert "payload-marker" not in serialized

    attention = client.get(
        f"/api/v1/organizations/{organization_id}/owner-attention",
        headers=owner_headers,
    )
    assert attention.status_code == 200
    warning_items = [
        item
        for item in attention.json()["items"]
        if item["kind"] == "warning_security_event"
    ]
    assert len(warning_items) == 1
    assert attention.json()["summary"]["warnings"] >= 1
