from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book_summary import BookSummary


class SummaryTranslation(Base):
    """Cached OpenAI translation of a summary's markdown."""

    __tablename__ = "summary_translations"
    __table_args__ = (UniqueConstraint("summary_id", "locale", name="uq_summary_translation_locale"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    summary_id: Mapped[int] = mapped_column(
        ForeignKey("book_summaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    translated_markdown: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    summary: Mapped["BookSummary"] = relationship("BookSummary", back_populates="translations")
