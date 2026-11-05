"""SQLite-backed storage: meetings, utterances, chunks, FTS5 (BM25) index and embeddings.

Why SQLite instead of a dedicated vector DB for this build:
  * one file, zero extra services: `docker compose up` and you are running;
  * FTS5 gives a real BM25 index for the lexical half of hybrid search for free;
  * at meeting-corpus scale (thousands of chunks) exact cosine over a numpy matrix
    is a few milliseconds, faster and more accurate than an ANN index.
The `MeetingStore` surface is small on purpose so it can be re-implemented on
Postgres + pgvector + tsvector (the production target, see README) without touching
retrieval or chat code.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.domain.models import (
    Chunk,
    InsightsStatus,
    Meeting,
    MeetingInsights,
    Utterance,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    date TEXT,
    source_filename TEXT NOT NULL,
    format TEXT NOT NULL,
    duration_s REAL NOT NULL,
    speakers TEXT NOT NULL,
    utterance_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    insights_status TEXT NOT NULL,
    insights_error TEXT,
    insights TEXT
);
CREATE TABLE IF NOT EXISTS utterances (
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL,
    text TEXT NOT NULL,
    PRIMARY KEY (meeting_id, idx)
);
CREATE TABLE IF NOT EXISTS chunks (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    start_idx INTEGER NOT NULL,
    end_idx INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    speakers TEXT NOT NULL,
    text TEXT NOT NULL,
    embed_text TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_meeting ON chunks(meeting_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    embed_text, content='chunks', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, embed_text) VALUES (new.rowid, new.embed_text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, embed_text) VALUES('delete', old.rowid, old.embed_text);
END;
"""


@dataclass(frozen=True)
class DenseIndex:
    chunk_ids: list[str]
    meeting_ids: list[str]
    speakers: list[list[str]]
    matrix: np.ndarray  # (n_chunks, dim), L2-normalised rows


class MeetingStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._version = 0
        self._dense_cache: tuple[int, DenseIndex] | None = None
        # A single shared connection keeps ":memory:" databases alive (tests) and is
        # safe here because every access goes through `self._lock`.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._conn:
            yield self._conn

    # ---------- writes ----------

    def add_meeting(
        self,
        meeting: Meeting,
        utterances: list[Utterance],
        chunks: list[Chunk],
        embeddings: np.ndarray,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must align")
        with self._tx() as c:
            c.execute(
                "INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    meeting.id,
                    meeting.title,
                    meeting.date,
                    meeting.source_filename,
                    meeting.format,
                    meeting.duration_s,
                    json.dumps(meeting.speakers),
                    meeting.utterance_count,
                    meeting.created_at,
                    meeting.insights_status.value,
                    meeting.insights_error,
                ),
            )
            c.executemany(
                "INSERT INTO utterances VALUES (?,?,?,?,?,?)",
                [(meeting.id, u.idx, u.speaker, u.start_s, u.end_s, u.text) for u in utterances],
            )
            c.executemany(
                "INSERT INTO chunks (id, meeting_id, start_idx, end_idx, start_s, end_s, speakers,"
                " text, embed_text, embedding) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        ch.id,
                        ch.meeting_id,
                        ch.start_idx,
                        ch.end_idx,
                        ch.start_s,
                        ch.end_s,
                        json.dumps(ch.speakers),
                        ch.text,
                        ch.embed_text,
                        np.asarray(vec, dtype=np.float32).tobytes(),
                    )
                    for ch, vec in zip(chunks, embeddings, strict=True)
                ],
            )
            self._version += 1

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._tx() as c:
            # Delete chunks explicitly so the FTS delete trigger fires for each row.
            c.execute("DELETE FROM chunks WHERE meeting_id = ?", (meeting_id,))
            cur = c.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            self._version += 1
            return cur.rowcount > 0

    def set_insights(
        self,
        meeting_id: str,
        status: InsightsStatus,
        insights: MeetingInsights | None = None,
        error: str | None = None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE meetings SET insights_status=?, insights=?, insights_error=? WHERE id=?",
                (
                    status.value,
                    insights.model_dump_json() if insights else None,
                    error,
                    meeting_id,
                ),
            )

    # ---------- reads ----------

    @staticmethod
    def _row_to_meeting(r: sqlite3.Row) -> Meeting:
        return Meeting(
            id=r["id"],
            title=r["title"],
            date=r["date"],
            source_filename=r["source_filename"],
            format=r["format"],
            duration_s=r["duration_s"],
            speakers=json.loads(r["speakers"]),
            utterance_count=r["utterance_count"],
            created_at=r["created_at"],
            insights_status=InsightsStatus(r["insights_status"]),
            insights_error=r["insights_error"],
        )

    def list_meetings(self) -> list[Meeting]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM meetings ORDER BY COALESCE(date, created_at), created_at"
            ).fetchall()
        return [self._row_to_meeting(r) for r in rows]

    def get_meeting(self, meeting_id: str) -> Meeting | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        return self._row_to_meeting(r) if r else None

    def find_by_filename(self, filename: str) -> Meeting | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM meetings WHERE source_filename=?", (filename,)).fetchone()
        return self._row_to_meeting(r) if r else None

    def get_insights(self, meeting_id: str) -> MeetingInsights | None:
        with self._tx() as c:
            r = c.execute("SELECT insights FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not r or not r["insights"]:
            return None
        return MeetingInsights.model_validate_json(r["insights"])

    def get_utterances(
        self, meeting_id: str, start_idx: int | None = None, end_idx: int | None = None
    ) -> list[Utterance]:
        sql = "SELECT * FROM utterances WHERE meeting_id=?"
        args: list[object] = [meeting_id]
        if start_idx is not None:
            sql += " AND idx >= ?"
            args.append(start_idx)
        if end_idx is not None:
            sql += " AND idx <= ?"
            args.append(end_idx)
        with self._tx() as c:
            rows = c.execute(sql + " ORDER BY idx", args).fetchall()
        return [
            Utterance(
                idx=r["idx"],
                speaker=r["speaker"],
                start_s=r["start_s"],
                end_s=r["end_s"],
                text=r["text"],
            )
            for r in rows
        ]

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        with self._tx() as c:
            rows = c.execute(f"SELECT * FROM chunks WHERE id IN ({marks})", chunk_ids).fetchall()
        return {
            r["id"]: Chunk(
                id=r["id"],
                meeting_id=r["meeting_id"],
                start_idx=r["start_idx"],
                end_idx=r["end_idx"],
                start_s=r["start_s"],
                end_s=r["end_s"],
                speakers=json.loads(r["speakers"]),
                text=r["text"],
                embed_text=r["embed_text"],
            )
            for r in rows
        }

    def lexical_search(
        self, fts_query: str, meeting_ids: list[str] | None, limit: int
    ) -> list[tuple[str, float]]:
        """BM25 over chunk text. Returns (chunk_id, bm25) best-first (SQLite bm25 is lower=better)."""
        if not fts_query:
            return []
        sql = (
            "SELECT c.id AS id, bm25(chunks_fts) AS score FROM chunks_fts "
            "JOIN chunks c ON c.rowid = chunks_fts.rowid WHERE chunks_fts MATCH ?"
        )
        args: list[object] = [fts_query]
        if meeting_ids:
            sql += f" AND c.meeting_id IN ({','.join('?' * len(meeting_ids))})"
            args.extend(meeting_ids)
        sql += " ORDER BY score LIMIT ?"
        args.append(limit)
        with self._tx() as c:
            rows = c.execute(sql, args).fetchall()
        return [(r["id"], float(r["score"])) for r in rows]

    def dense_index(self) -> DenseIndex:
        """All chunk embeddings as one matrix, cached until the next write."""
        cached = self._dense_cache
        if cached and cached[0] == self._version:
            return cached[1]
        with self._tx() as c:
            rows = c.execute(
                "SELECT id, meeting_id, speakers, embedding FROM chunks ORDER BY rowid"
            ).fetchall()
            version = self._version
        if rows:
            matrix = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        else:
            matrix = np.zeros((0, 0), dtype=np.float32)
        index = DenseIndex(
            chunk_ids=[r["id"] for r in rows],
            meeting_ids=[r["meeting_id"] for r in rows],
            speakers=[json.loads(r["speakers"]) for r in rows],
            matrix=matrix,
        )
        self._dense_cache = (version, index)
        return index
