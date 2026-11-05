"""Gemini adapter (google-genai SDK).

Notes on choices:
  * automatic function calling is disabled: the agent loop is ours, so we control the
    step budget, scope enforcement, tracing and citation bookkeeping;
  * every streamed `Part` is kept verbatim in the history, which preserves Gemini's
    thought signatures across tool-calling turns (required by thinking models);
  * capacity errors (429 / 5xx) get one quick SDK retry, then fall back to the next model in
    the chain (e.g. 3.8-flash -> 3.5-flash -> 3.1-flash-lite). Fallback only happens before any
    output has been streamed, and is sticky for the rest of a chat so one conversation is
    answered by one model.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors, types

from app.llm.base import (
    ChatTurn,
    LLMError,
    StepDone,
    StepEvent,
    T,
    TextDelta,
    ToolCall,
    ToolSpec,
    Usage,
)
from app.observability import log_event

logger = logging.getLogger(__name__)

# Errors worth trying another model for: rate/quota limits, overload, timeouts.
FALLBACK_CODES = frozenset({404, 429, 500, 502, 503, 504})


def _thinking(model: str) -> types.ThinkingConfig | None:
    """Keep reasoning light: grounded Q&A over retrieved text doesn't need long thinking."""
    if model.startswith("gemini-2.5-flash"):
        return types.ThinkingConfig(thinking_budget=512)
    if model.startswith("gemini-3") and "lite" not in model:
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    return None


def _usage(meta: types.GenerateContentResponseUsageMetadata | None, model: str) -> Usage:
    if meta is None:
        return Usage(model=model)
    out = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
    return Usage(input_tokens=meta.prompt_token_count or 0, output_tokens=out, model=model)


def _error(exc: errors.APIError) -> LLMError:
    return LLMError(f"Gemini request failed ({exc.code}): {exc.message}", code=exc.code)


@dataclass
class _StepState:
    parts: list[types.Part] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    usage: types.GenerateContentResponseUsageMetadata | None = None
    streamed: bool = False


def _consume_part(part: types.Part, st: _StepState) -> str | None:
    """Record a streamed part; return its text if it is user-visible answer text."""
    st.parts.append(part)
    fc = part.function_call
    if fc and fc.name:
        st.calls.append(
            ToolCall(id=fc.id or f"call_{len(st.calls)}", name=fc.name, args=dict(fc.args or {}))
        )
        return None
    if part.text and not part.thought:
        st.text.append(part.text)
        st.streamed = True
        return part.text
    return None


