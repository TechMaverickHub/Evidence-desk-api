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
| 007 | [Keyword search (FTS) + RRF hybrid (Exp. B)](tasks/007-keyword-hybrid-search.md) | retrieval | W2 | ✅ Done; 193 tests; hybrid not adopted (test nDCG@10 Δ −0.038, CI [−0.117, +0.045]) |
| 008 | [Cross-encoder reranking (Exp. C)](tasks/008-cross-encoder-rerank.md) | retrieval | W3 | ✅ Done; 208 tests; rerank top 20: nDCG@10 +0.060 dev / +0.058 test, ~1.9 s p50 |
| 009a | [Grounded answers: `POST /v1/answers`, structured output, citation validation, abstention](tasks/009a-grounded-answers.md) | generation | W3 | ✅ Done; 247 tests; live check: 8/10 answered correctly, 2/2 unanswerable abstained |
| 009b | [Answer evaluation: abstention rate, citation precision, LLM-judged correctness/faithfulness, dev-calibrated threshold](tasks/009b-answer-evaluation.md) | evaluation, generation | W3 | ✅ Done; 268 tests; test: 86% answered, 5/5 refused, 50/56 judged correct; gate not adopted |
| 010 | [Chunking and context-budget experiments (Exp. D)](tasks/010-chunking-context.md) | ingestion, evaluation | W3 | ✅ Done; 278 tests; 450/75 chunks adopted (dev hit@5 +0.057); test answers 59/65 vs 56/65 |
| 011 | [Reliability: LLM failure taxonomy, bounded retries, stale jobs, failure scenarios](tasks/011-reliability.md) | generation, jobs, evaluation | W4 | ✅ Done; 295 tests; 12 failure scenarios catalogued and tested |
| 012 | [Observability: OpenTelemetry traces, stage latency, token usage and cost](tasks/012-observability.md) | core, all | W5 | ✅ Done; 308 tests; stage spans + trace_id in logs + cost_usd |
| 013 | Docker Compose (api, worker, db), GitHub Actions, evaluation regression gate | repo | W5 | Not started |
| 014 | Streamlit dashboard (separate repo) | — | W5 | Not started |
| 015 | Load test + final held-out evaluation report + known limitations | evaluation | W6 | Not started |
| 016 | Bounded tool-calling workflow: read-only log-bundle diagnosis (optional) | generation | W6 | Not started |

Next: write the plan for task 013 (Docker Compose for api, worker and db; GitHub Actions; evaluation regression gate). Task 009 is split into 009a/b; see 009a for why.
