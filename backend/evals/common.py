"""Shared helpers for the eval harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.domain.models import Meeting
from app.ingestion.service import IngestionService
from app.retrieval.store import MeetingStore

EVALS_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVALS_DIR.parents[1] / "sample_data"
RESULTS_DIR = EVALS_DIR / "results"


@dataclass
class Case:
    id: str
    question: str
    type: str
    meeting: str | None = None
    evidence: str | None = None
    must_include: list[list[str]] = field(default_factory=list)
    answerable: bool = True


def load_cases() -> list[Case]:
    raw = yaml.safe_load((EVALS_DIR / "dataset.yaml").read_text())
    return [Case(**c) for c in raw["cases"]]


def ingest_samples(ingestion: IngestionService) -> dict[str, Meeting]:
    """Ingest all sample transcripts; returns {filename: meeting}."""
    out = {}
    for path in sorted(SAMPLE_DIR.iterdir()):
        if path.suffix in {".txt", ".vtt", ".srt"}:
            out[path.name] = ingestion.ingest(path.read_text("utf-8"), path.name)
    return out


def meeting_for(prefix: str, meetings: dict[str, Meeting]) -> Meeting:
    matches = [m for name, m in meetings.items() if name.startswith(prefix)]
    assert len(matches) == 1, f"meeting prefix {prefix!r} matched {len(matches)} files"
    return matches[0]


def contains(text: str, phrase: str) -> bool:
    return phrase.lower() in " ".join(text.split()).lower()


def new_store() -> MeetingStore:
    return MeetingStore(":memory:")
