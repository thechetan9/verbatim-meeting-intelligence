from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_container
from app.api.schemas import ChatRequest, HealthOut, SearchHit, SearchRequest
from app.chat.guardrails import GuardrailViolation, validate_question
from app.container import Container
from app.llm.base import ChatTurn
from app.observability import request_id_var
from app.retrieval.hybrid import SearchFilters, SearchMode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])
ContainerDep = Annotated[Container, Depends(get_container)]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest, c: ContainerDep) -> StreamingResponse:
    """Streams the agent's work as Server-Sent Events:
    tool_call / tool_result (agent steps), delta (answer tokens), reset, citations, done, error."""
    if c.agent is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No LLM configured. Set GEMINI_API_KEY."
        )
    try:
        question = validate_question(req.question, c.settings.max_question_chars)
    except GuardrailViolation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    history = [ChatTurn(role=t.role, content=t.content) for t in req.history]
    agent = c.agent
    request_id = request_id_var.get()

    def stream() -> Iterator[str]:
        # Starlette resumes a sync generator in a worker thread with a fresh context copy each
        # time, so the request id is re-applied before every step to keep logs correlated.
        events = agent.run(question, history, req.meeting_ids)
        while True:
            request_id_var.set(request_id)
            try:
                ev = next(events)
            except StopIteration:
                return
            except Exception:  # surface failures to the client instead of a silently cut stream
                logger.exception("chat.crashed")
                yield _sse("error", {"message": "Something went wrong while answering."})
                return
            yield _sse(ev["event"], ev["data"])

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/search")
def search(req: SearchRequest, c: ContainerDep) -> list[SearchHit]:
    """Raw retrieval (no LLM). Useful for debugging and for comparing retrieval modes."""
    hits = c.retriever.search(
        req.query,
        k=req.k,
        filters=SearchFilters(meeting_ids=req.meeting_ids, speaker=req.speaker),
        mode=SearchMode(req.mode),
    )
    return [
        SearchHit(
            chunk_id=h.chunk.id,
            meeting_id=h.chunk.meeting_id,
            score=h.score,
            ranks=h.ranks,
            start_s=h.chunk.start_s,
            end_s=h.chunk.end_s,
            speakers=h.chunk.speakers,
            text=h.chunk.text,
        )
        for h in hits
    ]


@router.get("/health")
def health(c: ContainerDep) -> HealthOut:
    return HealthOut(
        status="ok",
        llm_enabled=c.llm is not None,
        model=c.llm.model if c.llm else None,
        meetings=len(c.store.list_meetings()),
    )
