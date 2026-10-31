# EvidenceDesk API — Plan

Backend only. One feature per task file; each plan is approved before it is implemented
([CLAUDE.md](CLAUDE.md)). Order of priority: **labelled retrieval evaluation first, hybrid
search and reranking second, grounded generation third, reliability throughout.** Agentic
behaviour only after the retrieval system is shown to work.

```
W1 Foundation    001 setup ✅ → 002 auth ✅ → 003 ingestion ✅ → 004 dense search ✅
W2 Measurement   005a metrics ✅ → 005b corpus ✅ → 005c benchmark   <- NEXT → 006 eval runs + baseline (Exp. A) → 007 hybrid (Exp. B)
W3 RAG quality   008 rerank (Exp. C) → 009 grounded answers + abstention → 010 chunking (Exp. D)
W4 Reliability   011 timeouts/retries/failure tests (security tests ship with 002–004)
W5 Operations    012 tracing + cost → 013 Docker + CI + eval gate → 014 dashboard (separate repo)
W6 Polish        015 load test + held-out report → 016 tool-calling workflow (optional)
```

Assumes ~1.5–2 h of focused work on most days. If time is short, cut 014 and 016 before
cutting any experiment.

## Milestone deliverables

| Week | Deliverable |
|---|---|
| W1 | Documents ingested and searchable with dense retrieval, tenant-scoped, tested |
| W2 | Labelled dev/test dataset; baseline-vs-hybrid report with P@k, R@k, MRR, nDCG@k by query type |
| W3 | Reranking trade-off (quality vs latency); grounded answers with validated citations and abstention; answer-quality evaluation |
| W4 | Defined failure scenarios all tested (provider timeout, rate limit, invalid output, empty retrieval, interrupted ingestion) |
| W5 | Per-stage traces, token/cost per request; `docker compose up` runs everything; CI runs tests + eval gate |
| W6 | Held-out report, measured p50/p95 with environment, known limitations, interview walkthrough |

## Experiments

| ID | Change | Compare against | Primary metrics | Task |
|---|---|---|---|---|
| A | Dense baseline (fixed chunker, k, model) | — | R@5, nDCG@10, MRR, p95 | 006 |
| B | Dense + FTS fused with RRF | A | Same, split by `exact_identifier` vs `paraphrase` | 007 |
| C | Hybrid top-50 → cross-encoder → top-10 | B | nDCG@10 gain vs added p95 | 008 |
| D | Chunk size / overlap / top-k / context budget | best of B/C | R@5, context precision, answer correctness | 010 |

## Acceptance criteria (provisional; revise if the baseline makes them unrealistic)

| Dimension | Criterion |
|---|---|
| Retrieval | Hybrid improves R@5 or nDCG@10 over dense on the **test** split |
| Ranking trade-off | Reranker gain quantified against its latency cost |
| Answers | Faithfulness, relevance, correctness measured with a documented procedure |
| Abstention | Unanswerable questions answered `insufficient_evidence` without unsupported claims; rate reported |
| Security | All cross-tenant tests pass |
| Reliability | All defined failure-scenario tests pass |
| Performance | p50/p95 published with the test environment |
| Reproducibility | A fresh clone can run the documented evaluation command |

## Deliberately out of scope

| Deferred | Why |
|---|---|
| Multi-agent orchestration, LangChain/LlamaIndex | One bounded workflow (016) shows tool use; plain Python is easier to explain |
| Fine-tuning | The question is retrieval quality, not model training |
| Kubernetes, microservices | Docker Compose + CI is enough |
| Celery / Redis | A DB-backed job table covers ingestion and eval runs at this scale |
| A second vector store (FAISS) | Optional baseline only if time allows; pgvector is the system of record |
| Postgres row-level security | App-layer tenant filtering + tests first; RLS is a possible hardening step |

## Open decisions

| Decision | Default until decided |
|---|---|
| Groq model for generation | Pick in task 009 from what Groq lists at the time; record it in the run config |
| Ragas vs own LLM-judge prompts for faithfulness | Try Ragas in 009; fall back to own prompts if its dependencies are too heavy |
| Dataset size | Start at ~150 reviewed queries; grow only if per-type counts are too small to compare |

## Guardrails for every task
- Every tenant-owned query takes `tenant_id`; every tenant-owned endpoint gets a cross-tenant test.
- Prompts in `prompts.md`, structured output validated, citations checked server-side.
- Results only from real runs, with dataset hash, split, config and git SHA.
- Keep the OpenAPI schema and [api-spec.md](api-spec.md) in step with every endpoint change.
