# Task 001 — Project setup

**Status:** ✅ Done (2026-10-27); 8 tests passed, ruff clean
**Week:** W1 · **Modules:** `app/core`, repo tooling

## Goal

A runnable, tested FastAPI skeleton managed by uv, connected to PostgreSQL + pgvector, with
the conventions every later task relies on: settings, DB session, Alembic, error envelope,
JSON logging, health endpoint and a pytest setup against a real database.

No domain features (auth, documents, retrieval) in this task.

## Scope

In:
- `pyproject.toml` (uv), `.python-version` (3.12), `uv.lock`, ruff config.
- `docker-compose.yml` with **only** the `postgres` service (`pgvector/pgvector:pg16`) for
  local dev and tests. API/worker containers come in task 013.
- `app/main.py` app factory, `app/core/{config,db,errors,logging}.py`.
- Alembic initialised; first revision enables the `vector` extension (no tables yet).
- `GET /v1/health` → `{status, database}`; 503 when the DB is unreachable.
- Error envelope for `AppError`, request validation errors and unhandled exceptions.
- Request logging middleware: one JSON line per request with a `request_id`
  (also returned as the `X-Request-ID` header).
- `.env.example`, README quick-start.
- Tests: health OK, health with DB down, validation-error envelope, unhandled-error envelope.

Out: auth (002), any tables (002+), Dockerfile for the API (013), CI (013), OpenTelemetry (012).

## Assumptions

1. Docker Desktop is available locally (Postgres runs in a container; no native install).
2. uv installs Python 3.12 itself (`uv python install 3.12`); the system Python 3.11 is not used.
3. Sync SQLAlchemy is acceptable for the whole project (see Architecture decisions).
4. The test database is a second database (`evidencedesk_test`) on the same container,
   created by an init script.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Sync vs async DB | Sync SQLAlchemy 2.0 + `psycopg` 3 | Simpler code and tests. FastAPI runs sync endpoints in a threadpool; embedding/reranking are CPU-bound so async would not help them. Revisit only if load tests (015) show the threadpool is the bottleneck |
| Settings | `pydantic-settings`, one `Settings` class, cached `get_settings()` | Typed, reads `.env`, easy to override in tests |
| Session handling | `get_session()` FastAPI dependency yielding a `Session`; services open `session.begin()` | Transactions are owned by services, per [coding-standards.md](../coding-standards.md) |
| Errors | `AppError(status_code, error_code, message, field_errors)` base class + three handlers | One envelope everywhere; subclasses (e.g. `NotFoundError`) added when first needed |
| Logging | stdlib `logging` + a ~20-line JSON formatter | No extra dependency; OTel added later |
| URL prefix | `/v1` via an `APIRouter(prefix="/v1")` | Versioned API from day one |
| Migrations | Alembic with `env.py` reading the URL from `Settings` | No URL duplicated in `alembic.ini` |

### Design principles applied (see [coding-standards.md](../coding-standards.md))

| Principle | Where it shows up in this task |
|---|---|
| SRP | `config.py` only reads settings, `db.py` only manages engine/sessions, `errors.py` only maps exceptions to the envelope, `logging.py` only formats and emits logs, `main.py` only composes them in `create_app()` |
| OCP | New feature routers are added with one `include_router` line in `create_app()`; new error types are `AppError` subclasses picked up by the existing handler, with no handler changes |
| LSP | Every `AppError` subclass renders through the same handler with the same envelope shape |
| ISP / DIP | The health router depends on a `check_database` dependency (a plain callable, `() -> bool`), not on the engine. Tests swap it with `app.dependency_overrides` instead of monkeypatching or stopping Postgres. No `Protocol` yet: one function is enough until a second implementation appears |
| DRY | One `get_settings()`, one `get_session()`, one envelope builder used by all three exception handlers |
| Flat control flow | The health endpoint and handlers use early returns; no nesting beyond one level |
| Error handling | DB ping catches only `sqlalchemy.exc.OperationalError` (not a bare `except`); the global `Exception` handler logs with `logger.exception` and returns `INTERNAL_ERROR` |
| Test by risk | Tests cover the envelope contract and the DB-down path (what later tasks rely on), not framework internals |
| Version control | Work on `task/001-project-setup` off `dev`; commits like `chore: set up uv project`, `feat: add health endpoint`; one PR into `dev` |

