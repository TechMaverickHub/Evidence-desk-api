# Task 010 — Chunking and context experiments (Experiment D)

**Status:** ✅ Done (D2 450/75 adopted; 5 context chunks kept)
**Week:** W3 · **Modules:** `app/ingestion`, `app/retrieval`, `app/evaluation`, `app/generation` (small) ·
**Branch:** `task/010-chunking` (off `task/009b-answer-evaluation`)

## Goal

009b showed that answers fail mainly because the evidence never reaches the 5 context
chunks:
- About 9 in 10 wrong refusals are retrieval misses.
- Context hit is 46 % for paraphrase and 56 % for multi-passage questions (test).

Experiment D asks which change gets more evidence into the answer context:
- chunk size
- a contextual header (document title, version and heading path) shown to the embedder and
  reranker
- passing more chunks to the LLM

It is measured on the exact pipeline that `/v1/answers` uses (dense → rerank top 20 → top
k), decided on dev by a rule fixed here, and confirmed once on test.

## Scope

In:
- **A new retrieval metric, hit@k:** whether any evidence item is in the top k. It is what
  "evidence reached the context" means for answers, which R@k (the share of items found)
  doesn't capture.
  - Added to `metrics.py`, run records, reports and `compare`; `compare` includes hit@k in
    its paired bootstrap.
- **Chunker variants that coexist in one tenant.** The chunker name already keys chunks.
  - Variants are named `tokens-<max>-overlap-<o>`, with a `-ctx` suffix for the contextual
    header.
  - `RunConfig.chunker` (optional) selects one per evaluation run; the default remains the
    settings chunker.
- **Contextual header (variant):**
  - The text the embedder and the reranker see becomes
    `"<title> (<source> <version>) > <heading path>\n\n<chunk text>"`.
  - Chunk text and offsets are unchanged, so labels and citations still match.
  - Keyword search keeps indexing chunk text only (out of scope; hybrid was not adopted).
- **`ingestion.cli rechunk`:** chunks and embeds every ingested document of a tenant with a
  given chunker variant, alongside existing chunks. It is resumable: documents that already
  have that variant are skipped.
- **Adoption, if a variant wins:**
  - Change the settings defaults (`CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`, new
    `CHUNK_CONTEXT_HEADER`) and/or `ANSWER_CONTEXT_CHUNKS`.
  - Run one test-split answer run (deterministic metrics, no judge) and compare it with
    009b's test run.
- **The answer-run record** gains the chunker name in `GeneratorSettings`.

Out:
- Keyword-index changes (`tsv` over headers).
- Semantic or LLM-based chunking.
- Changing the embedding or reranker model.
- Re-judging answers with the LLM judge: Groq budget, and deterministic answer metrics are
  enough to confirm a retrieval change.
- Removing old chunk variants from the database (kept for reproducibility; a cleanup command
  is future work).

## Experiment design (fixed before any run)

**Pipeline under test:** dense → rerank the top 20 → top 10, i.e. `dense-rerank20`, the
answer pipeline. Context hit is read at k = 5 (the current context) and k = 8.

| Id | Chunker | Header | Why |
|---|---|---|---|
| D0 | `tokens-300-overlap-50` | no | Baseline (current) |
| D1 | `tokens-150-overlap-30` | no | Smaller chunks: more distinct candidates, sharper matches for short facts |
| D2 | `tokens-450-overlap-75` | no | Larger chunks: more of a section per chunk (incident root cause plus symptoms; multi-passage) |
| D3 | `tokens-300-overlap-50-ctx` | yes | Title, version and heading on every chunk: targets the version blind spot (008) and section-level misses (006a) |
| D4 | best of D1/D2 + header | yes | Built **only if** both the best size variant and D3 beat D0 on dev (see the rule) |

**Context budget:** compare hit@5 and hit@8 of the chosen chunker, read from the same run.
No extra variant is needed.

