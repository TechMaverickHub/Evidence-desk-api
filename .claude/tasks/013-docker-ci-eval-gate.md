# Task 013 — Docker Compose, GitHub Actions CI, evaluation regression gate

**Status:** ✅ Implemented and verified locally; GitHub runs pending the push (option A approved)
**Week:** W5 · **Modules:** repo (Docker, CI), `app/evaluation` (gate), `app/auth/cli.py` ·
**Branch:** `task/013-docker-ci-eval-gate` (off `task/012-observability`)

## Goal

Anyone can run the whole system with one command, every push is linted and tested
automatically, and a retrieval change cannot silently make the benchmark worse:
- **Docker Compose:** `docker compose up` starts Postgres, runs migrations, then the API and
  the worker. An optional Jaeger service shows the task 012 traces.
- **CI:** GitHub Actions runs ruff, the migrations check and the test suite against a
  pgvector Postgres, and builds the Docker image.
- **Evaluation regression gate:** a workflow ingests the corpus with the real models, runs
  the production retrieval config on the **dev** split, and fails if the headline metrics
  fall below the committed baseline by more than a fixed tolerance.

## Scope

In:
- **`Dockerfile`** (one image for api, worker and migrate):
  - Build stage on the official uv image: `uv sync --frozen --no-dev`. Torch comes from the
    CPU index already pinned in `pyproject.toml`, so no CUDA wheels.
  - Runtime stage on `python:3.12-slim-bookworm`: copies the virtualenv and only what runs
    (`app/`, `migrations/`, `alembic.ini`, `corpus/`, `eval/datasets/`, `eval/configs/`).
    The worker needs `corpus/` and `eval/datasets/` for evaluation-run jobs (006b).
  - Runs as a non-root user. `HF_HOME=/models`, so the model cache is a volume, not a layer.
  - The default command is the API (`uvicorn app.main:app --host 0.0.0.0`); compose
    overrides it for the worker and migrate.
- **`.dockerignore`:** `.git`, `.venv`, `.env`, `.cache`, `.idea`, `tests`, `.claude`,
  `eval/reports`, `tools`, caches. This keeps secrets and bulk out of the build context.
- **`docker-compose.yml`** (extends the existing file; `postgres` is unchanged, so
  `docker compose up -d postgres` for tests still works):

  | Service | What it does |
  |---|---|
  | `migrate` | One-shot `alembic upgrade head`; waits for Postgres to be healthy |
  | `api` | Port `${API_HOST_PORT:-8000}`; starts after `migrate` completes; healthcheck on `/v1/health` |
  | `worker` | `python -m app.worker`; starts after `migrate` completes |
  | `jaeger` | Profile `tracing` only: Jaeger all-in-one, UI on 16686, OTLP/HTTP on 4318 |

  - Settings come from `.env` (`env_file`, optional). Compose overrides `DATABASE_URL`, so
    containers reach `postgres:5432` instead of the host port.
  - `hf-models` volume shared by api and worker, so the models download once.
  - With `--profile tracing`, set `TELEMETRY_EXPORTER=otlp` and
    `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318` (documented in `.env.example`).
- **`.github/workflows/ci.yml`:** runs on push to `main`, `dev` and `task/**`, and on pull
  requests.
  - **`lint`:** `ruff check` and `ruff format --check`.
  - **`test`:**
    - Postgres service `pgvector/pgvector:pg16`; a step creates `evidencedesk_test`, as the
      local init script does.
    - `uv sync --frozen`, then `alembic upgrade head` and `alembic check` on the main
      database, then `pytest -q`. Model tests stay excluded, as locally.
  - **`docker`:** builds the image without pushing, with the GitHub Actions layer cache,
    so a broken Dockerfile fails CI.
- **`.github/workflows/eval-gate.yml`:**
  - Triggers:
    - Manual (`workflow_dispatch`).
    - Pull requests to `main` that touch `app/retrieval/**`, `app/ingestion/**`,
      `app/evaluation/**`, `corpus/**`, `eval/datasets/**`, `eval/configs/**`, `uv.lock` or
      `pyproject.toml`.
    - Not on every push: it takes minutes and downloads models.
  - **Steps:**
    1. Postgres service; `uv sync --frozen`; restore the Hugging Face model cache with
       `actions/cache`.
    2. `alembic upgrade head`.
    3. Create the tenant non-interactively (see the next item) and `load-corpus --process`.
    4. `pytest -m model`: the real-model tests, cheap once models are cached.
    5. Run the evaluation: `cli run --config eval/configs/d2-tokens450.yaml --split dev`.
    6. `cli gate` against `eval/reports/d2-tokens450-dev.json`.
    7. Write the gate's Markdown to the job summary and upload the run record as an
       artifact.
- **`create-tenant --password-env NAME`** (`app/auth/cli.py`): reads the admin password from
  the named environment variable instead of prompting. The prompt stays the default, and
  the password still never appears in argv. The gate generates a random one per run.
- **`cli gate`** (`app/evaluation/gate.py` + a subcommand in `app/evaluation/cli.py`):
  - Usage: `gate BASELINE CANDIDATE [--tolerance 0.02] [--out PATH]`.
  - **Refuses:** different dataset, split or sha256; different config (name, retriever,
    rerank, chunker, cutoffs); a split other than `dev`; different question sets. These
    reuse `_paired_questions` validation where it applies.
  - **Gated metrics** (query type `all`): nDCG@10, recall@10, hit@5.
  - **Fails** (exit 1) when any gated metric's candidate − baseline < −tolerance.
  - **Reports** each metric with baseline, candidate and delta, plus the paired bootstrap 95%
    CI (from `report.paired_bootstrap_ci`) and the per-query_type deltas. The CI and
    query-type rows are informational; small groups are too noisy to gate on.
  - Exit codes: `0` pass, `1` regression, `2` refused comparison.

Out:
- Publishing images to a registry, deployment, and secrets in CI. The gate needs no Groq
  key.
- An answer-quality gate (LLM calls cost quota and are non-deterministic). This is future
  work.
- A nightly schedule: nothing changes between runs without a PR.
- Branch protection rules on GitHub. They are settings on the repo, which only you can
  change.

## Assumptions

1. **Determinism.** The gate's baseline was produced on Windows. On Linux CPU, embeddings
   and cross-encoder scores can differ by float noise, which can flip near-tied ranks. A
   tolerance of **0.02** absorbs that and still catches real regressions: the smallest
   adopted change so far was +0.057 hit@5. The first CI run records the observed drift.
   - If the drift is above 0.02, I'll stop and ask; I won't loosen the tolerance silently.
2. **Runner time.** A GitHub-hosted runner (2–4 vCPU) can embed the corpus (285 documents)
   and rerank 80 queries × 20 in roughly 10–20 minutes. The model cache saves about 200 MB
   of downloads on later runs.
3. **Action versions.** The actions (`actions/checkout`, `astral-sh/setup-uv`,
   `actions/cache`, `actions/upload-artifact`, `docker/setup-buildx-action`,
   `docker/build-push-action`) are pinned to their current major versions, checked against
   their official READMEs during implementation.
4. **Infrastructure versions.** The base images are `ghcr.io/astral-sh/uv` (pinned minor)
   and `python:3.12-slim-bookworm`. Jaeger is `jaegertracing/all-in-one` (pinned tag); its
   OTLP receiver is on by default in current versions.
5. **No new Python dependencies.**

## Architecture decisions

| Decision | Why |
|---|---|
| One image, three commands (api, worker, migrate) | Same code and dependencies; nothing to keep in sync |
| Migrations as a one-shot `migrate` service, not at API startup | Two API replicas never race on `alembic upgrade`; failures are visible as a failed service |
| Models in a volume, not baked into the image | Keeps the image ~1 GB smaller and lets api and worker share one download |
| Gate on an absolute tolerance, not on the bootstrap CI | Same code on the same data should reproduce the baseline; the CI answers "is change X better?", while the gate answers "did we break it?" CIs on 70 questions are wide, so a CI rule would let real drops through |
| Gate dev only | Test is for final, deliberate comparisons (Evaluation Rules); an automatic test run on every PR would turn it into a tuning set |
| Gate in a separate workflow | The normal CI stays fast (no models); the gate runs when retrieval-relevant files change |
| `--password-env` instead of a `--password` argument | Arguments land in process lists and logs; an env var name does not expose the value |

