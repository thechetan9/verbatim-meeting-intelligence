---
description: Run every quality gate (lint, types, tests, retrieval eval, frontend build) and report failures verbatim
---
Run these in order and stop at the first failure. Report the exact failing output and propose a fix; do not edit tests or eval thresholds to make them pass.

1. `cd backend && uv run ruff check . && uv run ruff format --check .`
2. `cd backend && uv run mypy app evals`
3. `cd backend && uv run pytest`
4. `cd backend && uv run python -m evals.retrieval_eval`
5. `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`

Finish with a one-line summary per gate: PASS / FAIL.
