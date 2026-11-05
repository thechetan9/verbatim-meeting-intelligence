"""Core domain types shared across ingestion, retrieval, insights and chat.

Kept deliberately free of framework/storage concerns so every layer can depend on it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


def format_ts(seconds: float) -> str:
    """Render seconds as HH:MM:SS (or MM:SS for meetings under an hour)."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class Utterance(BaseModel):
    """One speaker turn. `idx` is the position inside its meeting and is the unit of citation."""

    idx: int
    speaker: str
    start_s: float
    end_s: float | None = None
    text: str

    @property
    def timestamp(self) -> str:
        return format_ts(self.start_s)


class ParsedTranscript(BaseModel):
    format: str
    utterances: list[Utterance]

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for u in self.utterances:
            seen.setdefault(u.speaker, None)
        return list(seen)

    @property
    def duration_s(self) -> float:
        if not self.utterances:
            return 0.0
        last = self.utterances[-1]
        return last.end_s if last.end_s is not None else last.start_s


class Chunk(BaseModel):
    """A retrieval unit: a window of consecutive speaker turns from a single meeting."""

    id: str
    meeting_id: str
    start_idx: int
    end_idx: int  # inclusive
    start_s: float
    end_s: float
    speakers: list[str]
    text: str  # the turns rendered as "[ts] Speaker: text" lines
    embed_text: str  # text + contextual header; what actually gets embedded / indexed


class InsightsStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"  # no LLM configured


class Meeting(BaseModel):
    id: str
    title: str
    date: str | None = None
    source_filename: str
    format: str
    duration_s: float
    speakers: list[str]
    utterance_count: int
    created_at: str
    insights_status: InsightsStatus = InsightsStatus.PENDING
    insights_error: str | None = None


# ---------- Insights (structured extraction) ----------


class Decision(BaseModel):
    text: str = Field(description="The decision, phrased as a short declarative statement.")
    decided_by: str | None = Field(
        default=None, description="Who made or confirmed the decision, if stated."
    )
    evidence: list[int] = Field(
        description="Utterance numbers (#) that show this decision being made."
    )


class ActionItem(BaseModel):
    task: str = Field(description="What needs to be done, starting with a verb.")
    owner: str | None = Field(default=None, description="Person responsible, if stated.")
    due: str | None = Field(default=None, description="Deadline exactly as stated, if any.")
    evidence: list[int] = Field(description="Utterance numbers (#) where it was assigned.")


class OpenQuestion(BaseModel):
    text: str
    evidence: list[int]


class Topic(BaseModel):
    title: str = Field(description="2-6 word topic label.")
    start_idx: int = Field(description="First utterance number (#) of this topic.")


class MeetingInsights(BaseModel):
    summary: str = Field(description="3-5 sentence neutral summary of the meeting.")
    decisions: list[Decision]
    action_items: list[ActionItem]
    open_questions: list[OpenQuestion]
    topics: list[Topic]
