# Architectural Decision Log

This document records the core technical choices behind Verbatim, the alternatives I evaluated, and what would trigger a change as the system scales. Retrieval and answer-quality metrics come from `backend/evals/` (24 retrieval queries and 28 end-to-end questions across the 4 sample meetings), so I treat them as directional benchmarks to prevent regressions rather than statistically large guarantees.

---

## D1. Problem choice: Meeting Intelligence (Option 3)

- **Options considered:** Chat with Docs (Option 1), Code Documentation Assistant (Option 2), Meeting Intelligence (Option 3), Career Intelligence Assistant (Option 4).
- **Decision:** Option 3 (Meeting Intelligence), including the audio-to-transcript bonus.
- **Reasoning:** Spoken conversations create a much more interesting retrieval and reasoning problem than static PDFs. In real meetings, context splits across speaker turns, decisions made in week 1 get reversed in week 3, and attributing *who* said *what* and *when* is critical. I modeled the sample dataset around a clinical-trial operations team (steering committees, vendor reviews, safety syncs) because it reflects the regulated life-sciences workflows Newpage builds for.
- **Trade-off:** Handling messy transcript layouts (`.txt` variants, WebVTT, SRT, and raw audio) took more upfront ingestion work than parsing standard markdown or PDF files.

---

## D2. Chunking strategy: speaker-turn windows (~180 words, 1-turn overlap, metadata header)

- **Options considered:** Fixed token windows (splitting mid-sentence), single speaker turns per chunk, and multi-turn windows across varying word budgets.
- **Decision:** Group whole speaker turns up to a target of **180 words** (hard cap at 320 words; only split a single turn on sentence boundaries if someone speaks an unusually long monologue). Keep a **1-turn overlap** between adjacent chunks, force a chunk break on pauses longer than **90 seconds**, and prepend a contextual header to every chunk before indexing:
  `Meeting: <title> (<date>) | <time range> | Speakers: ...`

**Benchmark results** (`uv run python -m evals.retrieval_eval --target-words N --overlap M`):

| Target words | Turn overlap | Total chunks | Hit@1 | Hit@3 | MRR |
|---|---|---|---|---|---|
| 60 | 0 | 37 | 0.58 | 0.75 | 0.709 |
| 60 | 1 | 54 | 0.58 | 0.79 | 0.705 |
| 100 | 1 | 31 | 0.62 | 0.92 | 0.776 |
| 180 | 0 | 15 | 0.42 | 0.96 | 0.661 |
| **180** | **1** | **15** | **0.75** | **0.96** | **0.858** |
| 300 | 1 | 10 | 0.71 | 0.88 | 0.821 |

- **Why this works:** Very small windows (60 words) separate a question from its answer in back-and-forth dialogue. At 180 words, dropping the 1-turn overlap causes Hit@1 to drop from `0.75` to `0.42` because answers landing on the first turn of a new window lose the preceding prompt. At 300 words, multiple topics blur into a single vector and inflate LLM context tokens. ~180 words plus the header lands around 250 tokens, well inside `bge-small`'s 512-token window.
- **When to revisit:** For 60–90 minute recorded meetings, I would replace the 90-second silence heuristic with embedding-drift or LLM-based topic segmentation.

---

## D3. Retrieval pipeline: hybrid BM25 + dense cosine with Reciprocal Rank Fusion (RRF)

- **Options considered:** Dense vectors only, BM25 lexical search only, a weighted score sum of BM25 + dense, RRF (k=60), and adding a cross-encoder re-ranker.
- **Decision:** Retrieve the top 25 from SQLite FTS5 (BM25 with Porter stemming) and the top 25 by dense cosine similarity (`bge-small-en-v1.5`), apply a `0.35` cosine similarity floor to filter out pure noise, merge via **RRF (k=60)**, and pass the top 6 chunks to the agent.

| Retrieval mode | Hit@1 | Hit@3 | MRR |
|---|---|---|---|
| BM25 only | 0.62 | 0.96 | 0.788 |
| Dense only | 0.50 | 0.92 | 0.712 |
| **Hybrid (RRF)** | **0.75** | **0.96** | **0.858** |

- **Why RRF over a weighted score sum:** BM25 scores are unbounded and shift as corpus statistics change, whereas cosine similarity is bounded in `[-1, 1]`. Score normalization requires fragile tuning per dataset; rank-based fusion needs no calibration and handles both exact keyword lookups (protocol IDs, ticket numbers, names) and semantic paraphrases.
- **Why no re-ranker yet:** With a small corpus, the top 6 RRF chunks already give `0.96` Hit@3 and fit comfortably in the prompt. I would add a cross-encoder (`bge-reranker-base`) over the top 30 candidates once a workspace grows to hundreds of meetings.

---

## D4. Embedding model: local `BAAI/bge-small-en-v1.5` (via FastEmbed / ONNX)

- **Options considered:** OpenAI `text-embedding-3-small`, Gemini embeddings, Voyage AI, and local `bge-small-en-v1.5`.
- **Decision:** Run `bge-small-en-v1.5` (384 dimensions, ~67 MB ONNX model) locally on CPU.
- **Reasoning:**
  1. **Privacy and data minimization:** Raw transcripts are indexed entirely in-process; the external LLM API only ever sees the small retrieved excerpts during Q&A.
  2. **No external dependencies for CI and search:** The Docker image bakes the model weights in at build time, so ingestion, search, and the CI retrieval gate run offline, without API keys or rate limits, and deterministically.
