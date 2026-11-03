# Task 007 — Keyword search (Postgres FTS) + RRF hybrid (Experiment B)

**Status:** ✅ Done (Experiment B: hybrid not adopted)
**Week:** W2 · **Modules:** `app/retrieval`, `app/evaluation` (config), migrations ·
**Branch:** `task/007-keyword-hybrid` (off `task/006b-evaluation-runs-api`)

## Goal

Add keyword retrieval over chunks (PostgreSQL full-text search), and hybrid retrieval that
fuses dense and keyword rankings with Reciprocal Rank Fusion. Expose both through
`POST /v1/search` (`mode: keyword | hybrid`) and the evaluation `RunConfig`. Then run
**Experiment B:** does hybrid beat the dense baseline, overall and per `query_type`,
especially `exact_identifier` vs `paraphrase`?

## Scope

In:
- **Migration `0005_chunk_tsv`:** `chunks.tsv`, a stored generated column
  `to_tsvector('english', text)`, with a GIN index. Existing chunks are filled by Postgres
  when the column is added, so no re-ingest is needed.
- **`repository.keyword_search`:** same scoping as dense search (tenant, chunker, embedding
  model, optional source and version). It ORs the query terms and ranks by `ts_rank_cd`.
- **`fusion.py`:** `fuse_rankings_rrf`, a pure function of about 15 lines.
- **`service.search` takes a `SearchOptions`** (mode, k, fusion depth, RRF k, filters) and
  dispatches through a `{mode: retriever}` table.
- **Per-stage diagnostics:**
  - each hit's `dense_rank` and `keyword_rank`
  - latency per stage: `embed_query`, `dense`, `keyword`, `fuse`, `total`
- **`SearchRequest.mode`** accepts `keyword` and `hybrid`. **`RunConfig.retriever`**
  accepts `keyword` and `hybrid`, plus `fusion_depth` and `rrf_k`.
- **Experiment B:**
  - configs `keyword` and `hybrid-rrf`
  - dev runs compared with `dense-baseline-dev`, then one test run of the chosen
    configuration compared with `dense-baseline-test`
  - reports committed in a second commit, as in 006a

Out:
- Reranking (008).
- Weighting heading paths into the keyword index, other text-search configurations
  (`simple`), and tuning RRF k. These are listed as future options, not tuned here (see
  Risks).
- Re-chunking (010).

## Assumptions

1. **Text-search configuration `english`** (stemming plus stop words). Identifiers survive:
   `--timeout-keep-alive` indexes as `timeout-keep-al`, `timeout`, `keep` and `aliv`, and
   `use_cache=False` as `use`, `cach`, `fals` (checked on the dev database).
2. **The keyword index covers chunk text only.** The dense embeddings also cover only the
   chunk text, so the two retrievers see the same input.
3. **RRF uses k = 60**, the constant from Cormack, Clarke & Büttcher (2009), with a
   per-retriever candidate depth of 50. Fixed in advance, not tuned on the benchmark.
4. **The API's default mode stays `dense`** until the experiment says otherwise. Changing
   the default is a decision for after the test run, recorded in the handover.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Query parser | `plainto_tsquery('english', q)` with its `&` replaced by `\|` (OR) | Measured on the dev DB: full questions match 0 chunks with AND, and 1,487–3,320 with OR. `websearch_to_tsquery` is unsuitable because it reads a leading `-` as NOT, so `--timeout-keep-alive` became `!!(...)` |
