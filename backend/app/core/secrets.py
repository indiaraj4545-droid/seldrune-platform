from enum import StrEnum


class SecretProvider(StrEnum):
    ENV = "env"


class SecretStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
