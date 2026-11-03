# EvidenceDesk API — Database Schema

PostgreSQL 16 with the `vector` extension, managed **only** through SQLAlchemy models and
Alembic migrations. Raw SQL appears only inside migrations (extension, generated columns,
indexes).

> Status: auth, documents, chunks, jobs and evaluation tables exist (migrations 0001–0005).
> Each table lists the task that created it. Update this file when a migration lands.

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
  is a task-015 option.
  `tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED` + GIN index
  `ix_chunks_tsv` (task 007, migration `0005_chunk_tsv`). Postgres fills it on write; the
  ORM defers it so it is never loaded with a chunk.

`chunker` lets several chunking strategies coexist for Experiment D without re-ingesting the
documents. `chunk.text == documents.content[char_start:char_end]` always holds (tested); the
evaluation uses the offsets to decide whether a chunk overlaps a labelled evidence span.

### jobs (task 003 ✅)
- **jobs**: `id`, `tenant_id FK (indexed)`, `kind VARCHAR(32)` (free text: new kinds are code,
  not migrations), `payload JSONB`, `status (queued|running|succeeded|failed)` CHECK
  `job_status`, `attempts`, `error` (truncated to 2,000 chars), `created_at`, `started_at`,
  `finished_at`. Index `(status, created_at)`.
  The worker claims with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`.

### evaluation (task 006b ✅, migration `0004_evaluation_runs`)
- **evaluation_runs**:
  - Set when the run is queued: `id`, `tenant_id FK RESTRICT`, `created_by FK users RESTRICT`,
    `job_id FK jobs RESTRICT unique`, `dataset_name VARCHAR(64)`, `dataset_sha256`,
    `split (dev|test)` CHECK `dataset_split`, `config JSONB` (the `RunConfig`), `created_at`.
  - Filled by the worker on success (null before that, or if the run failed):
    `effective JSONB`, `git_sha`, `git_dirty`, `environment JSONB`, `corpus_documents`,
    `summary JSONB {metrics, overlap_bands, latency_ms}`, `executed_at`.
  - Index `(tenant_id, created_at)`.
  - **No status column.** Status, error and timings are the job's (`job_id`), so the two
    can't disagree.
- **evaluation_results**: `id`, `run_id FK CASCADE`, `position` (dataset order),
  `question_id`, `query_type`, `question TEXT`, `answerable`, `word_overlap`, `hits JSONB`
  (rank, slug, version, offsets, heading, score, matched items), `scores JSONB` (cutoff →
  P/R/RR/nDCG; null if unanswerable), `latency_ms JSONB`. Index `(run_id, position)`.
  - No tenant column: queries scope results through their run's `tenant_id`.
  - No `answer` column yet: task 009 adds it with its own migration.
- A stored run converts back to the 006a run record (`service.stored_run_report`, tested).

## Benchmark dataset (files, not tables) — format built in task 005a, v1 labelled in 005c

Current dataset: `evidencedesk-v1` (150 reviewed questions, 80 dev / 70 test); provenance,
guidelines and limitations in [eval/datasets/README.md](../eval/datasets/README.md).

Two files per dataset, both versioned in git:

**Source** `eval/datasets/source/<name>.yaml`, written and reviewed by people:

```yaml
questions:
  - id: q-0042                       # q-NNNN, unique
    query_type: exact_identifier
    question: What does use_cache=False change?
    reference_answer: ...
    reviewed: true                   # the builder refuses unreviewed questions
    notes: ...                       # optional: readings, absence searches
    evidence:                        # empty only for unanswerable questions
      - grade: 3                     # 1 related, 2 partially answers, 3 answers
        spans:                       # alternatives: any one satisfies this item
          - {slug: fastapi/dependencies, version: "0.115", quote: "unless `use_cache=False`"}
          - {slug: fastapi/dependencies, version: "0.110", quote: "unless `use_cache=False`"}
```

**Built** `eval/datasets/<name>.jsonl`, produced by `python -m app.evaluation.cli build-dataset`:
line 1 is a header `{format: "evidencedesk-dataset/1", name, seed, dev_fraction, questions}`,
then one question per line with `split`, `answerable` and resolved spans
`{slug, version, char_start, char_end, quote}`, plus `reviewed`, `notes` and `word_overlap`
(share of the question's content words found in its evidence; a drafting-bias measure).
`
` line endings; the file's SHA-256
identifies the dataset in every run.

- `query_type`: `factual | multi_passage | exact_identifier | paraphrase | version_specific | ambiguous | unanswerable`.
- **Quotes, not offsets, are authored.** A quote must occur exactly once in its document; the
  span becomes the enclosing paragraph (text between blank lines) unless `quote_only: true`.
- Labels are **character spans in documents, not chunk ids**, so they survive chunking
  changes. A chunk matches a span when same `(slug, version)` and
  `overlap ≥ 0.5 × min(span length, chunk length)` (`relevance.MIN_OVERLAP_FRACTION`).
- **Evidence items with alternative spans**: Recall@k counts items, and an item is satisfied by
  any of its spans (e.g. the same paragraph in two doc versions).
- `split` is deterministic: `sha256(seed:group)` < dev_fraction (default 0.6) → `dev`. The group is
  the slug of the first evidence span (version-independent); unanswerable questions use their id.
- Corpus bytes are protected from line-ending conversion by `.gitattributes` (`-text`).

## Migration discipline

- One Alembic revision per model change, committed with the change.
- `uv run alembic upgrade head` must work on an empty database.
- `uv run alembic check` must report no pending changes before handover.
