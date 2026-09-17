from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies import CurrentUserDep, SessionDep, require_org_permission
from backend.app.core.config import settings
from backend.app.core.mfa import derive_totp_secret, verify_totp
from backend.app.core.rbac import Permission, Role
from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.models.membership import Membership
from backend.app.models.organization_invitation import OrganizationInvitation
from backend.app.models.user import User
from backend.app.schemas.auth import AuthResponse, MemberPublic, UserPublic
from backend.app.schemas.membership_admin import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationPublic,
    MemberRoleUpdate,
)
from backend.app.services.audit import record_audit
from backend.app.services.mfa_recovery import consume_recovery_code
from backend.app.services.refresh_sessions import issue_refresh_token
from backend.app.services.security_events import record_user_security_event

router = APIRouter(tags=["membership-administration"])
MembersManageDep = Annotated[
    Membership,
    Depends(require_org_permission(Permission.MEMBERS_MANAGE)),
]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _effective_status(invitation: OrganizationInvitation) -> str:
    if invitation.status == "pending" and _aware(invitation.expires_at) <= _now():
        return "expired"
    return invitation.status


def _public(invitation: OrganizationInvitation) -> InvitationPublic:
    return InvitationPublic(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role=invitation.role,
        status=_effective_status(invitation),
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
    )


def _created(invitation: OrganizationInvitation, token: str) -> InvitationCreated:
    return InvitationCreated(**_public(invitation).model_dump(), token=token)


def _auth_response(session: SessionDep, user: User) -> AuthResponse:
    refresh_issue = issue_refresh_token(session, user.id)
    refresh_expires_in = max(
        0,
        int((_aware(refresh_issue.expires_at) - _now()).total_seconds()),
    )
    return AuthResponse(
        access_token=create_access_token(user.id, session_id=refresh_issue.family_id),
        refresh_token=refresh_issue.token,
        expires_in=settings.auth_access_token_minutes * 60,
        refresh_expires_in=refresh_expires_in,
        user=UserPublic.model_validate(user),
    )


def _assert_assignable(actor_role: str, target_role: str) -> None:
    if target_role == Role.ADMIN.value and actor_role != Role.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners can grant admin authority",
        )


def _membership(
    session: SessionDep,
    organization_id: UUID,
    user_id: UUID,
) -> Membership:
    membership = session.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    return membership


def _assert_manageable(actor_role: str, target_role: str, next_role: str | None = None) -> None:
    if target_role == Role.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner membership cannot be modified",
        )
    if actor_role != Role.OWNER.value:
        if target_role == Role.ADMIN.value or next_role == Role.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can manage admin authority",
            )


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    organization_id: UUID,
    payload: InvitationCreate,
    membership: MembersManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> InvitationCreated:
    _assert_assignable(membership.role, payload.role)
    email = str(payload.email).strip().lower()

    existing_user = session.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        existing_membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == existing_user.id,
            )
        )
        if existing_membership is not None:
            raise HTTPException(status_code=409, detail="User is already an organization member")

    pending = list(
        session.scalars(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == "pending",
            )
        )
    )
    for invitation in pending:
        if _effective_status(invitation) == "pending":
            raise HTTPException(status_code=409, detail="An active invitation already exists")
        invitation.status = "expired"

    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        organization_id=organization_id,
        invited_by_user_id=current_user.id,
        email=email,
        role=payload.role,
        token_hash=_token_hash(token),
        status="pending",
        expires_at=_now() + timedelta(hours=payload.expires_in_hours),
    )
    session.add(invitation)
    session.flush()
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="organization_invitation.created",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"email": email, "role": payload.role},
    )
    session.commit()
    session.refresh(invitation)
    return _created(invitation, token)


@router.get(
    "/organizations/{organization_id}/invitations",
    response_model=list[InvitationPublic],
)
def list_invitations(
    organization_id: UUID,
    _membership: MembersManageDep,
    session: SessionDep,
) -> list[InvitationPublic]:
    invitations = list(
        session.scalars(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc(), OrganizationInvitation.id.desc())
        )
    )
    return [_public(invitation) for invitation in invitations]


