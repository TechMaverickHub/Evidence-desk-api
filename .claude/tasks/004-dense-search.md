# Task 004 — Dense retrieval and `POST /v1/search`

**Status:** ✅ Done (2026-10-30); 88 tests + 4 opt-in model tests passed, ruff clean
**Week:** W1 · **Modules:** `app/retrieval`, `app/ingestion` (embedder protocol) ·
**Branch:** `task/004-dense-search`

## Goal

A viewer can send a question and get back the most similar chunks from **their own tenant**,
ranked by cosine similarity, with the document they came from, exact character offsets and
per-stage timings. This is the dense baseline that Experiment A (task 006) measures and that
hybrid search (007) and reranking (008) are compared against.

## Scope

In:
- `POST /v1/search` with `mode: "dense"` only. `keyword` / `hybrid` (007) and `rerank` (008)
  are added later without changing the response shape.
- `Embedder.embed_query()` on the protocol, the real embedder and the fake.
- Exact k-nearest-neighbour search in pgvector (`<=>` cosine distance), filtered by tenant,
  chunker and embedding model, with optional `source` / `version` filters.
- A query-embedder dependency in the API, loaded once per process, with an optional warm-up
  at startup.
- Chunk size settings moved into config, so the worker (which writes chunks) and search
  (which reads them) agree on the chunker name from one place.
- A latency measurement of exact search at a realistic upper corpus size, recorded in the handover.

Out:
- HNSW / IVFFlat index (see the decision below; revisit in task 015 if latency needs it).
- Keyword search, fusion, reranking (007, 008).
- Search result caching, pagination of results.

## Assumptions

1. The corpus stays small: the planned corpus is a few hundred documents, so at most
   ~20,000 chunks per tenant even with several chunkers stored side by side.
2. The API process may load the embedding model (~130 MB on disk; torch import ≈ 40 s on the
   dev machine, once per process).
3. `k ≤ 50` is enough for every planned use, including the reranker's candidate pool in task 008.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Exact vs approximate search | **Exact KNN** (`ORDER BY embedding <=> :query LIMIT k`, no vector index) | (1) The benchmark must measure retrieval quality, not ANN recall error: an approximate index would add noise to every experiment. (2) An HNSW index scanned with a `tenant_id` filter returns at most `ef_search` (default 40) candidates *before* filtering, so a small tenant can get fewer than k results; pgvector 0.8's iterative scans fix that, but add tuning knobs. (3) At ≤ 20k × 384-dim vectors an exact scan should take milliseconds; step 9 measures it. HNSW stays a documented option for task 015 |
| Similarity score | `score = 1 − cosine distance` (= dot product, vectors are unit length) | Readable (higher is better, ≈ −1…1) and the same number the evaluation will log |
| Which chunks are searched | `chunks.tenant_id = caller`, `chunker = configured chunker name`, `embedding_model = configured model` | Several chunkers coexist (Experiment D) and vectors from two models must never be compared |
| Tie-breaking | `ORDER BY distance, chunks.id` | Deterministic ranking, so evaluation runs are repeatable |
| Query instruction | BGE's query instruction (`Represent this sentence for searching relevant passages: `) prefixed to queries, from setting `EMBEDDING_QUERY_INSTRUCTION`; empty string disables it. Recorded in the search diagnostics | The model card recommends it for short queries against passages but says to pick whichever scores better on your task. It becomes a cheap A/B in task 006. It is model input configuration, not an LLM prompt, so it lives in settings rather than `prompts.md` |
| Model loading in the API | `get_query_embedder()` dependency, cached per process, importing `local_models` lazily. Lifespan warm-up when `PRELOAD_EMBEDDING_MODEL=true` (default); tests set it to false and override the dependency with the fake | Without warm-up the first search would take ~1 minute on the dev machine. Tests never load torch |
| Chunker name from config | New settings `CHUNK_MAX_TOKENS=300`, `CHUNK_OVERLAP_TOKENS=50`; a pure `chunker_name(max, overlap)` function used by both `TokenWindowChunker.name` and search | One source of truth: a mismatch would silently return zero results |
| Retriever abstraction | None yet: one `dense_search` repository function and one `search` service | Only one strategy exists. Task 007 introduces a `Retriever` protocol when keyword search arrives (second implementation) |
| `mode` field | `Literal["dense"]` now | The request contract is stable; 007 widens the literal |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | Repository: one SQL query. Service: embed → retrieve → time the stages. Router: HTTP only. `deps.py`: building and caching the embedder |
| OCP | Response already carries per-stage diagnostics and a `mode` field, so 007/008 add stages and modes without breaking clients |
| LSP | `FakeEmbedder.embed_query` returns unit-length 384-dim vectors like the real one |
| ISP | The search service needs only `embed_query`; it still takes the existing `Embedder` protocol because the real class implements both methods and splitting it now would be abstraction for its own sake |
| DIP | The service receives the embedder; the router gets it from `Depends(get_query_embedder)`; tests override it |
| DRY | `chunker_name()` shared by chunker and search; tenant filter only in the repository |
| Error handling | No new `except` blocks; a model load failure surfaces at startup (warm-up) or as a logged 500 |

### Dependencies added
None.

## API

`POST /v1/search` — roles: viewer and above.

Request:
```json
{"query": "How do I disable dependency caching?", "k": 10, "mode": "dense",
 "filters": {"source": "fastapi-docs", "version": "0.115"}}
```
- `query`: 1–1,000 characters, not blank. `k`: 1–50 (default 10). `filters` optional, both keys optional.
- `extra="forbid"` on the request and on `filters`.

Response `200`:
```json
{"results": [{"rank": 1, "chunk_id": "…", "score": 0.83, "text": "…",
              "char_start": 104, "char_end": 277, "heading_path": "Dependencies > Caching",
              "document": {"id": "…", "source": "fastapi-docs", "slug": "fastapi/dependencies",
                           "version": "0.115", "title": "Dependencies"}}],
 "diagnostics": {"mode": "dense", "k": 10, "chunker": "tokens-300-overlap-50",
                 "embedding_model": "BAAI/bge-small-en-v1.5", "query_instruction": true,
                 "latency_ms": {"embed_query": 12.4, "retrieve": 3.1, "total": 15.9}}}
```
No matches (empty tenant, filters exclude everything) → `200` with `results: []`.

## Files to create / modify

```
.env.example                          + EMBEDDING_QUERY_INSTRUCTION, PRELOAD_EMBEDDING_MODEL,
                                        CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS
app/core/config.py                    same settings
app/ingestion/chunking.py             chunker_name(); TokenWindowChunker.name uses it
app/ingestion/embedding.py            + embed_query on the protocol
app/ingestion/local_models.py         + embed_query (instruction prefix, normalised)
app/worker.py                         build the chunker from the new settings
app/retrieval/__init__.py
app/retrieval/schemas.py              SearchRequest, SearchFilters, SearchResult, SearchResponse
app/retrieval/repository.py           dense_search()
app/retrieval/service.py              search() with stage timings
app/retrieval/deps.py                 get_query_embedder() (cached, lazy import)
app/retrieval/router.py               POST /v1/search
app/main.py                           router + lifespan warm-up
tests/conftest.py                     PRELOAD_EMBEDDING_MODEL=false, fake query embedder override
tests/fakes.py                        FakeEmbedder.embed_query (+ a way to pin vectors in tests)
tests/retrieval/test_dense_search.py  repository/service ranking, filters, isolation
tests/retrieval/test_search_api.py    API contract, roles, validation
tests/retrieval/test_search_model.py  (marked "model") real-model sanity query
.claude/{api-spec,architecture,database,tasks,plan}.md   at handover
```

## Step-by-step implementation plan

0. `git switch -c task/004-dense-search` from `task/003-ingestion`.
1. Settings + `.env.example`; `chunker_name()`; worker reads chunk sizes from settings.
2. `embed_query` on the protocol, real implementation and fake; extend the model-marked test
   (query vector is unit length; instruction on/off changes the vector).
