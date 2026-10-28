# EvidenceDesk API — Coding Standards

Derived from [CLAUDE.md](CLAUDE.md) and [architecture.md](architecture.md). Enforced in review.

## Architecture
- **Routers** validate input, resolve auth dependencies, call one service function and return
  a response schema. No queries, no business logic.
- **Services** hold business logic and own the transaction (`session.commit()` on success,
  `session.rollback()` before translating a DB error). They call repositories and gateways.
- **Repositories** run SQLAlchemy queries only. They may `flush()` but never commit, and **every tenant-owned
  query takes `tenant_id` as a required argument** (no default, no "all tenants" path).
- Shared helpers live in `app/core/`. Reuse them; never create a parallel helper.
- Keep functions under about 40 lines where practical. Prefer readability over cleverness.
- Type hints on every function signature. Pydantic models for every request and response.

## Design principles (SOLID, applied pragmatically)

Python is not Java: use functions and small classes, `typing.Protocol` for seams, and
FastAPI `Depends` for wiring. Apply each principle where it pays for itself today.

| Principle | How it applies here |
|---|---|
| **S** — Single Responsibility | One reason to change per unit: router = HTTP, service = business rules, repository = SQL, gateway = one external system. A function does one thing; if its name needs "and", split it. One module per concern (`fusion.py` only fuses rankings, `metrics.py` only scores them) |
| **O** — Open/Closed | New retrieval strategies, rerankers or metrics are **added** as new implementations of an existing protocol and registered in one place (e.g. a `RETRIEVERS = {"dense": ..., "keyword": ...}` dict), not by adding `if mode == ...` branches across services |
| **L** — Liskov Substitution | Any implementation of a protocol (real Groq client, fake test client; dense or keyword retriever) honours the same inputs, outputs and errors. A fake that returns a different shape or swallows errors is a bug |
| **I** — Interface Segregation | Protocols stay small and role-specific: `Embedder.embed(texts)`, `Reranker.rerank(query, passages)`, `LLMClient.complete_json(...)`. No catch-all "AIService" interface |
| **D** — Dependency Inversion | Services depend on protocols, not on concrete SDKs. Concrete clients are built in `app/core/deps.py` / module `deps.py` and injected with `Depends`; tests override them with `app.dependency_overrides`. Services never import `groq` or `sentence_transformers` directly |

Guardrails against over-applying SOLID:
- **Introduce a protocol only when there are, or will be in the current task, two
  implementations** (real + fake counts). Otherwise a plain function or class is fine.
- No abstract base classes, factories or generic repositories "for later". No inheritance
  hierarchies deeper than one level; prefer composition.
- Don't abstract over SQLAlchemy itself; repositories are the database boundary.

## Code structure
- **DRY:** logic that appears twice moves into one function in the module that owns it (or
  `app/core/` if truly shared). Search before writing a helper. Three similar lines are fine;
  two copies of a business rule are not.
- **Flat control flow:** guard clauses and early returns instead of nested `if`/`else`.
  At most two levels of nesting inside a function; extract a function beyond that.
- **Abstract with care:** build for the current task's requirements. Generalise on the second
  real use, not the first imagined one.

## Comments, naming and style
- **PEP 8**, enforced by `ruff check` and `ruff format` (line length 100). Imports sorted by ruff.
- **Descriptive, intent-revealing names**: `fuse_rankings_rrf`, `recall_at_k`,
  `validate_citations`; no abbreviations like `rr`, `ctx2`, `tmp`. Booleans read as
  questions (`is_answerable`, `has_evidence`).
- Each module starts with a one-to-three line docstring saying what it owns.
- Comment the **why** (a trade-off, a non-obvious formula, a reason for a limit), never the
  what. If code needs a "what" comment, rename or extract instead.
- Metric and ranking functions cite their definition in a short docstring (e.g. the RRF and
  nDCG formulas), because they will be explained in interviews.
- Names follow the domain: `chunk`, `document`, `evidence span`, `run`, `query_type`.

## Error handling
- Never use a bare `except:` or an empty `except` block. Catch the **specific** exception you
  can handle, and either handle it, translate it into an `AppError`, or let it propagate.
- Translate external errors at the gateway boundary (e.g. Groq timeout → `LLMUnavailableError`)
  so services never see SDK-specific exceptions.
- `except Exception` is allowed only in the global handler and the worker loop, and must log
  with `logger.exception(...)` before converting the error.