**Decision rule (dev only):**
1. **Primary metric:** hit@5 on answerable dev questions, the share whose evidence reaches
   the 5 context chunks.
2. **A variant beats D0** when its paired-bootstrap 95 % CI on Δhit@5 excludes 0, and
   nDCG@10 is not worse with a CI excluding 0.
3. **Choice:** among variants that beat D0, take the one with the largest Δhit@5. On ties
   (|difference| < 0.01), take the smaller chunk size.
4. **If none beats D0, keep D0.** That is a reportable result.
5. **Context budget:** raise `ANSWER_CONTEXT_CHUNKS` to 8 only if Δ(hit@8 − hit@5) for the
   chosen chunker is ≥ 0.05 on dev. That is at least 3–4 more questions with evidence in
   context, for about 60 % more prompt tokens.

**Test, once:**
1. The chosen configuration vs D0 on the test split (retrieval).
2. If anything was adopted, one test answer run with the new settings, compared with
   009b's test answer run on answered rate, wrong refusals (retrieval vs generation),
   context hit and citation precision.

## Assumptions

1. **Re-chunking cost:** about 11–16 minutes per variant (005b and 006a timings), so 3–4
   variants is about 1 hour of background CPU work.
   - Disk and DB grow by about 5k–10k chunks per variant: fine for Postgres at this size.
2. **Embedding limits.** BGE truncates at 512 tokens, and the 450-token variant plus a
   header can exceed it slightly; the measurement includes that.
   - The reranker's 512-token pair limit truncates long passages in D2 more often.
   - D2 measures this real cost, not an artefact.
3. **Groq budget:** at most one test answer run of about 100k tokens on `gpt-oss-20b`, only
   if a variant is adopted. That is within one day's free tier. Approving this plan
   approves that run.
4. **Dev retrieval runs are model-local** (no Groq) and cost only CPU time: about 4 minutes
   each with reranking.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Variants side by side | Chunks keyed by chunker name (already the case); `rechunk` writes a new name; search reads the name it is given | No re-ingest of documents; every variant measured on identical documents; switching is a setting |
| Selecting a chunker per run | `SearchOptions.chunker` (default: settings) and `RunConfig.chunker` | Evaluation can compare variants without restarting the app or juggling environment variables. The API keeps the settings chunker |
| Header in the name | `-ctx` suffix in the chunker name, parsed by one function `chunker_spec(name)` | The name alone tells search whether the reranker needs the header, so the two can't disagree |
| Header content | `title (source version) > heading_path`, built by one function used by ingestion (embedding) and search (reranker input) | DRY; the reranker scores exactly what was embedded |
| Offsets | Chunk `text`, `char_start` and `char_end` never include the header | Labels, the overlap metrics and citation snippets stay valid |
| Rechunking path | A CLI that processes documents inline with an explicit `TokenWindowChunker(max, overlap)` plus a header flag, committing per document | The variant comes from arguments, not from worker settings; resumable per document |
| hit@k | Pure function `hit_at_k(matches, k)`; added to `QueryScores`, `MetricSummary`, `MetricRow` and the reports; optional (`None`) in records written before 010 | Backward-compatible reading of old reports; D0 is re-run with the new code anyway |
| Adoption | Change defaults in `config.py` and `.env.example`, then `rechunk` with the adopted variant (it already exists after the experiment) | Production behaviour changes only through settings, recorded in the handover |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| OCP | A chunker variant is data (a name); search, evaluation and ingestion don't branch on specific sizes |
| DRY | One header builder; one `chunker_spec` parser; hit@k sits next to the other metrics and reuses `match_evidence` |
| SRP | `rechunk` only re-chunks; experiment logic stays in configs and reports |
| Test by risk | Header never leaks into offsets; reranker input matches embedding input; hit@k maths; rechunk is idempotent and tenant-scoped |

### Dependencies added
None.

## Files to create / modify

