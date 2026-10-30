# Task 005a — Evaluation foundations: metrics, span relevance, dataset format

**Status:** ✅ Done (2026-10-30); 120 tests passed, ruff clean
**Week:** W2 · **Modules:** `app/evaluation` · **Branch:** `task/005a-eval-foundations`

## Why task 005 is split

Task 005 as listed ("corpus v1 + labelled benchmark + IR metrics") is three different kinds
of work with different risks. Each part gets its own plan, approval and commit:

| Part | What | Nature |
|---|---|---|
| **005a (this plan)** | Metric definitions, chunk-to-evidence relevance, dataset schema, validator and builder, tested on the fixture corpus | Pure Python, no DB, no downloads |
| 005b | Corpus v1 snapshot: build script, licences, manifest, line-ending protection | Needs your approval for downloads (file names, sources, sizes listed in its plan) |
| 005c | Benchmark v1: ~150 questions, LLM-drafted from the corpus, **every one reviewed by you**, dev/test split, stats | Mostly human review time |

Order matters: metrics and the dataset format come first, so the corpus and the questions
are built against a validator that already exists.

## Goal

Exact, tested definitions of how a ranked list of chunks is scored against labelled evidence,
and a dataset format plus tooling that make labels hard to get wrong: authors write a short
quote, the builder finds its exact character offsets, and the validator rejects anything
ambiguous.

## Scope

In:
- `app/evaluation/relevance.py`: does a retrieved chunk count as evidence?
- `app/evaluation/metrics.py`: Precision@k, Recall@k, reciprocal rank (MRR@k when averaged),
  nDCG@k with graded relevance; per-query and aggregate (overall and per `query_type`).
- `app/evaluation/dataset.py`: source format (YAML, written by people), built format (JSONL
  with offsets and splits), loading, validation, SHA-256 of the built file.
- `app/evaluation/cli.py`: `build-dataset` (resolve quotes → offsets, assign splits, write
  JSONL) and `stats` (counts by split and query type).
- `.gitattributes`: `corpus/** -text` and `tests/fixtures/corpus/** -text`, so git never
  rewrites corpus bytes (noted in task 003).
- A small fixture dataset against the existing fixture corpus, used by the tests.

Out: the real corpus (005b), the real questions (005c), running search over a dataset and
storing runs (006), answer-level metrics such as faithfulness (009).

## Assumptions

1. Evidence is identified by `(slug, version)` plus a character span in that document's
   content exactly as the loader ingests it.
2. One labelled "fact" can live in several places (the same paragraph in two doc versions).
   Retrieving any one of those places satisfies it.
3. Unanswerable questions have no evidence and are excluded from retrieval metrics; they are
   scored for abstention in task 009.

## Architecture decisions

### Dataset model: evidence items with alternative spans

```yaml
# eval/datasets/source/<name>.yaml (written and reviewed by people)
questions:
  - id: q-0001
    query_type: exact_identifier
    question: What does use_cache=False do on a dependency?
    reference_answer: The dependency is called again instead of reusing the cached value.
    reviewed: true          # only reviewed questions are built
    evidence:
      - grade: 3            # 1 = related, 2 = partially answers, 3 = answers
        spans:              # alternatives: any one satisfies this evidence item
          - {slug: fastapi/dependencies, version: "0.115", quote: "unless `use_cache=False`"}
          - {slug: fastapi/dependencies, version: "0.110", quote: "unless `use_cache=False`"}
```

- **Quotes, not offsets, are authored.** The builder finds each quote in the document; it must
  occur exactly once there (otherwise the author lengthens the quote). By default the span is
  the whole paragraph containing the quote, so labels are about passages, not phrases;
  `quote_only: true` limits it to the quote itself.
- **Evidence items with alternatives** solve two problems the planned flat span list had:
  a fact repeated in two versions should not need *both* retrieved for full recall, and a
  `multi_passage` question needs *each* of its items retrieved.
- Built JSONL stores resolved `char_start` / `char_end`, the split, and keeps the quote so a
  reviewer can read the label without opening the corpus. database.md is updated to this format.

### Relevance: when does a chunk count?

A chunk matches an evidence span when it is in the same `(slug, version)` and their
character ranges overlap by at least **half of the shorter of the two**:

`overlap ≥ 0.5 × min(span_length, chunk_length)`

So a chunk must contain at least half of a short span, or be at least half evidence when the
span is longer than the chunk. Touching by a few characters at a chunk boundary (overlap
windows) does not count. The 0.5 threshold is a named constant, recorded with every run.

### Metric definitions (all at cutoff k)

Let `R = c1…cn` be the ranked chunks and `E` the query's evidence items. `M(ci)` is the set
of items that chunk `ci` matches.

| Metric | Definition | Note |
|---|---|---|
| Precision@k | `|{i ≤ k : M(ci) ≠ ∅}| / k` | Chunk level; divides by k even if fewer than k were returned |
| Recall@k | `|⋃_{i≤k} M(ci)| / |E|` | **Evidence-item level**, so it doesn't depend on chunk size, and duplicates across versions aren't double-counted |
| RR@k | `1 / min{i ≤ k : M(ci) ≠ ∅}`, else 0 | MRR@k is the mean over queries |
| nDCG@k | `DCG = Σ_{i≤k} (2^{g_i} − 1) / log2(i + 1)`, where `g_i` is the highest grade among items **first** matched at rank i (0 otherwise); items are credited once. `IDCG` places items in grade order at ranks 1…min(|E|, k) | Crediting each item once stops a ranking from scoring well by repeating the same passage; it also keeps nDCG ≤ 1 |

Aggregates are means over answerable queries, reported overall and per `query_type`, with
the query count beside each mean (small groups must be visible as small).

### Split assignment

- Deterministic: `sha256(seed + group_key)` → `dev` if the value falls in the first 60 %,
  otherwise `test`.
- `group_key` = the document slug (without version) of the question's first evidence span,
  so questions about the same page, and its other versions, never straddle the split.
  Unanswerable questions use their own id.
- The seed and the resulting counts per split and type are printed by `stats` and kept in
  the dataset header line.

### Other decisions

| Decision | Choice | Reason |
|---|---|---|
| Source format | YAML (human-friendly, comments allowed) → built JSONL (machine format, hashed) | Reviewers edit YAML; runs consume a byte-stable JSONL whose hash identifies the dataset |
| Where documents are read from | The corpus manifest (same files the loader ingests), read with Python's default text mode exactly like `app.ingestion.cli` | Offsets refer to the same string the database stores |
| DB access | None in 005a | Keeps this task pure and fast to test; task 006 joins it with search |
| Abstractions | Plain functions and Pydantic models | Nothing has a second implementation |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `relevance.py` only decides matches; `metrics.py` only scores ranked match lists; `dataset.py` only parses, validates and builds; `cli.py` only wires arguments to them |
| OCP | New metrics are new functions over the same `RankedMatches` input; the relevance threshold is a parameter |
| DRY | Corpus files are located through the existing loader's manifest parsing (`read_manifest`), not a second parser |
| Flat control flow | Validation collects problems with guard clauses and reports all of them at once |
| Error handling | Builder raises one `DatasetError` listing every problem (missing doc, quote not found, quote not unique, bad grade, unreviewed item…); the CLI prints it and exits 1 |
| Test by risk | Metric functions tested against hand-computed values; relevance edge cases at the 0.5 boundary; builder failure modes |

### Dependencies added
None (`pyyaml` is already a dependency).

## Files to create / modify

```
.gitattributes                              + corpus/** -text, tests/fixtures/corpus/** -text
app/evaluation/__init__.py
app/evaluation/relevance.py                 Span, RetrievedChunk, overlaps(), match_evidence()
app/evaluation/metrics.py                   precision_at_k, recall_at_k, reciprocal_rank,
                                            ndcg_at_k, QueryScores, aggregate()
app/evaluation/dataset.py                   source + built models, build(), load(), sha256
app/evaluation/cli.py                       build-dataset, stats
app/ingestion/cli.py                        only if needed: expose manifest reading for reuse (no behaviour change)
tests/fixtures/datasets/mini.yaml           ~8 questions over the fixture corpus, every type
tests/evaluation/test_relevance.py
tests/evaluation/test_metrics.py
tests/evaluation/test_dataset.py
.claude/database.md, tasks.md, plan.md      format + status
```

## Step-by-step implementation plan

0. `git switch -c task/005a-eval-foundations` from `task/004-dense-search`.
1. `.gitattributes` entries; renormalise and confirm no fixture bytes change.
2. `relevance.py` + tests (same/different doc or version, the 0.5 boundary, span longer than chunk).
3. `metrics.py` + tests with hand-worked examples, including duplicates, multi-item queries,
   graded nDCG, fewer than k results, no relevant results.
4. `dataset.py`: models, quote resolution (paragraph expansion, uniqueness), split
   assignment, validation, writer and loader with SHA-256; tests on `mini.yaml`.
5. `cli.py` (`build-dataset --source --manifest --out --seed`, `stats --dataset`) + tests.
6. Docs (database.md format, metric definitions in architecture.md), handover, propose commit message.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Metric formula wrong (every later number depends on it) | Each metric against a hand-computed table, incl. graded nDCG to 1e-9 |
| Duplicate passages inflate scores | Same item matched at ranks 1 and 2 → credited once in recall and nDCG |
| Version duplicates break recall | Item with spans in two versions; retrieving either gives recall 1.0 |
| Boundary chunks counted as evidence | Overlap just below / at 0.5 × shorter length |
| Wrong offsets | Built span text equals the document slice; paragraph expansion stops at blank lines |
| Ambiguous labels | Quote found 0 or 2 times → build fails naming the question and quote |
| Leakage across split | Two questions on the same slug (different versions) always share a split |
| Silent bad data | Unreviewed question, grade outside 1–3, unanswerable with evidence, duplicate ids → all reported in one error |
| Reproducibility | Building twice gives byte-identical JSONL and the same SHA-256 |

## Edge cases and security

- Quotes are matched literally (no regex), so special characters in code can't break matching.
- Windows line endings: `.gitattributes` keeps corpus bytes fixed; reading in text mode
  matches what the loader stores either way.
