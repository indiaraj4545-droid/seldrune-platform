import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.login_failure import LoginFailure


class LoginThrottleError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many login attempts. Try again later.")
        self.retry_after_seconds = retry_after_seconds


def login_throttle_key(email: str, source_address: str) -> str:
    normalized_email = email.strip().lower()
    material = (
        f"seldrune-login-throttle-v1\0{settings.auth_secret_key}\0"
        f"{normalized_email}\0{source_address}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _window_start(now: datetime) -> datetime:
    return now - timedelta(minutes=settings.auth_login_failure_window_minutes)


def _recent_failure_count(session: Session, key: str, now: datetime) -> int:
    return int(
        session.scalar(
            select(func.count(LoginFailure.id)).where(
                LoginFailure.throttle_key_sha256 == key,
                LoginFailure.occurred_at >= _window_start(now),
            )
        )
        or 0
    )


def _retry_after_seconds(session: Session, key: str, now: datetime) -> int:
    oldest = session.scalar(
        select(LoginFailure.occurred_at)
        .where(
            LoginFailure.throttle_key_sha256 == key,
            LoginFailure.occurred_at >= _window_start(now),
        )
        .order_by(LoginFailure.occurred_at.asc())
        .limit(1)
    )
    if oldest is None:
        return 1
    unlock_at = _as_utc(oldest) + timedelta(
        minutes=settings.auth_login_failure_window_minutes
    )
    return max(1, math.ceil((unlock_at - now).total_seconds()))


def enforce_login_throttle(session: Session, key: str, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    if _recent_failure_count(session, key, current) >= settings.auth_login_failure_limit:
        raise LoginThrottleError(_retry_after_seconds(session, key, current))


def record_login_failure(session: Session, key: str, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    session.add(LoginFailure(throttle_key_sha256=key, occurred_at=current))
    session.commit()
    if _recent_failure_count(session, key, current) >= settings.auth_login_failure_limit:
        raise LoginThrottleError(_retry_after_seconds(session, key, current))


def clear_login_failures(session: Session, key: str) -> None:
    session.execute(
        delete(LoginFailure).where(LoginFailure.throttle_key_sha256 == key)
    )
