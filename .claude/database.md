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

### documents and chunks (task 003)
- **documents**: `id`, `tenant_id FK`, `source (e.g. fastapi-docs)`, `slug (stable id from the
  corpus manifest)`, `version (e.g. 0.115)`, `title`, `content (text)`, `content_hash (sha256)`,
  `status (pending|ingested|failed)`, `created_at`, `updated_at`.
  Unique `(tenant_id, slug, version)`; unique `(tenant_id, content_hash)` makes re-ingest idempotent.
- **chunks**: `id`, `document_id FK CASCADE`, `tenant_id`, `chunker (e.g. tokens-400-overlap-50)`,
  `ordinal`, `text`, `char_start`, `char_end`, `heading_path (e.g. "Tutorial > Dependencies")`,
  `embedding vector(384)`, `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`,
  `metadata JSONB`.
  Indexes: `(tenant_id, chunker)`, GIN on `tsv`, HNSW on `embedding vector_cosine_ops`.

`chunker` lets several chunking strategies coexist for Experiment D without re-ingesting the
documents. `char_start` / `char_end` are offsets into `documents.content`; the evaluation
uses them to decide whether a chunk overlaps a labelled evidence span.

### jobs (task 003)
- **jobs**: `id`, `tenant_id FK`, `kind (ingest|evaluate)`, `payload JSONB`,
  `status (queued|running|succeeded|failed)`, `attempts`, `error`, `created_at`,
  `started_at`, `finished_at`. Index `(status, created_at)`.
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
