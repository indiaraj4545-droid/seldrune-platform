from pydantic import BaseModel, ConfigDict, Field, model_validator

_RECOVERY_CODE_PATTERN = r"^(?:[0-9A-Fa-f]{4}-){5}[0-9A-Fa-f]{4}$"


class MfaStatus(BaseModel):
    enabled: bool
    setup_pending: bool
    recovery_codes_remaining: int = Field(ge=0)


class MfaSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)


class MfaSetupResponse(BaseModel):
    enabled: bool
    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^\d{6}$")


class MfaEnableResponse(MfaStatus):
    recovery_codes: list[str]


class MfaDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, pattern=_RECOVERY_CODE_PATTERN)

    @model_validator(mode="after")
    def require_one_factor(self) -> "MfaDisableRequest":
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Provide exactly one MFA factor")
        return self


class MfaRecoveryRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
    recovery_codes_remaining: int = Field(ge=0)