## Files to modify

| File | Change |
|---|---|
| `Dockerfile` (new) | Multi-stage uv build, non-root runtime |
| `.dockerignore` (new) | Keep `.env`, `.git` and bulk out of the build context |
| `docker-compose.yml` | Add `migrate`, `api`, `worker`, `jaeger` (profile); `hf-models` volume |
| `.github/workflows/ci.yml` (new) | Lint, test, Docker build |
| `.github/workflows/eval-gate.yml` (new) | Ingest, model tests, dev run, gate |
| `app/evaluation/gate.py` (new) | Gate rule and Markdown summary |
| `app/evaluation/cli.py` | `gate` subcommand |
| `app/auth/cli.py` | `--password-env` |
| `tests/evaluation/test_gate.py` (new), `tests/auth/test_cli.py` (or the existing auth CLI tests) | Tests |
| `.env.example` | `API_HOST_PORT`; OTLP-to-Jaeger example |
| `README.md` | Docker Compose quick start, CI and gate |
| `.claude/{architecture,tasks,plan}.md`, this file | Docs |

## Implementation steps

1. **Gate logic and tests first** (pure functions over two `RunReport`s): pass when equal;
   fail on a drop larger than the tolerance; pass on a drop within it; refuse on a dataset,
   config or split mismatch, or on a test-split record.
2. **`cli gate`:** exit codes and the written Markdown; CLI tests.
3. **`create-tenant --password-env`:** tests for a missing variable, a weak password
   (existing validation) and success.
4. **Local gate self-check:** run `cli gate` with the committed baseline against itself
   (pass), and against an older record with the same config shape if one fits. Otherwise a
   test fixture covers the fail path.
5. **Dockerfile and `.dockerignore`:** build locally and check the image size.
6. **Compose:**
   - `docker compose up -d`: migrate exits 0, the API healthcheck goes healthy, the worker
     polls.
   - Smoke test: create a tenant with `--password-env` and load the fixture corpus
     (`tests/fixtures/corpus`) via `docker compose exec`.
   - With `--profile tracing` and the OTLP settings, one search shows up in the Jaeger UI.
7. **`ci.yml`:** validate it locally with `actionlint` if available, via `uvx`/Docker; that
   is a download, which I'll name when I run it. It runs for real only after a push (see
   "Branch and push").
8. **`eval-gate.yml`:** same.
9. Docs: README, `.env.example`, architecture (deployment and CI section), tasks, plan,
   handover.

## Branch and push (needs your decision)

The CI workflows only run on GitHub. At the moment `origin/main` and `origin/dev` are both
at `e7ad82d` "Initial commit", and every task branch is local only. Both are ancestors of
this branch, so fast-forwards are possible. Options:

- **A (recommended).**
  1. After 013 is committed, fast-forward `dev` to `task/013-docker-ci-eval-gate` and push
     `dev` (CI runs).
  2. Then open a PR `dev` → `main`, so the evaluation gate runs on a real PR.
  3. Merging stays your call.
- **B.** Push only the task branch `task/013-docker-ci-eval-gate` (CI runs on `task/**`).
  Trigger the gate manually after that. `dev` and `main` stay as they are.
- **C.** Don't push. The workflows are validated locally only, and the handover says
  they have not run on GitHub.

Pushing publishes 24 commits of history, including the corpus (third-party docs under
their licences, see `corpus/licenses/`) and the benchmark. `.env` is git-ignored and has
never been committed. I'll check this again before any push.

## Edge cases

- **The gate is given a test-split record.** It refuses (exit 2) rather than gating on
  test.
