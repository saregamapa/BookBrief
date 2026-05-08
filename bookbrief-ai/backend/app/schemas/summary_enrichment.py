from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

class TranslateRequest(BaseModel):
    locale: str = Field(..., min_length=2, max_length=32, description="BCP-47 language tag, e.g. es, fr, ja")


class TranslateResponse(BaseModel):
    locale: str
    markdown: str
    from_cache: bool


class TranslationListItem(BaseModel):
    locale: str
    created_at: datetime


class TranslationsListResponse(BaseModel):
    items: List[TranslationListItem]


class VideoSummaryResponse(BaseModel):
    status: str
    video_url: Optional[str] = None
    subtitle_vtt: Optional[str] = None
    poster_url: Optional[str] = None
    error_message: Optional[str] = None
    progress_phase: Optional[str] = None
    progress_detail: Optional[str] = None
