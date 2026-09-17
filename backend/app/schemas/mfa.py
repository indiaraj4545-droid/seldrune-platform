from pydantic import BaseModel, ConfigDict, Field


class MfaStatus(BaseModel):
    enabled: bool
    setup_pending: bool


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


class MfaDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")
