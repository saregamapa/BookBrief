from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""


def _create_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if settings.db_backend == "sqlite":
        connect_args["check_same_thread"] = False
    return create_engine(
        url,
        connect_args=connect_args,
        echo=settings.debug,
        pool_pre_ping=True,
    )


engine = _create_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
