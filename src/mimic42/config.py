from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mimic42 API"
    environment: str = Field(default="development")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, le=65535)
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    database_connection_string: str | None = Field(
        default=None,
        validation_alias="DATABASE_CONNECTION_STRING",
    )
    mem0_api_key: str | None = Field(default=None, validation_alias="MEM0_API_KEY")
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    secret_key: str | None = Field(default=None, validation_alias="SECRET_KEY")
    telegram_api_id: int | None = Field(default=None, validation_alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, validation_alias="TELEGRAM_API_HASH")
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        validation_alias="CORS_ALLOW_ORIGINS",
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        # NoDecode passes the raw env string through: accept JSON lists and
        # plain comma-separated strings (e.g. CORS_ALLOW_ORIGINS=https://a,https://b).
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return parsed
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )
