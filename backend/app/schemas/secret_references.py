from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.core.secrets import SecretProvider, SecretStatus


_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class SecretReferenceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=100, pattern=_SLUG_PATTERN)
    provider: SecretProvider = SecretProvider.ENV
    locator: str = Field(min_length=3, max_length=240)

    @field_validator("name", "locator")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower()


class SecretReferenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    locator: str | None = Field(default=None, min_length=3, max_length=240)
    status: SecretStatus | None = None

    @field_validator("name", "locator")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SecretReferencePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    slug: str
    provider: str
    locator: str
    status: str
    created_at: datetime
    updated_at: datetime
