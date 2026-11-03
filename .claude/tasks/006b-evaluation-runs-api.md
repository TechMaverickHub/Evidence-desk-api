# Task 006b — Persisted evaluation runs: tables, worker job, `/v1/evaluations/runs`

**Status:** ✅ Done
**Week:** W2 · **Modules:** `app/evaluation`, `app/worker.py`, `app/jobs`, migrations ·
**Branch:** `task/006b-evaluation-runs-api` (off `task/006a-eval-runner`)

## Goal

An admin can start an evaluation run over HTTP. The worker executes it with the 006a runner,
and anyone in the tenant can list runs and read their metrics, provenance and per-question
results. The dashboard (014) and the CI gate (013) consume this API. The CLI keeps working
unchanged and stays the way committed reports are produced.

## Scope

In:
- **Migration `0004_evaluation_runs`:** two tables.
  - `evaluation_runs`: one row per run, holding provenance and the summary.
  - `evaluation_results`: one row per question.
- **Job kind `evaluate`:** a worker handler that runs the 006a runner and stores the result
  in the same transaction as the job's success.
- **Endpoints:**

  | Method | Path | Role |
  |---|---|---|
  | `POST` | `/v1/evaluations/runs` | admin |
  | `GET` | `/v1/evaluations/runs` | viewer |
  | `GET` | `/v1/evaluations/runs/{id}?include=results` | viewer |
- **Settings:** `EVAL_DATASETS_DIR` (default `eval/datasets`) and `EVAL_CORPUS_MANIFEST`
  (default `corpus/manifest.yaml`).

Out:
- Rendering Markdown over HTTP. The JSON holds the same numbers, and the CLI renders reports.
- Comparing runs over HTTP (the dashboard compares two run summaries).
- Cancelling or deleting runs.
- The `answer` column for answer-level evaluation (task 009 adds it with its own migration).

## Assumptions

1. **A run evaluates the caller's tenant.** The tenant must hold corpus v1. Otherwise the
   006a corpus check fails the job with a readable error, recorded on the job.
2. **Datasets are named, not uploaded.** `dataset: "evidencedesk-v1"` resolves to
   `<EVAL_DATASETS_DIR>/evidencedesk-v1.jsonl`. Datasets are reviewed files under version
   control (005c); uploading them over HTTP would bypass that review.
3. **The config is sent inline as a `RunConfig`**, the same model and validation as the
   YAML files, so the dashboard can vary `depth` and `cutoffs` without new files.
4. **One worker process runs ingestion and evaluation jobs.** Its embedding model is
   loaded once and shared; a run of about 80 queries takes seconds.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Run status | **Not stored on the run.** `evaluation_runs.job_id` references the job, whose `status`, `error`, `started_at` and `finished_at` are returned with the run | One source of truth. A copied status could disagree with the job after a crash |
