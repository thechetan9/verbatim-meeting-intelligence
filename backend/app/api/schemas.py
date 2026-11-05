from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import Meeting, MeetingInsights, Utterance


class ChatTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurnIn] = Field(default_factory=list, max_length=50)
    meeting_ids: list[str] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=6, ge=1, le=25)
    mode: Literal["hybrid", "lexical", "dense"] = "hybrid"
    meeting_ids: list[str] | None = None
    speaker: str | None = None


class SearchHit(BaseModel):
    chunk_id: str
    meeting_id: str
    score: float
    ranks: dict[str, int]
    start_s: float
    end_s: float
    speakers: list[str]
    text: str


class MeetingDetail(BaseModel):
    meeting: Meeting
    insights: MeetingInsights | None


class TranscriptOut(BaseModel):
    meeting_id: str
    utterances: list[Utterance]


class HealthOut(BaseModel):
    status: Literal["ok"]
    llm_enabled: bool
    model: str | None
    meetings: int


class SamplesOut(BaseModel):
    loaded: list[Meeting]
    skipped: list[str]
