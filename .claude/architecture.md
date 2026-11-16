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
| Chunking | Markdown-heading sections, then 450-token windows with 75 overlap (adopted in Experiment D, task 010; 300/50 before), measured with the model's own tokenizer. Variants (task 010) are named `tokens-<max>-overlap-<o>[-ctx]` and coexist in `chunks`; `-ctx` variants embed and rerank `title (source version) > heading path` + text, while stored text and offsets never include it | Word counts overflowed the 512-token limit on code (task 003) |
| Reranking | `sentence-transformers` CrossEncoder, `cross-encoder/ms-marco-MiniLM-L-6-v2` | Second-stage ranker for Experiment C |
| Fusion | Reciprocal Rank Fusion (own ~15-line function) | No library needed |
| Generation | Groq (`groq` SDK), structured JSON output | Low-cost hosted inference |
| Auth | JWT (`PyJWT`), passwords hashed with `pwdlib[argon2]` | Matches the FastAPI docs' current recommendation |
| Background jobs | DB-backed `jobs` table + one worker process (`python -m app.worker`) | Enough for ingestion and eval runs; no Celery/Redis |
| Observability | stdlib `logging` with a JSON formatter carrying `trace_id`; OpenTelemetry traces (task 012): FastAPI's built-in request spans plus our stage spans; exporter `none` / `console` / `otlp` | Traces show where time goes per request without logging any text |
| Tests | pytest + FastAPI `TestClient` against a real Postgres (Docker) | pgvector and FTS cannot be faked meaningfully |
| Lint / format | ruff | One tool |
| Delivery | Docker Compose (postgres, migrate, api, worker; optional Jaeger), GitHub Actions CI + evaluation regression gate (task 013) | Reproducible locally and in CI; retrieval regressions fail a PR |

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
                        reports + comparison, regression gate, provenance (git, environment)
  jobs/                 job model + repository (shared by ingestion and evaluation)
migrations/             Alembic
corpus/                 Frozen corpus: generated pages, manifest.yaml, SOURCES.md, licenses/,
                        sources.yaml (pinned upstream tags), incidents/ (hand-written)
tools/                  Operator tooling, never imported by the app (build_corpus.py)
eval/datasets/          Labelled benchmark (JSONL), dev and test splits
eval/configs/           Retrieval configurations for evaluation runs (YAML)
eval/reports/           Generated experiment reports (Markdown + JSON)
tests/                  Mirrors app/ (tests/retrieval/test_fusion.py, ...)
Dockerfile              One image for api, worker and migrate (task 013)
docker-compose.yml      postgres, migrate, api, worker; jaeger under the "tracing" profile
.github/workflows/      ci.yml (lint, tests, image build), eval-gate.yml (dev regression gate)
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

## Failure scenarios (task 011)

Each defined failure has a defined behaviour and a test. LLM retries are tested through the
real Groq SDK over an `httpx.MockTransport` (no network), pinning the request count.

| # | Scenario | Behaviour | Test |
|---|---|---|---|
| 1 | Provider timeout | SDK retries `LLM_MAX_RETRIES` (2); then 503 `LLM_UNAVAILABLE`; 3 requests | `tests/generation/test_llm_retries.py::test_1_…` |
| 2 | Short rate limit (429, `retry-after` ≤ 60 s) | Retried after the hinted delay; success if a later attempt succeeds | `test_llm_retries.py::test_2_…` |
| 3 | Persistent 5xx / rate limit | 503 `LLM_UNAVAILABLE` + `Retry-After` when given | `test_llm_retries.py::test_3_…`, `test_a_short_429_…` |
| 4 | Daily quota (429 with `retry-after` > 60 s, or a per-day message) | 503 `LLM_QUOTA_EXCEEDED` + `Retry-After`; `answer-run` stops with a resume hint, finished answers kept | `test_llm_retries.py::test_4_…`, `tests/evaluation/test_answer_runner.py::test_a_daily_quota_stops_…`, `tests/generation/test_answers_api.py::test_the_retry_hint_…` |
| 5 | Bad key / no access / unknown model (401/403/404) | 503 `LLM_NOT_CONFIGURED`, not retried (1 request); runs stop with an operator hint | `test_llm_retries.py::test_5_…`, `test_answer_runner.py::test_a_configuration_error_…` |
| 6 | No `GROQ_API_KEY` | 503 `LLM_NOT_CONFIGURED`; search unaffected | `test_answers_api.py::test_without_an_llm_configured_…` |
| 7 | Invalid model output | One corrective retry; then 502 `LLM_INVALID_OUTPUT` (format) or `insufficient_evidence` (unsupported) | `test_answers_api.py::test_malformed_output_twice_is_a_502`, `::test_an_unsupported_answer_twice_…` |
| 8 | Empty retrieval | `insufficient_evidence`, 0 LLM calls | `test_answers_api.py::test_nothing_retrieved_means_no_llm_call` |
| 9 | Ingestion fails mid-document | Rolled back; job and document `failed`; resubmit retries | `tests/jobs/test_worker.py::test_failure_mid_document_…`, `::test_failed_document_can_be_resubmitted_…` |
| 10 | Worker dies mid-job (interrupted ingestion) | After `JOB_STALE_AFTER_SECONDS` (1800) requeued; after `JOB_MAX_ATTEMPTS` (3) `failed` + document `failed` | `tests/jobs/test_stale_jobs.py` |
| 11 | Judge provider failure | `answer-judge` exits 1 with a resume hint; judged records kept | `tests/evaluation/test_answer_cli.py::test_a_judge_provider_failure_…` |
| 12 | Database unreachable | `/health` 503 `{database: unreachable}` | `tests/health/test_health.py::test_health_returns_503_…` |

