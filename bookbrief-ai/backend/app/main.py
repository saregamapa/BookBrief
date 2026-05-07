"""BookBrief AI — FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.limiter import limiter
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from app.routers import audio, auth, billing, health, summaries, user
from app.routers.summaries import reset_stuck_processing_jobs

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
STATIC_DIR = ROOT_DIR / "static"

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# OpenAPI tag metadata — controls the order and descriptions in /docs
# ---------------------------------------------------------------------------
_OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness and readiness probes for load-balancers and orchestrators.",
    },
    {
        "name": "auth",
        "description": (
            "Registration, login, logout, JWT management, password change/reset, "
            "and session revocation.  All tokens are short-lived JWTs; use "
            "`/auth/change-password` or `/auth/revoke-all` to invalidate existing sessions."
        ),
    },
    {
        "name": "summaries",
        "description": (
            "Asynchronous book summarization.  POST endpoints return **202 Accepted** "
            "immediately and begin a background LangGraph pipeline.  Poll "
            "`GET /api/v1/summaries/{id}/status` until `status` is `completed` or `failed`, "
            "then fetch the full result with `GET /api/v1/summaries/{id}`."
        ),
    },
    {
        "name": "stripe",
        "description": (
            "Stripe Checkout, Customer Portal, and webhook ingestion.  "
            "Use `/stripe/create-checkout-session` to start a subscription upgrade, "
            "`/stripe/create-portal-session` to open the billing self-service portal, "
            "and `/stripe/webhook` receives Stripe events (signature-verified)."
        ),
    },
    {
        "name": "user",
        "description": "Authenticated user profile and live subscription state.",
    },
]


def create_app() -> FastAPI:
    settings = get_settings()

    # ── Logging (configure before anything logs) ─────────────────────────────
    configure_logging(debug=settings.debug)

    logger.info(
        "starting_bookbrief",
        app=settings.app_name,
        debug=settings.debug,
        db_backend=settings.db_backend,
    )

    app = FastAPI(
        title=settings.app_name,
        description=(
            "**BookBrief AI** — multi-stage LangGraph summarization, "
            "Stripe subscriptions, and a reading-focused UI.\n\n"
            "All versioned API routes live under `/api/v1/`.  "
            "Authentication uses short-lived Bearer JWTs obtained via `POST /api/v1/auth/login`."
        ),
        version="1.0.0",
        debug=settings.debug,
        openapi_tags=_OPENAPI_TAGS,
        # Hide docs in production to reduce attack surface
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # ── Rate limiter ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── Middleware (outermost → innermost) ────────────────────────────────────
    # 1. Security headers — outermost so every response gets them.
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Request-ID tracing — runs just inside security headers so the ID is
    #    available to all downstream middleware and route handlers.
    app.add_middleware(RequestIDMiddleware)

    # 3. GZip: compress responses > 1 KB
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # 4. CORS: must come after security headers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    # ── Versioned API router ──────────────────────────────────────────────────
    # All application routes live under /api/v1/.  Older clients or internal
    # tools hitting bare paths (e.g. /health) are handled by the unversioned
    # mounts below.
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(health.router)
    api_v1.include_router(auth.router)
    api_v1.include_router(billing.router)
    api_v1.include_router(user.router)
    api_v1.include_router(summaries.router)
    api_v1.include_router(audio.router)
    app.include_router(api_v1)

    # ── Unversioned aliases (backward compat / liveness probes) ──────────────
    # /health and /ready are kept at the root so existing monitors still work.
    app.include_router(health.router)

    # ── Static file mounts ────────────────────────────────────────────────────
    if FRONTEND_DIR.is_dir():
        app.mount(
            "/frontend",
            StaticFiles(directory=str(FRONTEND_DIR), html=True),
            name="frontend",
        )
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Root redirect ─────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/frontend/index.html")

    # ── Startup / shutdown events ─────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup() -> None:
        # Reset any summaries stuck in 'processing' from a previous crash.
        reset_stuck_processing_jobs()
        logger.info("bookbrief_ready", frontend_dir=str(FRONTEND_DIR))

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("bookbrief_shutdown")

    return app


app = create_app()
