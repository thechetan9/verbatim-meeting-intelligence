import itertools

from app.domain.models import Utterance
from app.ingestion.chunker import ChunkingConfig, chunk_utterances


def _utts(n: int, words: int = 30, gap: float = 10.0) -> list[Utterance]:
    return [
        Utterance(
            idx=i,
            speaker=f"S{i % 3}",
            start_s=i * gap,
            end_s=i * gap + gap - 1,
            text=" ".join(["w"] * words),
        )
        for i in range(n)
    ]


def test_never_splits_turns_and_covers_everything():
    utts = _utts(20)
    chunks = chunk_utterances(
        "m1", "Title", "2026-01-01", utts, ChunkingConfig(target_words=100, max_words=200)
    )
    covered = set()
    for c in chunks:
        covered.update(range(c.start_idx, c.end_idx + 1))
        assert c.text.count("\n") == c.end_idx - c.start_idx  # one line per whole turn
    assert covered == set(range(20))


def test_overlap_between_consecutive_chunks():
    chunks = chunk_utterances(
        "m1", "T", None, _utts(20), ChunkingConfig(target_words=100, overlap_turns=1)
    )
    for a, b in itertools.pairwise(chunks):
        assert b.start_idx == a.end_idx  # exactly one shared turn


def test_long_silence_starts_new_chunk_without_overlap():
    utts = [
        *_utts(4),
        Utterance(idx=4, speaker="S1", start_s=500, end_s=510, text="new topic after a long break"),
    ]
    chunks = chunk_utterances(
        "m1", "T", None, utts, ChunkingConfig(target_words=1000, gap_break_s=90)
    )
    assert [(c.start_idx, c.end_idx) for c in chunks] == [(0, 3), (4, 4)]


def test_oversized_turn_is_split_on_sentences():
    text = " ".join(f"Sentence number {i} has some words." for i in range(60))
    utts = [Utterance(idx=0, speaker="A", start_s=0, end_s=60, text=text)]
    chunks = chunk_utterances("m1", "T", None, utts, ChunkingConfig(target_words=50, max_words=80))
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= 80 + 10 for c in chunks)  # +10 for the "[ts] A:" prefix


def test_contextual_header_is_embedded_but_not_shown():
    [c] = chunk_utterances("m1", "Steering Committee", "2026-10-06", _utts(2))
    assert c.embed_text.startswith("Meeting: Steering Committee (2026-10-06) | 00:00-")
    assert "Speakers: S0, S1" in c.embed_text
    assert not c.text.startswith("Meeting:")
    assert c.id == "m1:0"