Dependencies added (and why):
- `fastapi`, `uvicorn[standard]` — web framework and server.
- `pydantic-settings` — typed env config.
- `sqlalchemy`, `psycopg[binary]`, `alembic` — DB access and migrations.
- dev: `pytest`, `httpx` (required by `TestClient`), `ruff`.

`pgvector` (Python) is **not** added yet; task 003 adds it with the `chunks` table.

## Files to create

```
.python-version
pyproject.toml                  project metadata, deps, ruff + pytest config
uv.lock                         generated
.env.example                    DATABASE_URL, TEST_DATABASE_URL, LOG_LEVEL, APP_ENV
docker-compose.yml              postgres (pgvector/pgvector:pg16), healthcheck, volume
docker/postgres-init/01-test-db.sql   CREATE DATABASE evidencedesk_test
alembic.ini
migrations/env.py
migrations/script.py.mako
migrations/versions/0001_enable_pgvector.py
app/__init__.py
app/main.py                     create_app(), registers routers + handlers + middleware
app/core/__init__.py
app/core/config.py              Settings, get_settings()
app/core/db.py                  engine, SessionLocal, get_session(), check_database()
app/core/errors.py              AppError + exception handlers
app/core/logging.py             JSON formatter, configure_logging(), request-logging middleware
app/health/__init__.py
app/health/router.py            GET /v1/health
tests/__init__.py
tests/conftest.py               settings override to TEST_DATABASE_URL, TestClient fixture
tests/core/test_errors.py
tests/health/test_health.py
README.md                       quick-start (replace the one-line stub)
```

## Step-by-step implementation plan

0. `git switch -c task/001-project-setup` from `dev`.
1. `uv init --app --python 3.12` style setup by hand: write `pyproject.toml` and
   `.python-version`, then `uv add` the runtime deps and `uv add --dev` the dev deps.
2. Write `docker-compose.yml` + the init SQL; `docker compose up -d postgres`; confirm it is healthy.
3. `app/core/config.py`: `Settings` with `database_url`, `test_database_url`, `log_level`,
   `app_env`; `get_settings()` with `lru_cache`.
4. `app/core/db.py`: engine (`pool_pre_ping=True`), `SessionLocal`, `get_session()`,
   `check_database()` (`SELECT 1`, returns `False` on `OperationalError`).
5. `app/core/errors.py`: `AppError`; handlers for `AppError`, `RequestValidationError`
   (maps Pydantic errors to `field_errors`) and `Exception` (logs with `request_id`, returns
   `INTERNAL_ERROR` without leaking details).
6. `app/core/logging.py`: JSON formatter, `configure_logging()`, middleware that sets
   `request_id`, times the request and logs one line.
7. `app/health/router.py` + `app/main.py` (`create_app()`, module-level `app = create_app()`).
8. Alembic: `alembic init migrations`, point `env.py` at `Settings`, add
   `0001_enable_pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`).
9. Tests: `conftest.py` and the four tests listed in Scope. DB-down test overrides the
   `check_database` dependency rather than stopping the container.
10. README quick-start; run `uv run pytest -q`, `uv run ruff check .`,
    `uv run ruff format --check .`, `uv run alembic upgrade head` on a fresh DB.

## Edge cases and security

- DB unreachable at startup: the app still starts; `/v1/health` reports 503 instead of crashing.
- Unhandled exceptions never return stack traces or exception text to the client.
- Client-supplied `X-Request-ID` is accepted only if it is a short safe string (≤ 64 chars,
  `[A-Za-z0-9-]`); otherwise a new UUID is generated, to avoid log injection.
- `.env` stays in `.gitignore`; `.env.example` holds dummy values only.

## Risks

- **Windows + Docker volume / line-ending issues** with the init SQL script → keep it LF
  and tiny; document the reset command (`docker compose down -v`).
- **Port 5432 already used** by a native Postgres → expose the container on `5433` by
  default and put that in `.env.example`.
- **pgvector image tag drift** → pin `pgvector/pgvector:pg16` (major version) and record the
  resolved version in the handover.

## Future improvements

- Dockerfile + API/worker services in compose (013).
- OpenTelemetry tracing and metrics (012).
- Pre-commit hook running ruff (only if it proves useful).

## Checklist

