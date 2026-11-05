"""Provider-neutral LLM interface.

The agent, insight extractor and transcriber only depend on these types, so swapping
Gemini for Claude / OpenAI / a self-hosted model means writing one adapter, and tests
run against a scripted fake with no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised for provider failures (auth, quota, timeouts, malformed output)."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code  # provider HTTP status when known (429 rate limit, 503 overloaded...)


def user_message(exc: LLMError) -> str:
    """A safe, actionable message for end users (provider details stay in the logs)."""
    if exc.code == 429:
        return "The language model's rate limit was reached. Please wait a minute and try again."
    if exc.code in (500, 502, 503, 504):
        return "The language model is overloaded right now. Please try again shortly."
    return "The language model request failed. Please try again."


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StepDone:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""  # the model that actually produced this step (fallbacks may differ)


StepEvent = TextDelta | StepDone


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class ChatSession(Protocol):
    """A multi-step tool-calling conversation. The provider keeps its native message state."""

    def stream_step(self, allow_tools: bool = True) -> Iterator[StepEvent]:
        """Stream one model turn: zero or more TextDelta, then exactly one StepDone."""
        ...

    def add_tool_results(self, results: list[tuple[ToolCall, dict[str, Any]]]) -> None: ...

    def add_user_note(self, text: str) -> None:
        """Append a short instruction from the orchestrator (not the end user) to the conversation."""
        ...


class LLM(Protocol):
    model: str

    def start_chat(
        self, system: str, history: list[ChatTurn], message: str, tools: list[ToolSpec]
    ) -> ChatSession: ...

    def generate_json(self, system: str, prompt: str, schema: type[T]) -> tuple[T, Usage]: ...

    def generate_json_from_audio(
        self, system: str, prompt: str, audio: bytes, mime_type: str, schema: type[T]
    ) -> tuple[T, Usage]: ...
