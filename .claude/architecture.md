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
| Embeddings | `sentence-transformers`, `BAAI/bge-small-en-v1.5` (384 dims) | Small, local, reproducible |
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
  ingestion/            parsing, chunking, embedding, idempotent ingest pipeline
  retrieval/            dense search, keyword search, RRF fusion, reranker, retrieval config
  generation/           prompt loading, LLM client, citation validation, abstention
  evaluation/           dataset loader, IR metrics, run orchestration, reports
  jobs/                 job model + repository (shared by ingestion and evaluation)
migrations/             Alembic
corpus/                 Versioned source documents + manifest.yaml
eval/datasets/          Labelled benchmark (JSONL), dev and test splits
eval/reports/           Generated experiment reports (Markdown + JSON)
tests/                  Mirrors app/ (tests/retrieval/test_fusion.py, ...)
```

There is no `common` or `utils` package. Shared code lives in `app/core/`.

## Request flows

**Search** (`POST /v1/search`): normalise query → dense top-N (pgvector, cosine) and keyword
top-N (FTS), both filtered by `tenant_id` → RRF fusion → optional cross-encoder rerank →
return top-k passages with per-stage scores.

**Answer** (`POST /v1/answers`): run search → select context within a token budget → LLM
call with structured output `{answer, cited_chunk_ids, status}` → **server-side citation
check** (every cited ID must be in the supplied context, else `status = insufficient_evidence`
or a 502 `LLM_INVALID_OUTPUT` after one retry) → response with citations.

**Ingest** (`POST /v1/documents/ingest`): store the document (dedupe by `content_hash`) →
enqueue an `ingest` job → worker chunks, embeds and writes chunks in one transaction.
Re-ingesting the same content is a no-op (idempotent).

**Evaluation** (`POST /v1/evaluations/runs`): enqueue an `evaluate` job with a retrieval
config and a dataset split → worker runs every query, scores it, stores per-query results and
aggregate metrics → `GET /v1/evaluations/runs/{id}` returns them.

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
