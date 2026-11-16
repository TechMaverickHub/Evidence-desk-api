# EvidenceDesk API

Evaluation-driven engineering knowledge assistant: answers technical questions from versioned
documentation with validated citations, abstains when evidence is insufficient, and measures
every retrieval change against a labelled benchmark.

Project docs live in [`.claude/`](.claude/) — start with [PROJECT.md](.claude/PROJECT.md),
[architecture.md](.claude/architecture.md) and [plan.md](.claude/plan.md).

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and Docker. uv installs Python 3.12 itself.

```bash
cp .env.example .env              # dummy local values; adjust POSTGRES_HOST_PORT if 5434 is taken
docker compose up -d --wait postgres
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs, or check `GET /v1/health`.

Create a tenant and its first admin (password is prompted), then load documents and process
them with the worker:

```bash
uv run python -m app.auth.cli create-tenant --name acme --admin-email admin@acme.example.com
uv run python -m app.ingestion.cli load-corpus --tenant acme --manifest tests/fixtures/corpus/manifest.yaml
uv run python -m app.worker --once   # or without --once to keep polling for new jobs
```

The first worker run downloads the embedding model (~130 MB) into the Hugging Face cache.
The API also loads it at startup so searches are fast; set `PRELOAD_EMBEDDING_MODEL=false`
for quicker `--reload` restarts when you are not using search.

## Run everything with Docker Compose

```bash
cp .env.example .env              # optional; compose falls back to dev-only defaults
docker compose up -d --build --wait
```

This starts Postgres, runs the migrations once (`migrate`), then the API on
http://127.0.0.1:8000 and the worker. The first start downloads the models into the
`hf-models` volume. Create a tenant inside the API container; `--password-env` reads the
admin password from a variable instead of prompting:

```bash
docker compose exec -e ADMIN_PASSWORD api python -m app.auth.cli create-tenant   --name acme --admin-email admin@acme.example.com --password-env ADMIN_PASSWORD
```

Traces: set `TELEMETRY_EXPORTER=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318` in
`.env`, start with `docker compose --profile tracing up -d`, then open http://127.0.0.1:16686.

## CI and the evaluation gate

- **CI** (`.github/workflows/ci.yml`, every push and PR): ruff, `alembic check`, the test
  suite against a pgvector Postgres, and a Docker build.
- **Evaluation gate** (`.github/workflows/eval-gate.yml`, PRs to `main` that touch
  retrieval, ingestion, evaluation, corpus, datasets or dependencies; or run by hand):
  ingests the corpus with the real models, runs the adopted config on the **dev** split and
  fails if nDCG@10, recall@10 or hit@5 drops more than 0.02 below the committed baseline.
  The same check locally:

```bash
uv run python -m app.evaluation.cli gate eval/reports/d2-tokens450-dev.json <new-run>.json
```

## Development

```bash
uv run pytest -q                  # needs the compose Postgres running (uses evidencedesk_test)
uv run pytest -q -m model         # opt-in tests against the real embedding model
uv run ruff check .
uv run ruff format --check .
uv run alembic check              # no pending model changes
```

The evaluation corpus in `corpus/` is generated; rebuild it from the pinned upstream tags with
`uv run python -m tools.build_corpus fetch` (network, ~2.5 MB of text into `.cache/`) and then
`uv run python -m tools.build_corpus build` (offline, byte-for-byte reproducible). Load it with
`uv run python -m app.ingestion.cli load-corpus --tenant <name> --manifest corpus/manifest.yaml`.

Benchmark datasets are built from a reviewed YAML source and checked against the corpus
(`app/evaluation/cli.py` shows the usage; `stats` prints counts per split and query type).

Reset the local database: `docker compose down -v` (deletes the volume; the init script
recreates the test database on next start).
