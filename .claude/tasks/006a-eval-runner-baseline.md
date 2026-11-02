# Task 006a — Evaluation runner, reports and the dense baseline (Experiment A)

**Status:** 🔨 Implemented; test run and final reports pending the code commit
**Week:** W2 · **Modules:** `app/evaluation`, `eval/configs/`, `eval/reports/` ·
**Branch:** `task/006a-eval-runner` (off `task/005c-benchmark-v1`)

## Why 006 is split

The roadmap row for 006 bundles two features:
- a runner that scores retrieval against the benchmark, with its report
- persisted runs: tables, a worker job and three API endpoints

Experiment A needs only the first. The second exists for the dashboard (014) and the CI gate
(013), and adds a migration, a job kind and tenant-scoped endpoints with cross-tenant tests.
Splitting keeps each PR to one feature, as 005 was split into 005a/b/c.

| Task | Scope |
|---|---|
| **006a (this plan)** | Runner, CLI, JSON + Markdown reports, run comparison; Experiment A on the real corpus |
| 006b | `evaluation_runs` / `evaluation_results` tables, the `evaluate` worker job, `POST/GET /v1/evaluations/runs`; it reuses the 006a runner unchanged |

## Goal

One command scores a retrieval configuration on a dataset split. It writes a report that
anyone can reproduce:
- dataset hash, split, configuration, models and git SHA
- P@k, R@k, MRR and nDCG@k, overall and per `query_type`, with counts
- latency p50 and p95

Then measure the **dense baseline (Experiment A)** on the real corpus, and settle the
query-instruction A/B that task 004 deferred to this task.

## Scope

In:
- **`app/evaluation/runner.py`:** for each question in the split, call the existing
  `retrieval.service.search` and match the hits against the evidence spans with
  `relevance.match_evidence`. Score each question with `metrics.score_query` at every
  cutoff, then aggregate.
- **A run configuration file** (`eval/configs/*.yaml`) validated by a Pydantic model.
- **A corpus check before every run:** each document the dataset cites must be ingested in
  the tenant with exactly the bytes in `corpus/`. If not, the run stops.
- **Reports in `eval/reports/`:**
  - `<run>.json`: the full record, including per-query results.
  - `<run>.md`: the human-readable report.
  - `compare-<a>-vs-<b>.md`: per-type deltas between two runs, per-query win/tie/loss
    counts, and a paired bootstrap 95 % interval on the delta.
- **CLI commands:**
  - `run --config --dataset --split --tenant [--allow-test]`
  - `compare <a.json> <b.json>`
- **Experiment A:**
  1. Load corpus v1 into a dedicated tenant.
  2. Run the baseline with and without the BGE query instruction on `dev`, and pick one.
  3. Run the chosen configuration once on `test` and record it as the baseline that 007 is
     compared against.
  4. Commit the reports.

Out:
- Tables, the worker job and the API (006b).
- Keyword and hybrid search (007), reranking (008), answer metrics (009).
- Changing the chunker or the embedding model (010).

## Assumptions

1. **The corpus is loaded into a tenant named `eval-corpus-v1`**, created with the existing
   `auth.cli create-tenant` and filled with `ingestion.cli load-corpus --process`. The dev
   database is currently empty. 005b measured the load at about 11 minutes.
2. **Only settings fix the chunker and the embedding model** (`tokens-300-overlap-50`,
   `BAAI/bge-small-en-v1.5`). A run records them but cannot change them, because changing
   them needs a re-ingest (Experiment D, task 010).
3. **The query instruction can vary per run** because it applies only at query time. The
   config sets it; when it is omitted, the run uses the setting.
4. **Retrieval depth is 10, and metrics are computed at k = 5 and k = 10.** These are the
   primary metrics in [plan.md](../plan.md): R@5, nDCG@10, MRR, p95.
5. **Unanswerable questions are run but not scored.** Their top score is recorded as a
   diagnostic for the abstention work in 009, as 005a defined.
6. **Runs go through the service layer directly**, not over HTTP. That is the same code the
   API calls, minus auth and serialisation. The latency reported is therefore service
   latency, labelled as such.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| What the runner calls | `retrieval.service.search` | No second retrieval path, so the evaluation measures exactly what `/v1/search` serves (DRY). Adding a retriever in 007 changes the service, not the runner |
