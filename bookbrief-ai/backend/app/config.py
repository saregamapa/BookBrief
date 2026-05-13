from functools import lru_cache
import os
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_render_runtime() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_URL"))


def _default_database_url() -> str:
    """Local dev uses SQLite. On Render, DATABASE_URL must come from linked Postgres or the dashboard."""
    if _is_render_runtime():
        raise ValueError(
            "DATABASE_URL is not set. On Render: Dashboard → your Web Service → Environment → "
            "link your PostgreSQL instance (or add DATABASE_URL from Postgres → Info → Internal Database URL). "
            "If you use Docker on Render, link the database to that service so DATABASE_URL is injected."
        )
    return "sqlite:///./bookbrief.db"


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
        default_factory=_default_database_url,
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

    # OpenRouter — all LLM, TTS, video, translation, summarization
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_api_base: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_API_BASE",
    )
    openrouter_http_referer: Optional[str] = Field(default=None, alias="OPENROUTER_HTTP_REFERER")
    openrouter_summary_model: str = Field(
        default="google/gemma-4-26b-a4b-it",
        alias="OPENROUTER_SUMMARY_MODEL",
    )
    # Chat JSON — podcast script only (must support chat completions + JSON mode on OpenRouter).
    openrouter_podcast_model: str = Field(
        default="openai/gpt-4o-mini",
        alias="OPENROUTER_PODCAST_MODEL",
    )
    # Speech API ``POST /audio/speech`` — must be a TTS-capable model (not general chat).
    openrouter_tts_model: str = Field(
        default="openai/gpt-4o-mini-tts",
        alias="OPENROUTER_TTS_MODEL",
    )
    # Video API ``POST /videos`` — must be a video model (e.g. Google Veo on OpenRouter).
    openrouter_video_model: str = Field(
        default="google/veo-3.1-lite",
        alias="OPENROUTER_VIDEO_MODEL",
    )
    openrouter_tts_response_format: str = Field(default="mp3", alias="OPENROUTER_TTS_RESPONSE_FORMAT")
    openrouter_tts_timeout_seconds: float = Field(default=300.0, alias="OPENROUTER_TTS_TIMEOUT_SECONDS")
    openrouter_video_duration: int = Field(default=8, ge=4, le=8, alias="OPENROUTER_VIDEO_DURATION")
    openrouter_video_resolution: str = Field(default="720p", alias="OPENROUTER_VIDEO_RESOLUTION")
    openrouter_video_aspect_ratio: str = Field(default="16:9", alias="OPENROUTER_VIDEO_ASPECT_RATIO")
    openrouter_video_generate_audio: bool = Field(
        default=True,
        alias="OPENROUTER_VIDEO_GENERATE_AUDIO",
    )
    openrouter_video_poll_interval: float = Field(default=5.0, alias="OPENROUTER_VIDEO_POLL_INTERVAL")
    openrouter_video_timeout_seconds: float = Field(
        default=1800.0,
        alias="OPENROUTER_VIDEO_TIMEOUT_SECONDS",
    )

    # Manus AI (optional) — TTS fallback when OPENROUTER_API_KEY is unset
    manus_api_base: str = Field(default="https://api.manus.ai", alias="MANUS_API_BASE")
    manus_api_key: str = Field(default="", alias="MANUS_API_KEY")
    manus_tts_timeout_seconds: int = Field(default=480, alias="MANUS_TTS_TIMEOUT_SECONDS")
    manus_agent_profile: str = Field(default="manus-1.6-lite", alias="MANUS_AGENT_PROFILE")

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
        if not (self.openrouter_api_key or "").strip():
            bad.append("OPENROUTER_API_KEY is not set")
        if not self.stripe_secret_key:
            bad.append("STRIPE_SECRET_KEY is not set")
        # Webhook signing secret is optional at boot: ``POST /stripe/webhook`` returns 503 until set.
        if "sqlite" in self.database_url.lower():
            hint = "Use PostgreSQL in production (Render: link Postgres or set DATABASE_URL to the Internal Database URL)."
            if self.render_external_url or os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_URL"):
                hint += (
                    " This service is running on Render but still has a SQLite URL — "
                    "the database is usually not linked to this web service."
                )
            bad.append(f"DATABASE_URL is SQLite ({hint})")

        if bad:
            issues = "\n  • ".join(bad)
            raise ValueError(
                f"Production misconfiguration detected — set DEBUG=true to bypass:\n  • {issues}"
            )
        return self

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Strip BOM/whitespace, first line only, Render-style ``postgres://`` → ``postgresql://``."""
        if not isinstance(v, str):
            v = str(v) if v is not None else ""
        v = v.strip().lstrip("\ufeff")
        if not v:
            raise ValueError(
                "DATABASE_URL is empty. Set it to a PostgreSQL URL "
                "(Render: Environment → link Postgres or paste Internal Database URL)."
            )
        v = v.splitlines()[0].strip()
        if not v:
            raise ValueError(
                "DATABASE_URL is empty after stripping. Use a single-line PostgreSQL connection string."
            )
        if v.startswith("postgres://"):
            v = "postgresql://" + v.removeprefix("postgres://")
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
