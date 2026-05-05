from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import BookSourceType, SummaryJobStatus, SummaryStyle, sqlalchemy_enum_values

if TYPE_CHECKING:
    from app.models.user import User


class BookSummary(Base):
    __tablename__ = "book_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    source_type: Mapped[BookSourceType] = mapped_column(
        Enum(BookSourceType, values_callable=sqlalchemy_enum_values, native_enum=False),
        nullable=False,
    )
    style: Mapped[SummaryStyle] = mapped_column(
        Enum(SummaryStyle, values_callable=sqlalchemy_enum_values, native_enum=False),
        nullable=False,
    )

    personalization_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    output_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[SummaryJobStatus] = mapped_column(
        Enum(SummaryJobStatus, values_callable=sqlalchemy_enum_values, native_enum=False),
        default=SummaryJobStatus.pending,
        nullable=False,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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

    user: Mapped[User] = relationship("User", back_populates="summaries")
