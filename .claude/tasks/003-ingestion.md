# Task 003 — Documents, jobs, worker and the ingestion pipeline

**Status:** ✅ Done (2026-10-28); 70 tests + 2 opt-in model tests passed, ruff clean
**Week:** W1 · **Modules:** `app/documents`, `app/jobs`, `app/ingestion`, `app/worker.py` ·
**Branch:** `task/003-ingestion`

## Goal

An editor can submit a document. A background worker splits it into chunks that keep exact
character offsets into the original text, embeds each chunk locally, and stores the result
in pgvector. Submitting the same document again does nothing new, and no tenant can see
another tenant's documents or jobs.

After this task, task 004 only has to add a query path; everything it searches over exists.

## Scope

In:
- Tables `documents`, `chunks`, `jobs` (migration `0003`).
- `POST /v1/documents/ingest`, `GET /v1/documents`, `GET /v1/documents/{id}`, `GET /v1/jobs/{id}`.
- Job queue on Postgres (`FOR UPDATE SKIP LOCKED`) and a worker process: `uv run python -m app.worker`
  (`--once` drains the queue and exits).
- Markdown-aware word-window chunker that records `char_start`, `char_end` and `heading_path`.
- `Embedder` protocol with a sentence-transformers implementation (`BAAI/bge-small-en-v1.5`,
  384 dims) and a deterministic fake for tests.
- Idempotent ingestion at two levels: the API (same document → same ids, no new job) and the
  worker (re-running a job replaces chunks instead of duplicating them).
- Corpus loader CLI: `uv run python -m app.ingestion.cli load-corpus --tenant <name> --manifest corpus/manifest.yaml [--process]`,
  tested against a small fixture corpus in `tests/fixtures/corpus/`.

Out:
- **The real corpus content** (FastAPI / PostgreSQL / Python docs, synthetic incidents). It
  moves to task 005, because evidence labels point at character spans and the corpus must be
  frozen and labelled together. Recorded in [tasks.md](../tasks.md).
- Vector index (HNSW) → task 004, where the query that needs it is added.
- `tsvector` column + GIN index → task 007 (keyword search).
- Automatic job retries, stuck-job recovery, ingestion timeouts → task 011 (reliability).
- Other chunking strategies → task 010 (Experiment D).
- Document deletion or update endpoints.

## Assumptions

1. A `(slug, version)` pair is **immutable** within a tenant. New content means a new
   version. That keeps evidence labels (character spans) valid for ever.
2. Documents are UTF-8 Markdown or plain text up to 1,000,000 characters. No PDF/HTML parsing.
3. Embedding on CPU is fast enough: the planned corpus is a few hundred documents.
4. The first worker run downloads the embedding model (~130 MB) into the Hugging Face cache;
   later runs work offline.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Idempotency key | `(tenant_id, slug, version)` + `content_hash` (SHA-256) | Same slug + version + same hash → 200 with existing ids. Same slug + version + **different** hash → 409 (versions are immutable). **Deviation from database.md:** drop the planned unique `(tenant_id, content_hash)`, because an unchanged page in two doc versions has identical content and must be allowed twice |
| Re-ingesting a failed document | Same payload for a `failed` document enqueues a new job (202) | Gives a manual retry path until task 011 adds automatic retries |
| Chunk boundaries | Split into sections at Markdown headings (ignoring `#` inside code fences), then sliding windows of 250 words with 40 words overlap inside each section | Headings are natural topic boundaries. Word windows need no tokenizer and are deterministic |
| Why 250 words | ≈ 330 BERT tokens, under bge-small's 512-token limit, so no chunk is silently truncated by the model | A test asserts the limit with the real tokenizer (model-marked test). Experiment D tunes it |
| Offsets | A chunk's text is always `content[char_start:char_end]`, an exact slice | Evidence labels (task 005) are character spans; overlap with chunks must be exact |
| `chunker` column | Each chunk stores its chunker name, e.g. `words-250-overlap-40` | Several chunkings of the same document can coexist for Experiment D |
| `embedding_model` column | Each chunk stores the model name | Detects mixed-model vectors after a model change, instead of silently comparing incompatible vectors |
| Chunker abstraction | One `WordWindowChunker` dataclass with parameters, no protocol | Only one implementation exists. A protocol is added in task 010 if a structurally different chunker appears |
| Embedder abstraction | `Embedder` protocol: `model_name`, `dimension`, `embed_documents(texts)` | Two implementations now (real + test fake), and tests must not download a model. `embed_query` is added in task 004, where it is first needed |
| Model loading | Real model loaded once per worker process (lazy, cached) | Loading takes seconds. The API process never loads it in this task |
| Job queue | `jobs` table, worker claims with `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` | Several workers can run without double-processing; no Redis/Celery |
| Job handlers | `HANDLERS = {"ingest": …}` dict in the worker; task 006 adds `"evaluate"` | New job kinds are added, not branched in (OCP) |
| Transactions in the worker | (1) claim + mark `running`, commit; (2) process, commit; (3) on failure roll back, then mark `failed` with the error in a new transaction | A failed job never leaves half-written chunks, and the failure is always recorded |
| Processing idempotency | Delete existing chunks for `(document_id, chunker)` before inserting, in the same transaction | Re-running a job, or a retry in task 011, never duplicates chunks |
| torch wheels | `torch` pinned to the PyTorch CPU index via `[tool.uv.sources]` | Avoids multi-GB CUDA wheels on Linux (Docker, CI). Windows PyPI wheels are CPU-only anyway |
| Corpus loader | Calls `documents.service.ingest_document` directly (no HTTP, no token) for a tenant looked up by name; `--process` then runs the worker once | Same code path as the endpoint (DRY). Runs as an operator tool, like the tenant CLI |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `documents` owns document records and the ingest request; `jobs` owns the queue; `ingestion/chunking.py` only splits text; `ingestion/embedding.py` only turns text into vectors; `ingestion/pipeline.py` only orchestrates chunk → embed → store for one document; `worker.py` only claims jobs and dispatches them |
| OCP | New job kinds register in `HANDLERS`; new embedders implement the protocol; new chunker settings are new parameter values |
| LSP | `FakeEmbedder` returns the same shape (unit-length, 384 floats, one per input, same order) as the real one, so pipeline tests stay valid |
| ISP | `Embedder` has one method and two attributes. The pipeline takes an `Embedder` and a chunker, not a settings object |
| DIP | `pipeline.process_document(session, document, chunker, embedder)` receives its collaborators. The worker builds the real embedder; tests pass the fake. Nothing outside `embedding.py` imports `sentence_transformers` |
| DRY | One `ingest_document` service used by the endpoint and the loader. Tenant filters live only in repository functions |
| Flat control flow | Ingest service: guard clauses for "exists and identical", "exists and different", "exists and failed", then the create path |
| Error handling | The worker's top-level `except Exception` is one of the two allowed places: it logs with `logger.exception`, rolls back, and records the error (truncated to 2,000 chars). The loader catches only `FileNotFoundError`, `yaml.YAMLError` and `ValidationError` |

### Dependencies added (and why)
- `pgvector` — SQLAlchemy `Vector` column type.
- `sentence-transformers` — local embedding model (pulls in `torch` and `transformers`).
- `torch` — declared explicitly only so it can be pinned to the CPU index.
- `pyyaml` — parse `corpus/manifest.yaml`. Already installed transitively; declared because we import it.

## Data model (migration `0003_documents_chunks_jobs`)

- **documents**: `id`, `tenant_id FK (indexed)`, `source VARCHAR(100)`, `slug VARCHAR(200)`,
  `version VARCHAR(50)`, `title VARCHAR(300)`, `content TEXT`, `content_hash CHAR(64)`,
  `metadata JSONB DEFAULT '{}'`, `status VARCHAR(16) CHECK (pending|ingested|failed)`,
  `created_at`, `updated_at`. Unique `(tenant_id, slug, version)`.
- **chunks**: `id`, `document_id FK CASCADE`, `tenant_id` (denormalised, indexed with
  `chunker`), `chunker VARCHAR(50)`, `ordinal INT`, `text TEXT`, `char_start INT`,
  `char_end INT`, `heading_path VARCHAR(500)`, `embedding vector(384)`,
  `embedding_model VARCHAR(100)`. Unique `(document_id, chunker, ordinal)`.
  CHECK `char_start >= 0 AND char_end > char_start`.
- **jobs**: `id`, `tenant_id FK (indexed)`, `kind VARCHAR(32)`, `payload JSONB`,
  `status VARCHAR(16) CHECK (queued|running|succeeded|failed)`, `attempts INT DEFAULT 0`,
  `error TEXT NULL`, `created_at`, `started_at NULL`, `finished_at NULL`.
  Index `(status, created_at)` for the claim query.

## API

