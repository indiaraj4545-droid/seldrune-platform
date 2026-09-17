from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status

from backend.app.api.dependencies import CurrentUserDep, SessionDep
from backend.app.core.mfa import build_totp_uri, derive_totp_secret, verify_totp
from backend.app.core.security import verify_password
from backend.app.schemas.mfa import (
    MfaCodeRequest,
    MfaDisableRequest,
    MfaRecoveryCodesResponse,
    MfaRecoveryRegenerateRequest,
    MfaRecoveryStatus,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaStatus,
)
from backend.app.services.audit import record_audit
from backend.app.services.mfa_recovery import (
    consume_recovery_code,
    delete_recovery_codes,
    generate_recovery_codes,
    remaining_recovery_codes,
)
from backend.app.services.refresh_sessions import revoke_user_refresh_sessions
from backend.app.services.security_events import record_user_security_event

router = APIRouter(prefix="/auth/mfa", tags=["auth"])


def _invalid_reauthentication() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid current credentials",
    )


def _record_recovery_code_use(current_user: CurrentUserDep, session: SessionDep) -> None:
    record_audit(
        session,
        action="auth.mfa_recovery_code_used",
        resource_type="user",
        actor_user_id=current_user.id,
        resource_id=str(current_user.id),
    )
    record_user_security_event(
        session,
        user_id=current_user.id,
        event_type="mfa_recovery_code_used",
        severity="medium",
        resource_type="user",
        resource_id=str(current_user.id),
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


@router.get("/recovery-codes/status", response_model=MfaRecoveryStatus)
def recovery_code_status(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MfaRecoveryStatus:
    remaining = (
        remaining_recovery_codes(session, current_user.id)
        if current_user.mfa_enabled
        else 0
    )
    return MfaRecoveryStatus(recovery_codes_remaining=remaining)


@router.post("/recovery-codes/regenerate", response_model=MfaRecoveryCodesResponse)
def regenerate_recovery_codes(
    payload: MfaRecoveryRegenerateRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MfaRecoveryCodesResponse:
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

    recovery_codes = generate_recovery_codes(session, current_user.id)
    record_audit(
        session,
        action="auth.mfa_recovery_codes_regenerated",
        resource_type="user",
        actor_user_id=current_user.id,
        resource_id=str(current_user.id),
    )
    record_user_security_event(
        session,
        user_id=current_user.id,
        event_type="mfa_recovery_codes_regenerated",
        severity="medium",
        resource_type="user",
        resource_id=str(current_user.id),
    )
    session.commit()
    return MfaRecoveryCodesResponse(
        recovery_codes=recovery_codes,
        recovery_codes_remaining=len(recovery_codes),
    )


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
    if not verify_password(payload.password, current_user.password_hash):
        raise _invalid_reauthentication()

    factor = "totp"
    if payload.code is not None:
        secret = derive_totp_secret(current_user.id, current_user.mfa_nonce)
        valid_factor = verify_totp(secret, payload.code)
    else:
        factor = "recovery_code"
        valid_factor = bool(
            payload.recovery_code
            and consume_recovery_code(session, current_user.id, payload.recovery_code)
        )
    if not valid_factor:
        raise _invalid_reauthentication()

    if factor == "recovery_code":
        _record_recovery_code_use(current_user, session)
    current_user.mfa_enabled = False
    current_user.mfa_nonce = None
    delete_recovery_codes(session, current_user.id)
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
