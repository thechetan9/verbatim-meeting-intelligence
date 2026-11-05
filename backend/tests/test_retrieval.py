from app.domain.models import InsightsStatus, Meeting
from app.ingestion.chunker import ChunkingConfig, chunk_utterances
from app.ingestion.parser import parse_transcript
from app.retrieval.embedder import HashingEmbedder
from app.retrieval.hybrid import (
    HybridRetriever,
    SearchFilters,
    SearchMode,
    build_fts_query,
    rrf_fuse,
)
from app.retrieval.store import MeetingStore

M1 = """[00:00:01] Alice: We picked AWS SNS for reminders because of the BAA.
[00:00:10] Bob: Ticket PRJ-2291 covers the Android sync bug.
[00:05:00] Alice: Unrelated: the cafeteria menu changes next week."""
M2 = """[00:00:01] Carol: Enrollment is at 112 of 300 patients.
[00:00:10] Dan: Site 14 in Cleveland is waiting for IRB approval."""


def _store() -> tuple[MeetingStore, HashingEmbedder]:
    store, emb = MeetingStore(":memory:"), HashingEmbedder()
    for mid, text in [("m1", M1), ("m2", M2)]:
        t = parse_transcript(text)
        chunks = chunk_utterances(
            mid, mid, None, t.utterances, ChunkingConfig(target_words=5, overlap_turns=0)
        )
        meeting = Meeting(
            id=mid,
            title=mid,
            source_filename=f"{mid}.txt",
            format="txt",
            duration_s=t.duration_s,
            speakers=t.speakers,
            utterance_count=len(t.utterances),
            created_at="now",
            insights_status=InsightsStatus.SKIPPED,
        )
        store.add_meeting(
            meeting, t.utterances, chunks, emb.embed_documents([c.embed_text for c in chunks])
        )
    return store, emb


def test_fts_query_is_sanitised():
    q = build_fts_query('What did we say about "PRJ-2291" OR drop table; NEAR(x)?')
    assert '"PRJ-2291"' in q
    assert '"drop"' in q and '"table"' in q  # keywords are quoted terms, not syntax
    assert '"what"' not in q.lower()  # stopwords removed
    assert build_fts_query("what is the") == ""


def test_rrf_rewards_agreement():
    fused = rrf_fuse({"lexical": ["a", "b", "c"], "dense": ["b", "a", "d"]}, k=60)
    ids = [d for d, _, _ in fused]
    assert set(ids[:2]) == {"a", "b"}
    assert ids.index("c") > 1 and ids.index("d") > 1
    assert fused[0][2].keys() == {"lexical", "dense"}


def test_exact_identifier_found_by_lexical_and_hybrid():
    store, emb = _store()
    r = HybridRetriever(store, emb, min_dense_score=0.0)
    for mode in (SearchMode.LEXICAL, SearchMode.HYBRID):
        hits = r.search("PRJ-2291", k=1, mode=mode)
        assert "PRJ-2291" in hits[0].chunk.text


def test_filters_by_meeting_and_speaker():
    store, emb = _store()
    r = HybridRetriever(store, emb, min_dense_score=0.0)
    hits = r.search(
        "approval enrollment reminders", k=10, filters=SearchFilters(meeting_ids=["m2"])
    )
    assert hits and {h.chunk.meeting_id for h in hits} == {"m2"}
    hits = r.search("approval enrollment reminders BAA", k=10, filters=SearchFilters(speaker="dan"))
    assert hits and all(any("Dan" in s for s in h.chunk.speakers) for h in hits)


def test_delete_meeting_removes_from_both_indexes():
    store, emb = _store()
    r = HybridRetriever(store, emb, min_dense_score=0.0)
    assert store.delete_meeting("m1")
    assert all(h.chunk.meeting_id == "m2" for h in r.search("SNS PRJ-2291 BAA", k=10))
    assert store.get_utterances("m1") == []
    assert not store.delete_meeting("m1")
