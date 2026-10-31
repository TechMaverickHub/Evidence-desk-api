# EvidenceDesk benchmark v1

The labelled retrieval benchmark that every experiment from task 006 on is measured
against. It holds 150 questions over corpus v1 (`corpus/`, 285 documents). Each question
has a reference answer and graded evidence spans. The split into dev and test is fixed.

| File | Role |
|---|---|
| `source/evidencedesk-v1.yaml` | Source of truth: questions, quotes, grades, notes. Edit this. |
| `evidencedesk-v1.jsonl` | Built file: resolved character spans plus the split. Never edit by hand. |

Rebuild it (strict mode refuses any question without `reviewed: true`):

```bash
uv run python -m app.evaluation.cli build-dataset --source eval/datasets/source/evidencedesk-v1.yaml --manifest corpus/manifest.yaml --out eval/datasets/evidencedesk-v1.jsonl --seed evidencedesk-v1
```

```bash
uv run python -m app.evaluation.cli stats --dataset eval/datasets/evidencedesk-v1.jsonl
```

The build is deterministic. Unchanged source and corpus files give a byte-identical JSONL,
with SHA-256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`.
Every evaluation run records this hash.

## Provenance

- **Drafted by Claude** (Anthropic, in the Claude Code session that built task 005c) while
  reading corpus v1. No external LLM API was called.
- **Reviewed by the project owner**, one person, in six batches of 25. Each question was
  reviewed on a Markdown review sheet that shows the resolved evidence text exactly as it
  gets built (`cli review-sheet`). Every question was accepted, and corrections were applied
  before acceptance.
- `reviewed: true` was set only for ids that the reviewer approved in chat.

## Labelling guidelines

- **Evidence is a character span in a document, not a chunk id**, so labels survive
  re-chunking. The author writes a short quote, and the builder requires it to occur exactly
  once in the document. By default the span grows to the enclosing paragraph. `quote_only`
  keeps exactly the quote, which is used for table rows and list items.
- **Grades:**
  - 3 = answers the question on its own.
  - 2 = needed but partial: one part of a multi-part answer, or one reading of an ambiguous
    question.
  - 1 = related background.
- **Alternative spans:** an evidence item can list several spans, and any one of them
  satisfies it.
  - Questions that name no version list the passage from both FastAPI 0.115.0 and 0.162.0
    when it exists in both. No page is byte-identical across the two versions.
  - q-0007 and q-0008 also accept the matching Starlette middleware passage.
- **Reference answers** are 1–3 sentences in the drafter's own words, faithful to the
  evidence.
- **Unanswerable questions** have no evidence. Their `notes` list the terms that were
  searched (exact counts over the corpus files) to confirm the corpus has no answer.
  - Topics that turned out to be answerable were not used, even when they looked absent:
    Celery, Redis, Django, Alembic, Gunicorn, Kubernetes, GraphQL, Brotli, mTLS, and
    translating error messages.
- **Ambiguous questions** have one grade-2 item per reasonable reading, and `notes` names
  the readings.

| query_type | Meaning | Guideline |
|---|---|---|
| factual | One passage answers it | Natural wording, not a copied sentence |
| exact_identifier | Asks about a flag, setting, error type or class name | The identifier appears in the question |
| paraphrase | Same meaning, different words | No 3+ word phrase from the evidence except unavoidable names |
| multi_passage | Needs 2–3 evidence items | Items from different sections or documents (e.g. an incident plus the doc behind its fix) |
| version_specific | Behaviour that differs between FastAPI 0.115.0 and 0.162.0 | The question names the version |
| ambiguous | Under-specified | One grade-2 item per reading |
| unanswerable | Plausible for this stack, absent from the corpus | Absence checked and recorded in `notes` |

## Split

`split = dev` when `sha256("evidencedesk-v1:" + group)` falls below the dev fraction, 0.6.

- **The group** is the slug of the first evidence span, so questions about the same page
  stay on the same side. Unanswerable questions use their own id.
- **The seed was fixed before any retrieval run** and will not change. Tune on `dev` only.
  Use `test` only for final comparisons.

## Statistics

| query_type | dev | test | total | mean word overlap |
|---|---|---|---|---|
| factual | 12 | 18 | 30 | 0.46 |
| exact_identifier | 18 | 12 | 30 | 0.45 |
| paraphrase | 12 | 13 | 25 | 0.11 |
| multi_passage | 11 | 9 | 20 | 0.36 |
| version_specific | 13 | 7 | 20 | 0.41 |
| ambiguous | 4 | 6 | 10 | 0.64 |
| unanswerable | 10 | 5 | 15 | – |
| **total** | **80** | **70** | **150** | |

- **Evidence items per question:** 0 for 15 questions (the unanswerable ones), 1 for 73,
  2 for 56 and 3 for 6.
- **Spans:** 260 in total. Length in characters: median 152, p90 295, max 810.
  52 evidence items carry alternative spans from both FastAPI versions.
- **Questions with evidence in each source** (a question can count under several):

  | Source | Questions |
  |---|---|
  | FastAPI | 68 |
  | Starlette | 28 |
  | incidents | 23 |
  | Uvicorn | 22 |
  | Pydantic | 17 |

**Word overlap** is the share of a question's content words (stop words removed,
case-insensitive) that also appear in its evidence text, averaged per type. It measures
drafting bias. A question written while reading a passage tends to reuse its words, which
favours keyword search.

- Paraphrase questions were reworded until their overlap was low.
- Ambiguous questions are high by design, because short generic questions share their few
  words with every reading.

## Known limitations

- **Single annotator.** There is no agreement figure. A second annotator on a 20 % sample
  is future work.
- **Drafting bias.** One model drafted every question from the passages it was reading.
  The overlap column makes this visible. Report dense and keyword results per query type,
  not only the aggregate.
- **Small groups.** Ambiguous (6 test) and unanswerable (5 test) results are indicative
  only. Always report per-type counts next to metrics.
- **The corpus contradicts itself on yield timing in FastAPI 0.115.0.**
  - The 0.115.0 tutorial says the code after `yield` runs after the response has been
    delivered.
  - The 0.162.0 docs say this exit code ran before the response was sent from 0.106.0
    until 0.118.0, which includes 0.115.0.
  - No question asks about 0.115.0's actual behaviour. q-0010 asks the version-independent
    question, and q-0097 asks for the history as the 0.162.0 docs tell it.
- **Two synthetic incidents were corrected during labelling.** Both originally
  contradicted the upstream docs in the corpus.
  - **INC-0002** blamed a missing `--proxy-headers`. Uvicorn enables proxy headers by
    default, so the root cause is now the default `--forwarded-allow-ips`.
  - **INC-0019** blamed `GZipMiddleware` for delaying Server-Sent Events. Starlette
    excludes `text/event-stream` from compression by default, so the cause is now a
    buffering reverse proxy.
- **Headings on FastAPI 0.162.0 pages** keep their `{ #anchor }` suffix in titles and
  heading paths. This is cosmetic for retrieval, but it shows up in citations.
