"""Input and output guardrails for the chat agent.

Input:  size limits, empty input, a prompt-injection *signal* (logged + traced, not blocked:
        heuristics have false positives, and the real defence is structural — transcript
        text is fenced as data and tools enforce scope server-side).
Output: every citation key must be one the model was actually shown; unknown keys are
        stripped. Each answer is labelled:
          grounded     - at least one valid citation
          no_evidence  - the model said the meetings don't cover it (a correct refusal)
          unsupported  - factual-looking answer without valid citations -> UI warns the user
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.chat.evidence import EvidenceRegistry, extract_citations, normalise_citations
from app.llm.base import ChatTurn


class GuardrailViolation(ValueError):
    pass


class Grounding(StrEnum):
    GROUNDED = "grounded"
    NO_EVIDENCE = "no_evidence"
    UNSUPPORTED = "unsupported"


_INJECTION_PATTERNS = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)|"
    r"disregard (the )?(system|previous) (prompt|instructions)|"
    r"you are now|reveal (your|the) (system )?prompt|act as (?!a meeting)",
    re.I,
)
_NO_EVIDENCE_PATTERNS = re.compile(
    r"(couldn'?t|could not|can'?t|cannot|didn'?t|did not|unable to) find|"
    r"(don'?t|do not|doesn'?t|does not) (cover|mention|contain|include|say)|"
    r"(no|not any) (information|mention|evidence|record)|not (mentioned|discussed|covered)|"
    r"only (help|answer) (with )?questions about",
    re.I,
)


def says_not_covered(text: str) -> bool:
    """True if the answer states that the meetings don't contain the requested information."""
    return bool(_NO_EVIDENCE_PATTERNS.search(text))


def validate_question(question: str, max_chars: int) -> str:
    q = (question or "").strip()
    if not q:
        raise GuardrailViolation("Question is empty.")
    if len(q) > max_chars:
        raise GuardrailViolation(f"Question is too long ({len(q)} > {max_chars} characters).")
    return q


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_PATTERNS.search(text))


def sanitise_history(
    history: list[ChatTurn], max_messages: int, max_chars: int = 2000
) -> list[ChatTurn]:
    """Keep the last N turns, drop stale citation keys (they belong to previous turns' evidence)."""
    from app.chat.evidence import strip_citations

    trimmed = history[-max_messages:] if max_messages else []
    # Gemini expects the conversation to start with a user turn.
    while trimmed and trimmed[0].role != "user":
        trimmed = trimmed[1:]
    return [ChatTurn(role=t.role, content=strip_citations(t.content)[:max_chars]) for t in trimmed]


@dataclass
class AnswerCheck:
    text: str
    valid_keys: list[str]
    invalid_keys: list[str]
    grounding: Grounding


def check_answer(text: str, registry: EvidenceRegistry) -> AnswerCheck:
    text = normalise_citations(text)
    keys = extract_citations(text)
    valid = [k for k in keys if registry.get(k)]
    invalid = [k for k in keys if not registry.get(k)]
    for k in invalid:
        text = text.replace(f"[{k}]", "")
    if valid:
        grounding = Grounding.GROUNDED
    elif says_not_covered(text):
        grounding = Grounding.NO_EVIDENCE
    else:
        grounding = Grounding.UNSUPPORTED
    return AnswerCheck(text=text, valid_keys=valid, invalid_keys=invalid, grounding=grounding)