| Ranking | `ts_rank_cd(tsv, query)` desc, chunk id as tie-break | Cover density rewards chunks where matched terms sit close together; the tie-break keeps runs deterministic (as dense) |
| Empty queries | A query of only stop words ("what was it?") produces an empty tsquery, so keyword returns `[]` without querying; hybrid then equals dense | Postgres would otherwise warn and match nothing |
| Index | Stored generated column + GIN, declared in the model with `Computed(...)` | Computed once at write time; the search query stays a plain column match |
| Fusion | `fuse_rankings_rrf(rankings, k=60)`: score(d) = Σ 1 / (k + rank_r(d)) over the rankings containing d; ties broken by best single rank, then chunk id | Uses ranks only, so cosine similarity and `ts_rank_cd` (incomparable scales) never need normalising |
| Candidate depth | Each retriever returns `fusion_depth` (default 50) candidates, fused, then cut to k | A chunk ranked 30th by one retriever can still win if the other ranks it highly |
| Dispatch | `RETRIEVERS: dict[str, Callable]` in `service.py` (dense, keyword, hybrid); `SearchOptions` dataclass | OCP as written in [coding-standards.md](../coding-standards.md): a new mode is a new entry, not an `if` chain. Rerank (008) wraps the result |
| Score field | `hit.score` = cosine for dense, `ts_rank_cd` for keyword, RRF score for hybrid; the response says which via `diagnostics.mode` | One field, documented per mode, plus explicit `dense_rank` and `keyword_rank` |
| Latency stage names | `embed_query`, `dense`, `keyword`, `fuse`, `total` (`retrieve` becomes `dense`) | `retrieve` is ambiguous once there are two retrievers. This changes the `/search` diagnostics, which have no consumer yet (dashboard 014). Old reports keep their names; `compare` doesn't use latency |
| Evaluation config | `RunConfig.retriever: Literal["dense", "keyword", "hybrid"]`, `fusion_depth` (k–200, default 50), `rrf_k` (default 60). `extra="forbid"` stays | The runner passes these to the same `service.search`; there is still no second retrieval path |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `fusion.py` only fuses ranked ids; `repository.py` only runs SQL; `service.py` orchestrates and times |
| OCP | The `RETRIEVERS` table; `SearchOptions` grows a rerank field in 008 without touching the retrievers |
| DRY | Dense and keyword search share one scoping helper (tenant, chunker, model, filters) and one hit-building path |
| Test by risk | Fusion maths, tenant isolation of the new query, OR semantics, identifier tokens, empty queries |

### Dependencies added
None.

## Files to create / modify

```
migrations/versions/0005_chunk_tsv.py      new: generated column + GIN index
app/documents/models.py                    DocumentChunk.tsv (Computed, TSVECTOR)
app/retrieval/repository.py                keyword_search; shared scoping; SearchHit + ranks
app/retrieval/fusion.py                    new: fuse_rankings_rrf
app/retrieval/service.py                   SearchOptions, RETRIEVERS, per-stage timing
app/retrieval/schemas.py, router.py        mode keyword|hybrid; dense_rank/keyword_rank; score docs
app/evaluation/records.py                  RunConfig.retriever, fusion_depth, rrf_k
app/evaluation/runner.py                   build SearchOptions from RunConfig
tests/retrieval/test_fusion.py, test_keyword_search.py   new
tests/retrieval/test_search_api.py, tests/evaluation/*   modes, config
eval/configs/keyword.yaml, hybrid-rrf.yaml new
eval/reports/*                             generated (second commit)
.claude/{architecture,api-spec,database,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/007-keyword-hybrid`.
1. **Migration and model.** Write the migration by hand, because autogenerate handles
   generated columns poorly. Then `alembic upgrade`, `alembic check`, and a downgrade and
   upgrade round trip.
2. **`fuse_rankings_rrf` and its tests** (hand-computed).
3. **`keyword_search` and the shared scoping helper.** Tests: ranking order, OR semantics,
   identifiers, empty query, tenant, chunker and model filters.
4. **`SearchOptions`, `RETRIEVERS` and per-stage timings in the service.** Then the router
   and schemas.
5. **`RunConfig` fields, and the runner passing them through.** Configs `keyword.yaml` and
   `hybrid-rrf.yaml`.
6. **Lint and the full suite.** Then docs, and commit 1 (code) after you confirm.
7. **Experiment B, from the clean tree:**
   1. Dev runs: `keyword` and `hybrid-rrf`.
   2. `compare dense-baseline-dev` against each.
   3. Choose on dev.
   4. One `--allow-test` run of the chosen configuration.
   5. `compare dense-baseline-test` against it.
   6. Handover, then commit 2 (reports) after you confirm.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Wrong fusion maths or unstable ties | Hand-computed RRF scores for two rankings; a document in only one ranking; ties ordered by best rank, then id; an empty ranking |