- **When to revisit:** If multilingual transcripts become a requirement, swap in a multilingual model behind the `Embedder` protocol, wired in `container.py`.

---

## D5. Storage layer: single-node SQLite (FTS5 + BLOB vectors + in-memory exact cosine)

- **Options considered:** Chroma, Qdrant, pgvector, LanceDB, Pinecone, and SQLite.
- **Decision:** Store meetings, utterances, chunks, the FTS5 index, and float32 vector blobs in a single SQLite database, computing exact cosine similarity in NumPy.
- **Reasoning:** For a local reviewer setup, `docker compose up` should start cleanly without orchestrating a separate vector database container. At meeting-corpus scale (thousands of chunks), an exact matrix product in NumPy takes milliseconds and avoids approximate-nearest-neighbour recall loss.
- **Production upgrade path:** Implement a PostgreSQL version (`pgvector` HNSW + native `tsvector` full-text search) behind the existing `MeetingStore` interface, enabling multi-tenant row-level security (RLS) and concurrent writes.

---

## D6. LLM selection and resilience: Gemini 3.5 Flash + automatic fallback chain

- **Options considered:** Gemini 3.8 Flash, Gemini 3.5 Flash, Gemini 3.1 Flash-Lite, Claude Sonnet, and local open-weight models.
- **What happened during testing:** I initially configured `gemini-2.5-flash`, which returns `404` for newly created Google AI Studio projects. On the free tier, the newer flash models allowed very few requests per day, and `gemini-3.8-flash` intermittently returned `503` (overloaded).
- **Decision:** I built a configurable **fallback chain** into `GeminiLLM` (retries a transient failure once, then falls back down the chain before any output has streamed) and ran `evals/answer_eval.py` across all three candidate models with fallbacks turned off:

| Model | Fact accuracy | Correct refusals | Latency (p50 / p95) |
|---|---|---|---|
| `gemini-3.8-flash` | 25/25 | 3/3 | 5.3 s / 7.7 s |
| **`gemini-3.5-flash` (default)** | **25/25** | **3/3** | **3.7 s / 5.7 s** |
| `gemini-3.1-flash-lite` | 25/25 | 3/3 | 2.1 s / 2.5 s |

- **Why `gemini-3.5-flash` as primary:** It matches `3.8-flash` on accuracy and citation hygiene while cutting median latency by ~30%. `3.1-flash-lite` is even faster, but in an earlier run it cited meeting ids instead of `[S#]` keys (the guardrail caught it), so I placed it first in the fallback chain rather than making it the primary model. Gemini also accepts `.m4a`/`.mp3` audio natively, which powers the transcription bonus without a separate Whisper service.

---

## D7. Agent orchestration: bounded custom tool loop (~150 lines) vs. frameworks

- **Options considered:** LangGraph, LlamaIndex workflows, a static retrieve-then-generate pipeline, or a custom bounded loop.
- **Decision:** A ~150-line tool-calling loop in `app/chat/agent.py` exposing two tools: `search_transcripts` and `get_meeting_insights`.
- **Why an agentic loop over static RAG:** User queries fall into different patterns. *"What action items does Priya own?"* is best answered from structured insights; *"Why did we drop Twilio?"* requires searching dialogue; *"Which sites are we adding now, and why did that change?"* needs evidence from more than one meeting. A loop lets the model inspect the first tool output and refine its search when needed.
- **Why no LangChain/LangGraph here:** With a single loop capped at 4 steps, writing the orchestration directly in Python keeps the step budget, the forced final-step answer, server-side meeting-scope filters, SSE progress events, and the `[S#]` citation registry transparent and easy to unit-test with the scripted `FakeLLM`. I'd reach for LangGraph when the flow needs branches, human-approval pauses, or durable state.

---

## D8. Background insight extraction at ingestion time

- **Decision:** Parse and embed synchronously so uploaded files are searchable in about a second, then run a background structured-output pass to extract a meeting summary, decisions, action items (owner and due date), and open questions.
- **Reasoning:** Pre-computing structured insights once per upload avoids re-reading full transcripts for common questions and powers the cross-meeting action-item tracker. Every extracted item must reference valid utterance numbers (`evidence`), or it is dropped before saving.

---

## D9. Post-generation citation verification (`[S#]` evidence registry)

- **Decision:** Every transcript line returned by a tool is assigned a key (`[S1]`, `[S2]`, ...) registered in the turn's `EvidenceRegistry`. The LLM is instructed to cite only those keys. After generation, the guardrail strips any key that wasn't shown in that turn's tool output and labels the answer `grounded`, `no_evidence`, or `unsupported`.
- **Reasoning:** Asking an LLM to copy exact quotes and timestamps leads to small formatting hallucinations and fragile fuzzy matching in the UI. Short symbolic keys let the backend verify that the cited utterance exists and let the frontend jump to the exact transcript line and timestamp on click.
- **Limit:** This proves the cited line exists and was shown, not that it fully supports the sentence (see README section 9).

---

## D10. Stateless chat API with sanitized client history

- **Decision:** Keep `/api/chat` stateless on the server; the browser keeps the conversation in `localStorage` and sends the last 8 turns with each request. The backend strips earlier `[S#]` tags from historical assistant messages before building the prompt.
- **Reasoning:** Stripping old `[S#]` keys stops the model from confusing evidence keys from turn 1 with new keys assigned in turn 2, while statelessness allows horizontal scaling behind a load balancer without sticky sessions.
