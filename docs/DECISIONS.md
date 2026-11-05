# Decision log

Short records of the choices that shaped Verbatim: what I considered, what I picked, and what
would make me change my mind. Numbers come from `backend/evals/` (24 labelled questions over the
4 synthetic meetings), so they are directional, not statistically strong.

---

## D1. Use case: Meeting Intelligence (option 3)

**Considered:** chat-with-docs, code docs assistant, meeting intelligence, career assistant.
**Chose:** meeting intelligence.
**Why:** it has the most interesting retrieval problem of the four. Transcripts are conversations, not
documents: the answer to a question is often spread across two speakers, decisions get revised in
later meetings, and "who said it, when" matters as much as "what". It also maps directly onto the
life-sciences work Newpage does (steering committees, governance reviews, sprint planning), so the
sample data is a clinical-trial team.
**Trade-off:** messier input (formats, speaker labels) than a PDF corpus, so more parsing work.

## D2. Chunking: whole speaker turns, ~180 words, 1-turn overlap, contextual header

**Considered:** fixed token windows; one chunk per turn; turn-windows of various sizes.
**Chose:** windows of whole turns (target 180 words, hard max 320), never splitting a turn unless it is
a monologue longer than the max (then split on sentences). One turn of overlap between windows. A
silence > 90 s closes a window (cheap topic-boundary signal). Each chunk's indexed text starts with
`Meeting: <title> (<date>) | <time range> | Speakers: ...`.

**Measured** (hybrid retrieval, `evals/retrieval_eval.py --target-words N --overlap M`):

| target words | overlap | chunks | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| 60 | 0 | 37 | 0.58 | 0.75 | 0.709 |
| 60 | 1 | 54 | 0.58 | 0.79 | 0.705 |
| 100 | 1 | 31 | 0.62 | 0.92 | 0.776 |
| 180 | 0 | 15 | 0.42 | 0.96 | 0.661 |
| **180** | **1** | **15** | **0.75** | **0.96** | **0.858** |
| 300 | 1 | 10 | 0.71 | 0.88 | 0.821 |

**Takeaways:** tiny chunks lose the question/answer pairing; overlap matters a lot at this size (an
answer at the start of a window loses its question without it); bigger chunks start to dilute the
embedding and send more tokens to the LLM. 180 words ≈ 250 tokens + header, comfortably inside
bge-small's 512-token limit.
**Revisit when:** meetings get much longer (topic segmentation by an LLM or by embedding drift
would beat a silence heuristic) or the corpus grows enough that the eval set needs to grow too.

## D3. Retrieval: hybrid BM25 + dense, fused with RRF

**Considered:** dense only; BM25 only; hybrid with weighted score sum; hybrid with RRF; adding a
cross-encoder re-ranker.
**Chose:** BM25 (SQLite FTS5, porter stemming) + dense cosine (bge-small), merged with Reciprocal
Rank Fusion (k=60), 25 candidates each, top 6 to the model.

| mode | hit@1 | hit@3 | MRR |
|---|---|---|---|
| BM25 only | 0.62 | 0.96 | 0.788 |
| dense only | 0.50 | 0.92 | 0.712 |
| **hybrid (RRF)** | **0.75** | **0.96** | **0.858** |

**Why RRF rather than a weighted sum:** BM25 scores and cosine similarities are on different scales and
BM25 scores shift as the corpus changes; RRF only uses ranks, so there is nothing to calibrate.
**Why not a re-ranker yet:** with ~15 chunks the candidates already fit in context; a re-ranker earns
its latency at hundreds of meetings. First thing I'd add at scale.
**Detail:** a dense-score floor (0.35) keeps unrelated chunks from being fused in when nothing matches,
which helps the model say "not covered" instead of answering from noise.

## D4. Embeddings: BAAI/bge-small-en-v1.5, run locally (fastembed/ONNX)

**Considered:** OpenAI `text-embedding-3-small`, Gemini embeddings, Voyage, local bge-small.
**Chose:** local bge-small (384-d, ~67 MB, CPU).
**Why:** transcript text never leaves the service just to be indexed (only retrieved snippets reach the
LLM, which matters for health-adjacent content); zero cost and no rate limits for bulk ingest;
deterministic, so the retrieval eval runs in CI without secrets.
**Trade-off:** English-only and weaker than large API models on subtle paraphrase. Hybrid search
covers part of that gap. Swapping is one class behind the `Embedder` protocol.

