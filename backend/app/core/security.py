import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from backend.app.core.config import settings

ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()


class TokenError(ValueError):
    """Raised when an access token cannot be trusted."""


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    expires_at: datetime
    session_id: UUID | None = None


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        return password_hash.verify(password, stored_hash)
    except (TypeError, ValueError):
        return False


def access_token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: UUID, *, session_id: UUID | None = None) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.auth_access_token_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, settings.auth_secret_key, algorithm=ALGORITHM)


def decode_access_token_claims(token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except InvalidTokenError as exc:
        raise TokenError("Invalid or expired access token") from exc

    if payload.get("type") != "access":
        raise TokenError("Invalid token type")

    try:
        user_id = UUID(str(payload["sub"]))
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
        session_id = UUID(str(payload["sid"])) if payload.get("sid") is not None else None
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TokenError("Invalid access token claims") from exc
    return AccessTokenClaims(
        user_id=user_id,
        expires_at=expires_at,
        session_id=session_id,
    )


def decode_access_token(token: str) -> UUID:
    return decode_access_token_claims(token).user_id
