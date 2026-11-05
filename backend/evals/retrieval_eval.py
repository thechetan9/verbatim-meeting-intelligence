"""Retrieval eval: lexical (BM25) vs dense vs hybrid (RRF) on the labelled question set.

Deterministic and offline (local embeddings, no LLM), so it runs in CI on every push and
fails the build if hybrid retrieval quality regresses below the threshold.

    uv run python -m evals.retrieval_eval [--k 6] [--min-mrr 0.75] [--min-hit3 0.9]

The sample corpus is small (16 chunks), so hit@6 saturates at 1.0 for every mode; ranking
quality (hit@1, MRR) is the signal that matters, and is what the CI gate checks.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import replace

from app.config import Settings
from app.ingestion.chunker import ChunkingConfig
from app.ingestion.service import IngestionService
from app.retrieval.embedder import FastEmbedEmbedder
from app.retrieval.hybrid import HybridRetriever, SearchMode
from evals.common import RESULTS_DIR, contains, ingest_samples, load_cases, meeting_for, new_store


def first_hit_rank(hits, meeting_id: str, evidence: str) -> int | None:
    for rank, h in enumerate(hits, start=1):
        if h.chunk.meeting_id == meeting_id and contains(h.chunk.text, evidence):
            return rank
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--min-mrr", type=float, default=0.75, help="minimum hybrid MRR to pass")
    ap.add_argument("--min-hit3", type=float, default=0.9, help="minimum hybrid hit@3 to pass")
    ap.add_argument("--target-words", type=int, default=None, help="chunking experiment override")
    ap.add_argument("--overlap", type=int, default=None, help="chunking experiment override")
    ap.add_argument("--no-write", action="store_true", help="don't overwrite results/retrieval.md")
    args = ap.parse_args()

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    store, embedder = (
        new_store(),
        FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir),
    )
    chunking = ChunkingConfig()
    if args.target_words:
        chunking = replace(
            chunking, target_words=args.target_words, max_words=max(args.target_words * 2, 60)
        )
    if args.overlap is not None:
        chunking = replace(chunking, overlap_turns=args.overlap)
    meetings = ingest_samples(IngestionService(store, embedder, extractor=None, chunking=chunking))
    n_chunks = len(store.dense_index().chunk_ids)
    retriever = HybridRetriever(store, embedder, min_dense_score=settings.retrieval_min_dense_score)
    cases = [c for c in load_cases() if c.evidence]

    modes = [SearchMode.LEXICAL, SearchMode.DENSE, SearchMode.HYBRID]
    ranks: dict[SearchMode, list[int | None]] = {m: [] for m in modes}
    by_type: dict[tuple[SearchMode, str], list[bool]] = defaultdict(list)
    misses: list[str] = []
    for case in cases:
        assert case.meeting and case.evidence
        meeting = meeting_for(case.meeting, meetings)
        for mode in modes:
            r = first_hit_rank(
                retriever.search(case.question, k=args.k, mode=mode), meeting.id, case.evidence
            )
            ranks[mode].append(r)
            by_type[(mode, case.type)].append(r is not None)
            if mode is SearchMode.HYBRID and r is None:
                misses.append(f"{case.id}: {case.question}")

    def hit_at(mode: SearchMode, k: int) -> float:
        return sum(1 for r in ranks[mode] if r is not None and r <= k) / len(cases)

    def mrr(mode: SearchMode) -> float:
        return sum(1 / r for r in ranks[mode] if r) / len(cases)

    types = sorted({c.type for c in cases})
    lines = [
        f"# Retrieval eval ({len(cases)} questions, k={args.k}, embeddings={settings.embedding_model})",
        "",
        f"Chunking: target {chunking.target_words} words, max {chunking.max_words}, "
        f"overlap {chunking.overlap_turns} turn(s) -> {n_chunks} chunks",
        "",
        "| mode | hit@1 | hit@3 | hit@k | MRR | " + " | ".join(f"hit@k {t}" for t in types) + " |",
        "|---|---|---|---|---|" + "---|" * len(types),
    ]
    for mode in modes:
        per_type = [f"{sum(by_type[(mode, t)])}/{len(by_type[(mode, t)])}" for t in types]
        lines.append(
            f"| {mode.value} | {hit_at(mode, 1):.2f} | {hit_at(mode, 3):.2f} | {hit_at(mode, args.k):.2f}"
            f" | {mrr(mode):.3f} | " + " | ".join(per_type) + " |"
        )
    if misses:
        lines += ["", "Hybrid misses:", *[f"- {m}" for m in misses]]
    report = "\n".join(lines)
    print(report)

    if not args.no_write:
        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / "retrieval.md").write_text(report + "\n")

    failures = []
    if mrr(SearchMode.HYBRID) < args.min_mrr:
        failures.append(f"hybrid MRR {mrr(SearchMode.HYBRID):.3f} < {args.min_mrr}")
    if hit_at(SearchMode.HYBRID, 3) < args.min_hit3:
        failures.append(f"hybrid hit@3 {hit_at(SearchMode.HYBRID, 3):.2f} < {args.min_hit3}")
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