## D5. Storage / "vector DB": SQLite (FTS5 + embeddings as blobs), exact search in numpy

**Considered:** Chroma, Qdrant, Pinecone, pgvector, LanceDB, SQLite.
**Chose:** SQLite for everything (meetings, turns, chunks, FTS5 index, vectors).
**Why:** one file, zero extra services, `docker compose up` just works. At meeting scale (thousands of
chunks) exact cosine over an in-memory matrix takes milliseconds and is more accurate than ANN.
FTS5 gives a real BM25 index, so hybrid search costs nothing extra.
**Production path:** Postgres with pgvector (HNSW) + full-text search behind the same `MeetingStore`
interface; adds tenancy (row-level security) and concurrent writers. OpenSearch if corpus or query
volume gets large.

## D6. LLM: Gemini 2.5 Flash behind a provider-neutral interface

**Considered:** Gemini 2.5 Flash / Pro, Claude Sonnet, GPT-4.1-mini, a local Llama via Ollama.
**Chose:** Gemini 2.5 Flash (configurable via `LLM_MODEL`), with thinking capped low.
**Why:** good tool calling and JSON-schema output, fast and cheap for an interactive loop, native
audio input (used for the voice-to-transcript bonus), long context for insight extraction, and a free
tier so reviewers can run it.
**Trade-off:** I'd want to A/B against Claude Sonnet on the answer eval before production; the
`LLM` protocol (`app/llm/base.py`) makes that one adapter file.

## D7. Orchestration: a small hand-written tool loop, not a framework

**Considered:** LangGraph, LlamaIndex query engines, Google ADK, a fixed retrieve-then-answer chain.
**Chose:** a bounded tool-calling loop (~150 lines, `app/chat/agent.py`) with two tools:
`search_transcripts` (hybrid retrieval) and `get_meeting_insights` (pre-extracted decisions/actions).
**Why a loop rather than a fixed chain:** questions mix two kinds of need. "What does Priya own?" is
best served by structured data; "why did we drop Twilio?" needs the discussion; "what changed between
the two steering meetings?" needs both, across meetings. Letting the model pick tools (and re-search
with better terms) handles all three.
**Why no framework:** the control flow is one loop. Owning it makes the important parts explicit and
testable: step budget (last step forces a text answer), scope enforcement in the tool layer (not the
prompt), per-step tracing, and citation bookkeeping. I'd reach for LangGraph when there are branches,
human-in-the-loop pauses or durable state.

## D8. Insights extracted once at ingestion, with evidence

**Chose:** one structured-output call per meeting (summary, decisions, action items with owner/due,
open questions, topics). Every item must cite utterance numbers; invalid numbers are dropped and
items left without evidence are discarded.
**Why:** the most common questions ("what did we decide", "what do I owe") get instant, consistent
answers, and the agent can reason across meetings from compact data instead of re-reading transcripts.
Runs in the background so uploads are searchable immediately.

## D9. Citations as keys, verified after generation

**Chose:** every transcript line the model sees is labelled `[S1]`, `[S2]`...; the model cites keys, not
quotes. After generation, keys are checked against what was actually shown; unknown keys are stripped
and each answer is labelled `grounded`, `no_evidence` or `unsupported` (shown in the UI).
**Why:** makes citations machine-checkable and lets the UI jump to the exact second. Free-text quotes
would need fuzzy matching and still can't prove the model saw them.
**Limit:** this proves the cited line exists, not that it supports the sentence. An NLI/LLM-judge
faithfulness check per sentence is the next step (see README).

## D10. Server-stateless chat with client-held history

**Chose:** the browser sends the last few turns with each question; the server keeps no session.
History is trimmed to 8 messages and stale citation keys are stripped before it reaches the model.
**Why:** horizontal scaling with no sticky sessions, nothing to expire, simpler privacy story.
**Trade-off:** history isn't persisted across devices; fine for this scope.
