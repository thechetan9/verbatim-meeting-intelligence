"""Suggested follow-up questions after an answer.

One small structured-output call after the answer has been delivered, so it never delays the
answer itself. It is best-effort: any failure just means no suggestions are shown.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.domain.models import Meeting
from app.llm.base import LLM

logger = logging.getLogger(__name__)

SYSTEM = """You suggest follow-up questions for a user exploring their meeting transcripts.
Rules:
- Suggest questions the meetings below can plausibly answer; do not invent topics.
- Each question is short (under 15 words), specific, and different from the original question.
- Prefer questions about decisions, owners, deadlines, reasons, or how something changed.
- Plain text only. No numbering."""


class FollowUps(BaseModel):
    questions: list[str] = Field(description="2-3 short follow-up questions.")


def suggest_followups(
    llm: LLM, question: str, answer: str, meetings: list[Meeting], limit: int = 3
) -> list[str]:
    catalog = "\n".join(f"- {m.title} ({m.date or 'no date'})" for m in meetings) or "(none)"
    prompt = (
        f"Meetings:\n{catalog}\n\nUser question: {question}\n\nAnswer given (truncated):\n"
        f"{answer[:1500]}\n\nSuggest up to {limit} follow-up questions."
    )
    try:
        result, _ = llm.generate_json(SYSTEM, prompt, FollowUps)
    except Exception:  # best-effort feature: never let it break the chat
        logger.warning("followups.failed", exc_info=True)
        return []

    def key(text: str) -> str:
        return text.strip().lower().rstrip("?")

    seen: set[str] = {key(question)}
    out: list[str] = []
    for q in result.questions:
        q = " ".join(q.split()).strip(" -•")
        if not q or len(q) > 140 or key(q) in seen:
            continue
        seen.add(key(q))
        out.append(q if q.endswith("?") else f"{q}?")
    return out[:limit]
