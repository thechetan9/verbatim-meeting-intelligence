"""Optional bonus: audio -> speaker-labelled, timestamped transcript using Gemini's audio input.

The output is rendered in the same "[HH:MM:SS] Speaker: text" format the parser already
accepts, so audio uploads flow through exactly the same pipeline as text transcripts.
Trade-off: diarisation by a general LLM is decent for small meetings but not as accurate as a
dedicated ASR + diarisation stack (e.g. WhisperX / AWS Transcribe); see README.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import format_ts
from app.ingestion.parser import parse_timestamp
from app.llm.base import LLM

AUDIO_MIME_TYPES = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}

SYSTEM = (
    "You are a precise meeting transcriber. Transcribe speech verbatim (light clean-up of filler "
    "words is fine). Split into one segment per speaker turn. Identify distinct speakers: use a "
    "person's name only if they introduce themselves or are clearly addressed by name; otherwise "
    "use 'Speaker 1', 'Speaker 2', consistently. Do not summarise or invent content."
)
PROMPT = "Transcribe this meeting recording into speaker turns with start times."


class Segment(BaseModel):
    start: str = Field(description="Start time of the turn as MM:SS or HH:MM:SS.")
    speaker: str
    text: str


class AudioTranscript(BaseModel):
    segments: list[Segment]


def transcribe_audio(llm: LLM, audio: bytes, mime_type: str) -> str:
    result, _ = llm.generate_json_from_audio(SYSTEM, PROMPT, audio, mime_type, AudioTranscript)
    lines = []
    for seg in result.segments:
        text = " ".join(seg.text.split())
        if not text:
            continue
        try:
            ts = format_ts(parse_timestamp(seg.start))
        except ValueError:
            ts = "00:00"
        speaker = seg.speaker.strip().replace(":", "") or "Speaker"
        lines.append(f"[{ts}] {speaker}: {text}")
    return "\n".join(lines)