Worst-case latency of one LLM call: 3 attempts × `LLM_TIMEOUT_SECONDS` (20 s) + backoff
(≤ 1.5 s) ≈ 62 s; an answer makes at most 2 calls (≈ 124 s).

## Observability (task 012)

- **Provider.** `app/core/telemetry.configure_telemetry(service)` installs one global
  `TracerProvider`. The API passes it to FastAPI's built-in telemetry, which creates the
  request, dependency, endpoint and serialisation spans; `/v1/health` is excluded. The
  worker installs its own (`evidencedesk-worker`).
- **Exporter.** `TELEMETRY_EXPORTER`:
  - `none` (default): spans exist but are not exported
  - `console`: printed to stdout
  - `otlp`: sent via the standard `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` variables;
    export is batched in the background
- **Our spans:**

  | Span | Attributes |
  |---|---|
  | `search` | mode, rerank, k, chunker, results |
  | `search.<stage>` | one per stage: embed_query, dense, keyword, fuse, rerank. Opened by the same timer that fills `latency_ms`, so the two always agree |
  | `answer` | status, passages, citations, LLM call count |
  | `llm.call` | attempt, model, outcome, token counts, cost; provider errors recorded on the span |
  | `job` | kind, id, attempts, outcome |
- **Privacy.** No span or log carries question, passage, answer or prompt text (tested).
- **Logs.** JSON lines include `trace_id` and `span_id` when written inside a span.
- **Cost.** `generation.costs` turns tokens into USD from `LLM_PRICES` (per model, USD per
  million input/output tokens).
  - `/v1/answers` returns `usage.cost_usd`, which is null for unpriced models.
  - Answer-run headers record the prices in force, and reports show the run's estimated
    generator cost at those prices.

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
  timeout only); failures are classified into transient, quota and configuration errors
  (see Failure scenarios). Empty retrieval short-circuits to `insufficient_evidence`
  without an LLM call. Orphaned jobs are requeued, then failed after `JOB_MAX_ATTEMPTS`.
- **Pagination:** `limit` / `offset` with a max `limit` of 100. Simple is fine here.

## Local topology and delivery (task 013)

```
docker-compose.yml (one image, `Dockerfile`, for migrate / api / worker):
  postgres (pgvector/pgvector:pg16, host :5434)
    -> migrate (alembic upgrade head, once)
      -> api (uvicorn :8000, healthcheck /v1/health)   worker (python -m app.worker)
  jaeger (profile "tracing": UI :16686, OTLP/HTTP :4318)
  volumes: postgres-data, hf-models (Hugging Face cache shared by api and worker)
Groq -> real key from .env, or the generation tests use a fake client
```

- **Image.** Built with uv from `uv.lock` (`--locked --no-dev`, CPU-only torch), then copied
  into a `python:3.12-slim-bookworm` runtime as a non-root user. It holds `app/`,
  `migrations/`, `corpus/` and `eval/{datasets,configs}` (evaluation-run jobs need them),
  but no models: they are downloaded into the `hf-models` volume on first use. `.env`, tests
  and reports are excluded by `.dockerignore`.
- **Migrations** run in their own one-shot service, so API replicas never race on them.
- **Settings** come from `.env` when present; compose overrides `DATABASE_URL` to reach
  `postgres:5432` and gives a dev-only `JWT_SECRET_KEY` fallback.
- **CI** (`.github/workflows/ci.yml`, push and PR): ruff; `alembic upgrade head` +
  `alembic check`; `pytest -q` against a pgvector service; Docker build with the GitHub
  Actions layer cache. Workflows have `contents: read` only and use no secrets.
- **Evaluation gate** (`.github/workflows/eval-gate.yml`, PRs to `main` on
  retrieval-relevant paths, or manual):
  1. Model tests (`pytest -m model`), with the Hugging Face cache restored by `actions/cache`.
  2. A fresh tenant (`create-tenant --password-env`, throwaway password) loads the corpus.
  3. `cli run` of the adopted config (`d2-tokens450`) on **dev**.
  4. `cli gate` (`app/evaluation/gate.py`) against the committed
     `eval/reports/d2-tokens450-dev.json`.
  - **Rule:** fail when nDCG@10, recall@10 or hit@5 (all questions) drops by more than
    0.02. The paired bootstrap CI and per-`query_type` deltas are reported, not gated: same
    code on the same data should reproduce the baseline, and on 70 questions a CI is too wide
    to catch real drops.
  - **Refusals (exit 2):** a test-split record, different configs, datasets or questions,
    or a config without cutoffs 5 and 10.
  - **Changing the baseline** (after adopting a new config) is an explicit change to the
    workflow's `GATE_CONFIG` / `GATE_BASELINE` in the PR.
