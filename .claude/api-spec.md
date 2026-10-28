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
| POST | `auth/token` | public | OAuth2 password form (`username` = email). Returns `{access_token, token_type}`; 60 min expiry | 002 |
| GET | `auth/me` | any | Current user, tenant, role | 002 |
| POST | `auth/users` | admin | Create a user in the caller's tenant; cannot create a user in another tenant | 002 |

Tenants and the first admin are created by a CLI command (`uv run python -m app.auth.cli create-tenant`), not over HTTP.

## documents — `app/documents`, `app/ingestion`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `documents/ingest` | editor | `{source, slug, version, title, content, metadata?}`. 202 + `{document_id, job_id}`. Same content again → 200 with the existing ids (idempotent) | 003 |
| GET | `documents` | viewer | Tenant's documents; filters `source`, `version`; `limit`/`offset` | 003 |
| GET | `documents/{id}` | viewer | Document metadata and chunk count | 003 |
| GET | `jobs/{id}` | viewer | Job status, attempts, error | 003 |

## search — `app/retrieval`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `search` | viewer | `{query, k=10, mode: dense\|keyword\|hybrid, rerank=false, filters?: {source, version}}`. Returns ranked passages with `chunk_id`, `document`, `text`, `score` and per-stage diagnostics (`dense_rank`, `keyword_rank`, `rerank_score`, `latency_ms` per stage) | 004 (dense), 007 (keyword, hybrid), 008 (rerank) |

## answers — `app/generation`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `answers` | viewer | `{question, retrieval?: same options as search}`. Returns `{status: answered\|insufficient_evidence, answer, citations: [{chunk_id, document, snippet}], retrieval, usage: {prompt_tokens, completion_tokens, model}, latency_ms}` | 009 |

## evaluations — `app/evaluation`
| Method | Path | Roles | Notes | Task |
|---|---|---|---|---|
| POST | `evaluations/runs` | admin | `{dataset, split: dev\|test, config}`. 202 + `{run_id, job_id}` | 006 |
| GET | `evaluations/runs` | viewer | List runs with aggregate metrics | 006 |
| GET | `evaluations/runs/{id}` | viewer | Aggregate metrics, per-`query_type` breakdown, and per-query results (`?include=results`) | 006 |

Evaluations can also run from the CLI without the API: `uv run python -m app.evaluation.cli run --split dev --config configs/hybrid.yaml`.

## Error envelope

Every non-2xx response:

```json
{"error_code": "DOCUMENT_NOT_FOUND", "message": "Document not found.", "field_errors": {"k": ["must be <= 50"]}}
```

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body / query fails validation (`field_errors` set) |
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
