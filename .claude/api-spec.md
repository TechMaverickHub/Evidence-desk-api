# EvidenceDesk API — Endpoint Index

A compact index. The machine contract is the live OpenAPI schema at `/openapi.json`
(Swagger UI at `/docs`). Update both when an endpoint changes.

Every path is under `/v1/`. "Tenant" means the caller's tenant from the JWT; objects of other
tenants return **404**. Status column: the task that builds the endpoint.

## health
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| GET | `health` | public | `{status: ok\|degraded, database: ok\|unreachable}`; 503 with the same body (not the error envelope) if the DB is unreachable | 001 ✅ |

## auth — `app/auth`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `auth/token` | public | OAuth2 password form (`username` = email). Returns `{access_token, token_type: "bearer", expires_in}` (seconds; 60 min default). Same 401 `INVALID_CREDENTIALS` for unknown email, wrong password and inactive user | 002 ✅ |
| GET | `auth/me` | any | `{id, email, role, tenant: {id, name}}` | 002 ✅ |
| POST | `auth/users` | admin | `{email, password (12–128), role}` → 201 `{id, email, role, tenant_id}`. Tenant is always the admin's; a body `tenant_id` is a 422. Duplicate email (any case) → 409 | 002 ✅ |

Tenants and the first admin are created by a CLI command (`uv run python -m app.auth.cli create-tenant --name <name> --admin-email <email>`, password prompted), not over HTTP.

A 401 always carries `WWW-Authenticate: Bearer`. Tenant and role are re-read from the database on every request, so deactivation takes effect immediately.

## documents — `app/documents`, `app/ingestion`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `documents/ingest` | editor | `{source, slug (^[a-z0-9][a-z0-9/_.-]{0,199}$), version, title, content (≤ 1,000,000 chars, not blank), metadata? (flat, ≤ 20 keys)}`. 202 + `{document_id, job_id, status}` when a job is queued (new, or retry of a failed document). 200 with the existing ids if already submitted. 409 if the slug + version exists with different content | 003 ✅ |
| GET | `documents` | viewer | `{items: [{id, source, slug, version, title, status, created_at}], total, limit, offset}`; filters `source`, `version`; `limit` 1–100 (default 20). Content is never listed | 003 ✅ |
| GET | `documents/{id}` | viewer | List fields + `content_hash`, `metadata`, `chunk_count` | 003 ✅ |
| GET | `jobs/{id}` | viewer | `{id, kind, status, attempts, error, created_at, started_at, finished_at}` | 003 ✅ |

## search — `app/retrieval`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `search` | viewer | `{query, k=10, mode: dense\|keyword\|hybrid, rerank=false, filters?: {source, version}}`. Returns ranked passages with `chunk_id`, `document`, `text`, `score` and per-stage diagnostics (`dense_rank`, `keyword_rank`, `rerank_score`, `latency_ms` per stage) | 004 ✅ (dense), 007 ✅ (keyword, hybrid), 008 ✅ (rerank) |

**As built in task 004:** request `{query (1–1,000 chars, not blank), k (1–50, default 10), mode: "dense", filters?: {source?, version?}}`, `extra="forbid"` on both. Response `{results: [{rank, chunk_id, score (cosine similarity), text, char_start, char_end, heading_path, document: {id, source, slug, version, title}}], diagnostics: {mode, k, chunker, embedding_model, query_instruction, latency_ms: {embed_query, retrieve, total}}}`. No matches → `results: []`. Only chunks of the configured chunker and the embedder's model are searched.

**Task 007 changes:**
- `mode` accepts `dense` (default), `keyword` or `hybrid`.
- Each result adds `dense_rank` and `keyword_rank` (null when absent from that list).
  `score` means cosine similarity (dense), `ts_rank_cd` (keyword) or the RRF score
  (hybrid).
- `diagnostics.latency_ms` stages are now `embed_query`, `dense`, `keyword`, `fuse` and
  `total`, as used by the mode. **Breaking rename:** `retrieve` is now `dense`. There
  was no consumer yet.

**Task 008 changes:**
- The request takes `rerank: bool = false`. When true, the top 50 candidates of the
  chosen mode are re-scored by the cross-encoder and cut to k.
- Results add `rerank_score` (raw model output) and `first_stage_rank`, both null unless
  reranked. `score` is the rerank score when reranked.
- `diagnostics` adds `reranker_model` (null unless reranked), and `latency_ms` adds
  `rerank`.
- The first rerank request loads the model (seconds) unless `PRELOAD_RERANKER=true`.
  Reranking costs about 1.8 s per 20 candidates on the dev machine's CPU.

