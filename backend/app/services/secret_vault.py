from __future__ import annotations

import os
import re

from backend.app.core.secrets import SecretProvider, SecretStatus
from backend.app.models.secret_reference import SecretReference

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,239}$")


class SecretVaultError(RuntimeError):
    pass


def validate_secret_locator(provider: str, locator: str) -> None:
    if SecretProvider(provider) is SecretProvider.ENV and not _ENV_NAME.fullmatch(locator):
        raise SecretVaultError("Environment secret locator must be an uppercase variable name")


def resolve_secret(reference: SecretReference) -> str:
    if reference.status != SecretStatus.ACTIVE.value:
        raise SecretVaultError("Secret reference is disabled")
    provider = SecretProvider(reference.provider)
    validate_secret_locator(provider.value, reference.locator)
    if provider is SecretProvider.ENV:
        value = os.getenv(reference.locator)
        if not value:
            raise SecretVaultError("Referenced environment secret is not available")
        return value
    raise SecretVaultError(f"Unsupported secret provider: {reference.provider}")
