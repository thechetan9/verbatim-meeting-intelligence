"""The meeting assistant: a small, bounded tool-calling loop (our own orchestration, no framework).

    question -> [model decides: call tools | answer] x up to `max_steps` -> guardrail check

Why hand-rolled instead of LangGraph/agents SDK: the control flow is a single loop with two
tools; a framework would add a dependency and indirection without adding capability. Owning
the loop makes the important parts explicit and testable: the step budget (last step forces a
text answer), server-side scope enforcement, per-step tracing, and citation bookkeeping.

The agent yields UI events as plain dicts; the API layer serialises them as Server-Sent Events.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app.chat.evidence import EvidenceRegistry
from app.chat.guardrails import check_answer, looks_like_injection, sanitise_history
from app.chat.prompts import build_system_prompt
from app.chat.tools import TOOL_SPECS, ToolExecutor
from app.config import Settings
from app.llm.base import LLM, ChatTurn, LLMError, StepDone, TextDelta
from app.observability import Trace, log_event
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.store import MeetingStore

logger = logging.getLogger(__name__)

Event = dict[str, Any]


class MeetingAgent:
    def __init__(
        self, llm: LLM, store: MeetingStore, retriever: HybridRetriever, settings: Settings
    ):
        self.llm = llm
        self.store = store
        self.retriever = retriever
        self.settings = settings

    def run(
        self, question: str, history: list[ChatTurn], scope: list[str] | None = None
    ) -> Iterator[Event]:
        trace = Trace()
        registry = EvidenceRegistry()
        meetings = self.store.list_meetings()
        scope = [m for m in (scope or []) if any(x.id == m for x in meetings)] or None
        executor = ToolExecutor(
            self.store, self.retriever, registry, scope, top_k=self.settings.retrieval_top_k
        )
        injection = looks_like_injection(question)
        session = self.llm.start_chat(
            system=build_system_prompt(meetings, scope),
            history=sanitise_history(history, self.settings.max_history_messages),
            message=question,
            tools=TOOL_SPECS,
        )

        answer = ""
        steps_used = 0
        models_used: list[str] = []
        try:
            for step in range(self.settings.agent_max_steps):
                steps_used = step + 1
                allow_tools = step < self.settings.agent_max_steps - 1
                done: StepDone | None = None
                with trace.span("llm.generate", step=step, tools_allowed=allow_tools) as span:
                    for ev in session.stream_step(allow_tools=allow_tools):
                        if isinstance(ev, TextDelta):
                            yield {"event": "delta", "data": {"text": ev.text}}
                        else:
                            done = ev
                    assert done is not None
                    span.attributes.update(
                        model=done.model or self.llm.model,
                        input_tokens=done.input_tokens,
                        output_tokens=done.output_tokens,
                        tool_calls=[c.name for c in done.tool_calls],
                    )
                trace.add_usage(done.input_tokens, done.output_tokens)
                if done.model and done.model not in models_used:
                    models_used.append(done.model)

                if not done.tool_calls:
                    answer = done.text
                    break
                if done.text:  # preamble text before tool calls is not the answer
                    yield {"event": "reset", "data": {}}

                results = []
                for call in done.tool_calls:
                    yield {
                        "event": "tool_call",
                        "data": {"id": call.id, "name": call.name, "args": call.args},
                    }
                    with trace.span(f"tool.{call.name}") as span:
                        result = executor.execute(call)
                        span.attributes.update(result.meta)
                    yield {
                        "event": "tool_result",
                        "data": {
                            "id": call.id,
                            "name": call.name,
                            "summary": result.summary,
                            "duration_ms": round(span.duration_ms, 1),
                        },
                    }
                    results.append((call, result.payload))
                session.add_tool_results(results)
        except LLMError as exc:
            log_event(logger, "chat.llm_error", error=str(exc))
            yield {
                "event": "error",
                "data": {"message": "The language model request failed. Please try again."},
            }
            return

        checked = check_answer(answer, registry)
        citations = [registry.get(k).to_dict() for k in checked.valid_keys]  # type: ignore[union-attr]
        summary = trace.summary(
            self.settings.llm_price_input_per_m, self.settings.llm_price_output_per_m
        )
        summary.update(
            model=models_used[-1] if models_used else self.llm.model,
            steps=steps_used,
            evidence_shown=len(registry),
            citations=len(citations),
            invalid_citations=checked.invalid_keys,
            grounding=checked.grounding.value,
            injection_signal=injection,
        )
        log_event(logger, "chat.answered", question_chars=len(question), **summary)
        yield {"event": "citations", "data": {"items": citations}}
        yield {
            "event": "done",
            "data": {
                "answer": checked.text,
                "grounding": checked.grounding.value,
                "trace": summary,
            },
        }
