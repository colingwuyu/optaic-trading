from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_RBAC_MODES = {"casbin"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    app_env: str = Field(default="local", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    centrifugo_url: str = Field(
        default="http://localhost:8001",
        validation_alias="CENTRIFUGO_URL",
    )
    centrifugo_api_key: str = Field(
        default="dev-api-key",
        validation_alias="CENTRIFUGO_API_KEY",
    )
    centrifugo_hmac_secret: str = Field(
        default="dev-secret-change-me",
        validation_alias="CENTRIFUGO_HMAC_SECRET",
    )
    rbac_mode: str = Field(default="casbin", validation_alias="RBAC_MODE")
    s3_endpoint: str = Field(
        default="http://localhost:9000",
        validation_alias="S3_ENDPOINT",
    )
    s3_access_key: str = Field(
        default="minioadmin",
        validation_alias="S3_ACCESS_KEY",
    )
    s3_secret_key: str = Field(
        default="minioadmin",
        validation_alias="S3_SECRET_KEY",
    )
    s3_bucket: str = Field(
        default="attachments",
        validation_alias="S3_BUCKET",
    )
    s3_region: str = Field(
        default="us-east-1",
        validation_alias="S3_REGION",
    )
    agent_api_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias="AGENT_API_BASE_URL",
    )
    agent_poll_interval: float = Field(
        default=2.0,
        validation_alias="AGENT_POLL_INTERVAL",
    )
    agent_batch_size: int = Field(
        default=50,
        validation_alias="AGENT_BATCH_SIZE",
    )
    agent_model: str = Field(default="stub-1", validation_alias="AGENT_MODEL")
    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ALLOW_ORIGINS",
    )
    s3_endpoint: str = Field(
        default="http://localhost:9000",
        validation_alias="S3_ENDPOINT",
    )
    s3_access_key: str = Field(
        default="minioadmin",
        validation_alias="S3_ACCESS_KEY",
    )
    s3_secret_key: str = Field(
        default="minioadmin",
        validation_alias="S3_SECRET_KEY",
    )
    s3_bucket: str = Field(
        default="attachments",
        validation_alias="S3_BUCKET",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"Invalid LOG_LEVEL '{value}'")
        return level

    @field_validator("rbac_mode")
    @classmethod
    def _validate_rbac_mode(cls, value: str) -> str:
        mode = value.lower()
        if mode not in _RBAC_MODES:
            raise ValueError(f"Invalid RBAC_MODE '{value}'")
        return mode


@lru_cache
def get_settings() -> Settings:
    return Settings()