```
app/evaluation/metrics.py        + hit_at_k; QueryScores / MetricSummary
app/evaluation/records.py        MetricRow.hit, RunConfig.chunker
app/evaluation/report.py         hit@k columns; compare bootstrap includes hit@5
app/evaluation/runner.py         pass the chunker through; verify_corpus for that chunker
app/ingestion/chunking.py        chunker_spec(name) / -ctx naming; contextual header builder
app/ingestion/pipeline.py        embed header + text when the variant has a header
app/ingestion/cli.py             + rechunk command
app/retrieval/service.py         SearchOptions.chunker; reranker input with the header for -ctx chunkers
app/evaluation/answer_records.py GeneratorSettings.chunker
app/core/config.py, .env.example + CHUNK_CONTEXT_HEADER (only flipped if adopted)
tests/...                        metrics, chunking/header, pipeline, rechunk, search, runner
eval/configs/d0..d4-*.yaml       variants (dense-rerank20 + chunker)
eval/reports/*                   generated (second commit)
.claude/{architecture,database,api-spec,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/010-chunking`.
1. **hit@k** in the metrics, records, reports and compare, with tests (hand-computed).
2. **`chunker_spec` and the header builder,** with tests: names round-trip, offsets
   unchanged, header format.
3. **Pipeline:** embed the header text for `-ctx` variants. Test that the fake embedder
   receives header + text, while the stored text has no header.
4. **`SearchOptions.chunker`** and the reranker input for `-ctx`. Tests: search reads only
   the chosen chunker; the reranker receives header + text.
5. **`RunConfig.chunker`** through the runner and `verify_corpus`; the answer record's
   chunker; tests.
6. **`rechunk` CLI:** tenant-scoped, resumable, with tests on the fixture corpus.
7. **Lint, full suite and docs;** commit 1 after you confirm.
8. **Experiment on dev**, from the clean tree, in the background:
   1. Run `rechunk` for D1, D2 and D3.
   2. Run D0–D3 with the `dense-rerank20` pipeline.
   3. Compare each variant against D0.
   4. Build D4 if the rule calls for it.
   5. Decide.
9. **Test, once:** the chosen configuration vs D0. If adopted: settings change, then a test
   answer run (deterministic metrics only) compared with 009b.
10. **Handover;** commit 2 (reports, plus the settings change if adopted) after you confirm.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Header leaks into offsets or citations | `-ctx` chunks keep `text == content[char_start:char_end]`; snippets have no header |
| Reranker and embedder see different text | For `-ctx`, the reranker receives exactly the header + text that was embedded (fakes record inputs) |
| A run mixes chunkers | Search with `chunker=X` returns only chunks of X; `verify_corpus` requires X's chunks for every document |
| hit@k wrong | Hand-computed: none in top k → 0; any item in top k → 1; unanswerable excluded |
| Rechunk duplicates or crosses tenants | Running it twice yields the same chunk count; another tenant's documents are untouched |
| Old reports become unreadable | A 006a/008 report JSON still loads (`hit` is None) and `compare` refuses hit@5 deltas when one side lacks it |

## Edge cases

- **Very short sections** (one sentence): the 150-token variant produces the same chunk as
  300; that's fine, and counts don't need to differ.
- **Header longer than expected** (deep heading paths): it is part of the 512-token budget,
  and the chunk text is cut by the model, not by us. The plan accepts that.
- **A variant with zero chunks for a document** (only headings): the existing
  `IngestionError` path. `rechunk` logs and skips it; `verify_corpus` then fails for that
  variant, which is visible rather than hidden.

## Security

No new endpoints. `rechunk` is an operator CLI scoped to one tenant by name. Header text
comes from stored document metadata (title, source, version), never from requests.

## Risks

- **Overfitting dev.** There are 4 or 5 variants, fixed in advance, plus one pre-registered
  conditional combination, and one test run. The rule and its CIs are recorded.
- **Reranker interaction.** A variant can raise dense recall but lose after reranking (or
  the reverse). Measuring the full answer pipeline, not dense alone, is deliberate.
