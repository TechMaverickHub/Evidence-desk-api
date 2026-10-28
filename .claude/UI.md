# EvidenceDesk API — UI

**This repo has no UI.** `Evidence-desk-api` is the FastAPI backend only (see [PROJECT.md](PROJECT.md)).

The only UI this repo exposes is FastAPI's **Swagger UI at `/docs`** (schema at
`/openapi.json`). That is the contract any client consumes, so keep it accurate: every
endpoint has typed request/response models, a summary and its error responses.

## Planned client (separate repo, task 014)

A small **Streamlit** dashboard (`evidence-desk-ui`) that calls this API:

| Screen | Uses |
|---|---|
| Ask | `POST /v1/answers` — answer, citations, abstention state |
| Search diagnostics | `POST /v1/search` — dense / keyword / fused / reranked ranks and per-stage latency |
| Evaluation runs | `GET /v1/evaluations/runs`, `GET /v1/evaluations/runs/{id}` — metric comparison by config and query type |

A task's "Frontend Changes" handover section lists any contract change the dashboard must
pick up. No frontend code is written here.
