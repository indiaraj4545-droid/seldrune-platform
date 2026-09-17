from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import quote
from uuid import UUID

from backend.app.core.config import settings

_PERIOD_SECONDS = 30
_DIGITS = 6
_DOMAIN = b"seldrune:mfa:totp:v1\x00"


def derive_totp_secret(user_id: UUID, nonce: str) -> str:
    try:
        nonce_bytes = bytes.fromhex(nonce)
    except ValueError as exc:
        raise ValueError("Invalid MFA enrollment nonce") from exc
    digest = hmac.new(
        settings.auth_secret_key.encode("utf-8"),
        _DOMAIN + user_id.bytes + nonce_bytes,
        hashlib.sha256,
    ).digest()
    return base64.b32encode(digest[:20]).decode("ascii").rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    normalized = secret.strip().upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def totp_code(secret: str, *, at_time: int | None = None) -> str:
    timestamp = int(time.time()) if at_time is None else int(at_time)
    counter = timestamp // _PERIOD_SECONDS
    digest = hmac.new(
        _secret_bytes(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % (10**_DIGITS):0{_DIGITS}d}"


def verify_totp(secret: str, code: str, *, at_time: int | None = None) -> bool:
    if len(code) != _DIGITS or not code.isdigit():
        return False
    timestamp = int(time.time()) if at_time is None else int(at_time)
    return any(
        hmac.compare_digest(totp_code(secret, at_time=timestamp + offset), code)
        for offset in (-_PERIOD_SECONDS, 0, _PERIOD_SECONDS)
    )


def build_totp_uri(*, email: str, secret: str) -> str:
    issuer = "Seldrune"
    label = quote(f"{issuer}:{email}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD_SECONDS}"
    )
