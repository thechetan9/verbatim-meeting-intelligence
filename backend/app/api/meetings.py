from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_container
from app.api.schemas import MeetingDetail, SamplesOut, TranscriptOut
from app.container import Container
from app.domain.models import Meeting
from app.ingestion.parser import TranscriptParseError
from app.ingestion.service import DuplicateMeetingError, content_fingerprint, infer_title
from app.ingestion.transcribe import AUDIO_MIME_TYPES, transcribe_audio
from app.llm.base import LLMError

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
ContainerDep = Annotated[Container, Depends(get_container)]


def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {limit // 1_000_000} MB limit."
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    return data


def _ingest_and_schedule(
    c: Container,
    content: str,
    filename: str,
    title: str | None,
    date: str | None,
    fingerprint: str | None = None,
) -> Meeting:
    try:
        meeting = c.ingestion.ingest(
            content, filename, title=title, date=date, fingerprint=fingerprint
        )
    except DuplicateMeetingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except TranscriptParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if c.ingestion.extractor:
        c.run_background(c.ingestion.generate_insights, meeting.id)
    return meeting


@router.get("")
def list_meetings(c: ContainerDep) -> list[Meeting]:
    return c.store.list_meetings()


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_meeting(
    c: ContainerDep,
    file: Annotated[UploadFile, File(description="Transcript (.txt/.vtt/.srt) or audio file")],
    title: Annotated[str | None, Form(max_length=200)] = None,
    date: Annotated[str | None, Form(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> Meeting:
    filename = Path(file.filename or "transcript.txt").name
    suffix = Path(filename).suffix.lower()

    if suffix in AUDIO_MIME_TYPES:
        if c.llm is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Audio transcription needs an LLM API key."
            )
        audio = _read_limited(file, c.settings.max_audio_bytes)
        # Check before transcribing: a re-upload shouldn't cost another transcription call.
        fingerprint = content_fingerprint(audio)
        try:
            c.ingestion.check_duplicate(fingerprint)
        except DuplicateMeetingError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        try:
            content = transcribe_audio(c.llm, audio, AUDIO_MIME_TYPES[suffix])
        except LLMError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Transcription failed: {exc}"
            ) from exc
        return _ingest_and_schedule(
            c,
            content,
            f"{Path(filename).stem}.txt",
            title or infer_title("", filename),
            date,
            fingerprint,
        )

    raw = _read_limited(file, c.settings.max_upload_bytes)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Transcript must be UTF-8 text."
        ) from exc
    return _ingest_and_schedule(c, content, filename, title, date)


@router.post("/samples")
def load_samples(c: ContainerDep) -> SamplesOut:
    """One-click demo data: ingest the bundled synthetic transcripts (idempotent)."""
    folder = Path(c.settings.sample_data_dir)
    if not folder.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample data folder not found.")
    loaded, skipped = [], []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".txt", ".vtt", ".srt"}:
            continue
        if c.store.find_by_filename(path.name):
            skipped.append(path.name)
            continue
        loaded.append(_ingest_and_schedule(c, path.read_text("utf-8"), path.name, None, None))
    return SamplesOut(loaded=loaded, skipped=skipped)


@router.get("/{meeting_id}")
def get_meeting(meeting_id: str, c: ContainerDep) -> MeetingDetail:
    meeting = c.store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    return MeetingDetail(meeting=meeting, insights=c.store.get_insights(meeting_id))


@router.get("/{meeting_id}/transcript")
def get_transcript(meeting_id: str, c: ContainerDep) -> TranscriptOut:
    if c.store.get_meeting(meeting_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    return TranscriptOut(meeting_id=meeting_id, utterances=c.store.get_utterances(meeting_id))


@router.post("/{meeting_id}/insights", status_code=status.HTTP_202_ACCEPTED)
def regenerate_insights(meeting_id: str, c: ContainerDep) -> dict[str, str]:
    if c.store.get_meeting(meeting_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    if not c.ingestion.extractor:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No LLM configured.")
    c.run_background(c.ingestion.generate_insights, meeting_id)
    return {"status": "scheduled"}


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str, c: ContainerDep) -> None:
    if not c.store.delete_meeting(meeting_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