| Cross-tenant leakage in the new query | Keyword search never returns another tenant's chunk, or chunks of another chunker or model |
| AND semantics silently returning nothing | A multi-word question where no chunk has every term still returns the chunks with some terms, ranked by matches |
| Identifiers lost by the parser | A chunk containing `--timeout-keep-alive` is the top keyword hit for a question about it |
| Empty or stop-word queries | `"what was it?"` → keyword `[]` and no SQL error; hybrid returns the dense hits |
| API contract | `mode: keyword` and `hybrid` return ranks and per-stage latency; unknown mode → 422 |
| Eval plumbing | A `RunConfig` with `retriever: hybrid` reaches the service (fixture run) |

## Edge cases

- **A chunk in both lists:** fused once, both ranks reported.
- **Fewer than k candidates in total:** return what there is (dense always fills k when the
  tenant has at least k chunks).
- **Punctuation-heavy queries** (`{**mapping}`, `x=1&y=2`): `plainto_tsquery` ignores the
  operators, and the query is parameterised, so there is no injection.
- **Filters (`source`, `version`)** apply to both retrievers before fusion.

## Security

- The query text is passed as a bound parameter to `plainto_tsquery`, never interpolated.
  The OR rewrite operates on the tsquery's own text output, not on user input.
- Tenant scoping is shared with dense search, and a cross-tenant test guards the new
  query.
- Request limits are unchanged: query ≤ 1,000 chars, k ≤ 50, `fusion_depth` ≤ 200, and
  only `RunConfig` sets it.

## Risks

- **Tuning on a small dev set.** About 70 answerable dev questions. Only two configurations
  are compared (keyword, hybrid with the literature defaults), and no grid search. The
  choice and its bootstrap interval are recorded, and test runs once.
- **Per-type numbers flip between splits** (seen in 006a). Experiment B's acceptance
  criterion is the overall test-split comparison with its interval. Per-type deltas are
  reported as indicative.
- **Postgres FTS is a weaker BM25.** `ts_rank_cd` has no IDF. If keyword search alone is
  poor, hybrid can still help. If hybrid doesn't help, that is a result to report, not a
  reason to tune until it does.
- **Generated-column migration on large tables** rewrites the table. Here that is 5,005
  chunks, measured during the migration.

## Future improvements

- Heading-path weighting in the keyword index (setweight A), and a `simple` configuration
  for identifiers, as dev-split A/Bs.
- A BM25 extension (e.g. ParadeDB / pg_search) if `ts_rank_cd` proves the bottleneck.
- Make hybrid the API default if the test result supports it.

## Checklist

- [x] Branch `task/007-keyword-hybrid`
- [x] Migration 0005 + model; `alembic check` clean; round trip
- [x] `fuse_rankings_rrf` + tests
- [x] `keyword_search` + tests (isolation, OR, identifiers, empty query)
- [x] `SearchOptions` / `RETRIEVERS` / stage timings; API modes + tests
- [x] `RunConfig` retriever/fusion fields; configs
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Commit 1 (code) after confirmation
- [x] Experiment B: dev runs + comparisons, choice recorded, one test run + comparison
- [x] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [database.md](../database.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit 2 (reports + handover) after confirmation

---

## Handover

### Summary
Keyword retrieval (Postgres full-text search) and hybrid retrieval (dense plus keyword,
fused with Reciprocal Rank Fusion) now exist:
- in `POST /v1/search` (`mode: keyword | hybrid`)
- in evaluation configs (`retriever: keyword | hybrid`)

Migration `0005` adds `chunks.tsv` with a GIN index; existing chunks were filled in place.
193 tests pass, plus the real-model test.

**Experiment B: hybrid did not beat the dense baseline.**
- **Dev:** significantly worse (nDCG@10 −0.078, 95 % CI [−0.144, −0.014]).
- **Test:** −0.038, CI [−0.117, +0.045]; not a demonstrated difference.

The API default stays `dense`. Code is in `860c49b`, and all reports were generated from
that clean commit.

### Architecture Notes
- **Keyword query:**
  - `plainto_tsquery('english', q)` with `' & '` rewritten to `' | '`, then `@@` on
    `chunks.tsv`, ranked by `ts_rank_cd`, ties broken by chunk id.
  - The rewrite only touches the tsquery's own output (the user text is a bound
    parameter), and `&` inside quoted lexemes such as URLs is left alone (checked).
  - `websearch_to_tsquery` was rejected because it turns `--timeout-keep-alive` into a
    negation.