class GeminiChatSession:
    def __init__(
        self,
        client: genai.Client,
        models: list[str],
        system: str,
        contents: list[types.Content],
        tools: list[ToolSpec],
        temperature: float,
    ):
        self._client = client
        self._models = models
        self._active = 0  # index into _models; only moves forward
        self._system = system
        self._contents = contents
        self._temperature = temperature
        self._tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters_json_schema=t.parameters
                    )
                    for t in tools
                ]
            )
        ]

    def _config(self, model: str, allow_tools: bool) -> types.GenerateContentConfig:
        mode = (
            types.FunctionCallingConfigMode.AUTO
            if allow_tools
            else types.FunctionCallingConfigMode.NONE
        )
        return types.GenerateContentConfig(
            system_instruction=self._system,
            temperature=self._temperature,
            tools=self._tools,  # type: ignore[arg-type]
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=mode)
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=_thinking(model),
        )

    def _stream_once(self, model: str, allow_tools: bool, st: _StepState) -> Iterator[TextDelta]:
        stream = self._client.models.generate_content_stream(
            model=model, contents=self._contents, config=self._config(model, allow_tools)
        )
        for chunk in stream:
            st.usage = chunk.usage_metadata or st.usage
            candidate = chunk.candidates[0] if chunk.candidates else None
            parts = candidate.content.parts if candidate and candidate.content else None
            for part in parts or []:
                text = _consume_part(part, st)
                if text:
                    yield TextDelta(text)

    def stream_step(self, allow_tools: bool = True) -> Iterator[StepEvent]:
        while True:
            model = self._models[self._active]
            st = _StepState()
            try:
                yield from self._stream_once(model, allow_tools, st)
                break
            except errors.APIError as exc:
                can_fall_back = self._active + 1 < len(self._models)
                if st.streamed or exc.code not in FALLBACK_CODES or not can_fall_back:
                    raise _error(exc) from exc
                self._active += 1
                log_event(
                    logger,
                    "llm.fallback",
                    from_model=model,
                    to_model=self._models[self._active],
                    code=exc.code,
                )

        self._contents.append(types.Content(role="model", parts=st.parts))
        usage = _usage(st.usage, model)
        yield StepDone(
            text="".join(st.text),
            tool_calls=st.calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=model,
        )

    def add_tool_results(self, results: list[tuple[ToolCall, dict[str, Any]]]) -> None:
        response_parts = []
        for call, payload in results:
            part = types.Part.from_function_response(name=call.name, response=payload)
            if part.function_response is not None and not call.id.startswith("call_"):
                part.function_response.id = call.id
            response_parts.append(part)
        self._contents.append(types.Content(role="user", parts=response_parts))

    def add_user_note(self, text: str) -> None:
        last = self._contents[-1] if self._contents else None
        if last is not None and last.role == "user" and last.parts is not None:
            last.parts.append(types.Part.from_text(text=text))  # keep user/model turns alternating
        else:
            self._contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=text)])
            )


class GeminiLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: list[str] | None = None,
        temperature: float = 0.2,
        timeout_s: float = 60,
    ):
        self.model = model
        self.models = [model, *[m for m in (fallback_models or []) if m != model]]
        self._temperature = temperature
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_s * 1000),
                # One quick retry; after that, falling back to another model is faster.
                retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1.0, max_delay=4.0),
            ),
        )

    def start_chat(
        self, system: str, history: list[ChatTurn], message: str, tools: list[ToolSpec]
    ) -> GeminiChatSession:
        contents = [
            types.Content(
                role="model" if turn.role == "assistant" else "user",
                parts=[types.Part.from_text(text=turn.content)],
            )
            for turn in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
        return GeminiChatSession(
            self._client, self.models, system, contents, tools, self._temperature
        )

    def _json_once(
        self, model: str, system: str, contents: Any, schema: type[T]
    ) -> tuple[T, Usage]:
        resp = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.1,
                response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(),
                thinking_config=_thinking(model),
            ),
        )
        if not resp.text:
            raise LLMError(f"{model} returned an empty response")
        try:
            return schema.model_validate_json(resp.text), _usage(resp.usage_metadata, model)
        except ValueError as exc:
            raise LLMError(f"Model output did not match the expected schema: {exc}") from exc

    def _json_call(self, system: str, contents: Any, schema: type[T]) -> tuple[T, Usage]:
        for i, model in enumerate(self.models):
            try:
                return self._json_once(model, system, contents, schema)
            except errors.APIError as exc:
                if exc.code not in FALLBACK_CODES or i + 1 == len(self.models):
                    raise _error(exc) from exc
                log_event(
                    logger,
                    "llm.fallback",
                    from_model=model,
                    to_model=self.models[i + 1],
                    code=exc.code,
                )
        raise LLMError("No model configured")  # pragma: no cover - models is never empty

    def generate_json(self, system: str, prompt: str, schema: type[T]) -> tuple[T, Usage]:
        return self._json_call(system, prompt, schema)

    def generate_json_from_audio(
        self, system: str, prompt: str, audio: bytes, mime_type: str, schema: type[T]
    ) -> tuple[T, Usage]:
        contents = [types.Part.from_bytes(data=audio, mime_type=mime_type), prompt]
        return self._json_call(system, contents, schema)
