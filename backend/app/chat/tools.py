"""The agent's tools. Two, on purpose: fewer, well-described tools are chosen more reliably.

  search_transcripts   -> hybrid retrieval over what was *said* (quotes, reasons, discussion)
  get_meeting_insights -> pre-extracted decisions / action items / open questions (structured)

Scope enforcement happens here, not in the prompt: if the user limited the chat to some
meetings, any meeting ids the model asks for are intersected with that scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.chat.evidence import EvidenceRegistry
from app.domain.models import Meeting, MeetingInsights
from app.llm.base import ToolCall, ToolSpec
from app.retrieval.hybrid import HybridRetriever, SearchFilters
from app.retrieval.store import MeetingStore

SEARCH_TRANSCRIPTS = ToolSpec(
    name="search_transcripts",
    description=(
        "Search what was said in the meetings (hybrid keyword + semantic search). Returns "
        "transcript excerpts; each line has a citation key like [S3]. Use for questions about "
        "discussions, reasons, numbers, who said what, or anything not covered by insights. "
        "Call it again with different wording if the first results don't answer the question."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Focused search query: key terms, names, ids. Not the full question.",
            },
            "meeting_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict to these meeting ids. Omit to search all meetings.",
            },
            "speaker": {
                "type": "string",
                "description": "Only excerpts where this person speaks (name or part of it).",
            },
        },
        "required": ["query"],
    },
)

GET_MEETING_INSIGHTS = ToolSpec(
    name="get_meeting_insights",
    description=(
        "Get pre-extracted structured notes for meetings: summary, decisions, action items "
        "(owner + due date) and open questions, each with citation keys. Best for 'what was "
        "decided', 'what are the action items', 'what does X owe', summaries, and comparing "
        "decisions across meetings."
    ),
    parameters={
        "type": "object",
        "properties": {
            "meeting_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Meeting ids to fetch. Omit for all meetings.",
            },
            "owner": {
                "type": "string",
                "description": "Only return action items owned by this person.",
            },
        },
    },
)

TOOL_SPECS = [SEARCH_TRANSCRIPTS, GET_MEETING_INSIGHTS]


@dataclass
class ToolResult:
    payload: dict[str, Any]  # what the model sees
    summary: str  # what the UI shows ("6 excerpts from 2 meetings")
    meta: dict[str, Any]  # what goes into the trace


class ToolExecutor:
    def __init__(
        self,
        store: MeetingStore,
        retriever: HybridRetriever,
        registry: EvidenceRegistry,
        scope: list[str] | None,
        top_k: int = 6,
    ):
        self.store = store
        self.retriever = retriever
        self.registry = registry
        self.scope = scope or None
        self.top_k = top_k
        self._meetings = {m.id: m for m in store.list_meetings()}

    def _resolve_meetings(self, requested: list[str] | None) -> list[str] | None:
        """Intersect what the model asked for with the user's scope. None means 'all'."""
        requested = [m for m in (requested or []) if m in self._meetings] or None
        if self.scope and requested:
            return [m for m in requested if m in self.scope] or list(self.scope)
        return requested or self.scope

    def execute(self, call: ToolCall) -> ToolResult:
        if call.name == SEARCH_TRANSCRIPTS.name:
            return self._search(call.args)
        if call.name == GET_MEETING_INSIGHTS.name:
            return self._insights(call.args)
        return ToolResult(
            payload={
                "error": f"Unknown tool '{call.name}'. Available: search_transcripts, get_meeting_insights."
            },
            summary="unknown tool",
            meta={"error": "unknown_tool"},
        )

    # ---------- search_transcripts ----------

    def _search(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()[:300]
        if not query:
            return ToolResult(
                {"error": "query is required"}, "empty query", {"error": "empty_query"}
            )
        meeting_ids = self._resolve_meetings(_as_list(args.get("meeting_ids")))
        speaker = (str(args["speaker"]).strip() or None) if args.get("speaker") else None
        hits = self.retriever.search(
            query, k=self.top_k, filters=SearchFilters(meeting_ids=meeting_ids, speaker=speaker)
        )
        if not hits:
            return ToolResult(
                {"excerpts": "No matching transcript excerpts found."},
                "no results",
                {"query": query, "hits": 0},
            )

        # Group excerpts by meeting, in chronological order, so the model reads coherent dialogue.
        by_meeting: dict[str, list] = {}
        for h in hits:
            by_meeting.setdefault(h.chunk.meeting_id, []).append(h.chunk)
        blocks: list[str] = []
        for mid, chunks in by_meeting.items():
            meeting = self._meetings[mid]
            seen: set[int] = set()
            lines: list[str] = []
            for chunk in sorted(chunks, key=lambda c: c.start_idx):
                for u in self.store.get_utterances(mid, chunk.start_idx, chunk.end_idx):
                    if u.idx in seen:
                        continue
                    seen.add(u.idx)
                    key = self.registry.register(meeting, u)
                    lines.append(f"[{key}] {u.timestamp} {u.speaker}: {u.text}")
            blocks.append(f"{_meeting_header(meeting)}\n" + "\n".join(lines))

        return ToolResult(
            payload={
                "excerpts": "<transcript_excerpts>\n"
                + "\n\n".join(blocks)
                + "\n</transcript_excerpts>"
            },
            summary=f"{len(hits)} excerpts from {len(by_meeting)} meeting{'s' if len(by_meeting) > 1 else ''}",
            meta={
                "query": query,
                "meeting_ids": meeting_ids,
                "speaker": speaker,
                "hits": len(hits),
                "chunks": [
                    {"id": h.chunk.id, "score": round(h.score, 4), "ranks": h.ranks} for h in hits
                ],
            },
        )

    # ---------- get_meeting_insights ----------

    def _insights(self, args: dict[str, Any]) -> ToolResult:
        meeting_ids = self._resolve_meetings(_as_list(args.get("meeting_ids"))) or list(
            self._meetings
        )
        owner = (str(args.get("owner") or "").strip().lower()) or None
        blocks: list[str] = []
        missing: list[str] = []
        for mid in meeting_ids:
            meeting = self._meetings.get(mid)
            insights = self.store.get_insights(mid) if meeting else None
            if meeting is None or insights is None:
                missing.append(mid)
                continue
            blocks.append(self._render_insights(meeting, insights, owner))
        if missing:
            blocks.append(
                "Insights not available for: "
                + ", ".join(missing)
                + " (use search_transcripts instead)."
            )
        return ToolResult(
            payload={
                "insights": "<meeting_insights>\n" + "\n\n".join(blocks) + "\n</meeting_insights>"
            },
            summary=f"notes for {len(meeting_ids) - len(missing)} meeting(s)"
            + (f", owner '{owner}'" if owner else ""),
            meta={"meeting_ids": meeting_ids, "owner": owner, "missing": missing},
        )

    def _cite(self, meeting: Meeting, idxs: list[int]) -> str:
        utterances = {u.idx: u for u in self.store.get_utterances(meeting.id, min(idxs), max(idxs))}
        return "".join(
            f"[{self.registry.register(meeting, utterances[i])}]" for i in idxs if i in utterances
        )

    def _render_insights(self, meeting: Meeting, ins: MeetingInsights, owner: str | None) -> str:
        out = [_meeting_header(meeting)]
        if not owner:
            out.append(f"Summary: {ins.summary}")
            out.append("Decisions:")
            out += [
                f"- {d.text}"
                + (f" (decided by {d.decided_by})" if d.decided_by else "")
                + f" {self._cite(meeting, d.evidence)}"
                for d in ins.decisions
            ] or ["- none recorded"]
        items = [a for a in ins.action_items if not owner or (a.owner and owner in a.owner.lower())]
        out.append("Action items:")
        out += [
            f"- {a.task} | owner: {a.owner or 'unassigned'} | due: {a.due or 'not stated'} {self._cite(meeting, a.evidence)}"
            for a in items
        ] or ["- none"]
        if not owner:
            out.append("Open questions:")
            out += [
                f"- {q.text} {self._cite(meeting, q.evidence)}" for q in ins.open_questions
            ] or ["- none"]
        return "\n".join(out)


def _meeting_header(m: Meeting) -> str:
    return f'## Meeting {m.id}: "{m.title}"' + (f" ({m.date})" if m.date else "")


def _as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]
