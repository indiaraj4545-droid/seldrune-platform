from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

AssignableRole = Literal["member", "auditor", "admin"]
_RECOVERY_CODE_PATTERN = r"^(?:[0-9A-Fa-f]{4}-){5}[0-9A-Fa-f]{4}$"


class InvitationCreate(BaseModel):
    email: EmailStr
    role: AssignableRole = "member"
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class InvitationPublic(BaseModel):
    id: UUID
    organization_id: UUID
    email: EmailStr
    role: AssignableRole
    status: Literal["pending", "accepted", "revoked", "expired"]
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationCreated(InvitationPublic):
    token: str


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=128)
    mfa_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, pattern=_RECOVERY_CODE_PATTERN)

    @model_validator(mode="after")
    def require_at_most_one_mfa_factor(self) -> InvitationAccept:
        if self.mfa_code is not None and self.recovery_code is not None:
            raise ValueError("Provide at most one MFA factor")
        return self


class MemberRoleUpdate(BaseModel):
    role: AssignableRole
