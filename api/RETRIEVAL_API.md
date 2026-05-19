# Kyoritsu RAG — Retrieval API

**Version:** 1.0  
**Date:** 2026-05-15  
**Scope:** Stateless retrieval tool for internal multi-agent systems

---

## What This API Does

Agents in the multi-agent system call this API with a Japanese query and optional filters. The API retrieves the most relevant document chunks from the internal knowledge base and returns them as raw text with provenance metadata. No synthesis, no LLM call, no session state — just retrieval.

```
Agent  →  POST /v1/tool/retrieval  →  chunks[]  →  Agent reasons with chunks
```

---

## Architecture Overview

```
Agent Request
     │
     ▼
FastAPI Route Handler (async)
     │
     ├─► taxonomy_pass(query)          sync, ~1ms   — extract filters from query text
     │
     ├─► embed_query()                 GPU via executor(1)
     │        └─► ruri-v3-310m
     │
     ├─► asyncio.gather(
     │       bm25_search(),            async DB  ─┐
     │       vector_search()           async DB  ─┘ concurrent
     │   )
     │
     ├─► rrf_fuse()                    in-memory, ~0.1ms
     │
     ├─► fetch_chunks()                async DB
     │
     └─► rerank()                      GPU via executor(1)
              └─► bge-reranker-v2-m3
                       │
                       ▼
                  chunks[]  →  JSON Response
```

---

## Key Decisions, Results, and Tradeoffs

---

### 1. Framework — FastAPI + Uvicorn, Single Worker

**Decision:** FastAPI with a single Uvicorn worker process.

**Why:** The GPU models (embedding and reranker) are not thread-safe. Multiple
workers on a single GPU cause race conditions and crashes. A single async worker
with a serialized GPU executor is the correct model for one GPU.

**Result from smoke tests:**

5 concurrent requests (single wave):

| Metric | Value |
|---|---|
| Wall time | 2.65s |
| Avg per request | 1.76s |
| Pass rate | 5/5 |

25 concurrent requests (2 waves of 13+12, 1s delay, split embed+rerank executors):

| Metric | Value |
|---|---|
| Wave 1 wall time (13 reqs) | 6.44s |
| Wave 2 wall time (12 reqs) | 7.55s |
| Overall avg per request | 3.50s |
| Pass rate | 25/25 |

Wave 2 tail is slightly higher because the GPU queue was still draining from Wave 1 when the 1s delay elapsed.

**Tradeoff:**

| | Single Worker | Multiple Workers |
|---|---|---|
| GPU safety | ✅ No race conditions | ❌ GPU contention crashes |
| CPU parallelism | ❌ One event loop | ✅ N cores used |
| DB concurrency | ✅ asyncpg handles it | ✅ Each worker has own pool |
| Simplicity | ✅ | ❌ Need sticky sessions or shared state |

**When to change:** When you add a second GPU or move to a CPU-based embedding
server (TEI / vLLM encode), multiple workers become viable. At that point switch
to `--workers N` where N = number of GPU devices.

---

### 2. GPU Serialization — Two `ThreadPoolExecutor(max_workers=1)` executors

**Decision:** Embed and rerank run through **separate** single-slot executors
(`embed_executor`, `rerank_executor`). The async event loop never blocks — only
the GPU slots serialize within each stage.

**Why:** PyTorch encoder models mutate shared state during forward passes.
Two concurrent calls to the same model cause `AttributeError: 'NoneType' object
has no attribute 'shape'`. Separate executors guarantee one call per model at a
time, while allowing embed of request N+1 to overlap with rerank of request N.

**What happens under concurrent load:**

```
Request 1  ─── embed ──── DB ──── rerank ─────────────────────── done (2.1s)
Request 2  ──────── embed(overlap) ─── DB ──── rerank ────────── done (3.5s)
Request 3  ──────────── embed(overlap) ─── DB ─────── rerank ─── done (4.8s)
                │                                        │
            embed_executor                        rerank_executor
            serializes embed                      serializes rerank
            DB queries overlap freely
```

With a single executor: Request 2's embed waited for Request 1's rerank to
finish (worst case). With split executors: Request 2 can embed while Request 1
is still reranking — reduces avg latency by ~15–25% under concurrent load.

**Measured result (25 concurrent requests, split executors):**
- Wave 1 (13 reqs): 6.44s wall time, 3.89s avg
- Wave 2 (12 reqs): 7.55s wall time, 3.08s avg
- Overall: 3.50s avg, 25/25 pass

**Tradeoff:**

| Scenario | Behaviour |
|---|---|
| 1 agent | GPU always free, fastest path |
| 2 agents simultaneous | Embed overlaps with prior rerank, minimal wait |
| N agents simultaneous | Queue depth grows, tail ≈ (N-1) × avg_rerank_time |

