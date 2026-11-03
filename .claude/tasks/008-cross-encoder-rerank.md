# Task 008 — Cross-encoder reranking (Experiment C)

**Status:** 🔨 Code done; Experiment C reports pending the code commit
**Week:** W3 · **Modules:** `app/retrieval`, `app/ingestion/local_models.py`, `app/evaluation` ·
**Branch:** `task/008-rerank` (off `task/007-keyword-hybrid`)

## Goal

Add an optional second-stage ranker: retrieve candidates (dense, per Experiment B), re-score
each `(query, chunk)` pair with a cross-encoder, and return the top k. Then measure
**Experiment C**: how much nDCG@10 the reranker gains over the dense baseline, against how
much p95 latency it adds. Paraphrase questions, the weakest group on both splits, are the
main target.

## Scope

In:
- **A `Reranker` protocol** (`retrieval/reranking.py`) and a real gateway,
  `CrossEncoderReranker`, in `app/ingestion/local_models.py`. That file stays the only one
  importing torch and sentence-transformers.
- **`SearchOptions.rerank` (bool) and `rerank_depth` (default 50).** Reranking wraps any
  mode: the service retrieves `max(k, rerank_depth)` candidates with the chosen retriever,
  re-scores them, sorts, and cuts to k. A new stage is timed: `rerank`.
- **A `rerank_score` and the pre-rerank rank on every hit.** `score` becomes the rerank
  score when reranking is on.
- **API:**
  - `POST /v1/search` gets `rerank: bool = false`.
  - The reranker is a cached dependency, loaded on first use or at startup when
    `PRELOAD_RERANKER=true`.
- **Evaluation:**
  - `RunConfig.rerank` and `rerank_depth`.
  - The CLI builds the reranker only when a config asks for it.
  - The worker gets a lazily built reranker for `evaluate` jobs.
- **The report's "Top-1 similarity" section is labelled by score type** (cosine,
  `ts_rank_cd`, RRF or cross-encoder). This was a 007 follow-up, and it matters here
  because rerank scores are the next candidate signal for abstention (009).
- **Experiment C:**
  1. **Ceiling run first:** `dense-depth50`, cutoffs 10 and 50. Its R@50 is the ceiling a
     reranker of the top 50 can reach.
  2. **Two candidate depths on dev:** `dense-rerank20` and `dense-rerank50`. Depth is the
     latency/quality knob.
  3. **Choose on dev**, then run the choice once on test.
  4. **Compare each against `dense-baseline`.**
  5. **Two commits**, as before: code, then reports.

Out:
- Reranking hybrid results (hybrid was not adopted in B). It works through the same option
  but is not part of the experiment.
- Fine-tuning the reranker.
- Using rerank scores for abstention (009 decides that; this task only reports them).
- Batching or a GPU.

## Assumptions

1. **Model: `cross-encoder/ms-marco-MiniLM-L6-v2`** (Apache-2.0), as chosen in
   [architecture.md](../architecture.md). It is a 6-layer MiniLM trained on MS MARCO
   passage ranking. **Approving this plan approves downloading it once from huggingface.co
   (about 90 MB of weights plus tokenizer files) into the local Hugging Face cache.** It
   is not in the cache today.
2. **The reranker sees the chunk text only**, as the embedder and the keyword index do.
   Long chunks are truncated by the model at 512 tokens. Chunks are at most 300 tokens,
   so in practice only the query and chunk together can exceed that, rarely.
3. **CPU only, one process.** Each query costs one forward pass per candidate, batched (32).
   Latency is the price being measured, not a bug to optimise away here.
4. **The two depths (20, 50) are fixed in advance.** The dev choice is the cheaper depth
   unless the deeper one is better by an interval that excludes 0.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Where reranking lives | A wrapper step in `service.search`, after `RETRIEVERS[mode]` | OCP: any retriever can be reranked, and the retrievers don't change (as 007 planned) |
