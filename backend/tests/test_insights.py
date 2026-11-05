from app.domain.models import InsightsStatus, MeetingInsights
from app.insights.extractor import build_prompt, ground_insights
from tests.conftest import TRANSCRIPT, sample_insights


def test_grounding_drops_items_without_valid_evidence():
    grounded, dropped = ground_insights(sample_insights(), valid_idx={0, 1, 2, 3, 4, 5, 6})
    assert dropped == 1  # the open question cited utterance #999
    assert grounded.open_questions == []
    assert [a.owner for a in grounded.action_items] == ["Bob Singh", "Carol Diaz"]


def test_grounding_filters_partial_evidence():
    ins = sample_insights()
    ins.decisions[0].evidence = [2, 42]
    grounded, _ = ground_insights(ins, valid_idx={2})
    assert grounded.decisions[0].evidence == [2]


def test_ingestion_runs_insights_in_background(container):
    meeting = container.ingestion.ingest(TRANSCRIPT, "2026-01-05_weekly-sync.txt")
    assert meeting.insights_status == InsightsStatus.PENDING
    assert meeting.title == "Weekly sync"
    assert meeting.date == "2026-01-05"
    container.ingestion.generate_insights(meeting.id)
    stored = container.store.get_meeting(meeting.id)
    assert stored.insights_status == InsightsStatus.READY
    ins = container.store.get_insights(meeting.id)
    assert isinstance(ins, MeetingInsights) and len(ins.action_items) == 2
    prompt = container.llm.json_prompts[-1]
    assert "#2 [00:41] Alice Chen:" in prompt  # utterances are numbered for evidence


def test_insights_failure_is_recorded_not_raised(container):
    container.llm.fail_json = True
    meeting = container.ingestion.ingest(TRANSCRIPT, "sync.txt")
    container.ingestion.generate_insights(meeting.id)
    stored = container.store.get_meeting(meeting.id)
    assert stored.insights_status == InsightsStatus.FAILED
    assert "scripted failure" in stored.insights_error


def test_prompt_contains_meeting_header(container):
    meeting = container.ingestion.ingest(TRANSCRIPT, "2026-01-05_sync.txt", title="Sync")
    prompt = build_prompt(meeting, container.store.get_utterances(meeting.id))
    assert prompt.startswith("Meeting: Sync (2026-01-05)")
