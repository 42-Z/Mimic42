from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )
