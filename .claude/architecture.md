# EvidenceDesk API — Architecture

## Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Current, well supported by every library below |
| Packaging | **uv** (`pyproject.toml` + `uv.lock`) | Fast, reproducible installs; `uv run` for every command |
| Web framework | FastAPI + Pydantic v2 | Typed request/response models, OpenAPI for free |
| Database | PostgreSQL 16 + **pgvector** | One store for relational data, vectors and full-text search |
| ORM / migrations | SQLAlchemy 2.0 (sync, `psycopg` 3) + Alembic | Sync keeps the code simple; embedding and reranking are CPU-bound anyway |
| Keyword retrieval | PostgreSQL full-text search (`tsvector`, `ts_rank_cd`) | Exact identifiers, error codes, config keys |
| Embeddings | `sentence-transformers`, `BAAI/bge-small-en-v1.5` (384 dims), CPU-only `torch` from the PyTorch CPU index | Small, local, reproducible |
| Chunking | Markdown-heading sections, then 300-token windows with 50 overlap, measured with the model's own tokenizer | Word counts overflowed the 512-token limit on code (task 003) |
| Reranking | `sentence-transformers` CrossEncoder, `cross-encoder/ms-marco-MiniLM-L-6-v2` | Second-stage ranker for Experiment C |
| Fusion | Reciprocal Rank Fusion (own ~15-line function) | No library needed |
| Generation | Groq (`groq` SDK), structured JSON output | Low-cost hosted inference |
| Auth | JWT (`PyJWT`), passwords hashed with `pwdlib[argon2]` | Matches the FastAPI docs' current recommendation |
| Background jobs | DB-backed `jobs` table + one worker process (`python -m app.worker`) | Enough for ingestion and eval runs; no Celery/Redis |
| Observability | stdlib `logging` with a JSON formatter; OpenTelemetry tracing in task 012 | Start simple, add tracing once the pipeline exists |
| Tests | pytest + FastAPI `TestClient` against a real Postgres (Docker) | pgvector and FTS cannot be faked meaningfully |
| Lint / format | ruff | One tool |
| Delivery | Docker Compose (api, worker, postgres), GitHub Actions | Reproducible locally and in CI |

New dependencies need a one-line reason in the task doc that adds them.

## Layering

```
Router  (<module>/router.py)      -> validate input (Pydantic), resolve auth deps, call a service, return a schema
Service (<module>/service.py)     -> business logic, transactions, orchestration across repositories
Repository (<module>/repository.py) -> SQLAlchemy queries only; every query takes tenant_id
Model   (<module>/models.py)      -> SQLAlchemy table definitions
Gateway (app/<x>/..._client.py)   -> external systems: the LLM client, the embedding/reranker models
```

- Routers never touch the session or models directly.
- Services own the transaction: they call `session.commit()` when their work succeeds and
  `session.rollback()` before translating a DB error. Repositories may `flush()` but never commit.
  (`with session.begin():` is not used because the auth dependency has already read from the
  session, which auto-begins a transaction; see task 002.)
- AI calls go through `app/generation/llm_client.py`; prompts live in `app/generation/prompts.md`.

## Repository layout