| Method | Path | Roles | Request | Response |
|---|---|---|---|---|
| POST | `/v1/documents/ingest` | editor | `{source, slug, version, title, content, metadata?}` | `202 {document_id, job_id, status}` new or retried; `200` same body if already ingested or in progress; `409 CONFLICT` same slug + version, different content |
| GET | `/v1/documents` | viewer | `?source=&version=&limit=20&offset=0` (limit ≤ 100) | `200 {items: [{id, source, slug, version, title, status, created_at}], total, limit, offset}` |
| GET | `/v1/documents/{id}` | viewer | — | `200 {…list fields, content_hash, metadata, chunk_count}`; `404` missing or other tenant |
| GET | `/v1/jobs/{id}` | viewer | — | `200 {id, kind, status, attempts, error, created_at, started_at, finished_at}`; `404` missing or other tenant |

Validation: `slug` matches `^[a-z0-9][a-z0-9/_.-]{0,199}$`; `content` 1–1,000,000 characters
and not only whitespace; `metadata` is a flat object of string/number/boolean values, at most
20 keys. `content` is never returned by list endpoints.

## Files to create / modify

```
pyproject.toml, uv.lock               + pgvector, sentence-transformers, torch (CPU index), pyyaml
                                      pytest marker "model", deselected by default
.env.example                          + EMBEDDING_MODEL_NAME, WORKER_POLL_SECONDS
app/core/config.py                    + embedding_model_name, embedding_batch_size, worker_poll_seconds
app/core/errors.py                    + NotFoundError
app/documents/{__init__,models,schemas,repository,service,router}.py
app/jobs/{__init__,models,schemas,repository,router}.py
app/ingestion/__init__.py
app/ingestion/chunking.py             Chunk dataclass, WordWindowChunker
app/ingestion/embedding.py            Embedder protocol, SentenceTransformerEmbedder
app/ingestion/pipeline.py             process_document, run_ingest_job
app/ingestion/cli.py                  load-corpus command
app/worker.py                         claim → dispatch → record loop, --once, graceful stop
app/main.py                           include documents + jobs routers
migrations/env.py                     import new models
migrations/versions/0003_documents_chunks_jobs.py
tests/conftest.py                     + make_document fixture, FakeEmbedder
tests/fixtures/corpus/manifest.yaml + 2 small .md files
tests/ingestion/test_chunking.py
tests/ingestion/test_pipeline.py
tests/ingestion/test_embedding_model.py   (marked "model": real model, opt-in)
tests/ingestion/test_corpus_loader.py
tests/documents/test_ingest_api.py
tests/documents/test_documents_read_api.py
tests/jobs/test_worker.py
.claude/{api-spec,database,architecture,tasks}.md   at handover
```

## Step-by-step implementation plan

0. `git switch -c task/003-ingestion` from `task/002-auth`.
1. Dependencies (torch from the CPU index), settings, `.env.example`, pytest `model` marker.
2. `chunking.py` + unit tests (pure Python, no DB).
3. `embedding.py`: protocol, real implementation, `FakeEmbedder` in the tests; model-marked test
   for dimension, normalisation and the 512-token limit.
4. Models for `documents`, `chunks`, `jobs`; migration `0003`; upgrade/downgrade/upgrade; `alembic check`.
5. `jobs` repository (enqueue, claim_next, mark_succeeded, mark_failed, get_job_in_tenant).
6. `documents` repository + `ingest_document` service with the idempotency rules.
7. `pipeline.py` (`process_document`, `run_ingest_job`) + tests with the fake embedder.
8. `worker.py` (`HANDLERS`, loop, `--once`, SIGINT/SIGTERM finish-current-job) + tests,
   including the concurrent-claim test.
9. Schemas + routers for documents and jobs; register in `main.py`; API tests incl. cross-tenant.
10. `ingestion/cli.py` loader + fixture corpus + tests.
11. Manual check on the dev DB with the real model: create a tenant, load the fixture corpus
    with `--process`, inspect chunk counts and offsets; clean up.
