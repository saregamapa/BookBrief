from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BookBrief AI"
    debug: bool = False
    secret_key: str = Field(
        default="dev-only-change-me-in-production",
        alias="SECRET_KEY",
    )
    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        alias="CORS_ORIGINS",
    )

    database_url: str = Field(
        default="sqlite:///./bookbrief.db",
        alias="DATABASE_URL",
    )

    jwt_secret_key: str = Field(
        default="dev-only-jwt-change-me",
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 7,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # Manus AI (optional) — when set, audiobook/podcast TTS uses Manus tasks instead of OpenAI TTS
    manus_api_base: str = Field(default="https://api.manus.ai", alias="MANUS_API_BASE")
    manus_api_key: str = Field(default="", alias="MANUS_API_KEY")
    manus_tts_timeout_seconds: int = Field(default=480, alias="MANUS_TTS_TIMEOUT_SECONDS")
    manus_agent_profile: str = Field(default="manus-1.6-lite", alias="MANUS_AGENT_PROFILE")
    manus_video_timeout_seconds: int = Field(default=900, alias="MANUS_VIDEO_TIMEOUT_SECONDS")
    manus_video_agent_profile: str = Field(default="manus-1.6", alias="MANUS_VIDEO_AGENT_PROFILE")

    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    stripe_price_pro: str = Field(default="", alias="STRIPE_PRICE_PRO")
    stripe_price_growth: str = Field(default="", alias="STRIPE_PRICE_GROWTH")
    stripe_success_url: str = Field(default="", alias="STRIPE_SUCCESS_URL")
    stripe_cancel_url: str = Field(default="", alias="STRIPE_CANCEL_URL")

    public_app_url: str = Field(default="http://localhost:8000", alias="PUBLIC_APP_URL")
    render_external_url: Optional[str] = Field(default=None, alias="RENDER_EXTERNAL_URL")

    # ── Production safety guard ─────────────────────────────────────────────
    @model_validator(mode="after")
    def _reject_dev_secrets_in_production(self) -> "Settings":
        """Fail fast if obvious dev-only defaults are used outside debug mode."""
        if self.debug:
            return self

        _DEV_SECRET_KEY = "dev-only-change-me-in-production"
        _DEV_JWT_KEY = "dev-only-jwt-change-me"

        bad: list[str] = []
        if self.secret_key == _DEV_SECRET_KEY:
            bad.append("SECRET_KEY is still the dev default")
        if self.jwt_secret_key == _DEV_JWT_KEY:
            bad.append("JWT_SECRET_KEY is still the dev default")
        if not self.openai_api_key:
            bad.append("OPENAI_API_KEY is not set")
        if not self.stripe_secret_key:
            bad.append("STRIPE_SECRET_KEY is not set")
        if not self.stripe_webhook_secret:
            bad.append("STRIPE_WEBHOOK_SECRET is not set")
        if "sqlite" in self.database_url.lower():
            bad.append("DATABASE_URL is SQLite (use PostgreSQL in production)")

        if bad:
            issues = "\n  • ".join(bad)
            raise ValueError(
                f"Production misconfiguration detected — set DEBUG=true to bypass:\n  • {issues}"
            )
        return self

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_url(cls, v: str) -> str:
        if v.startswith("sqlite:///"):
            return v
        if v.startswith("sqlite://"):
            return v
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_public_origin(self) -> str:
        """Public site URL: PUBLIC_APP_URL, or Render's RENDER_EXTERNAL_URL when still on localhost default."""
        pub = (self.public_app_url or "").strip().rstrip("/") or "http://localhost:8000"
        ext = (self.render_external_url or "").strip().rstrip("/")
        if ext and pub == "http://localhost:8000":
            return ext
        return pub

    @property
    def db_backend(self) -> Literal["sqlite", "postgresql"]:
        if "sqlite" in self.database_url.lower():
            return "sqlite"
        return "postgresql"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
