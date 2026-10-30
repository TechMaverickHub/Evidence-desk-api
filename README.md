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

## Development

```bash
uv run pytest -q                  # needs the compose Postgres running (uses evidencedesk_test)
uv run pytest -q -m model         # opt-in tests against the real embedding model
uv run ruff check .
uv run ruff format --check .
uv run alembic check              # no pending model changes
```

Reset the local database: `docker compose down -v` (deletes the volume; the init script
recreates the test database on next start).