| What is stored | `evaluation_runs`: `dataset_name`, `dataset_sha256`, `split`, `config` JSONB, `created_by`. Filled by the worker: `effective` JSONB, `git_sha`, `git_dirty`, `environment` JSONB, `corpus_documents`, `summary` JSONB (`metrics`, `overlap_bands`, `latency_ms`). `evaluation_results`: `question_id`, `query_type`, `answerable`, `word_overlap`, `hits` JSONB, `scores` JSONB, `latency_ms` JSONB | Mirrors the 006a `RunReport`, so a stored run converts back to the same record (tested). JSONB for nested, read-only blobs; columns for what is filtered or listed |
| Results write | The handler inserts the results and fills the run in the job's own transaction | A run is never half-written: the job succeeds with complete results, or fails with none (the worker rolls back) |
| Dataset drift | POST records the dataset file's SHA-256. The worker recomputes it and fails the job if the file changed since it was queued | Otherwise a run could report numbers for a dataset other than the one requested |
| Dataset name validation | Pattern `^[a-z0-9][a-z0-9-]{0,63}$`, then must exist in `EVAL_DATASETS_DIR`. Unknown → 422 `VALIDATION_ERROR` with `field_errors.dataset` | The pattern rules out path traversal before any file access. A new `InvalidInputError` (422) joins `app/core/errors.py` for checks a schema can't express |
| Test-split guard | `split: "test"` requires `allow_test: true`, enforced by a request-model validator (422) | Same rule as the CLI's `--allow-test`. Tuning stays on dev |
| Query instruction per run | `SentenceTransformerEmbedder.for_queries(instruction)` returns a copy that **shares the loaded model**. The handler gets a `Callable[[str], Embedder]`; tests pass `lambda _: FakeEmbedder()` | A second model instance would double the worker's memory for one string |
| Reusing the runner | `runner.execute_run` takes a `tenant_id` instead of a tenant name. The CLI resolves the name first (one small change to 006a) | The worker already has the tenant id from the job, so there is no name lookup |
| `GET /runs` list | `items: [{id, job_id, status, dataset_name, split, config_name, created_at, finished_at, overall}]`, where `overall` is the `all` row at the largest cutoff (null until done); `limit` 1–100, `offset`; filters `dataset`, `split` | Enough for a run table in the dashboard without loading every result |
| `GET /runs/{id}` | Run, job status, provenance, `summary`; `results` only with `?include=results` | A run's results are about 100 KB; the default response stays small |
| Who can do what | POST: admin (it runs a heavy job). GETs: viewer | Matches [api-spec.md](../api-spec.md) roles |
| Failure hook | `on_failure` is a no-op for `evaluate`. The job's `failed` status and error are the run's failure state | Nothing on the run needs resetting, because results are written only on success |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `router.py` is HTTP only; `service.py` holds the run rules (create, process, read); `repository.py` holds SQL; `runner.py` still only scores |
| DRY | One `RunConfig`; one runner for the CLI and the worker; one record format (`RunReport` ↔ rows) |
| OCP | A new job kind is one entry in `build_handlers`; no branching in the worker loop |
| DIP | The handler depends on an `Embedder` factory, so tests never load torch |
| Flat flow | Guard clauses for dataset name, existence, drift and the test split |

### Dependencies added
None.

## Files to create / modify

```
migrations/versions/0004_evaluation_runs.py   new
app/evaluation/models.py           new: EvaluationRun, EvaluationResult
app/evaluation/schemas.py          new: request/response models
app/evaluation/service.py          new: create_run, run_evaluation_job, list_runs, get_run
app/evaluation/router.py           new: three endpoints
app/evaluation/repository.py       + run/result queries (tenant-scoped)
app/evaluation/runner.py           execute_run takes tenant_id
app/evaluation/cli.py              resolves tenant name → id
app/ingestion/local_models.py      + for_queries()
app/jobs/models.py                 + JobKind.EVALUATE
app/worker.py                      + evaluate handler
app/core/config.py, .env.example   + EVAL_DATASETS_DIR, EVAL_CORPUS_MANIFEST
app/core/errors.py                 + InvalidInputError (422)
app/main.py                        + router
tests/evaluation/test_runs_api.py, test_run_job.py   new
.claude/{database,api-spec,architecture,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/006b-evaluation-runs-api`.
1. **Models and migration:** `uv run alembic revision --autogenerate`, reviewed by hand;
   `alembic upgrade head`; `alembic check` reports nothing.
2. **`runner.execute_run(tenant_id)`** and the CLI change. The existing CLI tests must
   pass unchanged.
3. **`for_queries()`, `JobKind.EVALUATE`, settings and `InvalidInputError`.**
4. **Service:**
   - `create_run`: validate the dataset, record its hash, queue the job, commit.
   - `run_evaluation_job`: load the run in the job's tenant, check for drift, execute,
     store the results.
   - `list_runs` and `get_run`.
5. **Router and schemas; register the router.**
6. **Worker handler.**
7. **Tests**, then lint, then docs.
8. **Manual check:**
   - Start the API and the worker against the `eval-corpus-v1` tenant.
   - POST a dev run and poll it.
   - Confirm its metrics equal the committed `eval/reports/dense-baseline-dev.json`.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Cross-tenant reads | Another tenant's run → 404 on GET; list never shows it; the job handler loads runs only in the job's tenant |
| Wrong role starts heavy jobs | Viewer and editor get 403 on POST; viewer can GET |
| Path traversal / unknown datasets | `../x`, `a/b`, and a name that doesn't exist → 422 with `field_errors.dataset`; no file outside the directory is read |
| Accidental test runs | `split: test` without `allow_test` → 422 |
| Stored numbers differ from the runner's | End to end with the fixture corpus and the mini dataset: job succeeds; the run's summary and results, converted back to a `RunReport`, equal what `execute_run` returns |
| Half-written runs | Corpus mismatch → job `failed` with the corpus error, run has no summary and no result rows |
| Dataset changed after queueing | Rewriting the file before the job runs → job fails with a drift error |
| Large responses by default | `GET /runs/{id}` omits `results` unless `include=results` |