12. `ruff`, full test run, model-marked test run once, docs and handover.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Offsets drift (breaks every evaluation later) | For every chunk of several documents: `content[char_start:char_end] == text` |
| Code blocks misread as headings | `# comment` inside a fenced block does not start a new section |
| Over-long chunks truncated by the model | No chunk exceeds 250 words; (model-marked) no chunk exceeds 512 tokens |
| Overlap wrong | Consecutive windows share exactly 40 words; last window reaches the section end |
| Duplicate ingestion | Same payload twice → same ids, one job. Same slug + version, new content → 409. Failed document resubmitted → new job |
| Duplicate chunks | Running the same job twice leaves one set of chunks |
| Partial writes | Embedder raising mid-document → no chunks stored, document `failed`, job `failed` with error |
| Double processing | Two connections claim concurrently → each gets a different job; a locked job is skipped |
| **Cross-tenant** | Tenant B lists no documents of A; `GET /documents/{id}` and `GET /jobs/{id}` of A → 404 for B; the worker writes chunks with the document's own `tenant_id` |
| Privilege | Viewer → 403 on ingest; viewer can read |
| Loader | Loads fixture manifest; second run is a no-op; missing file → clear error, non-zero exit |

## Edge cases and security

- Large bodies: `content` capped at 1,000,000 characters by the schema.
- A section with only a heading and no body produces no chunk; a document whose text is all
  headings fails with a clear error instead of producing zero chunks silently.
- Text before the first heading gets an empty `heading_path`.
- `tenant_id` for documents, chunks and jobs always comes from the caller or from the job
  row, never from the request body (`extra="forbid"` on the ingest schema).
- Job error messages are stored truncated and are visible only to the owning tenant.
- The model name comes from settings; no remote code (`trust_remote_code=False`).

## Risks

- **torch install size and time** (~200 MB+ CPU wheel). Mitigation: CPU index; one-time cost;
  `uv sync` cache.
- **First run needs network** to download the model. Mitigation: documented; tests never need it
  (fake embedder; the real-model test is opt-in with `-m model`).
- **Windows-specific torch / tokenizer issues.** Mitigation: try the model-marked test early (step 3)
  before building on it.
- **Fixed `vector(384)` column.** Changing to a model with another dimension needs a
  migration. Accepted: `embedding_model` makes the mismatch visible, and model comparison is
  not a planned experiment.

## Future improvements

- Automatic retries with backoff, stuck-`running` job recovery, per-job timeout (task 011).
- HNSW index (004) and `tsvector` + GIN (007).
- Alternative chunkers, e.g. token-based or Markdown-structure-only (task 010).
- Document deletion / re-versioning endpoints if the dashboard needs them.

## Checklist

- [x] Branch `task/003-ingestion`
- [x] Dependencies (torch CPU index), settings, `.env.example`, `model` marker
- [x] Chunker + tests
- [x] Embedder protocol, real implementation, fake; model-marked test run once
- [x] Models + migration `0003` (upgrade/downgrade verified, `alembic check` clean)
- [x] Jobs repository; documents repository + `ingest_document` service
- [x] Pipeline + tests
- [x] Worker (`HANDLERS`, `--once`, graceful stop) + concurrency test
- [x] Documents and jobs routers + API tests incl. cross-tenant
- [x] Corpus loader CLI + fixture corpus + tests
- [x] Manual run on dev DB with the real model; cleaned up
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Self-review against the design-principles table
- [x] Update [api-spec.md](../api-spec.md), [database.md](../database.md), [architecture.md](../architecture.md), [tasks.md](../tasks.md), handover below

---

## Handover

### Summary
Editors submit documents with `POST /v1/documents/ingest`. Resubmitting the same document is
idempotent, and changing the content of an existing slug + version is a 409. A Postgres-backed
job queue and worker (`python -m app.worker [--once]`) split each document into Markdown-aware
token windows with exact character offsets, embed them with `bge-small-en-v1.5` on CPU, and
replace the document's chunks in one transaction. Documents and jobs can be read back, scoped
to the caller's tenant. A corpus loader ingests a `manifest.yaml`. 70 tests pass (28 new),
plus 2 opt-in tests against the real model.

### Architecture Notes
- **Chunk text is always `content[char_start:char_end]`**, checked in unit tests, in the
  real-model test and on the dev DB. This is what the task-005 span labels rely on.
- **The worker uses three transactions:** claim (commit) → run (handler commits) → on any
  exception roll back, call the handler's `on_failure` hook (marks the document `failed`),
  record the job error, commit. `JobHandler(run, on_failure)` keeps the worker unaware of
  documents; task 006 adds `evaluate` to `build_handlers`.
- **`SKIP LOCKED` claiming** is tested with three real connections: two get different jobs,
  the third gets none.
- **Idempotency** is `(tenant, slug, version)` plus a content-hash comparison. A concurrent
  duplicate request that hits the unique constraint rolls back and is treated as a resubmit.
