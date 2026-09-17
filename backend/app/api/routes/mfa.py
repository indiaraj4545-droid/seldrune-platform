from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status

from backend.app.api.dependencies import CurrentUserDep, SessionDep
from backend.app.core.mfa import build_totp_uri, derive_totp_secret, verify_totp
from backend.app.core.security import verify_password
from backend.app.schemas.mfa import (
    MfaCodeRequest,
    MfaDisableRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaStatus,
)
from backend.app.services.audit import record_audit
from backend.app.services.refresh_sessions import revoke_user_refresh_sessions

router = APIRouter(prefix="/auth/mfa", tags=["auth"])


def _invalid_reauthentication() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid current credentials",
    )


@router.get("", response_model=MfaStatus)
def mfa_status(current_user: CurrentUserDep) -> MfaStatus:
    return MfaStatus(
        enabled=current_user.mfa_enabled,
        setup_pending=bool(current_user.mfa_nonce and not current_user.mfa_enabled),
    )


@router.post("/setup", response_model=MfaSetupResponse)
def setup_mfa(
    payload: MfaSetupRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MfaSetupResponse:
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is already enabled",
        )
    if not verify_password(payload.password, current_user.password_hash):
        raise _invalid_reauthentication()

    current_user.mfa_nonce = secrets.token_hex(32)
    secret = derive_totp_secret(current_user.id, current_user.mfa_nonce)
    session.commit()
    return MfaSetupResponse(
        enabled=False,
        secret=secret,
        otpauth_uri=build_totp_uri(email=current_user.email, secret=secret),
    )


@router.post("/enable", response_model=MfaStatus)
def enable_mfa(
    payload: MfaCodeRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MfaStatus:
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is already enabled",
        )
    if not current_user.mfa_nonce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA setup must be started first",
        )

    secret = derive_totp_secret(current_user.id, current_user.mfa_nonce)
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")

    current_user.mfa_enabled = True
    revoke_user_refresh_sessions(session, current_user.id)
    record_audit(
        session,
        action="auth.mfa_enabled",
        resource_type="user",
        actor_user_id=current_user.id,
        resource_id=str(current_user.id),
    )
    session.commit()
    return MfaStatus(enabled=True, setup_pending=False)


@router.post("/disable", response_model=MfaStatus)
def disable_mfa(
    payload: MfaDisableRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MfaStatus:
    if not current_user.mfa_enabled or not current_user.mfa_nonce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is not enabled",
        )
    secret = derive_totp_secret(current_user.id, current_user.mfa_nonce)
    if (
        not verify_password(payload.password, current_user.password_hash)
        or not verify_totp(secret, payload.code)
    ):
        raise _invalid_reauthentication()

    current_user.mfa_enabled = False
    current_user.mfa_nonce = None
    revoke_user_refresh_sessions(session, current_user.id)
    record_audit(
        session,
        action="auth.mfa_disabled",
        resource_type="user",
        actor_user_id=current_user.id,
        resource_id=str(current_user.id),
    )
    session.commit()
    return MfaStatus(enabled=False, setup_pending=False)
