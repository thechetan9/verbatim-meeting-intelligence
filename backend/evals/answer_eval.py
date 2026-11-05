"""End-to-end answer eval: runs the real agent (Gemini) over the labelled questions.

Checks are deterministic (no LLM-as-judge), so a failure is always explainable:
  * correctness   - every `must_include` group has at least one term in the answer
  * grounded      - the answer carries at least one valid citation
  * citation hit  - at least one citation points into the meeting that holds the answer
  * refusal       - unanswerable / off-topic questions are declined, not answered
plus latency (p50/p95), tokens and estimated cost per question.

Needs GEMINI_API_KEY (reads backend/.env).  uv run python -m evals.answer_eval
"""

from __future__ import annotations

import statistics
import sys
import time

from app.config import Settings
from app.container import build_container
from app.llm.base import LLMError
from evals.common import RESULTS_DIR, contains, ingest_samples, load_cases, meeting_for, new_store


def _sync(fn, *args, **kwargs):
    fn(*args, **kwargs)


def main() -> int:
    settings = Settings(database_path=":memory:", log_json=True, log_level="WARNING")
    if not settings.llm_enabled:
        print("GEMINI_API_KEY is not set; skipping answer eval.", file=sys.stderr)
        return 2
    c = build_container(settings, store=new_store(), run_background=_sync)
    assert c.agent is not None
    meetings = ingest_samples(c.ingestion)
    for m in meetings.values():
        c.ingestion.generate_insights(m.id)
    failed_insights = [m.title for m in c.store.list_meetings() if m.insights_status != "ready"]

    rows: list[tuple] = []
    latencies: list[float] = []
    costs: list[float] = []
    tokens: list[int] = []
    for case in load_cases():
        started = time.perf_counter()
        try:
            events = list(c.agent.run(case.question, history=[]))
        except LLMError as exc:
            rows.append((case, False, f"LLM error: {exc}", {}, []))
            continue
        latencies.append(time.perf_counter() - started)
        done = next((e["data"] for e in events if e["event"] == "done"), None)
        cites: list[dict] = next(
            (e["data"]["items"] for e in events if e["event"] == "citations"), []
        )
        if done is None:
            rows.append((case, False, "no answer", {}, cites))
            continue
        trace = done["trace"]
        costs.append(trace["est_cost_usd"])
        tokens.append(trace["input_tokens"] + trace["output_tokens"])
        rows.append((case, True, done["answer"], done, cites))

    def correct(case, answer: str) -> bool:
        return all(any(contains(answer, term) for term in group) for group in case.must_include)

    answerable = [r for r in rows if r[0].answerable and r[1]]
    unanswerable = [r for r in rows if not r[0].answerable and r[1]]
    n_correct = sum(correct(case, ans) for case, _, ans, _, _ in answerable)
    n_grounded = sum(d.get("grounding") == "grounded" for _, _, _, d, _ in answerable)
    with_meeting = [r for r in answerable if r[0].meeting]
    n_cite_hit = sum(
        any(ci["meeting_id"] == meeting_for(case.meeting or "", meetings).id for ci in cites)
        for case, _, _, _, cites in with_meeting
    )
    n_refused = sum(
        d.get("grounding") in {"no_evidence", "unsupported"} and not cites
        for _, _, _, d, cites in unanswerable
    )

    p50 = statistics.median(latencies) if latencies else 0
    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else 0
    lines = [
        f"# Answer eval — model `{c.llm.model if c.llm else '-'}`, {len(rows)} questions",
        "",
        "| metric | result |",
        "|---|---|",
        f"| answer correctness (must-include terms) | {n_correct}/{len(answerable)} |",
        f"| grounded (≥1 valid citation) | {n_grounded}/{len(answerable)} |",
        f"| citation points to the right meeting | {n_cite_hit}/{len(with_meeting)} |",
        f"| correct refusals on unanswerable | {n_refused}/{len(unanswerable)} |",
        f"| latency p50 / p95 | {p50:.1f}s / {p95:.1f}s |",
        f"| avg tokens / question | {statistics.mean(tokens) if tokens else 0:.0f} |",
        f"| avg est. cost / question | ${statistics.mean(costs) if costs else 0:.5f} |",
        f"| insight extraction failures | {len(failed_insights)} |",
        "",
        "## Per question",
        "",
    ]
    for case, ok, ans, done, cites in rows:
        verdict = (
            ("PASS" if correct(case, ans) else "FAIL")
            if case.answerable
            else ("PASS" if done.get("grounding") != "grounded" else "FAIL")
        )
        if not ok:
            verdict = "ERROR"
        lines += [
            f"### {case.id} [{verdict}] {case.question}",
            f"_type: {case.type}, grounding: {done.get('grounding', '-')}, citations: {len(cites)}_",
            "",
            "> " + ans.replace("\n", "\n> "),
            "",
        ]
    report = "\n".join(lines)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "answers.md").write_text(report + "\n")
    print("\n".join(lines[:14]))
    print(f"\nFull report: {RESULTS_DIR / 'answers.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
