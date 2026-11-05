"""Structured logging, request correlation and lightweight per-request tracing.

Every log line is one JSON object carrying the request id, so a single question can
be followed through retrieval, tool calls and LLM calls in any log tool
(CloudWatch Logs Insights, Loki, Application Insights...).

`Trace` is a deliberately small span recorder: it is logged at the end of each chat
turn *and* streamed to the UI, so latency / tokens / cost per step are visible
without running a tracing backend. The span shape (name, duration, attributes)
maps 1:1 onto OpenTelemetry spans if/when an OTLP exporter is added.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "google_genai", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, msg: str, **data: Any) -> None:
    logger.info(msg, extra={"data": data})


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Span:
    name: str
    started_at: float
    duration_ms: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "duration_ms": round(self.duration_ms, 1), **self.attributes}


@dataclass
class Trace:
    trace_id: str = field(default_factory=new_request_id)
    spans: list[Span] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)
    input_tokens: int = 0
    output_tokens: int = 0

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        s = Span(name=name, started_at=time.perf_counter(), attributes=dict(attributes))
        try:
            yield s
        finally:
            s.duration_ms = (time.perf_counter() - s.started_at) * 1000
            self.spans.append(s)

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def summary(self, price_in_per_m: float, price_out_per_m: float) -> dict[str, Any]:
        cost = (self.input_tokens * price_in_per_m + self.output_tokens * price_out_per_m) / 1e6
        return {
            "trace_id": self.trace_id,
            "total_ms": round((time.perf_counter() - self.started_at) * 1000, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "est_cost_usd": round(cost, 6),
            "spans": [s.to_dict() for s in self.spans],
        }