```
app/
  main.py               FastAPI app factory, router registration, exception handlers
  worker.py             Job worker loop (claims jobs with FOR UPDATE SKIP LOCKED)
  core/                 config (pydantic-settings), db session, security (JWT, hashing),
                        errors (AppError + envelope), logging (JSON formatter), deps (current_user)
  auth/                 tenants, users, login, RBAC dependencies
  documents/            document records, ingest endpoint, listing
  ingestion/            chunking (pure), embedding protocol, local_models (torch gateways),
                        pipeline (chunk → embed → store), cli (corpus loader)
  retrieval/            dense search, keyword search, RRF fusion, reranker, retrieval config
  generation/           prompts.md + loader, LLM gateway (Groq), citation checks, answer
                        service, /v1/answers
  evaluation/           dataset builder, IR metrics, span relevance, runner, run records,
                        reports + comparison, provenance (git, environment)
  jobs/                 job model + repository (shared by ingestion and evaluation)
migrations/             Alembic
corpus/                 Frozen corpus: generated pages, manifest.yaml, SOURCES.md, licenses/,
                        sources.yaml (pinned upstream tags), incidents/ (hand-written)
tools/                  Operator tooling, never imported by the app (build_corpus.py)
eval/datasets/          Labelled benchmark (JSONL), dev and test splits
eval/configs/           Retrieval configurations for evaluation runs (YAML)
eval/reports/           Generated experiment reports (Markdown + JSON)
tests/                  Mirrors app/ (tests/retrieval/test_fusion.py, ...)
```

There is no `common` or `utils` package. Shared code lives in `app/core/`.

## Request flows

**Search** (`POST /v1/search`): normalise query → dense top-N (pgvector, cosine) and keyword
top-N (FTS), both filtered by `tenant_id` → RRF fusion → optional cross-encoder rerank →
return top-k passages with per-stage scores.
*As built (task 004): dense only.* The query is embedded with BGE's query instruction
(`EMBEDDING_QUERY_INSTRUCTION`), then an **exact** KNN query (`ORDER BY embedding <=> q, id`)
runs over the tenant's chunks of the configured chunker and model. There is deliberately no
vector index: exact search keeps evaluation free of ANN recall error, and an HNSW scan filtered
by tenant can return fewer than k rows. Measured on the dev machine: 20,000-chunk tenant
retrieve p50 47.6 ms / p95 55.7 ms (Postgres 33 ms); 4-chunk tenant p95 7.8 ms. Revisit in
task 015. The API loads the embedding model once at startup (`PRELOAD_EMBEDDING_MODEL`).

*As built (task 007): modes `dense | keyword | hybrid`.* `service.RETRIEVERS` maps each
mode to a function, and every mode reads the same chunks: one `SearchScope` covers
tenant, chunker, model and filters.
- **keyword:** `chunks.tsv` is a stored `to_tsvector('english', text)` with a GIN index.
  The query is `plainto_tsquery` with its terms ORed: AND matched 0 chunks for typical
  questions, and `websearch_to_tsquery` reads a leading `-` as NOT. Results are ranked by
  `ts_rank_cd`, then chunk id. A query of only stop words returns `[]`.
- **hybrid:** the top 50 from dense and the top 50 from keyword are fused with RRF
  (k = 60, `retrieval/fusion.py`; ranks only, ties by best rank, then id), then cut to k.
- Each hit carries `dense_rank` and `keyword_rank`. Stage latencies are `embed_query`,
  `dense`, `keyword`, `fuse` and `total`.
- The default mode stays `dense`. Experiment B (task 007) did not adopt hybrid: it was
  significantly worse on dev, and on test −0.038 nDCG@10 (CI includes 0) at about 3× the
  latency. `ts_rank_cd` has no IDF.

*As built (task 008): optional reranking.* With `rerank: true`:
- the chosen retriever returns `max(k, rerank_depth)` candidates (API: 50)
- `retrieval/reranking.rerank_hits` scores each `(query, chunk text)` pair with the
  `Reranker` protocol, sorts by score (ties keep the first-stage order) and cuts to k
- each hit keeps `first_stage_rank` and gets `rerank_score`, which also becomes `score`
- stage `rerank` is timed

The gateway is `CrossEncoderReranker` in `local_models.py`
(`cross-encoder/ms-marco-MiniLM-L6-v2`, `trust_remote_code=False`, CPU).
- **API:** the reranker is loaded lazily. The router receives a provider
  (`get_reranker_provider`) and calls it only for rerank requests, or at startup with
  `PRELOAD_RERANKER`.
- **CLI and worker:** they build it only for configs with `rerank: true`.
- **Cost:** about 1.8 s per 20 pairs on the dev machine's CPU (4 torch threads).
- **Experiment C:** reranking the dense top 20 gave nDCG@10 +0.060 (dev) and +0.058 (test).
  It is recommended for answer generation, while search keeps `rerank=false` by default.

**Answer** (`POST /v1/answers`): run search → select context within a token budget → LLM
call with structured output `{answer, cited_chunk_ids, status}` → **server-side citation
check** (every cited ID must be in the supplied context, else `status = insufficient_evidence`
or a 502 `LLM_INVALID_OUTPUT` after one retry) → response with citations.

*As built (task 009a):*
1. **Retrieval.** Defaults to dense with the top 20 reranked (Experiment C); the top
   `ANSWER_CONTEXT_CHUNKS` = 5 chunks become the context.
2. **No hits** → `insufficient_evidence` with no LLM call.
3. **Context.** Passages are labelled `[1]..[n]` in
   `<passage id source="slug@version">` blocks. Delimiters inside passage text are
   neutralised, and the system prompt says passages are untrusted data.
4. **LLM call.** `GroqClient` (`openai/gpt-oss-20b`) with a strict `json_schema`
   generated from `generation.schemas.ModelAnswer` (`{status, answer, citations: int[]}`),
   at temperature 0.
5. **Checks.** `generation.citations.check_reply` validates the reply with Pydantic, then
   checks that an answer has at least one citation, every label was sent, and the
   answer isn't empty. Labels map back to chunks server-side.
6. **One corrective retry**, using the `## retry` prompt. If the reply is still invalid:
   - a format problem → 502
   - an unsupported answer → `insufficient_evidence`
7. **Prompts** live in `app/generation/prompts.md`, loaded and checked at startup.
8. **The gateway** translates timeouts, connection errors, 401/403, 429 and 5xx to
   `LLM_UNAVAILABLE`, and a 400 to an invalid-output attempt. The SDK retries with
   backoff (`LLM_MAX_RETRIES`).
9. **No `GROQ_API_KEY`** → 503 for answers only.
10. **Logs** carry metadata only: model, attempt, outcome, tokens, latency.
11. **Optional gate (task 009b).** With rerank on, if the top cross-encoder score is
    below `ANSWER_MIN_RERANK_SCORE` (default off), the answer is `insufficient_evidence`
    with no LLM call.

**Answer evaluation** (task 009b, CLI `answer-run` / `answer-judge` / `answer-report`):
- **Runs.** Each question of a split goes through `generation.service.answer_question`
  with the API's dependencies.
  - Paced (`--pace`) and resumable: `answers-*.partial.jsonl` keeps finished questions;
    errors are retried on a rerun, and a mismatched run key is refused.
- **Records** (`answers-<config>-<split>.json`) hold raw facts: outcome, answer,
  citations and context with the evidence items each overlaps, top score, tokens,
  latency.
- **Metrics** (`answer_metrics.py`, pure) are computed from the records:
  - abstention, with false abstentions split into retrieval misses and generation
  - citation precision, evidence coverage and context hit
  - the gate sweep
- **The judge** (`judge.py`, `LLM_JUDGE_MODEL`, prompts in `prompts.md`) adds
  correctness (vs the reference) and faithfulness (vs cited passages only).
  - Strict schema, retried once, else `unjudged`.
  - Judged metrics are labelled with the human spot-check agreement.

**Ingest** (`POST /v1/documents/ingest`): store the document (idempotent on slug + version +
content hash) → enqueue an `ingest` job → worker chunks, embeds and replaces the document's
chunks in one transaction. On failure the worker rolls back, then marks the document and job
`failed` in a separate transaction.

**Heavy imports:** `app/ingestion/local_models.py` is the only module importing
sentence-transformers/transformers (≈ 40 s to import torch on the dev machine). The API, the
tests and everything else depend only on the `Embedder` / `Tokenizer` protocols.

**Metrics** (task 005a, `app/evaluation/metrics.py`), all at cutoff k, over the evidence
items each ranked chunk matches: Precision@k (relevant chunks / k), Recall@k (evidence items
matched / items), RR@k (1 / first relevant rank; averaged into MRR@k), nDCG@k with graded
relevance `(2^g − 1) / log2(rank + 1)`, crediting each item once (keeps nDCG ≤ 1 and stops
repeated passages inflating scores). Unanswerable questions are excluded from retrieval
metrics. Aggregates are reported overall and per `query_type` with counts.

**Evaluation run** (task 006a, CLI `python -m app.evaluation.cli run`):
1. **Corpus check.** The tenant must hold exactly the manifest's documents, with the
   same content hash and chunks of the configured chunker and model. Otherwise the run
   stops: labels are character offsets, so a single changed byte invalidates them.
2. **Questions.** Each question of the split goes through `retrieval.service.search`,
   the code `/v1/search` serves, after one unmeasured warm-up query.
3. **Scoring.** Hits are matched to evidence spans and scored at each cutoff.
   Unanswerable questions are run but not scored; their top-1 similarity is reported
   for task 009.
4. **Record.** `eval/reports/<config>-<split>.json` holds the dataset hash, config,
   effective settings, git SHA and dirty flag, environment, aggregates per
   `query_type` and per word-overlap band, latency p50/p95 and every question's hits.
   The `.md` report is rendered from it.
5. **Compare.** `compare` reports per-type deltas, per-question wins, ties and losses,
   and a paired bootstrap 95 % interval.
6. **Test split.** `--split test` requires `--allow-test`, and the failure listing is
   produced for dev only.

**Evaluation API** (task 006b):
1. `POST /v1/evaluations/runs` (admin) validates the dataset name, records the dataset file's
   hash, and stores an `evaluation_runs` row with an `evaluate` job.
2. The worker refuses a dataset that changed since then. Otherwise it runs the same
   `runner.execute_run` as the CLI, with an embedder copy carrying the run's query
   instruction that shares the loaded model (`for_queries`).
3. The handler does not commit. The run summary, the result rows and the job's success
   commit together, so a failed run has no partial results.
4. `GET /v1/evaluations/runs[/{id}]` reads runs; status and errors come from the job.

## Access control

- JWT bearer tokens carry `sub` (user id), `tenant_id` and `role`.
- Roles: `admin` (manage users, run evaluations), `editor` (ingest documents), `viewer`
  (search, answer). Each role includes the ones after it.
- **Tenant isolation is enforced in the repository layer**: every query that touches
  `documents`, `chunks`, `jobs` or evaluation tables filters on `tenant_id`, which comes only
  from the token, never from the request body. Fetching another tenant's object by ID returns
  404, not 403, so IDs cannot be probed. Dedicated cross-tenant tests guard this.

## Cross-cutting conventions

- **Errors:** every non-2xx response is `{error_code, message, field_errors?}` from
  `app/core/errors.py`. Codes are listed in [api-spec.md](api-spec.md).
- **Config:** `app/core/config.py` (`pydantic-settings`) reads env / `.env`. No secrets in code.
- **Logging:** one JSON line per request (method, path, status, duration_ms, request_id) and
  per pipeline stage. Never log full prompts, document text or tokens.
- **Reliability:** LLM calls have a timeout and bounded retries with backoff (429 / 5xx /
  timeout only). Empty retrieval short-circuits to `insufficient_evidence` without an LLM call.
- **Pagination:** `limit` / `offset` with a max `limit` of 100. Simple is fine here.

## Local topology

```
docker-compose.yml:
  postgres (pgvector/pgvector:pg16)   api (uvicorn :8000)   worker (python -m app.worker)
Groq -> real key from .env, or the generation tests use a fake client
```
