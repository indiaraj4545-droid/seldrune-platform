from datetime import UTC, datetime, timedelta

import backend.app.api.routes.membership_admin as membership_admin
from tests.test_autonomous_execution import register_owner

pytest_plugins = ["tests.test_autonomous_execution"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invite(client, organization_id: str, headers: dict[str, str], email: str, role: str):
    response = client.post(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=headers,
        json={"email": email, "role": role, "expires_in_hours": 24},
    )
    assert response.status_code == 201
    return response.json()


def _accept(client, token: str, display_name: str, password: str):
    return client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "display_name": display_name,
            "password": password,
        },
    )


def test_invitation_onboards_member_and_token_is_one_time(client) -> None:
    owner_token, organization_id = register_owner(client)
    owner_headers = _headers(owner_token)

    invitation = _invite(
        client,
        organization_id,
        owner_headers,
        "new-member@example.com",
        "member",
    )
    assert invitation["status"] == "pending"
    assert invitation["token"]

    listed = client.get(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "token" not in listed.json()[0]

    accepted = _accept(
        client,
        invitation["token"],
        "New Member",
        "member-password-123",
    )
    assert accepted.status_code == 201
    member_token = accepted.json()["access_token"]
    member_headers = _headers(member_token)

    profile = client.get("/api/v1/auth/me", headers=member_headers)
    assert profile.status_code == 200
    assert profile.json()["memberships"][0]["organization"]["id"] == organization_id
    assert profile.json()["memberships"][0]["role"] == "member"

    replay = _accept(
        client,
        invitation["token"],
        "New Member",
        "member-password-123",
    )
    assert replay.status_code == 409

    members = client.get(
        f"/api/v1/organizations/{organization_id}/members",
        headers=owner_headers,
    )
    member = next(item for item in members.json() if item["email"] == "new-member@example.com")

    promoted = client.patch(
        f"/api/v1/organizations/{organization_id}/members/{member['id']}",
        headers=owner_headers,
        json={"role": "auditor"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "auditor"

    removed = client.delete(
        f"/api/v1/organizations/{organization_id}/members/{member['id']}",
        headers=owner_headers,
    )
    assert removed.status_code == 204


def test_admin_role_ceiling_and_invitation_revocation(client) -> None:
    owner_token, organization_id = register_owner(client)
    owner_headers = _headers(owner_token)
    owner_profile = client.get("/api/v1/auth/me", headers=owner_headers).json()
    owner_user_id = owner_profile["user"]["id"]

    admin_invite = _invite(
        client,
        organization_id,
        owner_headers,
        "admin@example.com",
        "admin",
    )
    admin_accept = _accept(
        client,
        admin_invite["token"],
        "Organization Admin",
        "admin-password-123",
    )
    assert admin_accept.status_code == 201
    admin_headers = _headers(admin_accept.json()["access_token"])

    member_invite = _invite(
        client,
        organization_id,
        owner_headers,
        "managed-member@example.com",
        "member",
    )
    member_accept = _accept(
        client,
        member_invite["token"],
        "Managed Member",
        "managed-password-123",
    )
    assert member_accept.status_code == 201

    members = client.get(
        f"/api/v1/organizations/{organization_id}/members",
        headers=owner_headers,
    ).json()
    member_id = next(item["id"] for item in members if item["email"] == "managed-member@example.com")

    forbidden_admin_invite = client.post(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=admin_headers,
        json={"email": "peer-admin@example.com", "role": "admin"},
    )
    assert forbidden_admin_invite.status_code == 403

    ordinary_invite = _invite(
        client,
        organization_id,
        admin_headers,
        "auditor@example.com",
        "auditor",
    )
    revoked = client.delete(
        f"/api/v1/organizations/{organization_id}/invitations/{ordinary_invite['id']}",
        headers=admin_headers,
    )
    assert revoked.status_code == 204
    assert (
        _accept(
            client,
            ordinary_invite["token"],
            "Revoked Auditor",
            "auditor-password-123",
        ).status_code
        == 409
    )

    changed = client.patch(
        f"/api/v1/organizations/{organization_id}/members/{member_id}",
        headers=admin_headers,
        json={"role": "auditor"},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "auditor"

    forbidden_promotion = client.patch(
        f"/api/v1/organizations/{organization_id}/members/{member_id}",
        headers=admin_headers,
        json={"role": "admin"},
    )
    assert forbidden_promotion.status_code == 403

    assert (
        client.patch(
            f"/api/v1/organizations/{organization_id}/members/{owner_user_id}",
            headers=admin_headers,
            json={"role": "member"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/organizations/{organization_id}/members/{owner_user_id}",
            headers=admin_headers,
        ).status_code
        == 403
    )

    removed = client.delete(
        f"/api/v1/organizations/{organization_id}/members/{member_id}",
        headers=admin_headers,
    )
    assert removed.status_code == 204


def test_invitation_expiry_is_enforced(client, monkeypatch) -> None:
    owner_token, organization_id = register_owner(client)
    owner_headers = _headers(owner_token)
    baseline = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(membership_admin, "_now", lambda: baseline)

    response = client.post(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=owner_headers,
        json={
            "email": "expiring-member@example.com",
            "role": "member",
            "expires_in_hours": 1,
        },
    )
    assert response.status_code == 201
    invitation = response.json()

    monkeypatch.setattr(
        membership_admin,
        "_now",
        lambda: baseline + timedelta(hours=2),
    )
    expired = _accept(
        client,
        invitation["token"],
        "Expired Member",
        "expired-password-123",
    )
    assert expired.status_code == 410

    listed = client.get(
        f"/api/v1/organizations/{organization_id}/invitations",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "expired"
