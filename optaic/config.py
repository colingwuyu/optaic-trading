from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    mode: Literal["embedded", "prod"] = Field(default="embedded", validation_alias="MODE")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    centrifugo_port: int = Field(default=8001, validation_alias="CENTRIFUGO_PORT")
    centrifugo_api_key: str | None = Field(
        default="dev-api-key",
        validation_alias="CENTRIFUGO_API_KEY",
    )
    centrifugo_token_secret: str | None = Field(
        default="dev-secret-change-me",
        validation_alias="CENTRIFUGO_TOKEN_SECRET",
    )
    with_redis: bool = Field(
        default=False,
        validation_alias="OPTAIC_WITH_REDIS",
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPTAIC_REDIS_URL", "REDIS_URL"),
    )
    redis_port: int = Field(
        default=6379,
        validation_alias="OPTAIC_REDIS_PORT",
    )
    redis_bind: str = Field(
        default="127.0.0.1",
        validation_alias="OPTAIC_REDIS_BIND",
    )
    redis_version: str = Field(
        default="8.4.0",
        validation_alias="OPTAIC_REDIS_VERSION",
    )
    redis_flavor: Literal["msys2", "cygwin"] = Field(
        default="msys2",
        validation_alias="OPTAIC_REDIS_FLAVOR",
    )
    package_index_url: str | None = Field(
        default=None,
        validation_alias="OPTAIC_PACKAGE_INDEX_URL",
    )
    channel: Literal["prod", "uat", "staging"] = Field(
        default="prod",
        validation_alias="OPTAIC_CHANNEL",
    )
    artifactory_base_url: str | None = Field(
        default=None,
        validation_alias="OPTAIC_ARTIFACTORY_BASE_URL",
    )
    package_extra_index_url: str = Field(
        default="https://pypi.org/simple",
        validation_alias="OPTAIC_PACKAGE_EXTRA_INDEX_URL",
    )
    package_trusted_host: str | None = Field(
        default=None,
        validation_alias="OPTAIC_PACKAGE_TRUSTED_HOST",
    )
    package_name: str = Field(
        default="optaic",
        validation_alias="OPTAIC_PACKAGE_NAME",
    )
    api_port: int = Field(default=8080, validation_alias="API_PORT")
    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")


@lru_cache
def get_settings() -> Settings:
    return Settings()
