# Task 010 — Chunking and context experiments (Experiment D)

**Status:** 🔨 Code done; Experiment D runs pending the code commit
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
- [ ] Commit 1 after confirmation
- [ ] Dev: rechunk D1–D3, run D0–D3 (+D4 if triggered), decision by the rule
- [ ] Test: chosen vs D0; if adopted, settings change + test answer run vs 009b
- [ ] Update [architecture.md](../architecture.md), [database.md](../database.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [ ] Commit 2 after confirmation

---

## Handover

*(Filled in after implementation.)*

### Summary
### Architecture Notes
### Deviations from the plan
### Database Changes
### API Changes
### Evaluation Results
### Future Work
### Modified Files