**When to change (latency growing):**
- If embed latency is the bottleneck → serve ruri-v3-310m via HuggingFace TEI
  (dedicated embedding server with its own dynamic batching). Remove embed from
  the executor and call TEI over HTTP.
- If rerank latency is the bottleneck → increase `max_workers=2` only if you
  have two physical GPUs or move rerank to a dedicated process.
- If queue depth exceeds 5 regularly → add a second API instance behind a load
  balancer (each with its own GPU executor and model copy).

---

### 3. Database Driver — asyncpg with Connection Pool

**Decision:** Replace psycopg2 (synchronous) with asyncpg (native async),
pool min=2 max=10.

**Why:** psycopg2 blocks the entire event loop on every DB call. With 10
concurrent requests, 9 would be stalled waiting for a psycopg2 cursor even
though the DB could serve them in parallel. asyncpg uses the event loop
natively — DB I/O never stalls other requests.

**Tradeoff:**

| | psycopg2 in executor | asyncpg |
|---|---|---|
| Event loop blocking | ❌ Blocks | ✅ Non-blocking |
| Executor slot usage | ❌ Wastes GPU slots on I/O | ✅ GPU slots only for GPU |
| Parameter syntax | `%s` | `$1, $2, ...` |
| pgvector support | via text cast | via text cast (same approach) |
| Maturity | Very mature | Mature, widely used |

**When to change:** asyncpg is the correct choice at all scales on a single
machine. Only reconsider if you move to a distributed DB (e.g. CockroachDB,
PlanetScale) where a managed connection pooler like PgBouncer or pgpool-II sits
in front — in that case the pool config changes, not the driver.

---

### 4. BM25 + Vector Search — Concurrent via `asyncio.gather`

**Decision:** BM25 (ts_rank) and pgvector cosine search run simultaneously
inside each request. Results are merged via Reciprocal Rank Fusion (RRF, C=60).

**Why:** These are independent DB queries with no data dependency between them.
Running sequentially adds the vector search latency on top of BM25 for no
reason. asyncio.gather fires both against the asyncpg pool simultaneously.

**Result:** Concurrent DB execution reduces per-request latency by ~30-50%
compared to sequential BM25 → vector → RRF.

**Tradeoff:**

| | Sequential | Concurrent |
|---|---|---|
| Latency | BM25_time + vector_time | max(BM25_time, vector_time) |
| DB pool connections | 1 per request | 2 per request |
| Complexity | Simple | Slightly more code |
| Risk | None | Pool exhaustion if max_size too low |

**When to change:** If DB connection pool exhaustion appears in logs (pool
timeout errors), either raise `DB_POOL_MAX` in config.py or fall back to
sequential if under low-concurrency conditions. At current scale (2 agents,
pool max=10) there is no risk.

---

### 5. Filter Resolution — Taxonomy Pass + Agent Override

**Decision:** `taxonomy_pass()` extracts company, dept, section, year, month
from the query text using regex and keyword lookup. Agent-supplied filters
override taxonomy results.

**Why:** Agents that know their context can pass filters explicitly for
precision. Agents doing open-ended queries get automatic routing. The taxonomy
pass is rule-based (no LLM call) — deterministic, ~1ms, zero hallucination risk.

**Routing chain:**

```
Query text
    │
    ▼
taxonomy_pass()               ← regex + keyword lookup (~1ms)
    │
    ├── company / dept / section found  → use them
    │
    └── nothing found
            │
            ▼
        Agent-supplied filters  → use them
            │
            └── still nothing
                    │
                    ▼
                No filter  → search all documents (broad recall)
```

**Why no LLM routing here:** A previous implementation used an LLM intent layer
(Ollama qwen3:30b) to classify queries and extract filters. It was removed
because it hallucinated dept values, added 3-8s latency per request, and was
less accurate than the deterministic keyword lookup for known organizational
terms like 売上高 → 営業部.

**Tradeoff:**

| | LLM Intent Layer | Rule-based Taxonomy |
|---|---|---|
| Accuracy on known terms | Hallucinations observed | 100% deterministic |
| Accuracy on novel terms | Better generalisation | May miss unknown terms |
| Latency | +3–8s | ~1ms |
| Maintenance | Prompt tuning | Update keywords.py |

**When to change:** If agents start querying across multiple periods or
companies in a single call, the taxonomy pass already supports returning lists
of (year, month) pairs and building cartesian product filter combinations
(max 4). This is handled in `synthesize.py` for the CLI path. The API currently
takes the first resolved filter per dimension — extend `routes.py` to accept
a `multi_period` flag to enable cartesian retrieval if agents need it.