| Interface | `Reranker` protocol with `model_name` and `score(query, passages) -> list[float]` | One small role-specific interface (ISP). Tests use a deterministic fake, so they never load torch (DIP) |
| Gateway | `CrossEncoderReranker` in `local_models.py`: `trust_remote_code=False`, CPU, `predict(pairs, batch_size, show_progress_bar=False)` | Keeps the torch import in one module (≈40 s to import); never runs code shipped in a model repo |
| Score kept | Raw model output (no extra activation), stored as `rerank_score`; `score` = `rerank_score` when reranking. `dense_rank` / `keyword_rank` stay | Sorting needs only order. The raw value is reported for 009 to study, not interpreted as a probability |
| Ties | Higher rerank score first, then the original rank | Deterministic, and falls back to the first-stage order |
| Loading in the API | `get_reranker()`: an `lru_cache` dependency, built on the first `rerank: true` request or at startup with `PRELOAD_RERANKER` (default false) | Most requests don't rerank, so the API doesn't pay the model's memory or startup unless asked |
| Loading for runs | CLI: build when `config.rerank`. Worker: a cached factory, built on the first `evaluate` job that needs it | A dense-only run never loads the reranker |
| Run config | `rerank: bool = false`, `rerank_depth: int = 50` (k–200) | Same shape as `fusion_depth` in 007; `extra="forbid"` stays |
| Ceiling diagnostic | A `dense-depth50` run with `depth: 50, cutoffs: [10, 50]` | Without it, a small gain could be "the reranker is weak" or "the evidence isn't in the top 50". R@50 separates the two |
| Report score labels | `records.EffectiveSettings` gains `score_kind` (cosine \| ts_rank_cd \| rrf \| cross_encoder) | The report then says what its "Top-1" column is; old records default to `cosine` |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `reranking.py` holds the protocol and reordering; `local_models.py` holds the model; `service.py` orchestrates and times |
| OCP | Reranking is a step after any retriever, not a fourth mode |
| ISP / DIP | A one-method `Reranker`; services depend on it, never on sentence-transformers |
| DRY | The runner, worker and API all go through `service.search` with `SearchOptions` |

### Dependencies added
None. `sentence-transformers` 6.2.0 already provides `CrossEncoder`. The model download is
data, not a package.

## Files to create / modify

```
app/retrieval/reranking.py         new: Reranker protocol, rerank_hits()
app/ingestion/local_models.py      + CrossEncoderReranker
app/retrieval/service.py           rerank step, SearchOptions.rerank / rerank_depth, stage timing
app/retrieval/repository.py        SearchHit + rerank_score, first_stage_rank
app/retrieval/deps.py              + get_reranker (cached, lazy)
app/retrieval/schemas.py, router.py   rerank flag, rerank_score, first_stage_rank
app/main.py                        preload the reranker when PRELOAD_RERANKER
app/core/config.py, .env.example   RERANKER_MODEL_NAME, RERANKER_BATCH_SIZE, PRELOAD_RERANKER
app/evaluation/records.py          RunConfig.rerank / rerank_depth; EffectiveSettings.score_kind
app/evaluation/runner.py, cli.py, service.py   pass a reranker when the config asks
app/evaluation/report.py           label the top-1 section by score kind
app/worker.py                      lazy reranker factory for evaluate jobs
tests/fakes.py                     + FakeReranker
tests/retrieval/test_rerank.py     new; API + eval plumbing tests; one model-marked test
eval/configs/dense-depth50.yaml, dense-rerank20.yaml, dense-rerank50.yaml
eval/reports/*                     generated (second commit)
.claude/{architecture,api-spec,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/008-rerank`.
1. **Download the model** (approved with this plan) and confirm it loads with
   `trust_remote_code=False`.
2. **`Reranker` protocol, `rerank_hits()` and `FakeReranker`.** Tests: reordering,
   ties, an empty list, depth.
3. **Service rerank step, stage timing and `SearchHit` fields.** Then the API flag,
   `get_reranker` and the preload setting.
4. **`CrossEncoderReranker`, plus one `model`-marked test:** a relevant passage outscores
   an unrelated one.