- [x] `pyproject.toml`, `.python-version`, `uv.lock`, ruff config
- [x] `docker-compose.yml` + test DB init script; container healthy
- [x] `config.py`, `db.py`
- [x] `errors.py` with three handlers
- [x] `logging.py` JSON formatter + request middleware
- [x] `GET /v1/health`
- [x] Alembic initialised, `0001_enable_pgvector` applies on an empty DB
- [x] Tests: health OK, health 503, validation envelope, internal-error envelope
- [x] `uv run pytest -q`, `ruff check`, `ruff format --check` all clean
- [x] Self-review against the design-principles table above (SRP, DIP via `Depends`, no bare `except`, ≤ 2 nesting levels)
- [x] Work on `task/001-project-setup`, conventional commits, one PR into `dev`
- [x] `.env.example`, README quick-start
- [x] Update [tasks.md](../tasks.md), [api-spec.md](../api-spec.md) status, handover below

---

## Handover

### Summary
uv-managed FastAPI skeleton on Python 3.12: typed settings, lazy SQLAlchemy engine/session,
Alembic with a first revision enabling pgvector, one error envelope for every non-2xx, JSON
request logging with a sanitised `X-Request-ID`, and `GET /v1/health`. 8 tests run against
a real Postgres test database.

### Architecture Notes
- Engine and sessionmaker are `lru_cache`d factories, not module globals, so tests repoint
  `DATABASE_URL` at `evidencedesk_test` before the first connection.
- `check_database()` is injected into the health route with `Depends`; tests override it
  rather than stopping Postgres. It catches only `OperationalError`.
- `AppError` uses class attributes (`status_code`, `error_code`, `message`); new errors are
  subclasses and need no handler changes.
- The request-logging middleware logs in `finally`, so failed requests are logged as 500
  without catching the exception. The unhandled-error handler adds `X-Request-ID` itself,
  because it runs outside that middleware.
- `Base(DeclarativeBase)` was added to `db.py` now so `alembic check` works; task 002 adds
  the first models.

### Deviations from the plan
- **Postgres host port 5434, not 5433.** 5433 is used by another local container. The port
  is configurable through `POSTGRES_HOST_PORT` in `.env`.
- **Framework HTTP errors use the envelope too.** A handler for Starlette's `HTTPException`
  maps unknown routes and wrong methods to `NOT_FOUND` / `METHOD_NOT_ALLOWED`; otherwise
  they would return FastAPI's `{"detail": ...}` and break the "every non-2xx" rule. New code
  `METHOD_NOT_ALLOWED` added to api-spec.md.
- **`httpx2` instead of `httpx`** as the test-client dependency: Starlette 1.10 deprecates
  `httpx` for `TestClient`.
- **DB URLs use `127.0.0.1`, not `localhost`.** With `localhost`, an unreachable DB took
  ~6.5 s to fail (IPv6 then IPv4, 3 s each); now ~3.4 s.
- Added `.gitattributes` (LF for `*.sql`/`*.sh`) so the init script works from Windows.
- Ruff rules: `E, F, I, B, UP, SIM, N, BLE` (BLE blocks blind `except Exception`).
- Two extra tests beyond the plan: request-id echo/replacement (log-injection guard).

### Database Changes
- `0001_enable_pgvector`: `CREATE EXTENSION IF NOT EXISTS vector` (pgvector 0.8.6 in
  `pgvector/pgvector:pg16`). No tables. Upgrade → downgrade → upgrade verified; `alembic check` clean.

### API Changes
- `GET /v1/health` → `{status: ok|degraded, database: ok|unreachable}`; 503 when degraded.

### Evaluation Results
None (no retrieval yet).

### Future Work
- Task 002: auth, first models, and run migrations against the test DB in `conftest.py`.
- Task 013: Dockerfile and API/worker services in compose; CI.

### Modified Files
| File | Why |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | uv project, pinned deps, ruff and pytest config |
| `docker-compose.yml`, `docker/postgres-init/01-test-db.sql` | Postgres + pgvector and a separate test DB |
| `.env.example`, `.gitattributes` | Documented config; LF endings for container scripts |
| `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_enable_pgvector.py` | Migrations reading the URL from app settings |
| `app/main.py` | App factory |
| `app/core/config.py`, `db.py`, `errors.py`, `logging.py` | Settings, DB, error envelope, JSON logging |
| `app/health/router.py` | Health endpoint |
| `tests/conftest.py`, `tests/core/test_errors.py`, `tests/core/test_logging.py`, `tests/health/test_health.py` | Tests |
| `README.md` | Quick start |