- **Model gateways are separate from protocols:** `embedding.Embedder` and
  `chunking.Tokenizer` are protocols; `local_models.py` holds the real implementations and is
  the only module importing torch. The worker and loader import it lazily.
- **`string_enum()` helper** in `app/core/db.py` (separate refactor commit) keeps every status
  column as VARCHAR + CHECK.
- **`GET /v1/jobs/{id}` has no service layer**: it is a single tenant-scoped read with no
  rules, so the router calls the repository and raises `NotFoundError` itself.

### Deviations from the plan
- **Token windows instead of word windows (approved during implementation).** The real-model
  test showed 250-word windows of Python source reach about 1,000 tokens (85% of chunks over
  the 512 limit), so the model would silently truncate them. The chunker now measures windows
  with the model's tokenizer (`TokenWindowChunker`, `tokens-300-overlap-50`), takes the
  tokenizer as a dependency, and tests use a whitespace tokenizer fake. The worst-case file
  (`fastapi/routing.py`) now stays within the limit.
- **Embedder and tokenizer implementations moved to `app/ingestion/local_models.py`.**
  Importing sentence-transformers takes about 40 s on this machine; with it imported at
  collection time the test suite took 44 s instead of 4 s.
- **`tests/fakes.py`** holds `FakeEmbedder` and `WhitespaceTokenizer` instead of conftest.
- **No `make_document` fixture.** Tests call the real `ingest_document` service through an
  `ingest_request()` helper, which also exercises the idempotency code.
- **`auth.repository.get_tenant_by_name`** added for the loader.
- **Not manually verified:** the worker's SIGINT/SIGTERM graceful stop (the `--once` path of
  the same loop was exercised).

### Database Changes
- `0003_documents_chunks_jobs`: `documents`, `chunks` (with `vector(384)`), `jobs`. No unique
  `(tenant_id, content_hash)`; see database.md. Upgrade → downgrade → upgrade verified;
  `alembic check` clean.

### API Changes
- `POST /v1/documents/ingest`, `GET /v1/documents`, `GET /v1/documents/{id}`,
  `GET /v1/jobs/{id}` (details in api-spec.md).

### Evaluation Results
None. Manual run on the dev DB with the real model: 2 fixture documents → 4 chunks, every
offset exact, every vector unit length, both jobs succeeded, second load reported
"0 queued, 2 already present". Rows deleted afterwards.

### Future Work
- Snap window starts to word boundaries, so a chunk never begins mid-word (cosmetic, for
  citations). With 300 of 512 tokens used, re-tokenizing a slice can't overflow.
- **Line endings must be pinned for corpus files (task 005).** Git on this machine converts
  LF to CRLF on checkout (`core.autocrlf`), which would shift every character offset in a
  labelled document. Task 005 should add `corpus/** -text` (and the same for
  `tests/fixtures/corpus/**`) to `.gitattributes` so corpus bytes never change.
- Automatic retries, stuck-`running` job recovery and ingestion timeouts (task 011).
- Fair scheduling across tenants (today the queue is global FIFO).
- HNSW index (004), `tsvector` + GIN (007), other chunkers (010).

### Modified Files
| File | Why |
|---|---|
| `pyproject.toml`, `uv.lock` | `pgvector`, `sentence-transformers`, `torch` (CPU index), `pyyaml`; `model` marker |
| `.env.example` | Embedding model and worker poll settings |
| `app/core/config.py` | Same settings |
| `app/core/db.py`, `app/auth/models.py` | `string_enum` helper (refactor commit) |
| `app/core/errors.py` | `NotFoundError` |
| `app/auth/repository.py` | `get_tenant_by_name` for the loader |
| `app/documents/*` | Models, schemas, repository, service, router |
| `app/jobs/*` | Model, repository, schema, router |
| `app/ingestion/{chunking,embedding,local_models,pipeline,cli}.py` | Ingestion pipeline and loader |
| `app/worker.py` | Job worker |
| `app/main.py` | Register documents and jobs routers |
| `migrations/env.py`, `migrations/versions/0003_documents_chunks_jobs.py` | Migration |
| `tests/conftest.py`, `tests/fakes.py`, `tests/fixtures/corpus/*` | Helpers, fakes, fixture corpus |
| `tests/ingestion/*`, `tests/jobs/*`, `tests/documents/*` | Tests |
| `README.md`, `.claude/*.md` | Docs in step with the code |
