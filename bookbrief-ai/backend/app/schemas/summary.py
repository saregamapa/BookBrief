from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Literal, Optional

if TYPE_CHECKING:
    from app.models.book_summary import BookSummary

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BookSourceType, SummaryJobStatus, SummaryStyle


class SummaryCreateJSON(BaseModel):
    """Create a summary from pasted text or book title + author."""

    source_type: Literal["paste", "title_author"]
    style: SummaryStyle
    personalization_context: Optional[str] = Field(default=None, max_length=8000)
    content: Optional[str] = Field(default=None, max_length=500_000)
    title: Optional[str] = Field(default=None, max_length=512)
    author: Optional[str] = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_by_source(self) -> SummaryCreateJSON:
        if self.source_type == "paste":
            if not self.content or not str(self.content).strip():
                raise ValueError("Field 'content' is required for paste summaries")
        elif self.source_type == "title_author":
            if not self.title or not str(self.title).strip():
                raise ValueError("Field 'title' is required for title_author summaries")
        return self


class SummaryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    author: Optional[str] = None
    source_type: str
    style: str
    status: str
    output_preview: str = ""
    created_at: datetime

    @classmethod
    def from_row(cls, row: "BookSummary", preview_len: int = 400) -> SummaryListItem:
        def _safe_value(enum_col, fallback: str) -> str:
            """Return enum.value, or the raw fallback string if the DB holds an unknown value."""
            try:
                return enum_col.value
            except (LookupError, ValueError, AttributeError):
                return str(fallback)

        return cls(
            id=row.id,
            title=row.title,
            author=row.author,
            source_type=_safe_value(row.source_type, row.source_type),
            style=_safe_value(row.style, row.style),
            status=_safe_value(row.status, row.status),
            output_preview=(row.output_markdown or "")[:preview_len],
            created_at=row.created_at,
        )


class SummaryDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    author: Optional[str] = None
    source_type: str
    style: str
    status: str
    personalization_context: Optional[str] = None
    source_meta: Optional[dict] = None
    output_markdown: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SummaryListResponse(BaseModel):
    items: List[SummaryListItem]
    total: int


class SummaryStatusResponse(BaseModel):
    """Lightweight polling response — no full markdown to keep payload small."""

    id: int
    status: str
    error_message: Optional[str] = None


class SummaryDeleteResponse(BaseModel):
    ok: bool = True
    id: int
