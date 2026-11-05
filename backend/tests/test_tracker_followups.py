from app.chat.followups import FollowUps, suggest_followups
from app.insights.tracker import canonical_owner, collect_action_items
from app.llm.fake import FakeLLM, ScriptedStep
from tests.conftest import TRANSCRIPT

PEOPLE = ["Dr. Anita Rao", "Marcus Lee", "Priya Nair", "Mark Lee"]


def test_canonical_owner_resolves_titles_first_names_and_keeps_ambiguous():
    assert canonical_owner("Anita Rao", PEOPLE) == "Dr. Anita Rao"
    assert canonical_owner("dr. rao", PEOPLE) == "Dr. Anita Rao"
    assert canonical_owner("Priya", PEOPLE) == "Priya Nair"
    assert canonical_owner("Lee", PEOPLE) == "Lee"  # Marcus Lee or Mark Lee: don't guess
    assert canonical_owner("Finance team", PEOPLE) == "Finance team"
    assert canonical_owner(None, PEOPLE) is None
    assert canonical_owner("  ", PEOPLE) is None


def test_tracker_collects_across_meetings_with_timestamps(container):
    m1 = container.ingestion.ingest(TRANSCRIPT, "2026-01-05_a.txt")
    m2 = container.ingestion.ingest(TRANSCRIPT + "[00:09:00] Bob Singh: Bye.", "2026-01-12_b.txt")
    for m in (m1, m2):
        container.ingestion.generate_insights(m.id)
    items = collect_action_items(container.store)
    assert len(items) == 4  # 2 action items x 2 meetings
    assert [i.owner for i in items] == ["Bob Singh", "Bob Singh", "Carol Diaz", "Carol Diaz"]
    assert items[0].meeting_date == "2026-01-05" and items[1].meeting_date == "2026-01-12"
    assert items[0].start_s == 41.0  # evidence #2 is at 00:41
    assert len(collect_action_items(container.store, [m2.id])) == 2


def test_action_items_endpoint(client):
    r = client.post(
        "/api/meetings", files={"file": ("2026-01-05_sync.txt", TRANSCRIPT.encode(), "text/plain")}
    )
    mid = r.json()["id"]
    items = client.get("/api/action-items").json()
    assert {i["owner"] for i in items} == {"Bob Singh", "Carol Diaz"}
    assert client.get("/api/action-items", params={"meeting_ids": ["nope"]}).json() == []
    assert len(client.get("/api/action-items", params={"meeting_ids": [mid]}).json()) == 2


def test_followups_are_cleaned_deduplicated_and_capped():
    llm = FakeLLM(
        json_responses={
            FollowUps: FollowUps(
                questions=[
                    "Who owns the SNS integration",
                    "who owns the sns integration?",
                    "  - When is the next steering committee?  ",
                    "x" * 200,
                    "What changed after the DSMB review?",
                    "Which sites were added?",
                ]
            )
        }
    )
    qs = suggest_followups(llm, "Which sites were added?", "Columbus and Ann Arbor.", [])
    assert qs == [
        "Who owns the SNS integration?",
        "When is the next steering committee?",
        "What changed after the DSMB review?",
    ]


def test_followups_failure_is_silent():
    assert suggest_followups(FakeLLM(fail_json=True), "q", "a", []) == []


def test_agent_emits_suggestions_after_done(container):
    container.ingestion.ingest(TRANSCRIPT, "sync.txt")
    container.llm.json_responses[FollowUps] = FollowUps(questions=["What is Carol profiling?"])
    container.llm.chat_steps[:] = [ScriptedStep(text="We chose SNS.")]
    events = list(container.agent.run("Which vendor?", []))
    assert [e["event"] for e in events][-2:] == ["done", "suggestions"]
    assert events[-1]["data"]["questions"] == ["What is Carol profiling?"]