| Where the corpus check lives | `runner.verify_corpus()`: sha256 of each cited `(slug, version)` file vs `documents.content_hash` | Labels are character offsets. If the stored text differs by one byte, every score is silently wrong. One query per run, by slug and version |
| How the corpus check queries | A new `evaluation/repository.py` with one tenant-scoped query (cited documents' slug, version, hash, chunk count) | Repositories own SQL; the runner stays testable |
| Config format | YAML → `RunConfig` (Pydantic, `extra="forbid"`): `name`, `retriever: dense`, `depth`, `cutoffs`, `query_instruction?` | Same style as the dataset source. `retriever` is a `Literal` with one value today; 007 adds `keyword` and `hybrid` |
| Test-split guard | `--split test` needs `--allow-test`, and the report states it was a test run | Makes peeking at test a deliberate act ([CLAUDE.md](../CLAUDE.md): tune on dev only) |
| Failure listing | The Markdown report lists questions with R@10 = 0 and their top-3 slugs, **for dev runs only** | A failure analysis on test would invite tuning to test |
| Report storage | JSON is the record; Markdown is rendered from the JSON | `compare` and 006b read the same JSON; no regex over Markdown |
| Comparing runs | Per-type deltas, per-query win/tie/loss on nDCG@10, paired bootstrap 95 % CI on mean delta (1,000 resamples, fixed seed) | About 65 answerable dev questions are few. A delta without an interval would overclaim. It is about 20 lines of stdlib code, so no SciPy |
| Overlap bands | Also aggregate by word overlap: below vs at-or-above the median of the split | 005c's drafting-bias measure. Shows whether dense search does better on questions that reuse the passage's words |
| Latency | One unmeasured warm-up query, then per-stage times from `SearchOutcome.latency_ms`; p50/p95 per stage | The first call pays one-off costs that would distort p95 on ~80 queries |
| Git SHA | `git rev-parse HEAD` plus a dirty flag, read in the CLI | A run from a dirty tree is allowed but flagged. Committed reports must come from a clean tree |
| Environment in the report | Python version, OS, CPU count, Postgres server version | [PROJECT.md](../PROJECT.md): results state hardware and configuration |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `runner.py` scores; `report.py` renders; `repository.py` queries; `cli.py` parses arguments and does file I/O |
| DRY | Retrieval, span matching and metrics are reused unchanged; `report.py` renders both the run and the compare views from the same JSON models |
| OCP | New retrievers (007) and rerankers (008) extend `RunConfig` and the service; the runner does not change |
| DIP | The runner takes the `Embedder` protocol; tests pass `FakeEmbedder` and never load torch |
| Small functions, flat flow | Per-question scoring, aggregation, the bootstrap and rendering are separate functions; guard clauses for the corpus check and the test guard |

### Dependencies added
None. YAML parsing, Pydantic and the stdlib cover it; the bootstrap uses `random.Random(seed)`.

## Files to create / modify

```
app/evaluation/runner.py            new: RunConfig, verify_corpus, run_evaluation, scoring
app/evaluation/repository.py        new: cited-document lookup (tenant-scoped)
app/evaluation/report.py            new: run and compare models, Markdown rendering, bootstrap
app/evaluation/cli.py               + run, compare commands
tests/evaluation/test_runner.py     new
tests/evaluation/test_report.py     new
tests/evaluation/test_cli.py        + run / compare / test-split guard
eval/configs/dense-baseline.yaml    new
eval/configs/dense-no-instruction.yaml  new
eval/reports/*.json, *.md           generated, committed
.claude/{architecture,api-spec,tasks,plan}.md, eval/datasets/README.md (run command)
```

## Run record (`eval/reports/<run>.json`)

```
header:  run_name, created_at, dataset {name, sha256, split}, config (RunConfig as given),
         effective {chunker, embedding_model, query_instruction, min_overlap_fraction},
         git {sha, dirty}, environment {python, os, cpu_count, postgres}, corpus_check {documents, ok}
metrics: {"5": {all, <query_type>...}, "10": {...}}   each = {count, precision, recall, mrr, ndcg}
overlap_bands: {"10": {low, high}}                    median threshold recorded
latency_ms: {stage: {p50, p95}}                       stages from the service
questions: [{id, query_type, answerable, word_overlap,
             hits: [{rank, slug, version, char_start, char_end, heading_path, score, matched_items}],
             scores: {"5": {...}, "10": {...}} | null, latency_ms}]
```

Chunk text is not stored; offsets identify it. Hits are kept for every question, so
failures can be analysed without re-running.

## Step-by-step implementation plan

0. `git switch -c task/006a-eval-runner`.
1. **`RunConfig` and the config files.** Tests: valid file; unknown key; cutoff larger than
   depth.
2. **`repository.cited_documents` and `runner.verify_corpus`.** Tests:
   - matching hashes pass
   - a changed byte fails and names the document
   - a document that was never ingested fails
   - a document of another tenant is not visible
   - zero chunks for the configured chunker fails
3. **`run_evaluation`.** Hits become `Span`s, are matched, and scored per cutoff; then
   aggregation, overlap bands and latency percentiles. Uses `FakeEmbedder` plus a small
   ingested fixture tenant with hand-placed spans, so expected scores are computed by hand.
4. **`report.py`.** Markdown for a run and for a comparison; the paired bootstrap; win/tie/loss.
5. **CLI `run` and `compare`.** The CLI covers the git SHA, the environment, the test guard
   and file output.
6. **Lint and tests**, then docs.
7. **Experiment A:**
   1. Create the tenant and load corpus v1 (about 11 minutes).
   2. `run dense-baseline` on dev and `run dense-no-instruction` on dev, then `compare`.
   3. Choose the configuration on dev and write the reason in the handover.
   4. One `--allow-test` run of the chosen configuration.
   5. Commit the reports from a clean tree.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Scores computed against a corpus with different bytes | `verify_corpus` fails on a one-byte change, a missing document, and zero chunks |
| Wrong metric plumbing (cutoffs, unanswerable handling, alternative spans) | Fixture run with hand-computed P/R/MRR/nDCG at k = 5 and 10; unanswerable questions appear unscored and are not counted |
| Tenant leakage in the corpus check | Documents of another tenant are invisible to `cited_documents` |
| Accidental test-split runs | `run --split test` without `--allow-test` exits non-zero and writes nothing |
| Overclaiming in comparisons | Bootstrap on identical runs gives a CI around 0; a hand-built case gives the expected win/tie/loss counts; same seed gives the same CI |
| Report says something the JSON doesn't | Markdown is rendered from the JSON model; a test checks the per-type counts and the dataset hash appear |

Model-backed runs are not part of the default test suite (the `model` marker, as in 004).

## Edge cases

- **A split with no answerable questions of a type:** that type is omitted from the metric
  table and listed under "not scored".
- **Fewer than k hits returned:** precision still divides by k, as 005a defined.
- **A query returning zero hits** scores 0 and still counts.
- **A question citing a document the dataset knows but the tenant lacks:** caught by the
  corpus check before any query runs.
- **Ties in retrieval:** chunk id breaks them (task 004), so a re-run returns the same
  order. CPU embeddings may still differ in the last float bits across machines; the report
  records the environment.

## Security

- The CLI uses direct database access with a tenant chosen by name: the operator path, as
  in `load-corpus`. Every query is tenant-scoped.
- Reports hold questions, slugs, offsets and scores, never chunk text or credentials. The
  corpus is public documentation in any case.
- The git and environment lookups run fixed commands with no user input.

## Risks

- **Small groups:** 4 ambiguous and 10 unanswerable questions in dev. Report counts next to
  every number; the bootstrap interval makes the uncertainty visible.
- **Instruction A/B overfitting:** one binary choice on dev, decided once and recorded. That
  is the intended use of dev.
- **Latency noise on a laptop:** p95 is reported with the environment and is not compared
  across machines.
- **Long runs:** loading the model takes about 70 s. About 80 queries at ~50 ms is seconds,
  so the model load dominates.

## Future improvements

- 006b: persisted runs, worker job and API.
- Per-source breakdown (FastAPI, Starlette, Uvicorn, Pydantic, incidents) if Experiment A
  shows uneven results.
- A CI regression gate on the dev split (013).

## Checklist

- [x] Branch `task/006a-eval-runner`
- [x] `RunConfig` + config files + tests
- [x] `cited_documents` + `verify_corpus` + tests (incl. cross-tenant)
- [x] `run_evaluation` + fixture-based metric tests
- [x] `report.py` (run + compare, bootstrap) + tests
- [x] CLI `run` / `compare` + test-split guard + tests
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Tenant `eval-corpus-v1` loaded; corpus check passes
- [x] Experiment A: dev A/B run, choice recorded
- [ ] One test run and final reports from the committed tree
- [ ] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md) (CLI line), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [ ] Propose commit message, commit after confirmation

---

## Handover

### Summary
`python -m app.evaluation.cli run` scores a retrieval configuration on a dataset split.
`python -m app.evaluation.cli compare` contrasts two runs.

A run works like this:
1. It checks that the tenant holds exactly corpus v1: the same documents, the same bytes,
   and all of them chunked.
2. It sends every question of the split through the real search service, after one
   unmeasured warm-up query.
3. It scores each question at k = 5 and 10 and writes two files:
   - `eval/reports/<config>-<split>.json`, the full record: provenance, aggregates per
     `query_type` and per word-overlap band, latency, and every question's hits.
   - A Markdown report rendered from that JSON.

`compare` reports:
- per-type deltas
- per-question wins, ties and losses
- a paired bootstrap 95 % interval on the mean delta

Corpus v1 was loaded into the `eval-corpus-v1` tenant: 285 documents, 5,005 chunks, 0
failed jobs. Experiment A was run on dev.

166 tests pass (22 new).

### Architecture Notes
- **New modules in `app/evaluation`:**

  | Module | Role |
  |---|---|
  | `runner.py` | Orchestration and scoring |
  | `records.py` | The JSON record format and `RunConfig` |
  | `report.py` | Markdown rendering, bootstrap, win/tie/loss |
  | `repository.py` | Tenant-scoped document listing; Postgres version |
  | `provenance.py` | Git SHA and dirty flag; environment |

  The CLI only parses arguments and writes files.
