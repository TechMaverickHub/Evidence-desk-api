# EvidenceDesk — Project Context

**EvidenceDesk** is an evaluation-driven engineering knowledge assistant. It answers
engineering questions from technical documentation and incident reports, cites the passages
it used, and **abstains** when the evidence is not good enough.

The chat answer is not the point of the project. The point is the **evaluation and
optimisation system** behind it: every retrieval change (hybrid search, reranking, chunking)
is measured against a labelled benchmark before it is kept.

## Problems it solves

1. **Trustworthy answers.** Engineers need answers from versioned docs and past incidents that
   they can verify. Every answer carries citations that the server has checked against the
   passages it actually retrieved.
2. **Knowing when not to answer.** If the corpus does not support an answer, the API returns
   an explicit `insufficient_evidence` state instead of a guess.
3. **Measurable retrieval quality.** Retrieval configurations are compared on Precision@k,
   Recall@k, MRR and nDCG@k over a labelled dataset with a held-out test split, so claims like
   "hybrid search improved recall" are backed by numbers.

## Why it exists (portfolio goal)

This is a portfolio project for AI Engineer / LLM Engineer roles. It must let its author
defend, in an interview, every decision with an experiment, an observed failure or a stated
trade-off. Prefer a smaller system with real measurements over a larger one with claims.

## This repo: `Evidence-desk-api`

**Scope = the FastAPI backend only**: auth, ingestion, retrieval, generation, evaluation,
job worker, observability. No UI lives here (see [UI.md](UI.md)).

## Corpus (bounded and reproducible)

A Markdown-native "FastAPI stack" corpus (task 005b). PostgreSQL and Python docs were
dropped from the original plan: they are DocBook XML and reStructuredText, which the
heading-aware Markdown chunker would read as flat text.

| Source | Version(s) | Licence | Notes |
|---|---|---|---|
| FastAPI docs (tutorial, advanced, deployment, how-to) | 0.115.0 and 0.162.0 | MIT | Two versions for version-specific questions; code examples inlined |
| Pydantic docs (concepts, errors) | v2.14.2 | MIT | Validation behaviour and error codes |
| Starlette docs | 1.10.0 | BSD-3-Clause | Middleware, requests, lifespan |
| Uvicorn docs | 0.54.0 | BSD-3-Clause | Workers, deployment, timeouts |
| Synthetic incident reports | 1 | CC0-1.0 | 20 fictional incidents, labelled as synthetic |

The corpus is checked into `corpus/` (generated pages, `manifest.yaml`, `SOURCES.md` with tags
and commits, `licenses/`). `tools/build_corpus.py` rebuilds it byte-for-byte from the tags
pinned in `corpus/sources.yaml`. No crawling of the open internet.

## Sources of truth

| What | Where |
|---|---|
| Product strategy and roadmap | The "AI Engineering Portfolio Strategy" brief the project started from; distilled into [plan.md](plan.md) |
| As-built API contract | Live OpenAPI at `/openapi.json` (Swagger UI at `/docs`) and [api-spec.md](api-spec.md) |
| Work history and decisions | [tasks.md](tasks.md) and `.claude/tasks/NNN-*.md` |
| Experiment results | `eval/reports/` (generated, committed) |

When code and docs disagree, the code plus the task docs describe what exists.

## Constraints

- **Low cost.** Runs on a laptop with Docker. Embeddings and reranking run locally (CPU);
  only answer generation calls a hosted LLM (Groq).
- **No real secrets in the repo.** Everything comes from `.env` (see `.env.example`).
- **Honest results.** Reports state the dataset, split, hardware and configuration. No
  "production scale" claims; report the measured limits.

See [plan.md](plan.md) for what is next.
