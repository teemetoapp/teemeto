"""Application settings using Pydantic Settings v2."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Core application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://teemeto_app:teemeto_app_pass@localhost:5432/teemeto_db",
        description="Async connection URL for application operations (enforces RLS)",
    )
    database_admin_url: str = Field(
        default="postgresql+asyncpg://teemeto_user:teemeto_pass@localhost:5432/teemeto_db",
        description="Admin connection URL for migrations and DDL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # Telegram
    telegram_bot_token: str = Field(
        default="",
        description="Default or test telegram bot token",
    )
    telegram_webhook_secret: str = Field(
        default="",
        description="Secret token for verifying Telegram webhooks",
    )

    # Clerk Auth
    clerk_jwks_url: str = Field(
        default="",
        description="Clerk JWKS endpoint for JWT verification",
    )
    clerk_secret_key: str = Field(
        default="",
        description="Clerk backend API secret key",
    )

    # OpenAI / AI Providers
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for embeddings and completions",
    )

    # Environment & Logging
    environment: Literal["local", "testing", "staging", "production"] = Field(
        default="local",
        description="Runtime environment",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Application logging level",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns a cached instance of application settings."""
    return Settings()
