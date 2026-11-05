"""Citation bookkeeping for one chat turn.

Every transcript line shown to the model gets a short key ([S1], [S2], ...). The model
cites keys, never free-form quotes, which makes citations machine-checkable: after the
answer is generated we know exactly which meeting, speaker and second each one points to,
and we can reject keys the model never saw.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Meeting, Utterance

CITATION_RE = re.compile(r"\[(S\d+)\]")
# Models sometimes group keys: "[S1, S4]" -> normalised to "[S1][S4]".
_GROUPED_RE = re.compile(r"\[((?:S\d+\s*,\s*)+S\d+)\]")


@dataclass(frozen=True)
class Evidence:
    key: str
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    utterance_idx: int
    speaker: str
    start_s: float
    timestamp: str
    text: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "meeting_id": self.meeting_id,
            "meeting_title": self.meeting_title,
            "meeting_date": self.meeting_date,
            "utterance_idx": self.utterance_idx,
            "speaker": self.speaker,
            "start_s": self.start_s,
            "timestamp": self.timestamp,
            "text": self.text,
        }


class EvidenceRegistry:
    def __init__(self) -> None:
        self._by_key: dict[str, Evidence] = {}
        self._by_ref: dict[tuple[str, int], str] = {}

    def register(self, meeting: Meeting, u: Utterance) -> str:
        ref = (meeting.id, u.idx)
        if ref in self._by_ref:
            return self._by_ref[ref]
        key = f"S{len(self._by_key) + 1}"
        self._by_ref[ref] = key
        self._by_key[key] = Evidence(
            key=key,
            meeting_id=meeting.id,
            meeting_title=meeting.title,
            meeting_date=meeting.date,
            utterance_idx=u.idx,
            speaker=u.speaker,
            start_s=u.start_s,
            timestamp=u.timestamp,
            text=u.text,
        )
        return key

    def get(self, key: str) -> Evidence | None:
        return self._by_key.get(key)

    def __len__(self) -> int:
        return len(self._by_key)


def normalise_citations(text: str) -> str:
    return _GROUPED_RE.sub(lambda m: "".join(f"[{k.strip()}]" for k in m.group(1).split(",")), text)


def extract_citations(text: str) -> list[str]:
    return list(dict.fromkeys(CITATION_RE.findall(normalise_citations(text))))


def strip_citations(text: str) -> str:
    return re.sub(r"\s*\[S\d+(?:\s*,\s*S\d+)*\]", "", text)