- **The baseline is regenerated after an adopted improvement.** The gate always reads the
  committed baseline file. Adopting a new config means committing its dev report and
  updating the path in the workflow; that is a deliberate act in the PR.
- **A model download fails in CI** (Hugging Face outage). The job fails at ingest with a
  clear error; it is not reported as a gate pass.
- **The API container starts before the models are cached.** `PRELOAD_EMBEDDING_MODEL`
  downloads on first start, so the healthcheck needs a generous `start_period`.
- **`.env` is missing for compose.** `env_file` is `required: false`. The compose file gives
  a dev-only `JWT_SECRET_KEY` default through `${JWT_SECRET_KEY:-...}`, matching
  `.env.example`.

## Security

- **No secrets in images:** `.env` is in `.dockerignore`. Workflows use no repo secrets.
- **Non-root container user.** Postgres is exposed on the host only, as today.
- **Minimal workflow permissions:** `permissions: contents: read`.
- **Pinned actions:** major versions now; SHA pinning is noted as future work.
- **Gate tenant password:** generated per run (`openssl rand`). It is never echoed and the
  database is thrown away with the runner.

## Tests

- **Gate:** equal records pass; a drop of 0.03 on one metric fails and names it; a drop of
  0.01 passes; dataset sha, config, cutoffs or split mismatches are refused; test-split
  records are refused; the Markdown contains every gated metric.
- **CLI:** `gate` exit codes 0, 1 and 2; `create-tenant --password-env` reads the variable,
  rejects an unset one and never prompts.
- **Manual:**
  - `docker compose up` end-to-end with the smoke ingest and search.
  - A Jaeger trace.
  - CI and gate runs on GitHub, if you choose option A or B.

## Risks

- **Linux vs Windows drift exceeds the tolerance.** Then I'd stop and ask, with two
  options: regenerate the baseline in CI (a Linux dev run committed as the gate baseline)
  or raise the tolerance. Measured, not guessed.
- **Gate runtime or cache limits on GitHub-hosted runners.** Worst case it is a manual-only
  workflow.
- **Image size (~1.5–2 GB with CPU torch).** Accepted for a portfolio project. A slimmer
  ONNX runtime is future work.

## Future work

- An answer-quality gate on a small fixed subset, with a recorded Groq budget.
- Publishing images to GHCR and pinning actions by SHA.
- A `make`/`just` file for common commands.
- Branch protection requiring CI and the gate on `main`.

## Checklist

- [x] Gate logic + tests
- [x] `cli gate` + tests
- [x] `create-tenant --password-env` + tests
- [x] Dockerfile + `.dockerignore`; image builds
- [x] Compose: migrate, api, worker, jaeger profile; smoke test
- [x] `ci.yml` (actionlint clean)
- [x] `eval-gate.yml` (actionlint clean)
- [ ] Push per option A; CI and gate observed on GitHub
- [x] README, `.env.example`, architecture, tasks, plan
- [x] Handover

## Handover

### Summary
- **Docker.** One image runs the API, the worker and migrations:
  - Built with uv from the lock file; CPU-only torch; non-root user; 2.11 GB.
  - Run with `docker compose up -d --build --wait`: Postgres, then a one-shot `migrate`,
    then `api` (with a health check) and `worker`.
  - Models live in a shared `hf-models` volume.
  - `--profile tracing` adds Jaeger 2.16.
- **CI** (`ci.yml`): ruff, `alembic upgrade` and `alembic check`, pytest against a pgvector
  service, and a Docker build.
- **Evaluation gate** (`eval-gate.yml` + `cli gate`): real-model tests, corpus ingest, a
  dev run of `d2-tokens450`, then the gate against the committed
  `eval/reports/d2-tokens450-dev.json`. It fails when nDCG@10, recall@10 or hit@5 drops by
  more than 0.02.
- **`create-tenant --password-env NAME`:** non-interactive tenant creation for CI and
  containers.

327 tests pass (19 new). Ruff, `alembic check` and actionlint are clean.

### Architecture Notes
- **One image, three commands.** Migrations are their own one-shot service, so API replicas
  never race on them.