- Fail fast on bad input (Pydantic validation, guard clauses) rather than deep in the pipeline.

## Security
- `tenant_id` and `role` come only from the verified JWT (`app/core/deps.py`), never from
  the request body or query string.
- Another tenant's object → 404. Every new tenant-owned endpoint gets a cross-tenant test.
- No secrets in code; read them from settings. `.env.example` lists every variable with a
  dummy value.
- Never log passwords, tokens, full prompts or document text.

## API
- Errors use the `{error_code, message, field_errors?}` envelope via `AppError` subclasses
  from `app/core/errors.py`. New codes go into [api-spec.md](api-spec.md).
- Request limits are explicit in the schema (`k <= 50`, `content` size cap, `limit <= 100`).
- Endpoint changes update [api-spec.md](api-spec.md) in the same task.

## AI
- Prompts live in `app/generation/prompts.md`, loaded by `app/generation/prompts.py`. Never
  inline prompt text in Python.
- Always request structured JSON output and validate it with a Pydantic model before use.
- Validate cited chunk IDs against the context that was actually sent. A malformed or
  unsupported reply is retried once, then becomes `LLM_INVALID_OUTPUT` or
  `insufficient_evidence`; it is never passed through.
- Log every LLM call: model, latency, token usage, outcome. No prompt or answer text by default.
- AI gateways (`llm_client.py`, embedding and reranker wrappers) stay separate from services.

## Evaluation
- Deterministic IR metrics (P@k, R@k, MRR, nDCG) are pure functions with unit tests against
  hand-computed examples.
- Every run records the dataset name + SHA-256, split, full config, model names and git SHA.
- Tune only on `dev`. `test` is used for final comparisons and noted as such in the report.
- LLM-judged metrics (faithfulness, context precision/recall) are reported next to, never
  instead of, deterministic metrics.

## Data
- Schema changes only through models + Alembic revisions. `uv run alembic check` before handover.

## Dependencies
- Add with `uv add <pkg>` (or `uv add --dev <pkg>` for tooling); commit `pyproject.toml` and
  `uv.lock` together. Justify each new package in the task doc.

## Tests
- **Test by risk, not by coverage percentage.** Prioritise complex or high-impact logic:
  metrics, fusion, chunk/span overlap, citation validation, tenant isolation, failure paths.
  Don't write tests for trivial getters or framework behaviour.
- pytest, in `tests/` mirroring `app/` (`tests/retrieval/test_fusion.py`).
- Unit tests for pure logic (chunking, fusion, metrics, citation validation) need no DB.
- Integration tests use the Docker Postgres (`TEST_DATABASE_URL`) and roll back per test
  (`db_session` fixture). Use the `make_tenant` / `make_user` fixtures and `auth_headers(user)`
  from `tests/conftest.py`; never hand-roll users or tokens in tests.
- The LLM is replaced by a fake client in tests; no network calls in the default test run.
- Cover: happy path, role denial, cross-tenant access, and failure paths (timeouts, bad output).
- Commands: `docker compose up -d postgres`, then `uv run pytest -q` and `uv run ruff check .`.

## Never
- ❌ Placeholder implementations or `TODO` comments. Deferred work goes into a task file.
- ❌ Ignoring the existing architecture, or refactoring unrelated files.
- ❌ Changing working code unless required.
- ❌ Unnecessary packages (no LangChain/LlamaIndex for things that are 20 lines of Python).

## Workflow
One feature at a time. Plan in `.claude/tasks/NNN-*.md`, get approval, implement, then
update the checklist and handover sections and [tasks.md](tasks.md).

## Version control
- `main` is releasable; `dev` is the integration branch. Each task gets a short-lived branch
  off `dev` named `task/NNN-short-name`, merged back through a small, focused PR.
- One task per PR. Unrelated fixes go in their own PR (or a new task file).
- Commit messages: imperative summary under ~70 chars with a type prefix
  (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`), then a body explaining why.
  Example: `feat: add RRF fusion for hybrid search`.
- Commit `pyproject.toml` and `uv.lock` together; commit migrations with their model change.

## Refactoring
- Refactor only code touched by the current task, or as its own approved task. Never mix a
  refactor with a behaviour change in the same commit.
- Small cleanups found during a task go into the task doc's "Future improvements"; if they
  are worth doing, they become a dedicated task in [tasks.md](tasks.md). Plan one cleanup
  task after every few feature tasks (as in the roadmap's W4 and W6).