## answers — `app/generation`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `answers` | viewer | `{question (1–1,000 chars), retrieval?: {mode=dense, rerank=true, filters?}}`, `extra="forbid"`. Returns `{status: answered\|insufficient_evidence, answer, citations: [{chunk_id, document, heading_path, char_start, char_end, snippet}], retrieval: {mode, rerank, context_chunk_ids}, usage: {model, prompt_tokens, completion_tokens, llm_calls}, latency_ms: {retrieval, llm, total}}`. 502 `LLM_INVALID_OUTPUT` (invalid output after one retry); 503 `LLM_UNAVAILABLE` (provider failure, or no `GROQ_API_KEY`) | 009a ✅ |

**Data sent to the LLM provider:** the question and up to `ANSWER_CONTEXT_CHUNKS` (5)
retrieved passages go to Groq. That is fine for public documentation. A tenant with
private documents would be sending them to a third party.

**Guarantees:**
- Every returned citation is one of the passages sent.
- `answered` always has at least one citation.
- Unsupported or malformed model output is never returned.
- With no retrieved passages, there is no LLM call.

## evaluations — `app/evaluation`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `evaluations/runs` | admin | `{dataset (^[a-z0-9][a-z0-9-]{0,63}$, a file in EVAL_DATASETS_DIR), split: dev\|test, config: RunConfig {name, retriever: dense, depth 1–50, cutoffs, query_instruction?}, allow_test=false}`, `extra="forbid"`. 202 + `{run_id, job_id}`. 422 for an unknown dataset (`field_errors.dataset`), a split with no questions, or `split: test` without `allow_test: true` | 006b ✅ |
| GET | `evaluations/runs` | viewer | `{items: [{id, job_id, status, dataset_name, split, config_name, created_at, finished_at, overall}], total, limit, offset}`, newest first; filters `dataset`, `split`; `limit` 1–100. `overall` = the `all` metrics row at the largest cutoff, null until succeeded | 006b ✅ |
| GET | `evaluations/runs/{id}` | viewer | `{id, job_id, created_by, created_at, run: {status, error, started_at, finished_at}, dataset: {name, sha256, split}, config, executed_at, effective, git: {sha, dirty}, environment, corpus_documents, summary: {metrics, overlap_bands, latency_ms}, results}`. Provenance and `summary` are null until the run succeeds. `results` (per-question hits and scores) only with `?include=results` | 006b ✅ |

A run evaluates the caller's tenant, which must hold the corpus in `EVAL_CORPUS_MANIFEST`. If it doesn't, the job fails with the corpus check's error, visible in `run.error`. Runs are executed by the worker (`evaluate` job). The status comes from the job, so `GET jobs/{job_id}` works too.

Evaluations also run from the CLI (task 006a), which is how committed reports are produced:
`uv run python -m app.evaluation.cli run --config eval/configs/dense-baseline.yaml --dataset eval/datasets/evidencedesk-v1.jsonl --split dev --tenant eval-corpus-v1` (`--split test` also needs `--allow-test`), and
`uv run python -m app.evaluation.cli compare <base.json> <candidate.json>`. Reports are written to `eval/reports/`.

## Error envelope

Every non-2xx response:

```json
{"error_code": "DOCUMENT_NOT_FOUND", "message": "Document not found.", "field_errors": {"k": ["must be <= 50"]}}
```

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body / query fails validation, or a value fails a server-side check such as an unknown dataset (`field_errors` set; `InvalidInputError`) |
| `NOT_AUTHENTICATED` | 401 | Missing, invalid or expired token |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password at `auth/token` |
| `FORBIDDEN` | 403 | Role too low for the endpoint |
| `NOT_FOUND` | 404 | Object missing, in another tenant, or unknown route |
| `METHOD_NOT_ALLOWED` | 405 | Route exists but not for this HTTP method |
| `CONFLICT` | 409 | Unique constraint (e.g. same slug + version, different content) |
| `LLM_UNAVAILABLE` | 503 | Provider timeout / rate limit after retries |
| `LLM_INVALID_OUTPUT` | 502 | Model output not valid JSON or failed schema validation after one retry |
| `INTERNAL_ERROR` | 500 | Anything unhandled (logged with request_id) |

Add new codes here when they are introduced.

## Roles
| Role | Can |
|---|---|
| `viewer` | Search, answer, read documents, jobs and evaluation runs |
| `editor` | Viewer + ingest documents |
| `admin` | Editor + create users, start evaluation runs |