- **More chunks change the candidate pool.** With 150-token chunks, a top-20 rerank covers
  less text. That is part of what is measured.

## Future improvements

- Index headers in `tsv` if hybrid search is revisited.
- A cleanup command for unused chunk variants.
- Judge-level confirmation of the adopted variant when Groq budget allows.

## Checklist

- [x] Branch `task/010-chunking`
- [x] hit@k (metrics, records, reports, compare) + tests
- [x] `chunker_spec`, header builder, pipeline embedding + tests
- [x] `SearchOptions.chunker`, reranker header input + tests
- [x] `RunConfig.chunker`, runner, answer record chunker + tests
- [x] `rechunk` CLI + tests
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Commit 1 after confirmation
- [x] Dev: rechunk D1–D3, run D0–D3 (+D4 if triggered), decision by the rule
- [x] Test: chosen vs D0; if adopted, settings change + test answer run vs 009b
- [x] Update [architecture.md](../architecture.md), [database.md](../database.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit 2 after confirmation

---

## Handover

### Summary
**Experiment D measured how chunking affects whether evidence reaches the answer context.**
Three variants were compared with the current 300/50 chunker on the exact answer pipeline
(dense → rerank top 20), using a new metric, hit@k: any evidence in the top k.

**Adopted: 450-token windows with 75 overlap (D2).**
- **Why:** chosen by the dev rule fixed in the plan (hit@5 +0.057, 95 % CI [+0.014, +0.129]).
- **Defaults changed:** `CHUNK_MAX_TOKENS=450`, `CHUNK_OVERLAP_TOKENS=75`.
- **Context budget unchanged:** 5 chunks; 8 added only one dev question.
- **Test result:** the retrieval gain is in the same direction but not demonstrated
  (hit@5 +0.031, CI [−0.046, +0.108]). Answers improved from 56/65 to 59/65 answered, with
  retrieval-miss refusals down from 8 to 5.
- **Cost:** about 17 % more prompt tokens and slower reranking.

**What was built:**
- **Chunker variants** coexist by name.
- **`ingestion.cli rechunk`** adds a variant to every ingested document; it is resumable.
- **Contextual-header variants (`-ctx`)** embed and rerank "title (source version) >
  heading path" + text, without touching offsets.
- **Evaluation configs** can pick a chunker.

Code is in `ba5a15e`; all experiment reports were generated from that clean commit. 278 tests
pass.

### Architecture Notes
- **Naming.** A chunker name says everything: `tokens-<max>-overlap-<o>[-ctx]`.
  - `ingestion.chunking.has_context_header(name)` is how search knows to give the reranker
    the same header + text the embedder saw.
  - `contextual_header` and `model_input` build that text in one place.
- **Offsets.** Stored `text`, `char_start` and `char_end` never include the header (tested),
  so evidence labels, citations and snippets stay exact.
- **Chunker selection.**
  - `SearchOptions.chunker` and `RunConfig.chunker` select a variant per evaluation run.
  - The API reads `configured_chunker()`, which now includes the `CHUNK_CONTEXT_HEADER`
    setting (still off).
  - `verify_corpus` checks the selected variant exists for every document.
- **`rechunk_documents`** commits per document and skips documents that already have the
  variant, so it resumes after interruption and never duplicates chunks. It is
  tenant-scoped (tested).
- **hit@k** sits next to P/R/MRR/nDCG in `metrics.py`, run records, reports and `compare`.
  Records written before 010 load with `hit = None`, shown as "–", and are left out of
  hit comparisons.
- **The `eval-corpus-v1` tenant now holds four variants:**

  | Variant | Chunks |
  |---|---|
  | 300/50 | 5,005 |
  | 150/30 | 8,737 |
  | 450/75 | 3,920 |
  | 300/50-ctx | 5,005 |

  The adopted default (450/75) is already present, so nothing needs re-ingesting.

### Deviations from the plan
- **The D3 near miss.** D3 (contextual header) had the largest dev gains:
  - hit@5 +0.086
  - nDCG@10 +0.071, CI [+0.007, +0.138]
  - hit@8 +0.100, CI [+0.014, +0.186]

  But the lower bound of its primary-metric interval (hit@5) is exactly 0.0. The fixed
  rule requires an interval that excludes 0, so D3 does not qualify, and choosing it after
  seeing the numbers would be post-hoc tuning. As a result, D4 (best size + header) was not
  triggered either. Recorded as the strongest lead for future work.
- **The test answer run used environment variables** (`CHUNK_MAX_TOKENS=450`,
  `CHUNK_OVERLAP_TOKENS=75`) to apply D2 without editing committed code, so the run comes
  from a clean tree. Its record names the chunker it used. It needed its own answer config
  (`answers-d2-tokens450.yaml`), so it doesn't overwrite 009b's `answers-rerank20-test`.
- **D0 was re-run on dev and test** with the new code (for hit@k). Its numbers equal the
  008 `dense-rerank20` runs exactly: a reproducibility check.
- **`load_fixture_corpus` moved** to the shared `tests/conftest.py`, because the new
  ingestion tests need it.
- **Adopting D2 changed two tests:**
  - `test_search_api` now compares against `configured_chunker()`.
  - The header test names its 300/50 plain variant explicitly.

### Database Changes
No migration. The `chunks.chunker` values now include `tokens-150-overlap-30`,
`tokens-450-overlap-75` and `tokens-300-overlap-50-ctx` (the `String(50)` column fits them).
See [database.md](../database.md).

### API Changes
- **No endpoint changes.** `/v1/search` and `/v1/answers` now read 450/75 chunks by
  default.
- **New setting:** `CHUNK_CONTEXT_HEADER` (off).
- **Defaults changed:** `CHUNK_MAX_TOKENS` 300 → 450 and `CHUNK_OVERLAP_TOKENS` 50 → 75.
- **New CLI command:** `ingestion.cli rechunk`.
- **Retrieval reports** gain Hit@k.

See [api-spec.md](../api-spec.md).

### Evaluation Results
**Setup:**
- Dataset `evidencedesk-v1` (sha256 `b77c981f…cbcf9920`), tenant `eval-corpus-v1`.
- `BAAI/bge-small-en-v1.5`; reranker `cross-encoder/ms-marco-MiniLM-L6-v2` on the top 20
  (CPU); 5 context chunks.
- Git `ba5a15e` (clean). Same Windows 11 machine as before.

**Dev (70 answerable questions), against D0:**

| Variant | Chunks | hit@5 | Δ hit@5 (95 % CI) | nDCG@10 | Δ nDCG@10 (95 % CI) | retrieval p50 |
|---|---|---|---|---|---|---|
| D0 300/50 | 5,005 | 0.757 | — | 0.589 | — | 1.28 s |
| D1 150/30 | 8,737 | 0.743 | −0.014 [−0.100, +0.071] | 0.542 | −0.048 [−0.117, +0.011] | — |
| **D2 450/75** | 3,920 | **0.814** | **+0.057 [+0.014, +0.129]** | 0.615 | +0.026 [−0.002, +0.063] | 1.93 s |
| D3 300/50 + header | 5,005 | 0.843 | +0.086 [0.000, +0.171] | 0.660 | +0.071 [+0.007, +0.138] | 1.47 s |

**Dev hit@5 per type** (n): D0 / D1 / D2 / D3

| Type (n) | D0 | D1 | D2 | D3 |
|---|---|---|---|---|
| paraphrase (12) | 0.42 | 0.58 | 0.50 | 0.58 |
| multi_passage (11) | 0.82 | 0.73 | 0.82 | 0.91 |
| factual (12) | 0.67 | 0.58 | 0.75 | 0.83 |
| exact_identifier (18) | 0.94 | 0.83 | 1.00 | 1.00 |
| version_specific (13) | 0.92 | 0.92 | 0.92 | 1.00 |
| ambiguous (4) | 0.50 | 0.75 | 0.75 | 0.25 |

These groups are small and indicative only.

**Decisions by the rule:**
- **D2 beats D0, and is the only variant that qualifies.** Chosen.
- **D4 not built:** it needed D3 to qualify too.
- **Context budget:** D2's hit@8 − hit@5 = +0.014 (1 question), below 0.05, so 5 chunks
  stay.

**Test, one run each (65 answerable questions):**
- **Retrieval, D2 vs D0:**
  - hit@5 0.769 → 0.800, Δ +0.031, CI [−0.046, +0.108]
  - nDCG@10 0.608 → 0.597, Δ −0.011, CI [−0.063, +0.027]
  - R@5 Δ +0.023, CI [−0.038, +0.087]
- **No demonstrated difference on test.**

**Answers, test** (D2 settings vs 009b's D0 run; `gpt-oss-20b`; deterministic metrics, no
judge):

| | D0 (009b) | D2 |
|---|---|---|
| Answered (answerable) | 56/65 (86 %) | 59/65 (91 %) |
| Wrong refusals: retrieval miss / generation | 8 / 1 | 5 / 1 |
| Unanswerable correctly refused | 5/5 | 5/5 |
| Context hit | 77 % | 80 % |
| Citation precision / evidence coverage | 58 % / 82 % | 55 % / 81 % |
| Prompt / completion tokens | 99.7k / 15.4k | 116.8k / 16.7k |
| Total latency p50 / p95 | 10.3 s / 16.3 s | 12.9 s / 18.6 s |
| Errors | 0 | 0 |

**Caveat:** the two answer runs were 13 days apart on a hosted model, so provider-side drift
can't be ruled out.

**Reading:**
- **Larger chunks help get the evidence into context.** D1 shows smaller chunks hurt
  (nDCG −0.048).
- **On test the effect is within noise for retrieval,** while answers moved the same way as
  dev: three more answered, three fewer retrieval misses.
- **The decision follows the pre-registered rule, and you chose to adopt it;** the test
  evidence alone would not have demonstrated it.
- **The contextual header looks promising,** especially for version-specific, multi-passage
  and factual questions, but missed the bar by the narrowest margin.

### Future Work
- **Header variants:** evaluate D2 + header (450/75-ctx) and D3 on benchmark v2 or another
  dataset, not this dev split again.
- **Index headers** in keyword search if hybrid search is revisited.
- **A cleanup command** for unused chunk variants (150/30, 300/50, 300/50-ctx are kept for
  reproducibility).
- **011:** failure-scenario tests and clean stops on daily rate limits (from 009b).

### Modified Files
| File | Why |
|---|---|
| `app/evaluation/metrics.py`, `records.py`, `report.py`, `runner.py` | hit@k; `RunConfig.chunker` |
| `app/ingestion/chunking.py`, `pipeline.py`, `cli.py` | Variant naming, contextual header, `rechunk` |
| `app/retrieval/service.py`, `reranking.py` | `SearchOptions.chunker`; reranker input with header |
| `app/documents/repository.py` | `list_documents_missing_chunker` |
| `app/evaluation/answer_records.py`, `answer_runner.py`, `answer_report.py` | Chunker in answer records |
| `app/core/config.py`, `.env.example`, `app/worker.py` | `CHUNK_CONTEXT_HEADER`; defaults 450/75 adopted |
| `tests/...` | hit@k, header/offsets, search parity, rechunk, runner; shared fixture move |
| `eval/configs/d0-…d3-*.yaml`, `answers-d2-tokens450.yaml` | Experiment D configurations |
| `eval/reports/d*-{dev,test}.*`, `compare-d*`, `answers-d2-tokens450-test.*` | Results |
| `.claude/{architecture,database,api-spec,tasks,plan}.md`, this file | Docs |
