"""Transcript parsing: plain-text (several common layouts), WebVTT and SRT -> utterances.

Real transcripts are messy, so the parser is tolerant: it accepts a handful of
timestamp/speaker layouts, folds continuation lines into the previous turn, and
merges consecutive caption cues from the same speaker (Teams/Zoom VTT exports
split one sentence across many cues).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import ParsedTranscript, Utterance


class TranscriptParseError(ValueError):
    pass


_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"

# "[00:01:23] Speaker: text"  |  "00:01:23 Speaker: text"  |  "(01:23) Speaker - text"
_TS_FIRST = re.compile(
    rf"^\s*[\[(]?(?P<ts>{_TS})[\])]?\s*[-–|]?\s*(?P<speaker>[^:\[\]()]{{1,60}}?)\s*[:\-–]\s+(?P<text>.+)$"
)
# "Speaker (00:01:23): text"  |  "Speaker [01:23]: text"  |  "Speaker 00:01:23: text"
_SPEAKER_FIRST = re.compile(
    rf"^\s*(?P<speaker>[^:\[\]()\d][^:\[\]()]{{0,59}}?)\s*[\[(]?(?P<ts>{_TS})[\])]?\s*[:\-–](?!\d)\s*(?P<text>.+)$"
)
# Two-line "Otter" style header: "Speaker Name  00:01:23" (text on following lines)
_HEADER_ONLY = re.compile(
    rf"^\s*(?P<speaker>[^:\[\]()\d][^:\[\]()]{{0,59}}?)\s+[\[(]?(?P<ts>{_TS})[\])]?\s*$"
)
_CUE_TIMING = re.compile(rf"^\s*(?P<start>{_TS})\s*-->\s*(?P<end>{_TS})")
_VTT_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s(?P<speaker>[^>]+)>")
_INLINE_SPEAKER = re.compile(r"^(?P<speaker>[^:\n]{1,60}):\s(?P<text>.+)$", re.S)
_TAGS = re.compile(r"<[^>]+>")


def parse_timestamp(value: str) -> float:
    """'1:02:03.5' -> 3723.5 ; '02:03' -> 123.0 ; accepts ',' as the decimal separator (SRT)."""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:  # pragma: no cover - guarded by regexes
        raise TranscriptParseError(f"Bad timestamp: {value!r}") from exc
    seconds = 0.0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


def parse_transcript(content: str, filename: str = "") -> ParsedTranscript:
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not text.strip():
        raise TranscriptParseError("The file is empty.")

    lower = filename.lower()
    if lower.endswith(".vtt") or text.lstrip().startswith("WEBVTT"):
        fmt, raw = "vtt", _parse_cues(text)
    elif lower.endswith(".srt") or _looks_like_srt(text):
        fmt, raw = "srt", _parse_cues(text)
    else:
        fmt, raw = "txt", _parse_plain(text)

    if not raw:
        raise TranscriptParseError(
            "No speaker-labelled, timestamped lines found. Expected lines like "
            "'[00:01:23] Speaker: text', or a WebVTT/SRT file."
        )
    return ParsedTranscript(format=fmt, utterances=_finalise(raw))


@dataclass
class _Raw:
    speaker: str
    start_s: float
    end_s: float | None
    text: str


def _clean_speaker(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" -–|*").strip()


def _parse_plain(text: str) -> list[_Raw]:
    out: list[_Raw] = []
    pending_header: tuple[str, float] | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        m = _TS_FIRST.match(stripped) or _SPEAKER_FIRST.match(stripped)
        if m:
            pending_header = None
            out.append(
                _Raw(
                    _clean_speaker(m["speaker"]), parse_timestamp(m["ts"]), None, m["text"].strip()
                )
            )
            continue

        h = _HEADER_ONLY.match(stripped)
        if h:
            pending_header = (_clean_speaker(h["speaker"]), parse_timestamp(h["ts"]))
            continue

        if pending_header:
            speaker, start = pending_header
            out.append(_Raw(speaker, start, None, stripped))
            pending_header = None
        elif out:  # continuation of the previous turn
            out[-1].text = f"{out[-1].text} {stripped}"
        # else: preamble before the first turn (title lines etc.) is ignored
    return out


def _looks_like_srt(text: str) -> bool:
    lines = [ln for ln in text.split("\n") if ln.strip()][:3]
    return len(lines) >= 2 and lines[0].strip().isdigit() and bool(_CUE_TIMING.match(lines[1]))


def _split_cue_speaker(body: str) -> tuple[str | None, str]:
    """Return (speaker, text) for a cue body using <v Speaker> tags or a 'Speaker: ' prefix."""
    voice = _VTT_VOICE.search(body)
    plain = _TAGS.sub("", body)
    if voice:
        return voice["speaker"], plain
    inline = _INLINE_SPEAKER.match(plain)
    if inline:
        return inline["speaker"], inline["text"]
    return None, plain


def _parse_cue_block(block: str) -> tuple[str | None, float, float, str] | None:
    lines = [ln for ln in block.split("\n") if ln.strip()]
    for i, line in enumerate(lines):
        timing = _CUE_TIMING.match(line)
        if timing:
            speaker, text = _split_cue_speaker("\n".join(lines[i + 1 :]).strip())
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                return None
            return speaker, parse_timestamp(timing["start"]), parse_timestamp(timing["end"]), text
    return None  # header, NOTE or STYLE block


def _parse_cues(text: str) -> list[_Raw]:
    out: list[_Raw] = []
    for block in re.split(r"\n\s*\n", text):
        cue = _parse_cue_block(block)
        if cue is None:
            continue
        speaker, start, end, body = cue
        if speaker:
            speaker = _clean_speaker(speaker)
        else:  # caption without a label continues the previous speaker
            speaker = out[-1].speaker if out else "Unknown"

        # Merge consecutive cues from the same speaker into a single turn.
        if out and out[-1].speaker == speaker:
            out[-1].text = f"{out[-1].text} {body}"
            out[-1].end_s = end
        else:
            out.append(_Raw(speaker, start, end, body))
    return out


def _finalise(raw: list[_Raw]) -> list[Utterance]:
    utterances: list[Utterance] = []
    for i, r in enumerate(raw):
        end = r.end_s
        if end is None and i + 1 < len(raw):
            end = max(raw[i + 1].start_s, r.start_s)
        utterances.append(
            Utterance(idx=i, speaker=r.speaker, start_s=r.start_s, end_s=end, text=r.text.strip())
        )
    return utterances
