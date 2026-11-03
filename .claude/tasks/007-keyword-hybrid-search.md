# Task 007 — Keyword search (Postgres FTS) + RRF hybrid (Experiment B)

**Status:** 🔨 Code done; Experiment B reports pending the code commit
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
- [ ] Commit 1 (code) after confirmation
- [ ] Experiment B: dev runs + comparisons, choice recorded, one test run + comparison
- [ ] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [database.md](../database.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
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
