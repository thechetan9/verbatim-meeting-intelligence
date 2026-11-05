"""Ingestion pipeline: raw transcript -> parsed turns -> chunks -> embeddings -> store.

Insight extraction (an LLM call, seconds) is a separate step so uploads return as soon
as the meeting is searchable; the API schedules it in the background.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import InsightsStatus, Meeting
from app.ingestion.chunker import ChunkingConfig, chunk_utterances
from app.ingestion.parser import TranscriptParseError, parse_transcript
from app.insights.extractor import InsightsExtractor
from app.llm.base import LLMError
from app.observability import log_event
from app.retrieval.embedder import Embedder
from app.retrieval.store import MeetingStore

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".txt", ".vtt", ".srt", ".md"}
_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TRAILING_DATE = re.compile(r"\s*[—–\-|,]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*$")
_TIMESTAMPED = re.compile(r"\d{1,2}:\d{2}")


def infer_date(filename: str) -> str | None:
    m = _DATE_IN_NAME.search(filename)
    return m.group(1) if m else None


def infer_title(content: str, filename: str) -> str:
    """First descriptive preamble line (txt title line / VTT NOTE), else a prettified filename.

    Only text *before* the first timestamp counts as preamble, so the first line of dialogue
    (e.g. in an SRT file with no header) is never mistaken for a title.
    """
    lines = [ln.strip() for ln in content.lstrip("\ufeff").splitlines() if ln.strip()]
    for line in lines[:4]:
        if _TIMESTAMPED.search(line):
            break
        if line.upper() in {"WEBVTT", "NOTE"} or line.isdigit():
            continue
        if line.startswith("(") or line.lower().startswith("synthetic"):
            continue
        title = _TRAILING_DATE.sub("", line).strip(" —-")
        if 3 <= len(title) <= 120:
            return title
        break
    stem = _DATE_IN_NAME.sub("", Path(filename).stem).strip("_- ")
    return re.sub(r"[_\-]+", " ", stem).strip().title() or "Untitled meeting"


class DuplicateMeetingError(ValueError):
    def __init__(self, existing: Meeting):
        super().__init__(f'This file is already uploaded as "{existing.title}".')
        self.existing = existing


def content_fingerprint(data: str | bytes) -> str:
    """Hash of the upload, ignoring line-ending and surrounding-whitespace differences."""
    if isinstance(data, str):
        data = data.replace("\r\n", "\n").strip().encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class IngestionService:
    def __init__(
        self,
        store: MeetingStore,
        embedder: Embedder,
        extractor: InsightsExtractor | None,
        chunking: ChunkingConfig | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.extractor = extractor
        self.chunking = chunking or ChunkingConfig()

    def check_duplicate(self, fingerprint: str) -> None:
        existing = self.store.find_by_hash(fingerprint)
        if existing:
            raise DuplicateMeetingError(existing)

    def ingest(
        self,
        content: str,
        filename: str,
        title: str | None = None,
        date: str | None = None,
        fingerprint: str | None = None,
    ) -> Meeting:
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise TranscriptParseError(
                f"Unsupported file type. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )
        fingerprint = fingerprint or content_fingerprint(content)
        self.check_duplicate(fingerprint)
        started = time.perf_counter()
        parsed = parse_transcript(content, filename)
        meeting = Meeting(
            id=f"m_{uuid.uuid4().hex[:8]}",
            title=(title or "").strip() or infer_title(content, filename),
            date=(date or "").strip() or infer_date(filename),
            source_filename=filename,
            format=parsed.format,
            duration_s=parsed.duration_s,
            speakers=parsed.speakers,
            utterance_count=len(parsed.utterances),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            insights_status=InsightsStatus.PENDING if self.extractor else InsightsStatus.SKIPPED,
        )
        chunks = chunk_utterances(
            meeting.id, meeting.title, meeting.date, parsed.utterances, self.chunking
        )
        embeddings = self.embedder.embed_documents([c.embed_text for c in chunks])
        self.store.add_meeting(meeting, parsed.utterances, chunks, embeddings, fingerprint)
        log_event(
            logger,
            "meeting.ingested",
            meeting_id=meeting.id,
            filename=filename,
            format=parsed.format,
            utterances=len(parsed.utterances),
            chunks=len(chunks),
            ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return meeting

    def generate_insights(self, meeting_id: str) -> None:
        """Safe to run in a background task: failures are recorded on the meeting, not raised."""
        meeting = self.store.get_meeting(meeting_id)
        if meeting is None or self.extractor is None:
            return
        self.store.set_insights(meeting_id, InsightsStatus.PENDING)
        try:
            insights, _ = self.extractor.extract(meeting, self.store.get_utterances(meeting_id))
            self.store.set_insights(meeting_id, InsightsStatus.READY, insights)
        except LLMError as exc:
            logger.warning(
                "insights.failed", extra={"data": {"meeting_id": meeting_id, "error": str(exc)}}
            )
            self.store.set_insights(meeting_id, InsightsStatus.FAILED, error=str(exc)[:500])
        except Exception as exc:  # never let a background task die silently
            logger.exception("insights.crashed", extra={"data": {"meeting_id": meeting_id}})
            self.store.set_insights(meeting_id, InsightsStatus.FAILED, error=type(exc).__name__)
