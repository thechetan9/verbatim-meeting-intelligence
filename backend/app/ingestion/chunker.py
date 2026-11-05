"""Speaker-turn-aware chunking.

Why not fixed-size token windows? A meeting is a conversation: a question and its
answer usually live in adjacent turns from different speakers. Splitting at an
arbitrary token boundary separates "Should we add sites?" from "Yes, two in Ohio".

Strategy:
  * a chunk is a window of *whole* consecutive turns (never split mid-turn, unless
    a single turn is longer than the budget — then it is split on sentence boundaries);
  * windows close when they reach ~`target_words` or a long silence gap (topic shift proxy);
  * consecutive windows overlap by `overlap_turns` turns so an answer that sits
    right at a boundary still travels with its question;
  * every chunk gets a contextual header (meeting title, date, time range, speakers)
    prepended to what is embedded/indexed, so a chunk that says "we agreed on 3"
    still carries *which* meeting and *who* was talking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Chunk, Utterance, format_ts


@dataclass(frozen=True)
class ChunkingConfig:
    target_words: int = 180
    max_words: int = 320
    overlap_turns: int = 1
    gap_break_s: float = 90.0  # silence long enough to treat as a topic boundary


def render_turn(u: Utterance) -> str:
    return f"[{u.timestamp}] {u.speaker}: {u.text}"


def _words(text: str) -> int:
    return len(text.split())


def _split_long_turn(u: Utterance, max_words: int) -> list[Utterance]:
    """Split one oversized monologue into sentence-aligned pieces (same idx, same speaker)."""
    sentences = re.split(r"(?<=[.!?])\s+", u.text)
    pieces: list[str] = []
    buf: list[str] = []
    for s in sentences:
        if buf and _words(" ".join([*buf, s])) > max_words:
            pieces.append(" ".join(buf))
            buf = []
        buf.append(s)
    if buf:
        pieces.append(" ".join(buf))
    return [u.model_copy(update={"text": p}) for p in pieces]


def _expand_turns(utterances: list[Utterance], max_words: int) -> list[Utterance]:
    turns: list[Utterance] = []
    for u in utterances:
        turns.extend(_split_long_turn(u, max_words) if _words(u.text) > max_words else [u])
    return turns


def _gap_s(previous: Utterance, turn: Utterance) -> float:
    return turn.start_s - (previous.end_s or previous.start_s)


def _should_close(window: list[Utterance], turn: Utterance, cfg: ChunkingConfig) -> bool:
    size = sum(_words(t.text) for t in window)
    return (
        size + _words(turn.text) > cfg.max_words
        or size >= cfg.target_words
        or _gap_s(window[-1], turn) >= cfg.gap_break_s
    )


def _window_turns(turns: list[Utterance], cfg: ChunkingConfig) -> list[list[Utterance]]:
    windows: list[list[Utterance]] = []
    current: list[Utterance] = []
    for turn in turns:
        if current and _should_close(current, turn, cfg):
            windows.append(current)
            # Carry overlap forward, except across a long silence (likely a new topic).
            carry = current[-cfg.overlap_turns :] if cfg.overlap_turns else []
            keep_overlap = (
                bool(carry)
                and _gap_s(current[-1], turn) < cfg.gap_break_s
                and sum(_words(t.text) for t in carry) + _words(turn.text) <= cfg.max_words
            )
            current = list(carry) if keep_overlap else []
        current.append(turn)
    if current:  # always holds at least one turn that is not just overlap carry
        windows.append(current)
    return _absorb_small_tail(windows, cfg)


def _absorb_small_tail(
    windows: list[list[Utterance]], cfg: ChunkingConfig
) -> list[list[Utterance]]:
    """Fold a tiny trailing window (e.g. 'Thanks all') into its predecessor when it fits."""
    if len(windows) < 2:
        return windows
    prev, last = windows[-2], windows[-1]
    new_turns = [t for t in last if t not in prev]
    if not new_turns or _gap_s(prev[-1], new_turns[0]) >= cfg.gap_break_s:
        return windows  # a tail after a long silence is a separate topic; keep it apart
    merged_words = sum(_words(t.text) for t in [*prev, *new_turns])
    if (
        sum(_words(t.text) for t in new_turns) < cfg.target_words // 3
        and merged_words <= cfg.max_words
    ):
        return [*windows[:-2], [*prev, *new_turns]]
    return windows


def _to_chunk(
    meeting_id: str, n: int, title: str, date: str | None, window: list[Utterance]
) -> Chunk:
    speakers = list(dict.fromkeys(t.speaker for t in window))
    body = "\n".join(render_turn(t) for t in window)
    start_s = window[0].start_s
    end_s = window[-1].end_s or window[-1].start_s
    when = f" ({date})" if date else ""
    header = (
        f"Meeting: {title}{when} | {format_ts(start_s)}-{format_ts(end_s)}"
        f" | Speakers: {', '.join(speakers)}"
    )
    return Chunk(
        id=f"{meeting_id}:{n}",
        meeting_id=meeting_id,
        start_idx=window[0].idx,
        end_idx=window[-1].idx,
        start_s=start_s,
        end_s=end_s,
        speakers=speakers,
        text=body,
        embed_text=f"{header}\n{body}",
    )


def chunk_utterances(
    meeting_id: str,
    title: str,
    date: str | None,
    utterances: list[Utterance],
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    cfg = config or ChunkingConfig()
    windows = _window_turns(_expand_turns(utterances, cfg.max_words), cfg)
    return [_to_chunk(meeting_id, n, title, date, w) for n, w in enumerate(windows)]
