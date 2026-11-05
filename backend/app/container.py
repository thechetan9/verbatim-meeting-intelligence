"""Composition root: the one place where concrete implementations are chosen and wired.

Everything else depends on small interfaces (Embedder, LLM, MeetingStore), so tests build a
Container with fakes and the production app builds one from Settings.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.chat.agent import MeetingAgent
from app.config import Settings
from app.ingestion.service import IngestionService
from app.insights.extractor import InsightsExtractor
from app.llm.base import LLM
from app.retrieval.embedder import Embedder, FastEmbedEmbedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.store import MeetingStore


@dataclass
class Container:
    settings: Settings
    store: MeetingStore
    embedder: Embedder
    retriever: HybridRetriever
    llm: LLM | None
    ingestion: IngestionService
    agent: MeetingAgent | None
    # How slow background work (LLM insight extraction) is run. A thread pool in the app;
    # tests swap in a synchronous runner. In production this becomes a queue + worker.
    run_background: Callable[..., Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.run_background is None:
            pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg")
            self.run_background = pool.submit


def build_container(
    settings: Settings,
    *,
    store: MeetingStore | None = None,
    embedder: Embedder | None = None,
    llm: LLM | None = None,
    use_default_llm: bool = True,
    run_background: Callable[..., Any] | None = None,
) -> Container:
    store = store or MeetingStore(settings.database_path)
    embedder = embedder or FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    if llm is None and use_default_llm and settings.llm_enabled:
        from app.llm.gemini import GeminiLLM

        llm = GeminiLLM(
            api_key=settings.gemini_api_key or "",
            model=settings.llm_model,
            fallback_models=settings.llm_fallback_models,
            temperature=settings.llm_temperature,
            timeout_s=settings.llm_timeout_s,
        )
    retriever = HybridRetriever(store, embedder, min_dense_score=settings.retrieval_min_dense_score)
    ingestion = IngestionService(store, embedder, InsightsExtractor(llm) if llm else None)
    agent = MeetingAgent(llm, store, retriever, settings) if llm else None
    return Container(
        settings,
        store,
        embedder,
        retriever,
        llm,
        ingestion,
        agent,
        run_background,  # type: ignore[arg-type]
    )
