"""Hybrid retrieval: BM25 (SQLite FTS5) + dense cosine (bge-small), fused with RRF.

Why hybrid for meetings specifically:
  * people ask with *exact* tokens that dense models blur: ticket ids ("PRJ-2291"),
    vendor names ("Twilio"), site numbers, drug codes -> BM25 wins;
  * people also paraphrase ("did we push the launch?" vs "move go-live to March")
    -> dense wins.
Reciprocal Rank Fusion merges the two rankings without having to calibrate BM25
scores against cosine similarities (they live on different scales).
The eval harness (`evals/retrieval_eval.py`) measures all three modes side by side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from app.domain.models import Chunk
from app.retrieval.embedder import Embedder
from app.retrieval.store import MeetingStore

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "so",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "any",
        "all",
        "can",
        "could",
        "should",
        "meeting",
        "meetings",
        "said",
        "say",
        "says",
        "tell",
        "me",
        "us",
    ]
)
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    LEXICAL = "lexical"
    DENSE = "dense"


@dataclass
class SearchFilters:
    meeting_ids: list[str] | None = None
    speaker: str | None = None

    def speaker_ok(self, speakers: list[str]) -> bool:
        if not self.speaker:
            return True
        needle = self.speaker.lower()
        return any(needle in s.lower() for s in speakers)


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    ranks: dict[str, int] = field(default_factory=dict)  # mode -> 1-based rank


def build_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms (no syntax injection)."""
    terms: list[str] = []
    for tok in _TOKEN.findall(query):
        if tok.lower() in _STOPWORDS or len(tok) < 2:
            continue
        quoted = '"' + tok.replace('"', "") + '"'
        if quoted not in terms:
            terms.append(quoted)
    return " OR ".join(terms)


def rrf_fuse(
    rankings: dict[str, list[str]], k: int = 60
) -> list[tuple[str, float, dict[str, int]]]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank(d))."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, ids in rankings.items():
        for rank, doc_id in enumerate(ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(doc_id, {})[name] = rank
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(doc_id, score, ranks[doc_id]) for doc_id, score in ordered]


class HybridRetriever:
    def __init__(
        self,
        store: MeetingStore,
        embedder: Embedder,
        candidate_k: int = 25,
        rrf_k: int = 60,
        min_dense_score: float = 0.35,
    ):
        self.store = store
        self.embedder = embedder
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        # Dense search always returns *something*; this floor stops pure noise from being
        # fused in when nothing in the corpus is actually related to the question.
        self.min_dense_score = min_dense_score

    def _lexical(self, query: str, filters: SearchFilters) -> list[tuple[str, float]]:
        overfetch = self.candidate_k * (3 if filters.speaker else 1)
        hits = self.store.lexical_search(build_fts_query(query), filters.meeting_ids, overfetch)
        if filters.speaker:
            chunks = self.store.get_chunks([cid for cid, _ in hits])
            hits = [(cid, s) for cid, s in hits if filters.speaker_ok(chunks[cid].speakers)]
        return hits[: self.candidate_k]

    def _dense(self, query: str, filters: SearchFilters) -> list[tuple[str, float]]:
        index = self.store.dense_index()
        if not index.chunk_ids:
            return []
        allowed = np.array(
            [
                (not filters.meeting_ids or mid in filters.meeting_ids) and filters.speaker_ok(spk)
                for mid, spk in zip(index.meeting_ids, index.speakers, strict=True)
            ]
        )
        if not allowed.any():
            return []
        sims = index.matrix @ self.embedder.embed_query(query)
        sims = np.where(allowed, sims, -np.inf)
        top = np.argsort(-sims)[: self.candidate_k]
        return [
            (index.chunk_ids[i], float(sims[i]))
            for i in top
            if np.isfinite(sims[i]) and sims[i] >= self.min_dense_score
        ]

    def search(
        self,
        query: str,
        k: int = 6,
        filters: SearchFilters | None = None,
        mode: SearchMode = SearchMode.HYBRID,
    ) -> list[ScoredChunk]:
        filters = filters or SearchFilters()
        rankings: dict[str, list[str]] = {}
        if mode in (SearchMode.HYBRID, SearchMode.LEXICAL):
            rankings["lexical"] = [cid for cid, _ in self._lexical(query, filters)]
        if mode in (SearchMode.HYBRID, SearchMode.DENSE):
            rankings["dense"] = [cid for cid, _ in self._dense(query, filters)]

        fused = rrf_fuse(rankings, self.rrf_k)[:k]
        chunks = self.store.get_chunks([cid for cid, _, _ in fused])
        return [
            ScoredChunk(chunk=chunks[cid], score=score, ranks=ranks)
            for cid, score, ranks in fused
            if cid in chunks
        ]