---

### 6. Response Design — Raw Chunks, No Synthesis

**Decision:** Return `chunks[]` with full text and metadata. No LLM call inside
the API. Agents receive raw evidence and reason with it themselves.

**Why:** The multi-agent system uses this as a tool. Each agent has its own
reasoning loop, prompt, and chain-of-thought. Synthesizing inside the retriever
would:
- Force one prompt style on all agents
- Prevent agents from combining evidence across multiple retrieval calls
- Add 10-30s of LLM latency to what should be a fast retrieval step

**Fields returned per chunk:**

| Field | Purpose |
|---|---|
| `chunk` | Full text for agent reasoning |
| `company`, `dept`, `section` | Provenance for citation |
| `year`, `month`, `meeting_date` | Temporal grounding |
| `rrf_score`, `rerank_score` | Agent can apply its own relevance threshold |
| `doc_type` | Report vs action plan distinction |

**Fields intentionally dropped:** `bm25_rank`, `vec_rank` — internal retrieval
plumbing that agents have no use for.

---

### 7. Timeout and Error Handling

**Decision:** 60s timeout per request. Returns HTTP 504 on timeout.
Zero chunks returns HTTP 200 with empty list.

**Why 60s:** Under worst-case queue (multiple agents, GPU busy), a request may
wait 30-40s before its GPU slot is available. 60s provides headroom without
hanging agents indefinitely.

**Why 200 on empty:** No results is a valid retrieval state. Agents should
decide what to do next (retry with looser filters, report data unavailable).
A 404 would force agents to handle an exception path for a normal condition.

**Error map:**

| Condition | HTTP code | Agent action |
|---|---|---|
| Chunks found | 200 + chunks | Use chunks for reasoning |
| No chunks found | 200 + empty list | Retry or report no data |
| GPU queue timeout | 504 | Retry after backoff |
| Bad request body | 422 | Fix request schema |
| Server starting up | Connection refused | Wait for /v1/health → 200 |

---

## What to Change as Latency / Load Grows

### Signal: Avg request latency > 10s

**Cause:** GPU queue backing up. The `ThreadPoolExecutor(max_workers=1)`
serializes all embed + rerank calls.

**Fix (in order of effort):**
1. Move embedding to a dedicated TEI server — removes embed from the executor,
   only rerank stays serialized. TEI handles its own dynamic batching.
2. If rerank is still the bottleneck — add `--no-rerank` flag to low-priority
   agent calls, cutting rerank time from each request.
3. Add a second API instance on a second GPU, route agents round-robin.

---

### Signal: DB query latency > 2s

**Cause:** asyncpg pool exhausted or PostgreSQL index under pressure.

**Fix:**
1. Raise `DB_POOL_MAX` in `api/app/config.py` (currently 10).
2. Run `EXPLAIN ANALYZE` on BM25 and vector queries — verify `ivfflat` /
   `hnsw` indexes are being used.
3. Separate read replica for retrieval queries if write load is contending.

---

### Signal: 504s appearing under load

**Cause:** 60s timeout hit. Either GPU queue too deep or DB slow.

**Fix:**
1. Check which stage is slow — add per-stage timing logs in `retrieve_async()`.
2. If GPU: reduce `top_k` default (currently 8) or add request queuing with
   early rejection (return 503 if queue depth > N).
3. If DB: index tuning (see above).

---

### Signal: More than 5 agents concurrently

**Current design handles 2 agents comfortably.** At 5+ agents the GPU queue
grows and tail latency rises. Options:

| Agents | Recommended change |
|---|---|
| 2–5 | Current design, no change needed |
| 5–10 | TEI for embedding + keep rerank in executor |
| 10+ | Second GPU instance + load balancer |
| 20+ | Separate embedding service + rerank service, API becomes coordinator |

---

## Running the API

```bash
# Start
cd NW-RAG
venv/bin/uvicorn api.app.main:app --host 0.0.0.0 --port 8000 --workers 1

# Health check
curl http://localhost:8000/v1/health

# Single retrieval call
curl -X POST http://localhost:8000/v1/tool/retrieval \
  -H "Content-Type: application/json" \
  -d '{"query": "営業部の売上高の状況は？", "top_k": 8}'

# Smoke test — 5 requests
venv/bin/python api/smoke_test.py --no-wait

# Smoke test — 25 requests, 2 waves with 1s delay
venv/bin/python api/smoke_test.py --count 25 --waves 2 --delay 1 --no-wait
```

Logs: `api/logs/api.log` (runtime), `api/logs/smoke_<ts>.json` (test results)
