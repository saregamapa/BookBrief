from pydantic import BaseModel, Field
from typing import Literal, List, Optional


class NarrateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"] = "onyx"


class PodcastScriptRequest(BaseModel):
    summary_text: str = Field(..., min_length=50, max_length=8000)
    title: str = Field(..., max_length=200)
    author: Optional[str] = Field(None, max_length=100)


class PodcastSegment(BaseModel):
    speaker: str
    voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    text: str


class PodcastScriptResponse(BaseModel):
    segments: List[PodcastSegment]
