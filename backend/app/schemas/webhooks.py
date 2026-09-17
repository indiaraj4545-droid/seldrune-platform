from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.core.webhooks import (
    WEBHOOK_ABSOLUTE_MAX_PAYLOAD_BYTES,
    WEBHOOK_DEFAULT_MAX_PAYLOAD_BYTES,
    WEBHOOK_MIN_PAYLOAD_BYTES,
    WebhookEndpointStatus,
)


class WebhookEndpointCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    slug: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    secret_reference_id: UUID
    allowed_event_types: list[str] = Field(min_length=1, max_length=50)
    max_payload_bytes: int = Field(
        default=WEBHOOK_DEFAULT_MAX_PAYLOAD_BYTES,
        ge=WEBHOOK_MIN_PAYLOAD_BYTES,
        le=WEBHOOK_ABSOLUTE_MAX_PAYLOAD_BYTES,
    )

    @field_validator("allowed_event_types")
    @classmethod
    def validate_event_types(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            event_type = item.strip()
            if not event_type or len(event_type) > 200:
                raise ValueError("event types must be 1-200 characters")
            if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in event_type):
                raise ValueError("event types contain unsupported characters")
            if event_type not in cleaned:
                cleaned.append(event_type)
        return cleaned


class WebhookEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=160)
    secret_reference_id: UUID | None = None
    status: WebhookEndpointStatus | None = None
    allowed_event_types: list[str] | None = Field(default=None, min_length=1, max_length=50)
    max_payload_bytes: int | None = Field(
        default=None,
        ge=WEBHOOK_MIN_PAYLOAD_BYTES,
        le=WEBHOOK_ABSOLUTE_MAX_PAYLOAD_BYTES,
    )

    @field_validator("allowed_event_types")
    @classmethod
    def validate_event_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return WebhookEndpointCreate.validate_event_types(value)


class WebhookEndpointPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_by_user_id: UUID | None
    secret_reference_id: UUID
    name: str
    slug: str
    status: str
    allowed_event_types: list[str]
    max_payload_bytes: int
    created_at: datetime
    updated_at: datetime


class WebhookEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    endpoint_id: UUID
    delivery_id: str
    event_type: str
    payload_json: dict
    payload_sha256: str
    received_at: datetime


class WebhookReceipt(BaseModel):
    accepted: bool = True
    duplicate: bool = False
    event_id: UUID
    delivery_id: str
    event_type: str
