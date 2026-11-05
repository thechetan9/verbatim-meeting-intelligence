from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import (
    ActionItem,
    Decision,
    MeetingInsights,
    OpenQuestion,
    Topic,
)
from app.llm.fake import FakeLLM
from app.main import create_app
from app.retrieval.embedder import HashingEmbedder
from app.retrieval.store import MeetingStore

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"

TRANSCRIPT = """Weekly sync
[00:00:05] Alice Chen: Morning. First topic is the vendor contract for SMS.
[00:00:20] Bob Singh: We compared Twilio and AWS SNS. SNS is cheaper and already covered by our BAA.
[00:00:41] Alice Chen: Then we decide to use AWS SNS. Bob, please draft the integration plan by Friday.
[00:01:02] Bob Singh: Will do. I'll have the integration plan ready by Friday.
[00:02:30] Carol Diaz: Separate topic. The dashboard latency is 4 seconds on the reports page.
[00:02:51] Alice Chen: That's too slow. Carol, can you profile it this week?
[00:03:05] Carol Diaz: Yes, I'll profile the reports page and share findings Thursday.
"""


def sample_insights() -> MeetingInsights:
    return MeetingInsights(
        summary="The team chose AWS SNS and discussed dashboard latency.",
        decisions=[Decision(text="Use AWS SNS for SMS", decided_by="Alice Chen", evidence=[2])],
        action_items=[
            ActionItem(
                task="Draft SNS integration plan", owner="Bob Singh", due="Friday", evidence=[2, 3]
            ),
            ActionItem(
                task="Profile reports page", owner="Carol Diaz", due="Thursday", evidence=[6]
            ),
        ],
        open_questions=[OpenQuestion(text="Is 2s latency acceptable?", evidence=[999])],
        topics=[Topic(title="SMS vendor", start_idx=0), Topic(title="Latency", start_idx=4)],
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=":memory:",
        gemini_api_key=None,
        sample_data_dir=str(SAMPLE_DIR),
        log_json=False,
        retrieval_min_dense_score=0.0,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(json_responses={MeetingInsights: sample_insights()})


def _sync_runner(fn, *args, **kwargs):
    fn(*args, **kwargs)


@pytest.fixture
def container(settings: Settings, fake_llm: FakeLLM) -> Container:
    return build_container(
        settings,
        store=MeetingStore(":memory:"),
        embedder=HashingEmbedder(),
        llm=fake_llm,
        run_background=_sync_runner,
    )


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container=container))