@router.delete(
    "/organizations/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(
    organization_id: UUID,
    invitation_id: UUID,
    _membership: MembersManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    invitation = session.get(OrganizationInvitation, invitation_id)
    if invitation is None or invitation.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if _effective_status(invitation) != "pending":
        raise HTTPException(status_code=409, detail="Invitation is no longer active")
    invitation.status = "revoked"
    invitation.revoked_at = _now()
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="organization_invitation.revoked",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"email": invitation.email, "role": invitation.role},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/invitations/accept",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_invitation(payload: InvitationAccept, session: SessionDep) -> AuthResponse:
    invitation = session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == _token_hash(payload.token)
        )
    )
    if invitation is None:
        raise HTTPException(status_code=400, detail="Invalid invitation")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Invitation is no longer active")
    if _aware(invitation.expires_at) <= _now():
        invitation.status = "expired"
        session.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")

    user = session.scalar(select(User).where(User.email == invitation.email))
    recovery_code_used = False
    if user is None:
        user = User(
            email=invitation.email,
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
        )
        session.add(user)
        session.flush()
    else:
        if not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid existing-user credentials")
        if user.mfa_enabled:
            if payload.mfa_code is not None:
                if not user.mfa_nonce:
                    raise HTTPException(status_code=401, detail="Invalid existing-user credentials")
                secret = derive_totp_secret(user.id, user.mfa_nonce)
                if not verify_totp(secret, payload.mfa_code):
                    raise HTTPException(status_code=401, detail="Invalid existing-user credentials")
            elif payload.recovery_code is not None:
                if not consume_recovery_code(session, user.id, payload.recovery_code):
                    raise HTTPException(status_code=401, detail="Invalid existing-user credentials")
                recovery_code_used = True
            else:
                raise HTTPException(status_code=401, detail="Invalid existing-user credentials")

    if session.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    ) is not None:
        raise HTTPException(status_code=409, detail="User is already an organization member")

    session.add(
        Membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
        )
    )
    invitation.status = "accepted"
    invitation.accepted_at = _now()
    if recovery_code_used:
        record_audit(
            session,
            organization_id=invitation.organization_id,
            actor_user_id=user.id,
            action="auth.mfa_recovery_code_used",
            resource_type="user",
            resource_id=str(user.id),
        )
        record_user_security_event(
            session,
            user_id=user.id,
            event_type="mfa_recovery_code_used",
            severity="medium",
            resource_type="user",
            resource_id=str(user.id),
        )
    record_audit(
        session,
        organization_id=invitation.organization_id,
        actor_user_id=user.id,
        action="organization_invitation.accepted",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        details={"role": invitation.role},
    )
    try:
        response = _auth_response(session, user)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Invitation acceptance conflicted") from exc
    session.refresh(user)
    return response


@router.patch(
    "/organizations/{organization_id}/members/{user_id}",
    response_model=MemberPublic,
)
def update_member_role(
    organization_id: UUID,
    user_id: UUID,
    payload: MemberRoleUpdate,
    actor_membership: MembersManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MemberPublic:
    target = _membership(session, organization_id, user_id)
    _assert_manageable(actor_membership.role, target.role, payload.role)
    _assert_assignable(actor_membership.role, payload.role)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    before_role = target.role
    target.role = payload.role
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="organization_membership.role_changed",
        resource_type="membership",
        resource_id=str(user_id),
        details={"before_role": before_role, "after_role": target.role},
    )
    session.commit()
    return MemberPublic(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=target.role,
    )


@router.delete(
    "/organizations/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    organization_id: UUID,
    user_id: UUID,
    actor_membership: MembersManageDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    target = _membership(session, organization_id, user_id)
    _assert_manageable(actor_membership.role, target.role)
    before_role = target.role
    record_audit(
        session,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="organization_membership.removed",
        resource_type="membership",
        resource_id=str(user_id),
        details={"role": before_role},
    )
    session.delete(target)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
