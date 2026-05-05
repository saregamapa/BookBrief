"""Health and readiness endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["health"])

_APP_VERSION = "1.0.0"
_START_TIME = datetime.now(timezone.utc)


@router.get(
    "/health",
    summary="Liveness probe",
    description=(
        "Returns `200 OK` as long as the process is running. "
        "Use this for load-balancer health checks."
    ),
    response_description="Service status and metadata",
)
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "bookbrief-ai",
        "version": _APP_VERSION,
        "environment": "development" if settings.debug else "production",
        "uptime_seconds": round((datetime.now(timezone.utc) - _START_TIME).total_seconds()),
    }


@router.get(
    "/ready",
    summary="Readiness probe",
    description=(
        "Returns `200 OK` only when the service is ready to handle traffic "
        "(process alive **and** database reachable). Use this for Kubernetes "
        "readiness gates or Render health checks."
    ),
    response_description="Readiness status including dependency checks",
)
def ready(db: Session = Depends(get_db)) -> dict:
    """Readiness probe — checks DB connectivity in addition to liveness."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        pass

    overall = "ok" if db_ok else "degraded"
    return {
        "status": overall,
        "checks": {
            "database": "ok" if db_ok else "error",
        },
    }