3. `retrieval/repository.py::dense_search` + tests with hand-made vectors (exact ranking,
   tie order, tenant/chunker/model/source/version filters, `k` limit).
4. `retrieval/service.py::search` with `perf_counter` stage timings.
5. `retrieval/deps.py` + lifespan warm-up in `main.py`; conftest disables preload and
   overrides the dependency with the fake.
6. Schemas + router; API tests.
7. Model-marked end-to-end test: ingest the fixture corpus with the real model, ask
   "Why did the load balancer return 502 after a deploy?", expect the incident's root-cause or
   symptoms chunk at rank 1.
8. Manual check on the dev DB through Swagger with the fixture corpus.
9. Latency check: insert 20,000 random unit vectors for a throw-away tenant on the dev DB,
   run 50 searches, record p50/p95 of the `retrieve` stage and the `EXPLAIN ANALYZE` plan;
   delete the rows. If p95 > 50 ms, stop and bring back the HNSW option for a decision.
10. `ruff`, full tests, model tests once, docs and handover; propose the commit message.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| **Cross-tenant leak** | Tenant B has a chunk identical to the query vector; tenant A's search never returns it, even with `k=50` |
| Wrong ranking | Hand-made vectors with known cosine similarities → exact order and scores (to 1e-6) |
| Non-deterministic order | Two chunks with identical vectors → order is stable by chunk id across calls |
| Mixed vectors | Chunks from another chunker or another embedding model are excluded |
| Filters | `source` and `version` filters each narrow results; unknown values → empty list, not an error |
| Contract | Response shape, ranks 1..n, `len(results) ≤ k`, diagnostics present with non-negative timings |
| Privilege / validation | No token → 401; blank query, `k=0`, `k=51`, unknown `mode`, extra field → 422 |
| Model sanity (opt-in) | Real model ranks the relevant fixture chunk first for a paraphrased question |

## Edge cases and security

- `tenant_id` comes only from the token; `filters` cannot contain it (`extra="forbid"`).
- The query text is never logged; logs carry `k`, result count and stage latencies.
- Query length is capped (1,000 chars) so one request cannot make embedding slow.
- A tenant with no chunks gets an empty result, not an error.

## Risks

- **API startup slow on this machine** (torch import). Mitigation: warm-up at startup, so
  the cost is paid once and `/v1/health` responds only once the app is up;
  `PRELOAD_EMBEDDING_MODEL=false` for fast local reloads.
- **Exact search slower than expected.** Mitigation: measured in step 9 with a stop condition.
- **Instruction prefix hurts on this corpus.** Mitigation: it is a setting, logged in
  diagnostics, and compared in task 006.

## Future improvements

- HNSW with `hnsw.iterative_scan` if the corpus or latency target outgrows exact search (015).
- `Retriever` protocol + keyword and hybrid modes (007), reranking (008).
- Return highlighted spans for the dashboard (014).

## Checklist

- [x] Branch `task/004-dense-search`
- [x] Settings, `chunker_name()`, worker uses chunk-size settings
- [x] `embed_query` on protocol, real embedder, fake; model test extended
- [x] `dense_search` repository + ranking/filter/isolation tests
- [x] `search` service with stage timings
- [x] Query-embedder dependency + startup warm-up; tests never load torch
- [x] Schemas + router + API tests
- [x] Model-marked end-to-end sanity test
- [x] Manual Swagger check on the dev DB
- [x] Latency check at 20k chunks recorded (p50/p95, plan)
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Self-review against the design-principles table
- [x] Update [api-spec.md](../api-spec.md), [architecture.md](../architecture.md), [database.md](../database.md), [tasks.md](../tasks.md), handover below
- [x] Propose commit message, commit after confirmation

---

## Handover

