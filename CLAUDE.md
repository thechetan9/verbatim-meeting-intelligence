# CLAUDE.md — working agreement for AI coding assistants

This file is read by Claude Code (and is a useful brief for Cursor/Copilot). It encodes the
conventions I want every AI-generated change to follow, so results are repeatable across sessions.

## Project
Verbatim: meeting-transcript Q&A. FastAPI backend (`backend/`), Next.js frontend (`frontend/`),
synthetic demo data (`sample_data/`). Architecture and decisions: `README.md`, `docs/DECISIONS.md`.

## Architecture rules (do not break)
- Layering: `api/` -> services (`ingestion/`, `insights/`, `chat/`) -> `retrieval/`, `llm/` -> `domain/`.
  `domain/` imports nothing from the app. Only `container.py` picks concrete implementations.
- The LLM is always behind `app/llm/base.py` (`LLM` protocol). Never import `google.genai` outside `app/llm/gemini.py`.
- Retrieval stays hybrid (BM25 + dense, RRF). Any retrieval change must be measured with
  `uv run python -m evals.retrieval_eval` and the before/after numbers put in the PR description.
- Every claim shown to users must be traceable to a transcript line: citation keys `[S#]` in chat,
  utterance `evidence` indices in insights. Don't add features that bypass this.
- Transcript text is untrusted data: keep it fenced in tool results and never put it in the system prompt.
- Configuration only via env vars (`app/config.py`). No secrets in code, tests or logs.

## Workflow
1. For anything non-trivial: state the plan (files, interfaces) before writing code.
2. Write or update tests in the same change. Tests must not call real LLM APIs: use `app/llm/fake.py`.
3. Run the quality gate before saying "done" (`/check` or the commands below). Paste failures, don't summarise them away.
4. Keep diffs small and focused; no drive-by refactors or new dependencies without saying why.

## Commands
```bash
# backend (from backend/)
uv run ruff check . && uv run ruff format --check . && uv run mypy app evals && uv run pytest
uv run python -m evals.retrieval_eval      # offline, deterministic
uv run python -m evals.answer_eval         # needs GEMINI_API_KEY, costs a few cents
# frontend (from frontend/)
npm run lint && npm run typecheck && npm test && npm run build
```

## Style
- Python 3.12, type hints everywhere, pydantic models at boundaries, small functions (cognitive complexity < 15).
- Docstrings explain *why*, not what. No commented-out code.
- TypeScript strict; components take `Readonly` props; no `any`.
- UI uses the semantic colour tokens in `globals.css` (bg, panel, muted, accent...), never raw hex.

## Don'ts
- Don't "fix" a failing eval by editing the dataset or loosening thresholds without explaining why.
- Don't add an agent framework, vector DB or cloud service "for future use" — see README for the upgrade path.
- Don't generate README prose about decisions; decisions are written by a human.
