---
description: Try a retrieval/chunking change and measure it against the eval set before keeping it
argument-hint: <describe the change to try>
---
Goal: evaluate this retrieval change: $ARGUMENTS

1. Run `cd backend && uv run python -m evals.retrieval_eval` and save the table as the baseline.
2. Make the smallest change that implements the idea (chunker, `hybrid.py`, or config only).
3. Re-run the eval. Show baseline vs new side by side (hit@1, hit@3, MRR, per question type).
4. If MRR or hit@1 drops, revert the change and explain why it likely didn't help.
5. If it improves, keep it, add/adjust unit tests, and run `/check`.
Never change `evals/dataset.yaml` in the same experiment.
