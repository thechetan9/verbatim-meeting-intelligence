import json

from app.llm.fake import ScriptedStep
from tests.conftest import TRANSCRIPT


def _upload(client, content=TRANSCRIPT, name="2026-01-05_sync.txt", **data):
    return client.post(
        "/api/meetings", files={"file": (name, content.encode(), "text/plain")}, data=data
    )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "llm_enabled": True, "model": "fake-llm", "meetings": 0}
    assert r.headers["X-Request-ID"]


def test_upload_list_detail_transcript_delete(client):
    r = _upload(client)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["speakers"] == ["Alice Chen", "Bob Singh", "Carol Diaz"]
    assert m["insights_status"] == "pending"

    assert [x["id"] for x in client.get("/api/meetings").json()] == [m["id"]]
    detail = client.get(f"/api/meetings/{m['id']}").json()
    assert (
        detail["meeting"]["insights_status"] == "ready"
    )  # background runner is synchronous in tests
    assert len(detail["insights"]["decisions"]) == 1
    transcript = client.get(f"/api/meetings/{m['id']}/transcript").json()
    assert len(transcript["utterances"]) == 7

    assert client.delete(f"/api/meetings/{m['id']}").status_code == 204
    assert client.get(f"/api/meetings/{m['id']}").status_code == 404


def test_upload_validation(client):
    assert _upload(client, name="notes.pdf").status_code == 422
    assert _upload(client, content="no timestamps here").status_code == 422
    r = client.post("/api/meetings", files={"file": ("x.txt", b"\xff\xfe\x00bad", "text/plain")})
    assert r.status_code == 422
    assert _upload(client, date="05/01/2026").status_code == 422


def test_upload_size_limit(client, container):
    container.settings.max_upload_bytes = 100
    assert _upload(client).status_code == 413


def test_load_samples_is_idempotent(client):
    first = client.post("/api/meetings/samples").json()
    assert len(first["loaded"]) == 4
    second = client.post("/api/meetings/samples").json()
    assert second["loaded"] == [] and len(second["skipped"]) == 4
    titles = [m["title"] for m in client.get("/api/meetings").json()]
    assert titles[0] == "CARDIA-2 Trial Steering Committee"
    assert "Adherence App — Sprint 14 Planning" in titles


def test_search_modes(client):
    _upload(client)
    for mode in ("hybrid", "lexical", "dense"):
        hits = client.post("/api/search", json={"query": "Twilio SNS", "mode": mode, "k": 2}).json()
        assert hits and "SNS" in hits[0]["text"], mode


def test_chat_streams_sse(client, container):
    _upload(client)
    container.llm.chat_steps[:] = [
        ScriptedStep(tool_calls=[("get_meeting_insights", {})]),
        ScriptedStep(text="Bob owns the SNS plan [S1]."),
    ]
    r = client.post("/api/chat", json={"question": "What does Bob owe?", "history": []})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    assert [e for e, _ in events][-2:] == ["citations", "done"]
    assert events[-1][1]["grounding"] == "grounded"


def test_chat_rejects_bad_input(client):
    assert client.post("/api/chat", json={"question": ""}).status_code == 422
    assert client.post("/api/chat", json={"question": "x" * 2500}).status_code == 422


def test_chat_without_llm_returns_503(settings):
    from fastapi.testclient import TestClient

    from app.container import build_container
    from app.main import create_app
    from app.retrieval.embedder import HashingEmbedder

    c = build_container(settings, embedder=HashingEmbedder(), use_default_llm=False)
    client = TestClient(create_app(container=c))
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 503
    r = _upload(client)
    assert r.json()["insights_status"] == "skipped"  # ingestion & search still work without a key


def test_duplicate_upload_is_rejected_with_a_clear_message(client):
    first = _upload(client)
    assert first.status_code == 201
    again = _upload(client, content=TRANSCRIPT.replace("\n", "\r\n") + "\n\n", name="copy.txt")
    assert again.status_code == 409
    assert "already uploaded" in again.json()["detail"] and "Weekly sync" in again.json()["detail"]
    other = _upload(
        client, content=TRANSCRIPT + "[00:04:00] Alice Chen: One more thing.", name="b.txt"
    )
    assert other.status_code == 201
    assert len(client.get("/api/meetings").json()) == 2


def test_old_database_without_hash_column_is_migrated(tmp_path):
    import sqlite3

    from app.retrieval.store import MeetingStore

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE meetings (id TEXT PRIMARY KEY, title TEXT NOT NULL, date TEXT, "
        "source_filename TEXT NOT NULL, format TEXT NOT NULL, duration_s REAL NOT NULL, "
        "speakers TEXT NOT NULL, utterance_count INTEGER NOT NULL, created_at TEXT NOT NULL, "
        "insights_status TEXT NOT NULL, insights_error TEXT, insights TEXT)"
    )
    con.commit()
    con.close()
    store = MeetingStore(db)
    assert store.find_by_hash("abc") is None  # column added, query works