- **Fusion:** `retrieval/fusion.py` is a pure function. It uses ranks only, and breaks ties
  by best single rank, then id.
- **Dispatch:**
  - `service.RETRIEVERS` maps `dense`, `keyword` and `hybrid` to functions; a `_Search`
    context records each stage's latency.
  - `SearchOptions` is the one input shape for the API and the evaluation runner.
  - Reranking (008) can wrap a retriever without touching the others.
- **One scope for both retrievers:** `SearchScope` (tenant, chunker, model, source,
  version), so they always search the same chunks.
- **`chunks.tsv` is deferred in the ORM**, so it is never loaded with a chunk.

### Deviations from the plan
- **The search tests use the new signatures:** the dense-search helper and the real-model
  test now pass `SearchScope` / `SearchOptions`. Their assertions are unchanged, apart
  from the stage rename `retrieve` → `dense` that the plan announced.
- **A smoke run before commit 1.** I ran keyword and hybrid on dev into the scratchpad to
  catch problems against the real corpus. Its numbers were identical to the committed
  clean-tree runs, and no configuration was changed after seeing them.
- **Otherwise as planned:** two configurations, literature defaults, one test run.

### Database Changes
Migration `0005_chunk_tsv`:
- `chunks.tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`
- GIN index `ix_chunks_tsv`

Postgres computed the column for all 5,005 existing chunks during the migration, which
took about 6 s including Alembic startup. `alembic check` is clean, and downgrade followed
by upgrade worked.

### API Changes
`POST /v1/search`:
- `mode` accepts `keyword` and `hybrid`.
- Results carry `dense_rank` and `keyword_rank`. `score` means cosine (dense), `ts_rank_cd`
  (keyword) or the RRF score (hybrid).
- **Breaking:** the latency stage `retrieve` is renamed `dense`, alongside the new
  `keyword` and `fuse` stages. There was no consumer yet.

Details are in [api-spec.md](../api-spec.md).

### Evaluation Results
**Setup:** dataset `evidencedesk-v1` (sha256 `b77c981f…cbcf9920`), corpus v1 in tenant
`eval-corpus-v1`, chunker `tokens-300-overlap-50`, `BAAI/bge-small-en-v1.5` with the query
instruction, depth 10, git `860c49b` (clean). Same machine as 006a.

**Configurations** (fixed before any run):
- `keyword`: FTS alone
- `hybrid-rrf`: dense top-50 and keyword top-50, RRF k = 60

**Dev (70 answerable questions), against `dense-baseline-dev`:**

| config | R@5 | R@10 | MRR@10 | nDCG@10 | Δ nDCG@10 (95 % CI) | wins / ties / losses |
|---|---|---|---|---|---|---|
| dense (baseline) | 0.621 | 0.686 | 0.552 | 0.529 | — | — |
| keyword | 0.412 | 0.481 | 0.316 | 0.314 | −0.215 [−0.296, −0.136] | 11 / 20 / 39 |
| hybrid-rrf | 0.543 | 0.626 | 0.458 | 0.451 | −0.078 [−0.144, −0.014] | 15 / 30 / 25 |

**Hybrid vs dense per type** (nDCG@10, dev → test; n dev / test):

| query_type | dev | test |
|---|---|---|
| exact_identifier (18 / 12) | 0.759 → 0.645 (−0.114) | 0.504 → 0.738 (**+0.233**) |
| paraphrase (12 / 13) | 0.259 → 0.154 (−0.105) | 0.373 → 0.220 (−0.153) |
| version_specific (13 / 7) | 0.764 → 0.590 (−0.174) | 0.675 → 0.430 (−0.245) |
| factual (12 / 18) | 0.488 → 0.421 (−0.067) | 0.805 → 0.693 (−0.111) |
| multi_passage (11 / 9) | 0.410 → 0.440 (+0.030) | 0.389 → 0.393 (+0.005) |
| ambiguous (4 / 6) | 0.000 → 0.139 (+0.139) | 0.363 → 0.430 (+0.066) |

