from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Seldrune Platform"
    app_version: str = "0.82.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    enable_docs: bool = True