5. **Evaluation plumbing:**
   - `RunConfig` fields and `score_kind`.
   - CLI, runner and worker pass the reranker.
   - The report label.
   - The three configs.
6. **Lint, full suite and docs.** Commit 1 (code) after you confirm.
7. **Experiment C, from the clean tree:**
   1. `dense-depth50` (dev).
   2. `dense-rerank20` and `dense-rerank50` (dev).
   3. Compare each against `dense-baseline-dev` and choose.
   4. One `--allow-test` run of the choice.
   5. Compare it against `dense-baseline-test`.
   6. Handover. Commit 2 (reports) after you confirm.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Reranking reorders wrongly or loses hits | `FakeReranker` with known scores: output order, k cut, ties falling back to the first-stage rank; the first-stage rank is preserved on each hit |
| Reranking the wrong candidate set | The base retriever is asked for `max(k, rerank_depth)` candidates; with `rerank_depth=3, k=2`, exactly 3 pairs are scored |
| A dense-only request loads the model | `get_reranker` is never called when `rerank` is false (dependency spy) |
| API contract | `rerank: true` returns `rerank_score`, `first_stage_rank`, and a `rerank` latency stage |
| Eval plumbing | `RunConfig(rerank=True)` reaches the service; a run without a reranker but with `rerank: true` fails with a clear error |
| The real model behaves as a relevance scorer | A `model` test: a query about keep-alive scores the keep-alive passage above an unrelated one |

## Edge cases

- **No candidates** (an empty tenant, or keyword with stop words only): the reranker is not
  called.
- **Fewer candidates than k:** all are reranked and returned.
- **Very long query** (up to 1,000 characters): the model truncates the pair to 512 tokens.
  The chunk side may lose its tail.
- **`rerank: true` with `mode: keyword | hybrid`** works and is tested once. It is not part
  of the experiment.

## Security

- **Model loading:** `trust_remote_code=False`. Weights come from the model repository
  named in settings, downloaded once with your approval.
- **Inputs and limits:** the query and chunk text go only to the local model; nothing
  leaves the machine. Limits are unchanged (query ≤ 1,000 chars, k ≤ 50, `rerank_depth` ≤
  200, and only `RunConfig` sets the depth).
- **No new endpoints or roles.** `rerank` is a request option for any viewer. Its cost per
  request is bounded by the API's fixed rerank depth of 50.

## Risks

- **Latency.** Fifty pairs on CPU may add hundreds of milliseconds. That is the trade-off
  being measured: depth 20 vs 50 gives two points on the curve, and p95 is reported with
  the environment.
- **Domain shift.** MS MARCO is web search, while this corpus is technical documentation
  with code. Gains may be smaller than published ones. The ceiling run shows how much room
  there was.
- **Small groups, per-type flips** (006a, 007). The verdict uses the overall test
  comparison with its interval; per-type results are indicative.
- **First-call cost in the API.** Loading on the first rerank request takes seconds. It is
  documented, and `PRELOAD_RERANKER` exists for deployments that use reranking.

## Future improvements

- Use rerank scores for abstention thresholds (009).
- Prepend the heading path to the passage, or try a larger reranker (e.g. a 12-layer or a
  BGE reranker), as dev A/Bs.
- Rerank hybrid candidates once a better lexical ranker exists (007 follow-up).
- Serve the reranker in a separate process, or ONNX-quantise it, if API latency matters.

## Checklist

- [x] Branch `task/008-rerank`; model downloaded and loads
- [x] `Reranker` protocol, `rerank_hits`, `FakeReranker` + tests
- [x] Service rerank step, `SearchHit` fields, API flag, `get_reranker`, preload setting + tests
- [x] `CrossEncoderReranker` + model-marked test
- [x] `RunConfig` / `score_kind` / CLI / worker / report label + tests; configs
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [ ] Commit 1 (code) after confirmation
- [ ] Experiment C: ceiling run, two dev depths, choice, one test run, comparisons
- [ ] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [ ] Commit 2 (reports + handover) after confirmation

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
