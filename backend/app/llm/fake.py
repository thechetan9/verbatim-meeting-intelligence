"""Scripted LLM for tests: deterministic, offline, and records what it was sent."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.llm.base import ChatTurn, StepDone, StepEvent, T, TextDelta, ToolCall, ToolSpec, Usage


@dataclass
class ScriptedStep:
    """Either a list of tool calls, or a final text answer."""

    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    text: str = ""


class FakeChatSession:
    def __init__(self, llm: FakeLLM, steps: list[ScriptedStep]):
        self._llm = llm
        self._steps = list(steps)
        self.tool_results: list[tuple[ToolCall, dict[str, Any]]] = []

    def stream_step(self, allow_tools: bool = True) -> Iterator[StepEvent]:
        step = self._steps.pop(0) if self._steps else ScriptedStep(text="(no more scripted steps)")
        if not allow_tools and step.tool_calls:
            step = ScriptedStep(text=step.text or "Final answer without tools.")
        for word in step.text.split(" "):
            if word:
                yield TextDelta(word + " ")
        calls = [
            ToolCall(id=f"call_{i}", name=n, args=a) for i, (n, a) in enumerate(step.tool_calls)
        ]
        yield StepDone(text=step.text, tool_calls=calls, input_tokens=100, output_tokens=20)

    def add_tool_results(self, results: list[tuple[ToolCall, dict[str, Any]]]) -> None:
        self.tool_results.extend(results)
        self._llm.tool_results.extend(results)

    def add_user_note(self, text: str) -> None:
        self._llm.notes.append(text)


class FakeLLM:
    model = "fake-llm"

    def __init__(
        self,
        chat_steps: list[ScriptedStep] | None = None,
        json_responses: dict[type[BaseModel], BaseModel] | None = None,
        fail_json: bool = False,
    ):
        self.chat_steps = chat_steps or []
        self.json_responses = json_responses or {}
        self.fail_json = fail_json
        self.system_prompts: list[str] = []
        self.histories: list[list[ChatTurn]] = []
        self.tool_results: list[tuple[ToolCall, dict[str, Any]]] = []
        self.json_prompts: list[str] = []
        self.notes: list[str] = []

    def start_chat(
        self, system: str, history: list[ChatTurn], message: str, tools: list[ToolSpec]
    ) -> FakeChatSession:
        self.system_prompts.append(system)
        self.histories.append(history)
        return FakeChatSession(self, self.chat_steps)

    def generate_json(self, system: str, prompt: str, schema: type[T]) -> tuple[T, Usage]:
        from app.llm.base import LLMError

        self.json_prompts.append(prompt)
        if self.fail_json:
            raise LLMError("scripted failure")
        resp = self.json_responses[schema]
        assert isinstance(resp, schema)
        return resp, Usage(100, 50)

    def generate_json_from_audio(
        self, system: str, prompt: str, audio: bytes, mime_type: str, schema: type[T]
    ) -> tuple[T, Usage]:
        return self.generate_json(system, prompt, schema)
