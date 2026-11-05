# CLAUDE.md — engineering contract and workflow rules

This file defines the architectural boundaries, coding standards, and verification loops for Claude Code (and Cursor) when working in this repository. Every change must pass these rules before a task is considered complete.

## 1. System overview

**Verbatim** is an agentic meeting-intelligence application: `backend/` in Python 3.12 + FastAPI, `frontend/` in Next.js 16 + React 19 + TypeScript. Architecture and benchmark numbers live in `README.md` and `docs/DECISIONS.md`.

## 2. Architectural boundaries (never violate)

- **Dependency direction:** `api/` → application services (`ingestion/`, `insights/`, `chat/`) → infrastructure/adapters (`retrieval/`, `llm/`) → `domain/`.
- **`domain/` is pure:** only Pydantic models and value objects. Never import FastAPI, SQLite, or LLM SDKs inside `domain/`.
- **Single composition root:** concrete implementations (`GeminiLLM`, `FastEmbedEmbedder`, `MeetingStore`, `HybridRetriever`) are chosen and wired only in `app/container.py`.
- **LLM protocol isolation:** all code outside `app/llm/gemini.py` depends only on the `LLM` protocol (`app/llm/base.py`). Never import `google.genai` anywhere else.
- **Untrusted data fencing:** transcript text is untrusted user input. Never put raw transcript text into the system prompt; return excerpts inside fenced tool results (`<transcript_excerpts>`) and enforce meeting-scope filtering in Python code, not via prompt instructions.
- **Mandatory evidence grounding:** every chat claim must map to an `[S#]` key from the current turn's `EvidenceRegistry`, and every extracted insight must cite valid utterance indices. Never bypass post-generation citation verification.

## 3. Execution and verification loop

1. **Plan before coding:** for any non-trivial feature or refactor, state the affected modules and interface changes before editing files.
2. **Inspect installed SDKs before writing adapters:** don't rely on training-data memory for fast-moving libraries (`google-genai`, `mcp`, `next`). Check the installed signatures in `.venv` or `node_modules` first.
3. **Offline tests with every slice:** every backend change includes or updates tests using the scripted `FakeLLM` (`app/llm/fake.py`) and the deterministic `HashingEmbedder`. Automated tests never make live network or LLM API calls.
4. **Data-driven retrieval changes:** any change to chunking, FTS5 queries, the dense threshold, or RRF parameters must be measured with `/retrieval-experiment` (`uv run python -m evals.retrieval_eval`). Revert changes that lower MRR or hit@1; CI fails below MRR 0.75 or hit@3 0.90.
5. **Run `/check` before finishing:** never declare a task complete until linters, type checks, tests, the retrieval eval, and the frontend build pass. (Dependency vulnerability audits run in CI.)

## 4. Quality gates and commands

```bash
# Backend (run from backend/)
uv run ruff check . && uv run ruff format --check .
uv run mypy app evals
uv run pytest
uv run python -m evals.retrieval_eval      # offline, deterministic CI gate
uv run python -m evals.answer_eval         # live end-to-end eval (needs GEMINI_API_KEY)

# Frontend (run from frontend/)
npm run lint && npm run typecheck && npm test && npm run build
```

## 5. Code style and dependency hygiene

- **Python:** 3.12, type hints everywhere (mypy clean), cognitive complexity < 15 per function (SonarLint clean), 12-factor config via `app/config.py`. Docstrings explain *why*, not what.
- **TypeScript / React:** `strict: true`, no `any`, `Readonly` props, semantic colour tokens from `globals.css` (never raw hex in components). Derive state during render instead of syncing it in effects.
- **Supply-chain hygiene:** pin exact dependency versions. Prefer releases at least 14 days old, unless patching an advisory flagged by `pip-audit` or `npm audit`.

## 6. Hard don'ts

- Never weaken a test or eval threshold to make a failing check pass. Fix the underlying bug or surface the trade-off explicitly.
- Never add unrequested frameworks (LangChain, Celery, external vector DB containers) "for future scalability". Keep the local runtime self-contained; the upgrade path is documented in the README.
- Human ownership of the engineering narrative: README sections 8 and 9 and the trade-off reasoning in `docs/DECISIONS.md` reflect the engineer's own workflow and judgment.
