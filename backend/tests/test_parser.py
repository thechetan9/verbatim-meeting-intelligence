import pytest

from app.ingestion.parser import TranscriptParseError, parse_timestamp, parse_transcript
from tests.conftest import SAMPLE_DIR


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("00:01:23", 83),
        ("1:02:03", 3723),
        ("02:03", 123),
        ("00:00:01.500", 1.5),
        ("00:00:02,250", 2.25),
    ],
)
def test_parse_timestamp(value, seconds):
    assert parse_timestamp(value) == pytest.approx(seconds)


@pytest.mark.parametrize(
    "line",
    [
        "[00:01:23] Dr. Anita Rao: We will add two sites.",
        "00:01:23 Dr. Anita Rao: We will add two sites.",
        "(00:01:23) Dr. Anita Rao - We will add two sites.",
        "Dr. Anita Rao (00:01:23): We will add two sites.",
        "Dr. Anita Rao [01:23]: We will add two sites.",
    ],
)
def test_plain_text_layouts(line):
    t = parse_transcript(line)
    assert t.format == "txt"
    [u] = t.utterances
    assert u.speaker == "Dr. Anita Rao"
    assert u.start_s == 83
    assert u.text == "We will add two sites."


def test_two_line_header_layout_and_continuations():
    content = "Title line\n\nAlice  00:00:05\nHello there.\nSecond line.\n\nBob  00:00:09\nHi."
    t = parse_transcript(content)
    assert [(u.speaker, u.start_s, u.text) for u in t.utterances] == [
        ("Alice", 5, "Hello there. Second line."),
        ("Bob", 9, "Hi."),
    ]
    assert t.utterances[0].end_s == 9  # end inferred from next turn


def test_vtt_merges_consecutive_cues_from_same_speaker():
    content = (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Alice>Part one</v>\n\n"
        "2\n00:00:03.000 --> 00:00:05.000\n<v Alice>part two.</v>\n\n"
        "3\n00:00:05.000 --> 00:00:07.000\n<v.loud Bob>Reply</v>\n"
    )
    t = parse_transcript(content, "x.vtt")
    assert t.format == "vtt"
    assert [(u.speaker, u.text, u.start_s, u.end_s) for u in t.utterances] == [
        ("Alice", "Part one part two.", 1, 5),
        ("Bob", "Reply", 5, 7),
    ]


def test_srt_with_inline_speaker():
    content = "1\n00:00:01,000 --> 00:00:02,000\nAlice: Hi\n\n2\n00:00:02,500 --> 00:00:04,000\nBob: Hello\n"
    t = parse_transcript(content, "x.srt")
    assert t.format == "srt"
    assert [u.speaker for u in t.utterances] == ["Alice", "Bob"]


@pytest.mark.parametrize("content", ["", "   \n", "just some notes\nwith no timestamps"])
def test_rejects_unparseable(content):
    with pytest.raises(TranscriptParseError):
        parse_transcript(content)


def test_all_sample_transcripts_parse():
    files = sorted(SAMPLE_DIR.glob("*.*"))
    assert len(files) == 4
    for f in files:
        t = parse_transcript(f.read_text(), f.name)
        assert len(t.utterances) >= 20
        assert len(t.speakers) >= 4
        starts = [u.start_s for u in t.utterances]
        assert starts == sorted(starts), f"timestamps not monotonic in {f.name}"
        assert not any(u.text[:2].isdigit() for u in t.utterances), "timestamp leaked into text"
