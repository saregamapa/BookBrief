"""Persistent storage for async TTS jobs (audiobook / podcast narration).

In-memory jobs break when multiple uvicorn workers are used: POST and GET may hit
different processes. Rows are purged after ~15 minutes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AudioTtsJob(Base):
    __tablename__ = "audio_tts_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pending | done | error
    audio_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    media_type: Mapped[str] = mapped_column(String(64), default="audio/mpeg", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
