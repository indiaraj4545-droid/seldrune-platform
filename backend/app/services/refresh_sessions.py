from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.refresh_token import RefreshToken


class RefreshTokenError(ValueError):
    """Raised when a refresh token cannot be accepted."""


class RefreshTokenReplay(RefreshTokenError):
    """Raised after a consumed refresh token is presented again."""

    def __init__(self, user_id: UUID, family_id: UUID) -> None:
        super().__init__("Refresh token reuse detected")
        self.user_id = user_id
        self.family_id = family_id


@dataclass(frozen=True)
class RefreshIssue:
    token: str
    family_id: UUID
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def refresh_token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(
    session: Session,
    user_id: UUID,
    *,
    family_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> RefreshIssue:
    raw_token = secrets.token_urlsafe(48)
    family = family_id or uuid4()
    expiry = expires_at or (_now() + timedelta(days=settings.auth_refresh_token_days))
    session.add(
        RefreshToken(
            family_id=family,
            user_id=user_id,
            token_sha256=refresh_token_fingerprint(raw_token),
            expires_at=expiry,
        )
    )
    session.flush()
    return RefreshIssue(token=raw_token, family_id=family, expires_at=expiry)


def revoke_refresh_family(session: Session, family_id: UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )


def rotate_refresh_token(session: Session, raw_token: str) -> tuple[UUID, RefreshIssue]:
    token = session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_sha256 == refresh_token_fingerprint(raw_token))
        .with_for_update()
    )
    if token is None:
        raise RefreshTokenError("Invalid refresh token")

    now = _now()
    if token.used_at is not None:
        revoke_refresh_family(session, token.family_id)
        session.flush()
        raise RefreshTokenReplay(token.user_id, token.family_id)
    if token.revoked_at is not None or _aware(token.expires_at) <= now:
        raise RefreshTokenError("Invalid refresh token")

    token.used_at = now
    replacement = issue_refresh_token(
        session,
        token.user_id,
        family_id=token.family_id,
        expires_at=_aware(token.expires_at),
    )
    return token.user_id, replacement