- Dataset files contain no secrets or personal data; synthetic incidents are labelled synthetic (005b).

## Risks

- **Overlap threshold is a judgement call.** Mitigation: named constant, recorded in every run;
  task 010 can report sensitivity to it.
- **Paragraph expansion picks a span that is too large** (e.g. a long code block). Mitigation:
  `quote_only: true` per span, and `stats` reports span length percentiles.

## Future improvements

- Inter-annotator check (a second reviewer on a sample) if time allows.
- Label tooling UI in the dashboard (014).

## Checklist

- [x] Branch `task/005a-eval-foundations`
- [x] `.gitattributes` for corpus bytes
- [x] `relevance.py` + tests
- [x] `metrics.py` + hand-computed tests
- [x] `dataset.py` (resolve, validate, split, write, load, hash) + tests
- [x] `cli.py` (`build-dataset`, `stats`) + tests
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Self-review against the design-principles table
- [x] Update [database.md](../database.md), [architecture.md](../architecture.md), [tasks.md](../tasks.md), handover below
- [x] Propose commit message, commit after confirmation

## Preview: decisions 005b and 005c will ask you to confirm

- **Corpus sources (005b).** PROJECT.md lists FastAPI, PostgreSQL and Python docs. PostgreSQL
  (DocBook XML) and Python (reStructuredText) docs are not Markdown, so the heading-aware
  chunker would see them as flat text, and converting them needs pandoc or similar. I'll
  propose a Markdown-native "FastAPI stack" corpus instead: FastAPI docs at two release tags
  (for version-specific questions), plus Pydantic, Starlette and Uvicorn docs (all MIT/BSD),
  plus ~20 synthetic incident reports. FastAPI's `{* docs_src/… *}` code includes would be
  inlined by the build script so code identifiers are searchable.
- **Question drafting (005c).** I draft candidates from the corpus, you accept, edit or
  reject each one (`reviewed: true`), and the report states "LLM-drafted, human-reviewed".
  Target mix of ~150: factual 30, multi_passage 20, exact_identifier 30, paraphrase 25,
  version_specific 20, ambiguous 10, unanswerable 15.

---

## Handover

### Summary
Pure-Python evaluation foundations, with no database and no network:
- span relevance (`overlap ≥ 0.5 × shorter length`, same document version)
- Precision@k, Recall@k, RR@k / MRR, graded nDCG@k, with per-type aggregates
- a dataset pipeline: reviewers write YAML with quotes; `build-dataset` resolves each quote to
  its paragraph's exact offsets, checks everything, assigns dev/test splits by page, and writes
  a header + JSONL file whose SHA-256 identifies it; `stats` reports counts and span lengths
- `.gitattributes` keeps corpus bytes fixed

120 tests pass (32 new).

### Architecture Notes
- **Evidence items with alternative spans** replace the flat span list planned in
  database.md. Recall counts items, and any alternative satisfies an item, so a fact present in
  two FastAPI versions isn't counted twice, and a multi-passage question needs each of its items.
- **nDCG credits each evidence item once**, at the first rank that matches it, using the best
  grade among newly matched items. The ideal ranking puts one item per rank. This keeps
  nDCG ≤ 1 even when one chunk covers two items (tested).
- **Precision divides by k** even when fewer than k results come back.
- **The builder reuses `app.ingestion.cli.read_manifest`**, so labelled offsets refer to
  exactly the text the loader ingests. No change to that module was needed.
- **Every problem is reported in one `DatasetError`**: duplicate ids, unreviewed questions,
  unanswerable questions with evidence (and answerable ones without), quotes found 0 or 2+ times,
  missing documents, bad grades.

### Deviations from the plan
- **The fixture dataset has 5 questions, not about 8**, covering factual, exact_identifier,
  paraphrase, multi_passage and unanswerable. The fixture corpus has one version per document,
  so version alternatives and split grouping across versions are tested with in-test sources
  instead.
- **Added `tests/evaluation/test_cli.py`** (build → stats round trip, error exit).
- **No `app/ingestion/cli.py` change was needed.** The plan allowed for one.

### Database Changes
None. database.md's "Benchmark dataset" section now documents the built format.

### API Changes
None.

### Evaluation Results
None: no corpus or benchmark yet (005b, 005c). Fixture build: 5 questions, 6 spans, median
span 78 chars. With seed `evidencedesk`, all 5 fixture questions land in `dev`, which is
expected with only 3 page groups.

### Future Work
- 005b corpus snapshot, then 005c benchmark questions.
- Report how sensitive the metrics are to the 0.5 overlap threshold (task 010).
- A second reviewer on a sample of questions, if time allows.

### Modified Files
| File | Why |
|---|---|
| `.gitattributes` | `corpus/**` and `tests/fixtures/corpus/**` as `-text` |
| `app/evaluation/{relevance,metrics,dataset,cli}.py` | Evaluation foundations |
| `tests/evaluation/*`, `tests/fixtures/datasets/mini.yaml` | Tests and fixture |
| `README.md`, `.claude/{database,architecture,plan,tasks}.md`, this file | Docs |
