from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.mfa_recovery_code import MfaRecoveryCode

_RECOVERY_CODE_BYTES = 12
_RECOVERY_CODE_COUNT = 10
_RECOVERY_DOMAIN = b"seldrune:mfa:recovery:v1\x00"


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_recovery_code(code: str) -> str | None:
    normalized = code.strip().replace("-", "").upper()
    if len(normalized) != _RECOVERY_CODE_BYTES * 2:
        return None
    if any(character not in "0123456789ABCDEF" for character in normalized):
        return None
    return normalized


def _display_code(normalized: str) -> str:
    return "-".join(normalized[index : index + 4] for index in range(0, len(normalized), 4))


def recovery_code_digest(user_id: UUID, code: str) -> str | None:
    normalized = normalize_recovery_code(code)
    if normalized is None:
        return None
    return hmac.new(
        settings.auth_secret_key.encode("utf-8"),
        _RECOVERY_DOMAIN + user_id.bytes + normalized.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes(
    session: Session,
    user_id: UUID,
    *,
    count: int = _RECOVERY_CODE_COUNT,
) -> list[str]:
    session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    codes: list[str] = []
    for _ in range(count):
        normalized = secrets.token_hex(_RECOVERY_CODE_BYTES).upper()
        display = _display_code(normalized)
        digest = recovery_code_digest(user_id, display)
        if digest is None:
            raise RuntimeError("Failed to generate MFA recovery code")
        session.add(MfaRecoveryCode(user_id=user_id, code_digest=digest))
        codes.append(display)
    session.flush()
    return codes


def consume_recovery_code(session: Session, user_id: UUID, code: str) -> bool:
    digest = recovery_code_digest(user_id, code)
    if digest is None:
        return False
    statement = select(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == user_id,
        MfaRecoveryCode.code_digest == digest,
        MfaRecoveryCode.used_at.is_(None),
    )
    if session.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()
    recovery_code = session.scalar(statement)
    if recovery_code is None:
        return False
    recovery_code.used_at = _now()
    session.flush()
    return True


def remaining_recovery_codes(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count(MfaRecoveryCode.id)).where(
                MfaRecoveryCode.user_id == user_id,
                MfaRecoveryCode.used_at.is_(None),
            )
        )
        or 0
    )


def delete_recovery_codes(session: Session, user_id: UUID) -> None:
    session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
