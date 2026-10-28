# EvidenceDesk API — Task Index

Task files live in `.claude/tasks/`, numbered in sequence. Each is planned and approved
before it is implemented ([CLAUDE.md](CLAUDE.md)). Only the next task has a written plan;
later rows are the intended order and get their own task file when they come up.

| # | Task | Modules | Week | Status |
|---|---|---|---|---|
| 001 | [Project setup: uv, FastAPI skeleton, Postgres + pgvector, health, errors, tests](tasks/001-project-setup.md) | core | W1 | ✅ Done; 8 tests passed |
| 002 | Auth: tenants, users, JWT, RBAC, cross-tenant test helpers | auth, core | W1 | Not started |
| 003 | Documents, jobs table, worker, chunking + embeddings, idempotent ingest, corpus loader | documents, ingestion, jobs | W1 | Not started |
| 004 | Dense retrieval + `POST /v1/search` | retrieval | W1 | Not started |
| 005 | Labelled benchmark v1 (dev/test) + IR metrics (P@k, R@k, MRR, nDCG@k) | evaluation | W2 | Not started |
| 006 | Evaluation runs (API, CLI, worker) + baseline report (Exp. A) | evaluation | W2 | Not started |
| 007 | Keyword search (FTS) + RRF hybrid (Exp. B) | retrieval | W2 | Not started |
| 008 | Cross-encoder reranking (Exp. C) | retrieval | W3 | Not started |
| 009 | Grounded answers: structured output, citation validation, abstention, answer evaluation | generation, evaluation | W3 | Not started |
| 010 | Chunking and context-budget experiments (Exp. D) | ingestion, evaluation | W3 | Not started |
| 011 | Reliability: LLM timeouts, bounded retries, failure-scenario tests | generation, ingestion | W4 | Not started |
| 012 | Observability: OpenTelemetry traces, stage latency, token usage and cost | core, all | W5 | Not started |
| 013 | Docker Compose (api, worker, db), GitHub Actions, evaluation regression gate | repo | W5 | Not started |
| 014 | Streamlit dashboard (separate repo) | — | W5 | Not started |
| 015 | Load test + final held-out evaluation report + known limitations | evaluation | W6 | Not started |
| 016 | Bounded tool-calling workflow: read-only log-bundle diagnosis (optional) | generation | W6 | Not started |

Next: write the plan for task 002 (auth). See [plan.md](plan.md).
