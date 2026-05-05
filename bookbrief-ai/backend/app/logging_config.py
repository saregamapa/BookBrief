"""Structured logging configuration for BookBrief AI.

Call ``configure_logging(debug=...)`` once at startup, then use:

    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event_name", key="value", another=42)

In debug mode, output is coloured dev console. In production, each line is
a single JSON object that log aggregators (Datadog, Papertrail, etc.) can ingest.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, debug: bool = False) -> None:
    """Wire stdlib logging → structlog with JSON (prod) or pretty (dev) output."""

    log_level = logging.DEBUG if debug else logging.INFO

    # ── stdlib root logger ──────────────────────────────────────────────────
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )
    # Silence noisy third-party loggers in production
    if not debug:
        for noisy in ("uvicorn.access", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── shared processors ────────────────────────────────────────────────────
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if debug:
        # Human-friendly coloured output for local development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Machine-readable JSON for production aggregators
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Convenience wrapper — returns a bound structlog logger."""
    return structlog.get_logger(name)
