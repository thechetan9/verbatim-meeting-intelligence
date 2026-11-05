"""MCP server: exposes the meeting knowledge base to any MCP client (Claude Code, Claude Desktop,
Cursor, other agents) using the *same* tools the in-app agent uses.

    uv sync --extra mcp
    claude mcp add verbatim -- uv --directory /path/to/verbatim-meeting-intelligence/backend run python -m app.mcp_server

It reads the same SQLite database as the API (DATABASE_PATH), read-only. No LLM key needed:
retrieval and pre-extracted insights are served as-is and the client's model does the reasoning.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.chat.evidence import EvidenceRegistry
from app.chat.prompts import render_catalog
from app.chat.tools import ToolExecutor
from app.config import get_settings
from app.llm.base import ToolCall
from app.retrieval.embedder import FastEmbedEmbedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.store import MeetingStore

settings = get_settings()
store = MeetingStore(settings.database_path)
retriever = HybridRetriever(
    store,
    FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir),
    min_dense_score=settings.retrieval_min_dense_score,
)

server = MCPServer(
    name="verbatim",
    title="Verbatim meeting intelligence",
    instructions=(
        "Search meeting transcripts and pre-extracted decisions/action items. Call list_meetings "
        "first to get meeting ids. Results include citation keys like [S3] with speaker and timestamp; "
        "quote them when answering."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _run(name: str, args: dict) -> str:
    executor = ToolExecutor(
        store, retriever, EvidenceRegistry(), scope=None, top_k=settings.retrieval_top_k
    )
    result = executor.execute(ToolCall(id="mcp", name=name, args=args))
    return next(iter(result.payload.values()))


@server.tool(annotations=READ_ONLY)
def list_meetings() -> str:
    """List all ingested meetings: id, title, date, duration and participants."""
    return render_catalog(store.list_meetings())


@server.tool(annotations=READ_ONLY)
def search_transcripts(
    query: str, meeting_ids: list[str] | None = None, speaker: str | None = None
) -> str:
    """Hybrid (keyword + semantic) search over what was said in meetings.

    Args:
        query: focused search terms (names, ids, topics), not a full question
        meeting_ids: optional list of meeting ids to restrict the search to
        speaker: optional person name; only excerpts where they speak
    """
    return _run(
        "search_transcripts", {"query": query, "meeting_ids": meeting_ids, "speaker": speaker}
    )


@server.tool(annotations=READ_ONLY)
def get_meeting_insights(meeting_ids: list[str] | None = None, owner: str | None = None) -> str:
    """Decisions, action items (owner, due date) and open questions extracted from meetings.

    Args:
        meeting_ids: optional meeting ids; omit for all meetings
        owner: optional person name to list only their action items
    """
    return _run("get_meeting_insights", {"meeting_ids": meeting_ids, "owner": owner})


if __name__ == "__main__":
    server.run("stdio")