- **Models are downloaded at first use into a volume,** not baked into the image.
- **The gate rule is an absolute tolerance, not the bootstrap CI.**
  - The gate asks "did we break it?". Same code on the same data should reproduce the
    baseline.
  - On 70 dev questions the CI is too wide to catch real drops.
  - The CI and per-`query_type` deltas are still reported.
- **The gate refuses (exit 2)** test-split records, different configs, datasets or question
  sets, and configs without cutoffs 5 and 10. It exits 1 on a regression and 0 on a pass.
- **Changing the baseline** means editing `GATE_CONFIG` / `GATE_BASELINE` in the workflow.
  That is a visible change in the PR.
- **`report.paired_questions` and `report.row_order`** were made public (renamed only), so
  the gate reuses the comparison checks instead of duplicating them.

### Deviations from the plan
- **Jaeger image:** `jaegertracing/jaeger:2.16.0` (v2) instead of `all-in-one`, which is
  the v1 image. The v2 image has the OTLP receiver on by default.
- **The local smoke ingest used the API** (`POST /v1/documents/ingest` of one corpus page)
  rather than the fixture corpus, because `tests/` is not in the image. It covers
  api → job → worker → search end to end.
- **The image is 2.11 GB,** above the planned 1.5–2 GB, mostly torch. Accepted, as the plan
  allowed.

### Database Changes
None.

### API Changes
No HTTP changes. New CLI surface:
- `python -m app.evaluation.cli gate BASELINE CANDIDATE [--tolerance 0.02] [--out PATH]`
- `python -m app.auth.cli create-tenant ... --password-env NAME`
- New setting in `.env.example`: `API_HOST_PORT` (compose only).

### Evaluation Results
No retrieval change, so no new metrics.

**Gate self-checks on committed records:**

| Command | Result |
|---|---|
| `gate d2-tokens450-dev d2-tokens450-dev` | Pass, all deltas +0.000 (exit 0) |
| `gate d0-baseline-dev d2-tokens450-dev` | Refused: different configs (exit 2) |
| `gate d2-tokens450-dev d2-tokens450-test` | Refused: not dev (exit 2) |

**The first GitHub gate run** (Linux vs the Windows baseline) is pending the push. Its
observed drift will be recorded here.

**Manual checks (Docker Desktop, Windows host):**
- `docker compose up -d --wait api worker`: `migrate` exited 0, the API was healthy, the
  worker was running.
- Smoke test:
  1. `create-tenant --password-env` inside the API container.
  2. Ingest one FastAPI page: 202.
  3. The worker processed it: 24 chunks.
  4. `POST /v1/search`: 200 with 3 results.
- `--profile tracing` with OTLP: Jaeger listed `evidencedesk-api` with a `POST /v1/search`
  trace.

### Future Work
- An answer-quality gate on a small fixed subset, with a recorded Groq budget.
- Publish images to GHCR; pin actions by commit SHA.
- Branch protection requiring CI and the gate on `main` (a GitHub setting).
- A slimmer image (ONNX runtime instead of torch).

### Modified Files
| File | Why |
|---|---|
| `Dockerfile`, `.dockerignore` (new) | One non-root image for api, worker and migrate; secrets and bulk kept out of the context |
| `docker-compose.yml` | `migrate`, `api`, `worker`, `jaeger` (profile); `hf-models` volume |
| `.github/workflows/ci.yml`, `eval-gate.yml` (new) | CI and evaluation regression gate |
| `app/evaluation/gate.py` (new), `app/evaluation/cli.py` | Gate rule, Markdown summary, `gate` subcommand |
| `app/evaluation/report.py` | `paired_questions` and `row_order` made public for reuse (rename only) |
| `app/auth/cli.py` | `--password-env` |
| `tests/evaluation/test_gate.py` (new), `tests/auth/test_create_user.py` | Tests |
| `README.md`, `.env.example` | Compose, CI and gate usage; `API_HOST_PORT`; OTLP to Jaeger |
| `.claude/{architecture,tasks,plan}.md`, this file | Docs |