### Summary
`POST /v1/search` embeds the query (with BGE's query instruction) and runs an exact cosine
KNN query over the caller's tenant's chunks, restricted to the configured chunker and the
embedder's model, with optional `source` / `version` filters. Results carry rank, score,
exact offsets, heading path and document identity, plus per-stage latency diagnostics. The
API loads the model once at startup. 88 tests pass (18 new), plus 4 opt-in real-model tests.

### Architecture Notes
- **Exact search, no vector index.** Ties are broken by chunk id, so rankings are repeatable.
  The repository selects explicit columns, so neither document content nor chunk vectors
  are loaded into results.
- **One source of truth for the chunker name:** `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS`
  feed both the worker's `TokenWindowChunker` and search, through `chunker_name()`.
- **Search uses `embedder.model_name`** (not a setting) as the model filter, so a query can
  only meet vectors made by the same model.
- **`get_query_embedder()`** is cached per process and imports torch lazily; the lifespan
  hook warms it up when `PRELOAD_EMBEDDING_MODEL=true`. Tests set it to false and override the
  dependency with `lambda: FakeEmbedder()`. Passing the class itself made FastAPI treat
  `__init__` arguments as request fields (caught by the API tests).
- **The query instruction is configuration, not an LLM prompt**, so it lives in settings, and
  the response reports whether it was used.

### Deviations from the plan
- **Latency was over the stop condition and you chose to keep exact search.** p95 at 20k
  chunks was 55.7 ms, against the 50 ms threshold set in the plan. HNSW stays a task-015 option.
- `FakeEmbedder` gained `query_vectors` (pin a query to a hand-made vector). The repository
  tests in the end inserted chunks with hand-made vectors directly and didn't need it; it is
  kept for the 005/006 metric tests.
- `SentenceTransformerEmbedder` takes `query_instruction` in its constructor; the worker
  omits it because it only embeds passages.

### Database Changes
None (no migration). database.md now records "no vector index by design".

### API Changes
- `POST /v1/search` (dense mode). Contract in api-spec.md.

### Evaluation Results
No benchmark yet (task 005/006). Measured on the dev machine (Windows, Docker Postgres 16,
pgvector 0.8.6, CPU):

| Measurement | Result |
|---|---|
| Real-model sanity: "Why did the load balancer return 502 after a deploy?" | rank 1 = `incidents/0001` › Symptoms (score 0.842) |
| Real-model sanity: "How do I stop a dependency from being cached within a request?" | rank 1 = `fastapi/dependencies` › Caching (0.821) |
| Query embedding (bge-small, CPU) | 31–43 ms per query |
| Exact search, 20,000-chunk tenant, 50 queries, k=10 | retrieve p50 47.6 ms, p95 55.7 ms, max 83.5 ms |
| Exact search, 4-chunk tenant with 20k other rows present | p50 5.2 ms, p95 7.8 ms |
| `EXPLAIN ANALYZE` at 20k chunks | seq scan + top-N heapsort, 33.4 ms execution, 5,002 shared buffers |

All measurement rows were deleted afterwards. The script is in the session scratchpad and
not part of the repo.

### Future Work
- HNSW + `hnsw.iterative_scan` behind the same repository function, if task 015's load test
  or a larger corpus needs it. Evaluation would keep the exact path.
- A/B the query instruction on the dev split (task 006).
- `Retriever` protocol with keyword and hybrid modes (007), reranking (008).

### Modified Files
| File | Why |
|---|---|
| `.env.example`, `app/core/config.py` | Query instruction, preload flag, chunk sizes |
| `app/ingestion/chunking.py` | `chunker_name()` shared with search |
| `app/ingestion/embedding.py`, `app/ingestion/local_models.py` | `embed_query` |
| `app/worker.py` | Chunk sizes from settings |
| `app/retrieval/{repository,service,deps,schemas,router}.py` | Dense search |
| `app/main.py` | Search router, lifespan warm-up |
| `tests/conftest.py`, `tests/fakes.py` | Disable preload, fake query embedder |
| `tests/retrieval/*`, `tests/ingestion/test_embedding_model.py` | Tests |
| `README.md`, `.claude/*.md` | Docs |
