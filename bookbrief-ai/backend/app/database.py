from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""


_engine: Engine | None = None
_SessionMaker = sessionmaker(autocommit=False, autoflush=False)


def _create_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    connect_args: dict = {}
    if settings.db_backend == "sqlite":
        connect_args["check_same_thread"] = False
    return create_engine(
        url,
        connect_args=connect_args,
        echo=settings.debug,
        pool_pre_ping=True,
    )


def get_engine() -> Engine:
    """Lazily create the SQLAlchemy engine (avoids import-time DB URL during Alembic metadata load)."""
    global _engine
    if _engine is None:
        _engine = _create_engine()
        _SessionMaker.configure(bind=_engine)
    return _engine


def __getattr__(name: str) -> Engine:
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def SessionLocal(**kwargs: Any) -> Session:
    """Open a new ORM session (ensures engine exists first)."""
    get_engine()
    return _SessionMaker(**kwargs)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
