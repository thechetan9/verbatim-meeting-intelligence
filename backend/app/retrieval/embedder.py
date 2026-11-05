"""Embedding providers.

Default: BAAI/bge-small-en-v1.5 via fastembed (ONNX, CPU, 384-d, ~67 MB).
Running embeddings locally means:
  * transcript text is never sent to a third party just to be indexed
    (only the handful of retrieved snippets reach the LLM at question time);
  * retrieval is deterministic and free, so the retrieval eval runs in CI without secrets;
  * no per-token embedding cost or rate limits during bulk ingestion.
"""

from __future__ import annotations

import hashlib
import re
from functools import cached_property
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    """bge models expect a query instruction prefix; fastembed's query_embed adds it."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: str | None = None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.dim = 384

    @cached_property
    def _model(self):  # lazy: keeps app start-up and unit tests fast
        from fastembed import TextEmbedding

        return TextEmbedding(self.model_name, cache_dir=self.cache_dir)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.asarray(list(self._model.embed(texts)), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.asarray(next(iter(self._model.query_embed(text))), dtype=np.float32)


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder. Test double only — no semantics."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)
