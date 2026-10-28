# Plan & Review Workflow

## Before Starting Any Work

Always start in **Plan Mode**.

1. Understand the requested feature.
2. Break the work into the smallest possible MVP.
3. Think through architecture before writing code.
4. Research unfamiliar APIs, libraries, or best practices when necessary.
5. Prefer official documentation over blogs.
6. Avoid over-engineering. Build the simplest solution that satisfies the requirements.

---

## Planning

For every non-trivial task:

- Create a new task file inside

.claude/tasks/

using sequential numbering.

Example

.claude/tasks/001-project-setup.md

Each task document should include:

- Goal
- Scope
- Assumptions
- Architecture decisions
- Files to modify
- Step-by-step implementation plan
- Risks
- Future improvements
- Checklist

Do NOT begin implementation until I approve the plan.

---

## During Implementation

After completing each task:

- Update the checklist
- Record implementation decisions
- Document any deviations from the original plan
- List all modified files
- Explain why each change was made

If new work is discovered:

- Update the task document
- Ask for approval before expanding scope.

---

## Handover

Every completed task document should contain:

### Summary

A concise summary of what was implemented.

### Architecture Notes

Important design decisions.

### Database Changes

Schema changes and migrations.

### API Changes

Endpoints added or modified.

### Evaluation Results

Metrics measured in this task (dataset, split, config), or "none".

### Future Work

Suggested improvements.

This project should always be understandable by another engineer without additional explanation.

# Implementation Rules

Always implement one feature at a time.

Never implement multiple unrelated features in one response.

Before writing code:

- Explain the approach.
- Identify edge cases.
- Identify security concerns.
- Explain tradeoffs.

After writing code:

- Explain what changed.
- Explain why.
- Suggest tests.
- Wait for approval before continuing.

# Code Quality Rules

Never duplicate business logic.

Prefer composition over inheritance.

Business logic belongs in services.

Routers should only:

- validate input
- call services
- return responses

Repositories should only access the database.

Keep functions under 40 lines where practical.

Prefer readability over cleverness.

Avoid premature optimization.

Add short comments that explain *why*, not *what*.

Follow SOLID pragmatically: single responsibility per function/module, services depend on
small protocols injected via `Depends`, new strategies are added rather than branched in.
Introduce an abstraction only when a second implementation exists (a test fake counts).

Use guard clauses and early returns; no more than two levels of nesting.

Use descriptive names and PEP 8 (enforced by ruff).

Never write a bare or empty `except`; catch specific exceptions and translate external
errors at the gateway boundary.

Test by risk (metrics, ranking, citations, tenant isolation, failure paths), not for a
coverage number.

Keep PRs small: one task per branch (`task/NNN-name` off `dev`), conventional commit
messages, no refactors mixed with behaviour changes.

Full details: [coding-standards.md](coding-standards.md).

# Never Do These

❌ Never generate placeholder implementations.

❌ Never leave TODO comments.

❌ Never ignore existing architecture.

❌ Never hardcode secrets.

❌ Never create duplicate utilities.

❌ Never install unnecessary packages.

❌ Never refactor unrelated files.

❌ Never change working code unless required.

❌ Never report a metric that was not actually measured.

# AI Project Rules

When implementing AI features:

- Keep prompts in `app/generation/prompts.md`.
- Never hardcode prompts inside source code.
- Always use Structured JSON outputs.
- Validate AI responses before using or saving them.
- Validate citations against the retrieved context on the server.
- Handle malformed AI responses gracefully.
- Log AI requests and errors (metadata only, no prompt text by default).
- Separate AI services from business services.

# Evaluation Rules

- Build and label the dataset before tuning.
- Tune on the `dev` split only; use `test` for final comparisons.
- Record dataset hash, split, config, models and git SHA with every result.
- Break results down by `query_type`, not only the aggregate.

## Project Context

Before starting any implementation:

1. Read .claude/PROJECT.md
2. Read .claude/architecture.md
3. Read .claude/api-spec.md
4. Read .claude/database.md
5. Read .claude/tasks.md
6. Read .claude/plan.md
7. Read .claude/coding-standards.md
8. Read .claude/UI.md
These files define the current project requirements.

Do not assume requirements that are not documented.

## Commands

- Install: `uv sync`
- Run API: `uv run uvicorn app.main:app --reload`
- Run worker: `uv run python -m app.worker`
- Migrate: `uv run alembic upgrade head`
- Test: `docker compose up -d postgres` then `uv run pytest -q`
- Lint: `uv run ruff check .` and `uv run ruff format --check .`