- **No second retrieval path.** The runner calls `retrieval.service.search`. For the same
  reason, the chunker name now comes from a single place, `retrieval.service.configured_chunker()`,
  and the document hash rule from `documents.service.compute_content_hash()`.
- **The dirty flag ignores `eval/reports/`** (runs write there) and untracked files.
  Reports must be generated from a committed tree to carry an exact SHA.
- **Unanswerable questions** are run and their top-1 similarity is reported. That number
  is the starting point for the abstention threshold in 009.

### Deviations from the plan
- **The corpus check covers every manifest document, not only the cited ones.** A missing
  or extra distractor document changes rankings just as a changed evidence page does. The
  check also reports documents in the tenant that are not in the manifest.
- **The record models live in a new `records.py`, not in `report.py`.** Both the runner and
  the report use them, and keeping them apart avoids an import cycle.
- **A new `provenance.py`** holds the git and environment lookups. They were planned for
  the CLI, but there they would have made the run orchestration untestable without a
  subprocess.
- **The `eval-corpus-v1` tenant was created as a bare tenant row**, without the
  `create-tenant` CLI. That command requires an interactive admin password, and the
  evaluation tenant needs no users.
- **Loading the corpus took 16 min 19 s**, against about 11 min in 005b, on the same
  machine.
- **Two small refactors to share one rule each:** `compute_content_hash()` and
  `configured_chunker()`. Behaviour is unchanged.

### Database Changes
None. The `eval-corpus-v1` tenant and its corpus exist only in the local dev database; the
README's commands recreate them.

### API Changes
None (006b). New CLI commands, `run` and `compare`, are listed in
[api-spec.md](../api-spec.md).

### Evaluation Results
**Setup:**
- dataset `evidencedesk-v1`, sha256 `b77c981f…cbcf9920`, split **dev**: 80 questions, of
  which 70 are answerable
- corpus v1, chunker `tokens-300-overlap-50`, model `BAAI/bge-small-en-v1.5`, exact cosine
  search, depth 10
- span match: overlap ≥ 0.5 × the shorter range
- machine: Windows 11, Intel 8 CPUs, Postgres 16.14 in Docker
- reports in `eval/reports/`

**Experiment A, dense baseline with the BGE query instruction (dev):**