**Test (65 answerable questions), one run of `hybrid-rrf` against `dense-baseline-test`:**
- nDCG@10 0.551 → 0.513, Δ −0.038, CI [−0.117, +0.045], wins/ties/losses 14 / 28 / 23
- R@5 0.649 → 0.595, Δ −0.054, CI [−0.174, +0.067]

**Latency** (service level, 70 test queries): hybrid total p50 173 ms, p95 309 ms, against
dense p50 57 ms, p95 79 ms.
- Keyword is the slowest stage: p95 198 ms in the hybrid run, and 113 ms on its own on dev.
- ORed terms match thousands of chunks, and every one is ranked.

**Decision:** do not adopt hybrid. Dense stays the API default and the baseline for 008.
- On dev, hybrid is significantly worse. On test, the overall difference is not
  demonstrated, and hybrid costs about 3× the latency.
- The acceptance criterion in [plan.md](../plan.md), "hybrid improves R@5 or nDCG@10 over
  dense on the test split", is **not met**.

**Why (from per-question hits):**
- **`ts_rank_cd` has no inverse document frequency.** With ORed terms, chunks dense in
  common words (*validation*, *error*, *default*) outrank the chunk holding the rare,
  decisive term (`extra_forbidden`). Keyword-only nDCG@10 is 0.314.
- **RRF weights both lists equally,** so a weak keyword list pushes good dense hits down.
  That is why paraphrase and version-specific questions are hurt on **both** splits.
- **Exact identifiers flip by split, consistent with 006a.** Where dense already does well
  (dev, 0.759), keyword adds noise. Where dense struggles (test, 0.504), keyword recovers
  the identifier chunk (+0.233). This is the one signal that a *better* lexical ranker, or
  routing identifier-shaped queries, could pay off. With 12–18 questions per type it is
  indicative only.

### Future Work
- **A real BM25 ranker with IDF**, e.g. a Postgres BM25 extension or an in-process index,
  before hybrid is tried again.
- **Weighted fusion or query routing** (lexical weight only when the query contains an
  identifier pattern such as `--flag`, `snake_case` or `Error` types), decided on dev, and
  tested once.
- **Label the "Top-1 similarity" section with the retriever's score type.** For keyword and
  hybrid runs it currently shows `ts_rank_cd` or RRF scores, which are not similarities.
- **Keyword latency:** cap candidates before ranking, or rank with a cheaper function.
- Heading-path weighting and a `simple` text-search configuration, as listed in the plan.

### Modified Files
| File | Why |
|---|---|
| `migrations/versions/0005_chunk_tsv.py`, `app/documents/models.py` | Generated `tsv` column + GIN index; `TEXT_SEARCH_CONFIG` |
| `app/retrieval/fusion.py` | RRF |
| `app/retrieval/repository.py` | `SearchScope`, shared scoping, `keyword_search`, `any_term_query`, ranks on `SearchHit` |
| `app/retrieval/service.py` | `SearchOptions`, `RETRIEVERS`, hybrid, stage timings |
| `app/retrieval/schemas.py`, `app/retrieval/router.py` | Modes, ranks, score description |
| `app/evaluation/records.py`, `app/evaluation/runner.py` | `RunConfig` retriever/fusion fields; `search_options` |
| `tests/retrieval/test_fusion.py`, `test_keyword_search.py` (new); `test_search_api.py`, `test_dense_search.py`, `test_search_model.py`, `tests/evaluation/test_runner.py` | Risk-based tests; new signatures |
| `eval/configs/keyword.yaml`, `hybrid-rrf.yaml` | Experiment B configurations |
| `eval/reports/*keyword*`, `*hybrid-rrf*` | Run records and comparisons (dev ×2, test ×1) |
| `.claude/{architecture,api-spec,database,tasks,plan}.md`, this file | Docs |
