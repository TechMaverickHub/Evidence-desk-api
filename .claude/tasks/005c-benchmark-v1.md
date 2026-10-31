# Task 005c — Labelled benchmark v1

**Status:** ✅ Done
**Week:** W2 · **Modules:** `eval/datasets/`, small additions to `app/evaluation` ·
**Branch:** `task/005c-benchmark-v1`

## Goal

About 150 questions over corpus v1, each with a reference answer and evidence spans, **every
one reviewed by you**, built into `eval/datasets/evidencedesk-v1.jsonl` with a fixed dev/test
split. This is the yardstick for every experiment from task 006 on, so its quality matters
more than its size.

## Scope

In:
- `eval/datasets/source/evidencedesk-v1.yaml`: the questions (source of truth).
- `eval/datasets/evidencedesk-v1.jsonl`: built with seed `evidencedesk-v1`, dev fraction 0.6.
- `eval/datasets/README.md`: provenance ("drafted by Claude in this session, reviewed by
  you"), labelling guidelines, final stats, known limitations.
- Two small tooling additions:
  - an optional `notes` field on questions (e.g. the terms searched to confirm an
    unanswerable question really has no answer in the corpus)
  - a `review-sheet` CLI command that renders a batch as Markdown: question, reference answer,
    the resolved evidence text, and how many question words are copied from the evidence.
    It builds in draft mode, so unreviewed questions can be shown; `build-dataset` still
    refuses them.

Out: running retrieval on the dataset (task 006), answer-quality labels such as
faithfulness (task 009), a second annotator.

## Assumptions

1. You can spend roughly 2–3 hours reviewing, in six sittings of ~25 questions.
2. Questions are drafted by me in this session (no external LLM API, no cost). That is
   stated in the dataset README and in every report.
3. "Reviewed" means you accepted the question, its answer and its evidence as correct, after
   editing if needed. I set `reviewed: true` only for ids you approve in chat, or you flip
   it yourself in the YAML.

## Target mix (~150)

| query_type | Count | What it tests | Guideline |
|---|---|---|---|
| factual | 30 | One passage answers it | Natural question wording, not a copied sentence |
| exact_identifier | 30 | Flags, settings, error codes, class/function names | The question contains the identifier (`--timeout-keep-alive`, `extra_forbidden`, `use_cache`) |
| paraphrase | 25 | Meaning without shared words | No 3+ word phrase from the evidence except unavoidable names; checked by the overlap figure on the review sheet |
| multi_passage | 20 | Needs 2–3 evidence items | Items from different sections or documents (incident + the doc that explains its fix) |
| version_specific | 20 | Behaviour that differs between FastAPI 0.115.0 and 0.162.0 | Built from `diff-versions`: pages added or removed, or changed passages; the question names the version |
| ambiguous | 10 | Under-specified questions | e.g. "How do I set the timeout?" with grade-2 evidence for each reasonable reading |
| unanswerable | 15 | Abstention (task 009) | Plausible for this stack but absent from the corpus (e.g. Celery, Kafka, Django ORM, removed pages asked about the wrong version). `notes` lists the terms searched to confirm absence |

Source coverage target, roughly proportional to the corpus but with every source present:
FastAPI ~55 %, Pydantic ~15 %, Starlette ~10 %, Uvicorn ~10 %, incidents ~10 % (incidents
mostly in multi_passage and paraphrase).

## Labelling rules

- **Grades:** 3 = the passage answers the question on its own; 2 = needed but partial (one
  part of a multi-part answer, or one reading of an ambiguous question); 1 = related
  background that helps but doesn't answer it.
- **Version-independent questions** (no version named) list the evidence span in **both**
  FastAPI versions as alternatives, when the text exists in both. No page is identical
  across versions (005b), so each span is quoted separately per version.
- **Quotes** are short (5–15 words) and must be unique in their document; the builder
  rejects anything else. Spans default to the whole paragraph; `quote_only` is used for
  table rows and list items where a paragraph would be too broad.
- **Reference answers** are 1–3 sentences in my own words, faithful to the evidence.

## Workflow (six batches)

1. I draft ~25 questions into the YAML (`reviewed: false`), check every quote resolves
   (draft build), and generate `.cache/review/batch-N.md` with the review sheet.
2. You read the sheet and reply per id: ✅ accept, ✏️ change (say what), or ❌ drop.
3. I apply the changes, set `reviewed: true` for accepted ids, and rebuild in draft mode.
4. Repeat. After the last batch: a full strict build, stats, a check of the mix and of the
   per-type dev/test counts, the README, the handover and the commit.

The split seed is fixed **before** any retrieval run and never changed afterwards. If a
type ends up with fewer than 5 test questions, I report it rather than re-seeding, because
choosing a seed after seeing the questions would be a mild form of tuning.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Review format | Markdown review sheet with resolved evidence text | You can judge each label without opening corpus files; the YAML stays the single source of truth |
| Draft mode | `build_dataset(..., require_reviewed=False)` used only by `review-sheet` | Keeps the strict rule for the real build while allowing review of drafts |
| Bias check | Share of question words (stop words excluded) found in the evidence, shown per question and averaged per type in `stats` | Questions written while reading the passage tend to copy its words, which favours keyword search. Measuring it makes the bias visible in reports; paraphrase questions should score low |
| Review sheets location | `.cache/review/` (git-ignored) | Working files; the reviewed YAML and the README are the record |
| Who drafts | Claude in this session | No API cost or key; the risk of drafting bias is stated and measured, not hidden |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `review-sheet` only renders; resolution and validation stay in `dataset.py` |
| OCP | Draft mode is a parameter of the existing builder, not a second builder |
| DRY | The review sheet uses the same quote resolution as the real build, so what you review is exactly what gets built |
| Test by risk | Draft vs strict build behaviour, the overlap calculation, and review-sheet content |

### Dependencies added
None.

## Files to create / modify

```
app/evaluation/dataset.py              + notes field, require_reviewed parameter, word_overlap()
app/evaluation/cli.py                  + review-sheet command; stats shows overlap per type
tests/evaluation/test_dataset.py       draft mode, notes, overlap
tests/evaluation/test_cli.py           review-sheet output
eval/datasets/source/evidencedesk-v1.yaml
eval/datasets/evidencedesk-v1.jsonl    built
eval/datasets/README.md
.claude/{database,tasks,plan}.md       at handover
```

## Step-by-step implementation plan

0. `git switch -c task/005c-benchmark-v1` from `task/005b-corpus-v1`.
1. Tooling: `notes`, draft mode, `word_overlap`, `review-sheet`, stats overlap; tests.
2. Batch 1 (~25: factual + exact_identifier across sources) → your review → apply.
3. Batch 2 (exact_identifier + paraphrase) → review → apply.
4. Batch 3 (paraphrase + multi_passage, incidents) → review → apply.
5. Batch 4 (version_specific from the diff) → review → apply.
6. Batch 5 (ambiguous + unanswerable, absence checks in `notes`) → review → apply.
7. Batch 6: top up any type below target and fix balance across sources → review → apply.
8. Strict build, stats (mix, splits, span lengths, overlap), README, docs, handover;
   propose the commit message.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Unreviewed questions slip into the real dataset | Strict build still fails on `reviewed: false`; only draft mode passes |
| Reviewer sees something different from what is built | Review sheet evidence text equals the built span's document slice |
| Overlap figure wrong | Hand-computed examples (stop words ignored, case-insensitive) |
| Notes break the format | `notes` accepted in the source, carried into the built JSONL |

Dataset quality itself is checked by your review, not by tests; the builder guarantees
quotes resolve uniquely.

## Risks

- **Drafting bias** (questions mirror passage wording). Mitigation: paraphrase rules, the
  overlap figure, and reporting dense vs keyword results per query type in 006/007.
- **Review fatigue → rubber-stamping.** Mitigation: small batches, evidence shown inline,
  and drop rather than fix anything doubtful.
- **Too few test questions per type** (e.g. ambiguous: 10 total → ~4 in test). Mitigation:
  report per-type counts next to every metric; treat small groups as indicative only.
- **Single annotator.** Stated as a limitation in the README.

## Future improvements

- A second annotator on a 20 % sample, with agreement reported.
- Benchmark v2 with more ambiguous and version-specific questions if those groups prove too
  small to compare configurations.

## Checklist

- [x] Branch `task/005c-benchmark-v1`
- [x] Tooling: `notes`, draft mode, overlap, `review-sheet`, stats overlap + tests
- [x] Batch 1 reviewed and applied
- [x] Batch 2 reviewed and applied
- [x] Batch 3 reviewed and applied
- [x] Batch 4 reviewed and applied
- [x] Batch 5 reviewed and applied
- [x] Batch 6 reviewed and applied
- [x] Strict build passes; mix and per-type dev/test counts reported
- [x] `eval/datasets/README.md` (provenance, guidelines, stats, limitations)
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Update [database.md](../database.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Propose commit message, commit after confirmation

---

## Handover

### Summary
`eval/datasets/evidencedesk-v1.jsonl` holds **150 questions, all reviewed by the project
owner**. Each has a reference answer and graded evidence spans over corpus v1, split with
seed `evidencedesk-v1` into **80 dev / 70 test**. The source of truth is
`eval/datasets/source/evidencedesk-v1.yaml`. `eval/datasets/README.md` documents provenance,
guidelines, stats and limitations.

The questions were drafted by Claude in this session and reviewed in six batches of 25.
Every question was accepted; corrections were applied before acceptance.

Tooling added to `app/evaluation`:
- an optional `notes` field
- a draft build mode (`require_reviewed=False`)
- `word_overlap()` as a drafting-bias measure
- a `review-sheet` CLI command
- a per-type overlap column in `stats`

144 tests pass (8 new).

### Architecture Notes
- **What you review is what gets built.** `review-sheet` runs the same `build_dataset` in
  draft mode and prints each span's slice of the document. Spans longer than
  `REVIEW_SPAN_CHARS` (1,200) are truncated on the sheet only.
- **Draft mode exists only for review.** `build-dataset` always calls the builder with
  `require_reviewed=True`, so an unreviewed question can never reach the JSONL.
- **Word overlap** is the share of the question's content words (stop words removed,
  case-insensitive) that appear in its evidence text. It is stored on each built question,
  so later reports can split results by it.
- **`read_corpus_texts(manifest_path)`** is public because both the builder and the review
  sheet need the document texts.
- The builder is deterministic. A rebuild into a file with the same name is byte-identical
  (SHA-256 `b77c981f…cbcf9920`). The header's `name` comes from the output file name, so a
  different file name changes the hash.

### Deviations from the plan
- **Two synthetic incidents were corrected (approved during batch 3).** Both contradicted
  the upstream docs in the corpus:
  - **INC-0002** blamed a missing `--proxy-headers`, but Uvicorn enables it by default. The
    cause is now the default `--forwarded-allow-ips`.
  - **INC-0019** blamed `GZipMiddleware` for delayed Server-Sent Events, but Starlette
    excludes `text/event-stream` from compression. The cause is now a buffering reverse
    proxy.

  The corpus was rebuilt; only these two files changed.
- **q-0007 and q-0008 (CORS defaults) also accept the Starlette middleware passage** as an
  alternative span, because the same defaults are documented there (approved in batch 2).
- **`.gitattributes` gained `eval/datasets/*.jsonl -text`.** The dataset is identified by
  its hash, so git must never rewrite its line endings on Windows. This was not in the plan.
- **The topics for unanswerable questions changed.** Several first-choice topics turned out
  to be answerable (Celery, Redis, Django, Alembic, Gunicorn, Kubernetes, GraphQL, Brotli,
  mTLS, error-message translation) and were replaced. A first absence search had a broken
  grep command that reported zero hits everywhere; every count was redone in Python and is
  recorded in `notes`.
- **Fixed in passing:** a line in `.claude/database.md` where `\n` had been written as a
  literal line break.

### Database Changes
None (the dataset is files). `.claude/database.md` documents the new `notes`, `reviewed`
and `word_overlap` fields.

### API Changes
None. New CLI command:

```bash
uv run python -m app.evaluation.cli review-sheet --source eval/datasets/source/evidencedesk-v1.yaml --manifest corpus/manifest.yaml --out .cache/review/batch-N.md --seed evidencedesk-v1
```

Without `--all`, the sheet lists only unreviewed questions.

### Evaluation Results
No retrieval was run (that is task 006). These are dataset measurements: dataset
`evidencedesk-v1`, SHA-256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`,
seed `evidencedesk-v1`, dev fraction 0.6, corpus v1.

| query_type | dev | test | target | mean word overlap |
|---|---|---|---|---|
| factual | 12 | 18 | 30 | 0.46 |
| exact_identifier | 18 | 12 | 30 | 0.45 |
| paraphrase | 12 | 13 | 25 | 0.11 |
| multi_passage | 11 | 9 | 20 | 0.36 |
| version_specific | 13 | 7 | 20 | 0.41 |
| ambiguous | 4 | 6 | 10 | 0.64 |
| unanswerable | 10 | 5 | 15 | – |
| **total** | **80** | **70** | **150** | |

- **Every type meets its target count, and every type has at least 5 test questions.** The
  smallest are unanswerable (5) and version_specific (7), so treat their results as
  indicative only.
- **Evidence:**
  - 260 spans; length in characters: median 152, p90 295, max 810.
  - 52 evidence items carry spans from both FastAPI versions.
  - Evidence items per question: 0 for 15 questions, 1 for 73, 2 for 56 and 3 for 6.
- **Questions with evidence in each source:** FastAPI 68, Starlette 28, incidents 23,
  Uvicorn 22, Pydantic 17.
  - FastAPI accounts for 45 % of the 158 source mentions, below the ~55 % target. Batch 6
    deliberately added Starlette, Uvicorn and Pydantic questions, whose pages no question
    used yet.
- **Paraphrase overlap (0.11) is well below the other types**, as the guideline intends.
  Ambiguous questions score high by design, because their short wording shares its few
  words with every reading.

### Future Work
- **Task 006:** run dense retrieval on `dev`, and report per `query_type` and per
  word-overlap band.
- **A second annotator** on a 20 % sample, reporting agreement.
- **Benchmark v2:** more ambiguous, unanswerable and version-specific questions if those
  groups are too small to separate configurations.
- **Strip `{ #anchor }` suffixes** from FastAPI 0.162.0 titles and heading paths during
  ingestion. They are cosmetic for retrieval but show up in citations.
- **The corpus contradicts itself on yield timing in FastAPI 0.115.0:** its own tutorial
  disagrees with the 0.162.0 version history. No question depends on it, and it is
  documented in the dataset README.

### Modified Files
| File | Why |
|---|---|
| `app/evaluation/dataset.py` | `notes`, draft mode, `word_overlap`, public `read_corpus_texts` |
| `app/evaluation/cli.py` | `review-sheet` command; overlap column in stats |
| `tests/evaluation/test_dataset.py`, `tests/evaluation/test_cli.py` | Draft vs strict build, notes, overlap, review sheet |
| `eval/datasets/source/evidencedesk-v1.yaml` | 150 reviewed questions (source of truth) |
| `eval/datasets/evidencedesk-v1.jsonl` | Built dataset |
| `eval/datasets/README.md` | Provenance, guidelines, stats, limitations |
| `corpus/incidents/0002.md`, `corpus/incidents/0019.md` | Corrected to agree with the upstream docs |
| `.gitattributes` | Keep the built JSONL's bytes exact |
| `.claude/{database,tasks,plan}.md`, this file | Docs |
