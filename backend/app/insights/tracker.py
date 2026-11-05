"""Cross-meeting action-item tracker: every task from every meeting, with owners resolved to people.

Owners come from the LLM as written in the meeting ("Marcus", "Dr. Rao", "Priya Nair"), so
they are resolved against the participants seen across all meetings. That way one person's
tasks group together no matter how they were addressed.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.retrieval.store import MeetingStore

_TITLES = re.compile(r"^(dr|mr|ms|mrs|prof)\.?\s+", re.IGNORECASE)


class TrackedActionItem(BaseModel):
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    owner: str | None  # canonical participant name when it could be resolved
    task: str
    due: str | None
    evidence: list[int]
    start_s: float | None  # when the item was assigned (first evidence line)


def _normalise(name: str) -> str:
    return _TITLES.sub("", name).strip().lower()


def canonical_owner(owner: str | None, people: list[str]) -> str | None:
    """Map an owner as written ("Marcus", "Dr. Rao") to a participant name ("Marcus Lee")."""
    if not owner or not owner.strip():
        return None
    o = _normalise(owner)
    exact = [p for p in people if _normalise(p) == o]
    if exact:
        return exact[0]
    partial = [p for p in people if o in _normalise(p).split() or _normalise(p).startswith(o)]
    return partial[0] if len(partial) == 1 else owner.strip()  # ambiguous: keep as written


def collect_action_items(
    store: MeetingStore, meeting_ids: list[str] | None = None
) -> list[TrackedActionItem]:
    meetings = [m for m in store.list_meetings() if not meeting_ids or m.id in meeting_ids]
    people = list(dict.fromkeys(s for m in store.list_meetings() for s in m.speakers))
    items: list[TrackedActionItem] = []
    for m in meetings:
        insights = store.get_insights(m.id)
        if insights is None:
            continue
        for a in insights.action_items:
            first = a.evidence[0] if a.evidence else None
            lines = store.get_utterances(m.id, first, first) if first is not None else []
            items.append(
                TrackedActionItem(
                    meeting_id=m.id,
                    meeting_title=m.title,
                    meeting_date=m.date,
                    owner=canonical_owner(a.owner, people),
                    task=a.task,
                    due=a.due,
                    evidence=a.evidence,
                    start_s=lines[0].start_s if lines else None,
                )
            )
    # Unassigned last; within a person, oldest meeting first.
    return sorted(items, key=lambda i: (i.owner is None, i.owner or "", i.meeting_date or ""))
