from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import VideoJobStatus, sqlalchemy_enum_values

if TYPE_CHECKING:
    from app.models.book_summary import BookSummary


class SummaryVideo(Base):
    """Generated video summary for a book summary (one row per summary; e.g. OpenRouter / Veo)."""

    __tablename__ = "summary_videos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    summary_id: Mapped[int] = mapped_column(
        ForeignKey("book_summaries.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    status: Mapped[VideoJobStatus] = mapped_column(
        Enum(VideoJobStatus, values_callable=sqlalchemy_enum_values, native_enum=False),
        default=VideoJobStatus.pending,
        nullable=False,
    )
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subtitle_vtt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_phase: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    progress_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    summary: Mapped["BookSummary"] = relationship("BookSummary", back_populates="video_asset")