## Edge cases

- **Polling before the worker starts:** status `queued`; `summary`, `effective` and
  `results` are null or empty.
- **The worker crashes mid-run:** the job stays `running`, as for ingestion. Recovering
  stuck jobs is a reliability item for task 011, as it is for ingest jobs.
- **The same request twice:** two runs. Runs are experiments, so this is not idempotent by
  design; each has its own id.
- **A dataset with no questions in the split:** the runner's "no questions" error fails
  the job.

## Security

- Tenant, user and role come only from the JWT. `tenant_id` is never in the body
  (`extra="forbid"`).
- Dataset names are pattern-checked, then resolved inside a fixed directory, so no
  user-controlled path reaches the filesystem.
- Only admins start runs, and `RunConfig.depth ≤ 50` bounds each run's cost.
- Responses contain questions, slugs, offsets and scores, never chunk text, prompts or
  credentials.

## Risks

- **JSONB blobs drift from the record models.** Mitigation: the round-trip test
  (rows → `RunReport` equals the runner's output).
- **Git provenance inside a container is "unknown"** (no `.git`) once task 013 dockerises
  the worker. Recorded as is. Committed reports keep coming from the CLI on a clean tree.

## Future improvements

- Cancel and delete runs; retention.
- Recovering stuck jobs (011).
- Answer-level columns (009).
- A run-comparison endpoint if the dashboard needs bootstrap intervals server-side.

## Checklist

- [x] Branch `task/006b-evaluation-runs-api`
- [x] Models + migration 0004; `alembic check` clean
- [x] `execute_run(tenant_id)`; CLI tests unchanged and passing
- [x] `for_queries()`, `JobKind.EVALUATE`, settings, `InvalidInputError`
- [x] Service + router + worker handler
- [x] Tests: roles, cross-tenant, dataset validation, test guard, end-to-end round trip, failure and drift
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Manual API + worker run matches the committed dev report
- [x] Update [database.md](../database.md), [api-spec.md](../api-spec.md), [architecture.md](../architecture.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Propose commit message, commit after confirmation

---

## Handover

### Summary
Evaluation runs can now be started and read over the API:
- `POST /v1/evaluations/runs` (admin) queues an `evaluate` job.
- The worker runs the 006a runner and stores the run's provenance, summary and
  per-question results.
- `GET /v1/evaluations/runs` and `GET /v1/evaluations/runs/{id}` (viewer) list and read
  runs, with `?include=results` for per-question results.

Migration `0004_evaluation_runs` adds `evaluation_runs` and `evaluation_results`. The CLI
still works and is still how committed reports are produced. 178 tests pass (12 new).

### Architecture Notes
- **Status comes from the job.** A run has no status column; the API returns the job's
  status, error and timings.
- **No half-written runs.** The `evaluate` handler does not commit, so the summary, the
  result rows and the job's `succeeded` status are one transaction. On failure the worker
  rolls back, so a failed run has an error and nothing else.
- **Two checks keep the numbers tied to the requested dataset:**
  - The dataset name is validated by pattern before any file access.
  - The dataset file's hash is recorded at POST, and the worker refuses a file that has
    changed since.
- **One model, per-run instruction.** `SentenceTransformerEmbedder.for_queries(instruction)`
  is a shallow copy sharing the loaded model. `build_handlers` takes an optional
  `query_embedder_for`; tests with a fake embedder leave it out.
- **Storage round-trips.**
  - `service.store_report` writes a `RunReport` into the rows, and `stored_run_report`
    rebuilds it.
  - A test checks that the rebuilt record equals the original.
  - `GET /runs/{id}` loads result rows only with `include=results`.
- **Tenant isolation:**
  - Runs are read by `(id, tenant_id)`, so another tenant gets a 404.
  - Results have no tenant column and are scoped through their run.
  - The job handler finds its run by `(job_id, job.tenant_id)`.

### Deviations from the plan
- **A real bug caught by the tests:** Pydantic skips field validators for omitted fields,
  so `split: test` without `allow_test` was accepted (202). `validate_default=True` on
  `allow_test` fixed it.
- **Small changes to 006a code:**
  - **The query-instruction rule** (`effective_query_instruction`) moved from the CLI into
    `runner.py`, so the CLI and the worker share it.
  - **`tenant_id_by_name`** is the CLI's tenant lookup now that `execute_run` takes an id.
- **Additions that were not in the plan:**
  - **A split with no questions** is rejected at POST (422 on `split`), instead of failing
    later in the worker.
  - **The dataset file's header name must equal its file name**, because runs are stored
    by name.
  - **`evaluation_results` has `position` and `question`** columns, to keep dataset order
    and to make the stored rows convert back exactly.
- **`JobHandler` contract:** its comment now says a handler may leave the commit to the
  worker. Ingest jobs still commit themselves.
- **Manual-check user:** the manual check needed an admin in the `eval-corpus-v1` tenant
  (dev database only).
  - I added `eval-api-check@example.com` with a random password hash that is never stored
    or shown, and minted its token with `create_access_token`.
  - No password was entered anywhere. The user exists only in the local dev database.

### Database Changes
Migration `0004_evaluation_runs`:
- **`evaluation_runs`:** foreign keys to tenant, user and job (job unique); dataset name,
  hash and split; config; provenance and summary, which stay null until the run succeeds.
  Index `(tenant_id, created_at)`.
- **`evaluation_results`:** cascade from the run. Index `(run_id, position)`.

Checks: `alembic check` is clean, and downgrade followed by upgrade succeeded. Details are
in [database.md](../database.md).

### API Changes
- **Added:**
  - `POST /v1/evaluations/runs` (admin; 202 `{run_id, job_id}`; 422 for an unknown
    dataset, an empty split, or test without `allow_test`)
  - `GET /v1/evaluations/runs` (viewer; paginated; filters `dataset` and `split`)
  - `GET /v1/evaluations/runs/{id}` (viewer; `?include=results`)
- **Errors:** `VALIDATION_ERROR` now also covers server-side checks (`InvalidInputError`).
- **New settings:** `EVAL_DATASETS_DIR` and `EVAL_CORPUS_MANIFEST` (also in `.env.example`).
- Details are in [api-spec.md](../api-spec.md).
- **Frontend (014):** the dashboard can list runs and read their summaries.

### Evaluation Results
No new experiment. Manual end-to-end check, on dataset `evidencedesk-v1` (dev), tenant
`eval-corpus-v1` and the real model:
1. The API (uvicorn) queued a `dense-baseline` dev run over HTTP, and `python -m app.worker
   --once` executed it.
2. Metrics, overlap bands and all 80 questions' hit lists were **identical** to the committed
   `eval/reports/dense-baseline-dev.json`. The overall row was nDCG@10 0.529 and R@10 0.686
   over 70 answerable questions.
3. The run recorded git SHA `48ef7f3` with `dirty: true`, which is correct: 006b was
   uncommitted at the time.
4. Latency was higher than in the CLI run: total p50 92 ms, p95 151 ms, vs 57/78 ms, with
   the API process running on the same machine. Latency remains a per-environment figure.
5. A `split: test` request without `allow_test` returned 422 over HTTP.

### Future Work
- Cancel and delete runs, and retention.
- Recover jobs stuck in `running` after a worker crash (011).
- An `answer` column and answer metrics (009).
- Server-side comparison with bootstrap intervals, if the dashboard needs it.

### Modified Files
| File | Why |
|---|---|
| `migrations/versions/0004_evaluation_runs.py`, `migrations/env.py` | New tables; register the models for autogenerate |
| `app/evaluation/models.py` | `EvaluationRun`, `EvaluationResult`, `DatasetSplit` |
| `app/evaluation/schemas.py` | Request/response models; test-split guard |
| `app/evaluation/service.py` | Create, execute (job handler), list, get; record ↔ rows |
| `app/evaluation/router.py`, `app/main.py` | Three endpoints, registered |
| `app/evaluation/repository.py` | Tenant-scoped run and result queries |
| `app/evaluation/runner.py`, `app/evaluation/cli.py` | `execute_run(tenant_id)`, `tenant_id_by_name`, shared `effective_query_instruction` |
| `app/ingestion/local_models.py` | `for_queries()` |
| `app/worker.py`, `app/jobs/models.py` | `evaluate` job kind and handler |
| `app/core/config.py`, `.env.example` | `EVAL_DATASETS_DIR`, `EVAL_CORPUS_MANIFEST` |
| `app/core/errors.py` | `InvalidInputError` (422) |
| `tests/evaluation/test_runs_api.py` | Roles, isolation, input checks, job success/failure/drift, round trip |
| `.claude/{database,api-spec,architecture,tasks,plan}.md`, this file | Docs |
