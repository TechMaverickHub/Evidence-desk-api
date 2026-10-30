# EvidenceDesk API — Database Schema

PostgreSQL 16 with the `vector` extension, managed **only** through SQLAlchemy models and
Alembic migrations. Raw SQL appears only inside migrations (extension, generated columns,
indexes).

> Status: **planned**. Each table lists the task that creates it. Update this file when a
> migration lands.

## Conventions

- **PKs:** `UUID` (`uuid4`, generated in Python).
- **Timestamps:** `TIMESTAMPTZ` (set once in `Base.type_annotation_map`). `created_at` has
  server default `now()`, plus `updated_at` where rows change.
- **Tenant column:** every tenant-owned table has `tenant_id UUID NOT NULL FK tenants`, indexed.
  `chunks.tenant_id` is denormalised from its document so retrieval filters without a join.
- **Enums:** stored as `VARCHAR` with a `CHECK` constraint (easier to migrate than PG enums).
- **Deletes:** `chunks` cascade from `documents`; everything else is `RESTRICT`.

## Tables

### auth (task 002 ✅, migration `0002_auth_tables`)
- **tenants**: `id`, `name VARCHAR(100) unique`, `created_at`.
- **users**: `id`, `tenant_id FK RESTRICT (indexed)`, `email VARCHAR(254) unique, stored lower-case`,
  `password_hash (argon2id)`, `role VARCHAR(16) CHECK user_role (admin|editor|viewer)`,
  `is_active (default true)`, `created_at`.
- Exception to the tenant-filter rule: `get_user_by_email` (login) searches all tenants,
  because emails are globally unique and the tenant is not known before login.

### documents and chunks (task 003 ✅, migration `0003_documents_chunks_jobs`)
- **documents**: `id`, `tenant_id FK (indexed)`, `source VARCHAR(100)`, `slug VARCHAR(200)`,
  `version VARCHAR(50)`, `title VARCHAR(300)`, `content TEXT`, `content_hash (sha256 hex)`,
  `metadata JSONB DEFAULT '{}'` (ORM attribute `doc_metadata`; `metadata` is reserved by
  SQLAlchemy), `status (pending|ingested|failed)` CHECK `document_status`, `created_at`,
  `updated_at`. Unique `(tenant_id, slug, version)`.
  There is **no** unique `(tenant_id, content_hash)`: an unchanged page in two doc versions has
  identical content and must be stored twice. Idempotency is `(slug, version)` + hash comparison.
- **chunks**: `id`, `document_id FK CASCADE`, `tenant_id FK` (copied from the document),
  `chunker (e.g. tokens-300-overlap-50)`, `ordinal`, `text`, `char_start`, `char_end`,
  `heading_path (e.g. "Tutorial > Dependencies")`, `embedding vector(384)`,
  `embedding_model (e.g. BAAI/bge-small-en-v1.5)`.
  Unique `(document_id, chunker, ordinal)`; CHECK `char_start >= 0 AND char_end > char_start`;
  index `(tenant_id, chunker)`.
  No vector index by design (exact search, see architecture.md and task 004); an HNSW index
  is a task-015 option. Planned: `tsv` generated column + GIN (task 007).

`chunker` lets several chunking strategies coexist for Experiment D without re-ingesting the
documents. `chunk.text == documents.content[char_start:char_end]` always holds (tested); the
evaluation uses the offsets to decide whether a chunk overlaps a labelled evidence span.

### jobs (task 003 ✅)
- **jobs**: `id`, `tenant_id FK (indexed)`, `kind VARCHAR(32)` (free text: new kinds are code,
  not migrations), `payload JSONB`, `status (queued|running|succeeded|failed)` CHECK
  `job_status`, `attempts`, `error` (truncated to 2,000 chars), `created_at`, `started_at`,
  `finished_at`. Index `(status, created_at)`.
  The worker claims with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`.

### evaluation (task 006)
- **evaluation_runs**: `id`, `tenant_id FK`, `created_by FK users`, `dataset_name`,
  `dataset_sha256`, `split (dev|test)`, `config JSONB (retriever, k, chunker, rerank, models)`,
  `git_sha`, `status`, `metrics JSONB (aggregate + per query_type)`, `created_at`, `finished_at`.
- **evaluation_results**: `id`, `run_id FK CASCADE`, `query_id`, `query_type`,
  `retrieved JSONB (chunk ids, ranks, scores)`, `metrics JSONB`, `latency_ms`,
  `answer JSONB NULL` (filled by answer-level evaluation, task 009).

## Benchmark dataset (files, not tables)

`eval/datasets/<name>.jsonl`, one query per line, versioned in git:

```json
{"id": "q-0042", "split": "dev", "query_type": "exact_identifier",
 "question": "What does Depends(use_cache=False) change?",
 "answerable": true,
 "reference_answer": "...",
 "evidence": [{"slug": "fastapi/dependencies", "version": "0.115",
               "char_start": 1820, "char_end": 2210, "grade": 3}]}
```

- `query_type`: `factual | multi_passage | exact_identifier | paraphrase | version_specific | ambiguous | unanswerable`.
- `grade`: 0–3 graded relevance (used by nDCG). Unanswerable queries have `evidence: []`.
- Labels point at **character spans in documents, not chunk IDs**, so they survive changes
  to chunk size and overlap. A retrieved chunk counts as relevant if it overlaps a span; its
  grade is the highest overlapping span's grade.
- `split` is assigned per **source document group**, so near-duplicate questions about the
  same passage never land in both dev and test.

## Migration discipline

- One Alembic revision per model change, committed with the change.
- `uv run alembic upgrade head` must work on an empty database.
- `uv run alembic check` must report no pending changes before handover.