| query_type | n | R@5 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.621 | 0.686 | 0.552 | 0.529 |
| exact_identifier | 18 | 0.944 | 0.944 | 0.769 | 0.759 |
| version_specific | 13 | 0.885 | 0.885 | 0.823 | 0.764 |
| factual | 12 | 0.625 | 0.708 | 0.525 | 0.488 |
| multi_passage | 11 | 0.455 | 0.545 | 0.485 | 0.410 |
| paraphrase | 12 | 0.208 | 0.417 | 0.206 | 0.259 |
| ambiguous | 4 | 0.000 | 0.000 | 0.000 | 0.000 |

**Overlap bands and latency:**
- By word overlap @10, split at the median of 0.32:
  - below the median (35 questions): R@10 0.586, nDCG@10 0.459
  - at or above it (35 questions): R@10 0.786, nDCG@10 0.600
- Latency for 80 queries, service level: total p50 70.0 ms, p95 85.0 ms (embedding the
  query: p50 32.3 ms; retrieval: p50 37.6 ms).
- A repeated run gave identical metrics and rankings. Latency varied between runs: p95
  85.0 ms vs 91.7 ms.

**Query-instruction A/B (dev, without instruction minus with instruction):**
- **Overall:**
  - R@5 −0.014, 95 % CI [−0.057, +0.021], wins/ties/losses 2/66/2
  - MRR@10 −0.020, CI [−0.062, +0.021]
  - nDCG@10 −0.023, CI [−0.055, +0.012], 8/50/12
- **Per type, without the instruction:**
  - factual R@10 is 0.250 lower (12 questions)
  - version_specific MRR is 0.122 lower
  - multi_passage is slightly higher

**Decision:** keep the instruction (the `dense-baseline` configuration). Removing it is
worse on every overall metric, although no interval excludes 0, so this is a weak
preference, not a demonstrated difference. Keeping the instruction is also the model
card's recommendation and the current default, so nothing in the API changes.

**Findings for 007–010:**
- **Paraphrase questions are the weak spot** (R@5 0.208). Questions that share fewer words
  with their evidence score lower overall: 0.459 vs 0.600 nDCG@10. Reranking (008) is the
  natural test.
- **Exact identifiers already score R@5 0.944 with dense search alone.** Hybrid search
  (007) has little headroom there; its effect should be read per type.
- **Several misses retrieve the right incident but the wrong section.** q-0023, q-0063 and
  q-0071 get the incident's title, symptoms or timeline chunks, while the labelled root
  cause or fix is not in the top 10. Heading-aware chunking makes each short incident
  section its own chunk, which is an Experiment D (010) question.
- **Ambiguous questions get 0 recall** (4 questions). Their evidence is one reading per
  item, so a vague query finds neither.
- **Top-1 similarity separates poorly:**
  - answerable questions: mean 0.810, min 0.648
  - unanswerable questions: mean 0.725, max 0.775

  A raw similarity threshold will not be enough for abstention (009).

**Test run:** pending. It runs once, from the committed tree, after the code commit (see
the checklist).

### Future Work
- 006b: persisted runs, the `evaluate` worker job, `/v1/evaluations/runs`.
- A document-level hit rate next to span recall, to separate "wrong document" from "right
  document, wrong section".
- Per-source breakdown (FastAPI, Starlette, Uvicorn, Pydantic, incidents).
- Latency across several repeated runs, instead of a single run's p95.

### Modified Files
| File | Why |
|---|---|
| `app/evaluation/runner.py` | Config loading, corpus check, run orchestration, scoring, aggregation |
| `app/evaluation/records.py` | `RunConfig` and the JSON run record |
| `app/evaluation/report.py` | Markdown for runs and comparisons; bootstrap; win/tie/loss |
| `app/evaluation/repository.py` | Tenant-scoped stored-document listing; Postgres version |
| `app/evaluation/provenance.py` | Git SHA, dirty flag, environment |
| `app/evaluation/cli.py` | `run` and `compare` commands; parser split into two functions |
| `app/retrieval/service.py` | `configured_chunker()` shared with the runner |
| `app/documents/service.py` | `compute_content_hash()` shared with the runner |
| `tests/evaluation/conftest.py`, `test_runner.py`, `test_report.py`, `test_cli.py` | Risk-based tests |
| `eval/configs/dense-baseline.yaml`, `dense-no-instruction.yaml` | Experiment A configurations |
| `eval/reports/*` | Run records, reports, comparison |
| `.claude/{architecture,api-spec,tasks,plan}.md`, this file | Docs |
