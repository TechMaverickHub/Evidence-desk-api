# EvidenceDesk API — Task Index

Task files live in `.claude/tasks/`, numbered in sequence. Each is planned and approved
before it is implemented ([CLAUDE.md](CLAUDE.md)). Only the next task has a written plan;
later rows are the intended order and get their own task file when they come up.

| # | Task | Modules | Week | Status |
|---|---|---|---|---|
| 001 | [Project setup: uv, FastAPI skeleton, Postgres + pgvector, health, errors, tests](tasks/001-project-setup.md) | core | W1 | ✅ Done; 8 tests passed |
| 002 | [Auth: tenants, users, JWT, RBAC, cross-tenant test helpers](tasks/002-auth.md) | auth, core | W1 | ✅ Done; 33 tests passed |
| 003 | [Documents, jobs table, worker, chunking + embeddings, idempotent ingest, corpus loader](tasks/003-ingestion.md) | documents, ingestion, jobs | W1 | ✅ Done; 70 tests + 2 model tests passed |
| 004 | [Dense retrieval + `POST /v1/search`](tasks/004-dense-search.md) | retrieval | W1 | ✅ Done; 88 tests + 4 model tests passed |
| 005a | [Evaluation foundations: IR metrics, span relevance, dataset format + builder](tasks/005a-eval-foundations.md) | evaluation | W2 | ✅ Done; 120 tests passed |
| 005b | [Corpus v1 snapshot (frozen, licences, manifest, build script)](tasks/005b-corpus-v1.md) | corpus, tools | W2 | ✅ Done; 136 tests passed; 285 documents |
| 005c | [Labelled benchmark v1 (~150 questions, LLM-drafted, human-reviewed, dev/test)](tasks/005c-benchmark-v1.md) | evaluation | W2 | ✅ Done; 144 tests passed; 150 reviewed questions (80 dev / 70 test) |
| 006a | [Evaluation runner, reports, run comparison + dense baseline (Exp. A)](tasks/006a-eval-runner-baseline.md) | evaluation | W2 | ✅ Done; 166 tests passed; dense baseline nDCG@10 0.529 dev / 0.551 test |
| 006b | [Persisted evaluation runs: tables, worker job, `/v1/evaluations/runs` API](tasks/006b-evaluation-runs-api.md) | evaluation | W2 | ✅ Done; 178 tests passed; API run reproduces the committed dev report |
| 007 | [Keyword search (FTS) + RRF hybrid (Exp. B)](tasks/007-keyword-hybrid-search.md) | retrieval | W2 | 🔨 Code done (193 tests); Experiment B reports pending |
| 008 | Cross-encoder reranking (Exp. C) | retrieval | W3 | Not started |
| 009 | Grounded answers: structured output, citation validation, abstention, answer evaluation | generation, evaluation | W3 | Not started |
| 010 | Chunking and context-budget experiments (Exp. D) | ingestion, evaluation | W3 | Not started |
| 011 | Reliability: LLM timeouts, bounded retries, failure-scenario tests | generation, ingestion | W4 | Not started |
| 012 | Observability: OpenTelemetry traces, stage latency, token usage and cost | core, all | W5 | Not started |
| 013 | Docker Compose (api, worker, db), GitHub Actions, evaluation regression gate | repo | W5 | Not started |
| 014 | Streamlit dashboard (separate repo) | — | W5 | Not started |
| 015 | Load test + final held-out evaluation report + known limitations | evaluation | W6 | Not started |
| 016 | Bounded tool-calling workflow: read-only log-bundle diagnosis (optional) | generation | W6 | Not started |

Next: approve [task 007](tasks/007-keyword-hybrid-search.md). Task 006 is split into 006a/b; see [006a](tasks/006a-eval-runner-baseline.md) for why.
