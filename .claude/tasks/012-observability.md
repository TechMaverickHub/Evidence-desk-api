# Task 012 — Observability: traces per pipeline stage, token usage and cost

**Status:** ✅ Done
**Week:** W5 · **Modules:** `app/core` (telemetry, logging), `app/retrieval`, `app/generation`, `app/worker.py`, `app/evaluation` (cost) ·
**Branch:** `task/012-observability` (off `task/011-reliability`)

## Goal

For any request or job, you should be able to see where the time went and what it cost,
without logging any document or question text:
- **Traces:** one trace per HTTP request or worker job, with child spans for each pipeline
  stage (embed query, dense, keyword, fuse, rerank, each LLM call).
- **Attributes on spans:** stage parameters, result counts, token usage, outcome.
- **Logs:** each JSON log line carries the `trace_id`, so logs and traces join up.
- **Cost:** an estimated USD cost per answer and per evaluation run, from configured
  per-model prices.

## Scope

In:
- **`app/core/telemetry.py`:** sets up an OpenTelemetry `TracerProvider` from settings.
  - `TELEMETRY_EXPORTER`:
    - `none` (default): spans are created but not exported
    - `console`: spans printed to stdout, for local debugging
    - `otlp`: the standard `OTEL_EXPORTER_OTLP_ENDPOINT`, for a collector such as Jaeger in
      task 013
  - `OTEL_SERVICE_NAME` defaults to `evidencedesk-api` or `evidencedesk-worker`.
- **The API** passes its provider to FastAPI's built-in telemetry, so request and operation
  spans come for free (FastAPI 0.162 docs, `advanced/opentelemetry`). `/v1/health` is
  excluded from tracing.
- **Stage spans** from a module tracer `evidencedesk`:

  | Span | Attributes |
  |---|---|
  | `search` | mode, rerank, k, chunker, result count |
  | `search.embed_query`, `search.dense`, `search.keyword`, `search.fuse`, `search.rerank` | from the existing stage timer, so `latency_ms` and spans come from one place |
  | `answer` | status, passage count, LLM call count |
  | `llm.call` | model, attempt, outcome or error code, prompt and completion tokens, estimated cost |
  | `job` (worker) | kind, job id, attempts, outcome |
- **Cost:**
  - `LLM_PRICES`: a JSON map of model → `[input_usd_per_mtok, output_usd_per_mtok]`. It
    defaults to empty, so cost is `null`. That is honest for the free tier and avoids
    hard-coding prices that change.
  - `AnswerUsage.cost_usd` in `/v1/answers`.
  - The answer-run header records the prices in force; reports show estimated generator
    cost per run.
- **Logs:** the JSON formatter adds `trace_id` and `span_id` when a span is active.

Out:
- Custom metrics: FastAPI already records HTTP request metrics when a meter provider is set.
  Per-stage histograms are future work.
- Judge-call cost (judge tokens aren't stored yet).
- Hosting a trace backend. Docker Compose with Jaeger belongs to task 013; this task can
  export to it via OTLP.

## Assumptions

1. **New dependencies:**
   - `opentelemetry-sdk`: the provider, processors, and console and in-memory exporters
     (tests).
   - `opentelemetry-exporter-otlp-proto-http`: export to any OTLP collector.

   `opentelemetry-api` is already installed (a FastAPI dependency). Approving the plan
   approves `uv add` of these two.
2. **Prices are configured by you.** Groq's free tier costs $0, and paid prices change. The
   code computes `tokens / 1e6 × price` and never ships a price table.
3. **Overhead:** with `TELEMETRY_EXPORTER=none`, spans cost microseconds. With exporters,
   `BatchSpanProcessor` exports in the background.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Request spans | FastAPI's built-in telemetry with our provider (`telemetry={"tracer_provider": ..., "exclude": health}`) | No hand-written middleware; official in 0.162 |
| Stage spans | One context manager in the existing `_Search.timed()` opens a span and records the latency | One place times each stage, so the response's `latency_ms` and the trace can't disagree (DRY) |
| What spans carry | Counts, sizes, model names, token counts, error codes; **never** question, passage or answer text | Same rule as logs ([coding-standards.md](../coding-standards.md)); a test scans every exported span for the question text |
| Provider setup | `configure_telemetry(service_name)` called once in `create_app` / worker `main`; the global provider is set only if none is set | OpenTelemetry allows one global provider per process; tests install an in-memory provider first |
| Exporter choice | `none` / `console` / `otlp` setting; OTLP endpoint and headers via standard `OTEL_*` env vars | Standard env vars work with any collector; `none` keeps tests and keyless dev quiet |
| Cost | `cost_usd = (prompt × in + completion × out) / 1e6` from `LLM_PRICES[model]`; null if unpriced | Transparent and configurable; null is honest instead of a guessed number |
| Log correlation | Formatter reads `trace.get_current_span().get_span_context()` | Lets you find the log lines for a slow trace and vice versa |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `telemetry.py` only sets up providers; services only add spans and attributes |
| DRY | Stage timing and spans share one context manager; cost is one function used by the API and reports |
| Test by risk | Privacy (no text in spans), trace shape (stages nested under the request), cost maths, no-exporter default |

### Dependencies added
`opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http` (see Assumptions).

## Files to create / modify

```
app/core/telemetry.py              new: configure_telemetry, tracer
app/core/config.py, .env.example   TELEMETRY_EXPORTER, LLM_PRICES (+ documented OTEL_* vars)
app/core/logging.py                trace_id / span_id in JSON logs
app/main.py                        provider → FastAPI telemetry; exclude /v1/health
app/worker.py                      configure telemetry; span per job
app/retrieval/service.py           _Search.timed opens stage spans; `search` span
app/generation/service.py          `answer` + `llm.call` spans; usage.cost_usd
app/generation/costs.py            new: estimate_cost(model, prompt, completion)
app/generation/schemas.py          AnswerUsage.cost_usd
app/evaluation/answer_records.py, answer_runner.py, answer_report.py   prices in header; estimated run cost
pyproject.toml, uv.lock            + opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http
tests/core/test_telemetry.py, tests/generation/test_answer_tracing.py, cost tests
.claude/{architecture,api-spec,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/012-observability`; `uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`.
1. **`telemetry.py`** and settings; a session-wide in-memory provider in tests.
2. **API wiring** (FastAPI telemetry, health excluded); worker wiring with a span per job.
3. **Stage spans** through `_Search.timed`; `search` and `answer` spans; `llm.call` with
   tokens and cost.
4. **Cost:** `estimate_cost`, `AnswerUsage.cost_usd`, answer-run header prices and the report
   line.
5. **Log correlation.**
6. **Tests** (below); lint; docs; a manual check with `TELEMETRY_EXPORTER=console` on one
   search request (no Groq); commit after you confirm.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Text leaks into telemetry | `/v1/answers` with a distinctive question and passage: no span name, attribute or event contains either |
| Broken trace shape | One `/v1/answers` request produces one trace with the request span, `answer`, `search`, the stage spans and `llm.call` (×2 on a corrective retry), all sharing the trace id |
| Spans and `latency_ms` disagree | The stage spans present match the `latency_ms` keys of the same request |
| Wrong cost | Hand-computed cost for a priced model; `null` for an unpriced model or empty prices |
| Exporter misconfiguration | `none` adds no exporter; `console` adds a console exporter; an invalid value fails at settings load |
| Logs lose correlation | A log line emitted inside a span carries that span's `trace_id` |
| Health noise | `/v1/health` produces no span |

## Security

- Spans and logs carry no question, passage, answer, prompt or credential text (tested).
- OTLP headers (e.g. a collector API key) come from `OTEL_EXPORTER_OTLP_HEADERS` in the
  environment, never from code or logs.
- `exclude` keeps health probes out of traces.

## Risks

- **OpenTelemetry's single global provider** makes test isolation awkward. Mitigation: one
  session provider with an in-memory exporter, cleared per test.
- **FastAPI's built-in telemetry is new** (0.162). Mitigation: our stage spans don't depend
  on it, and a test checks request spans exist with our provider.
- **Prices drift.** Mitigation: user-configured, null by default, and recorded in each run
  header.

## Future improvements

- Per-stage latency histograms, and token and cost counters, as OTel metrics.
- Judge token and cost accounting.
- Sampling configuration for high traffic.
- Jaeger or Tempo in Docker Compose (013).

## Checklist

- [x] Branch `task/012-observability`; dependencies added
- [x] `telemetry.py` + settings; test provider
- [x] API + worker wiring; health excluded
- [x] Stage spans via `_Search.timed`; `search`, `answer`, `llm.call` spans
- [x] Cost estimation (API, runs, reports)
- [x] Log correlation
- [x] Tests; `ruff check`, `ruff format --check`, full suite; manual console-export check
- [x] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit after confirmation

---

## Handover

### Summary
Every API request and worker job can now be traced with OpenTelemetry:
- **Request spans** from FastAPI 0.162's built-in telemetry, using our provider:
  dependencies, endpoint and serialisation. Health checks are excluded.
- **Our spans:** `search`, one `search.<stage>` per stage, `answer`, one `llm.call` per
  model call (tokens and cost), and `job`.
- **Logs:** JSON lines carry `trace_id` and `span_id`, so logs and traces join up.
- **Cost:** `/v1/answers` reports `usage.cost_usd` from prices you configure in
  `LLM_PRICES`, null when a model is unpriced. Answer-run reports show the run's
  estimated generator cost at the prices recorded with the run.
- **Exporter:** `TELEMETRY_EXPORTER` = `none` (default), `console` or `otlp` (standard
  `OTEL_*` variables).

308 tests pass (13 new). A manual run printed one search request's spans to the console.

### Architecture Notes
- **One provider per process.** `configure_telemetry` installs it once and returns the
  existing one if already installed. Export goes through a `BatchSpanProcessor`, in the
  background.
- **One timer for latencies and spans.** Stage spans come from the existing `_Search.timed`
  context manager, so `latency_ms` and the trace can never list different stages (tested).
- **`llm.call` spans** get their attributes in `_log_call`, the same metadata as the log
  line. Provider errors propagate through the span, so OpenTelemetry marks it as an error.
- **Cost:**
  - `generation.costs.estimate_cost` uses current settings; `cost_at` uses explicit prices,
    so reports recompute from the prices recorded with a run.
  - `add_costs` keeps a total only while every part is priced.
- **Test isolation.**
  - `app.main` creates the app at import, which installs a default provider, and
    OpenTelemetry keeps the first one.
  - So `tests/telemetry_plugin.py`, loaded with `-p` (`pyproject.toml`, plus
    `pythonpath = ["."]`), installs an in-memory provider before any import.
  - The `spans` fixture clears it per test.

### Deviations from the plan
- **Test provider placement.** It was planned in `conftest.py`, but `app.main` installs a
  default provider at import (module-level `app = create_app()`), before conftest code
  runs. It moved to an early-loaded pytest plugin.
- **Pre-existing bug fixed (since 008).**
  - **The bug:** the `search` log line merged the stage latencies into the same dict as the
    options, so the stage `rerank` (ms) overwrote the option `rerank` (true/false). Seen in
    captured test logs.
  - **The fix:** latencies are now nested under `latency_ms` in that log line.
  - **Impact:** log consumers reading top-level stage keys from `search` lines need to read
    `latency_ms.<stage>`. There are no consumers yet.
- **`process_next_job` was split:** `_run_job` holds the handler call, so the job span wraps
  it without deeper nesting.
- **The manual check used `/v1/search`, not `/v1/answers`,** to avoid Groq calls. The
  answer path's spans are covered by tests with a scripted LLM.

### Database Changes
None.

### API Changes
- `/v1/answers` `usage` gains `cost_usd`.
- **New settings:** `TELEMETRY_EXPORTER` (`none` | `console` | `otlp`) and `LLM_PRICES`
  (JSON). The standard `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` and
  `OTEL_EXPORTER_OTLP_HEADERS` are honoured.
- **New dependencies:** `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http`
  (1.45.2). `opentelemetry-api` moved from 1.45.1 to 1.45.2 with them.

### Evaluation Results
None: no retrieval or answer behaviour changed.

**Manual check** (`TELEMETRY_EXPORTER=console`, real models, tenant `eval-corpus-v1`):

| What was sent | Result |
|---|---|
| One `POST /v1/search` (hybrid + rerank) | **10 spans in one trace** |
| One `GET /v1/health` | No span |

The 10 spans:
- `POST /v1/search`
- FastAPI's `fastapi.dependencies`, `fastapi.endpoint` and `fastapi.serialization`
- `search`: mode hybrid, rerank true, k 10, chunker `tokens-450-overlap-75`, 10 results
- `search.embed_query`, `search.dense`, `search.keyword`, `search.fuse`, `search.rerank`

The query text did not appear anywhere in the exported output.

### Future Work
- **Metrics:** per-stage latency histograms, plus token and cost counters as OpenTelemetry
  metrics. FastAPI already records HTTP metrics when a meter provider is set.
- **Judge cost:** judge-call token and cost accounting in answer runs.
- **Sampling:** configure it for higher traffic.
- **Trace viewer:** a Jaeger or Tempo service in Docker Compose (013), with
  `TELEMETRY_EXPORTER=otlp`.

### Modified Files
| File | Why |
|---|---|
| `app/core/telemetry.py` (new) | Provider setup, exporter choice, module tracer |
| `app/core/config.py`, `.env.example` | `TELEMETRY_EXPORTER`, `LLM_PRICES` |
| `app/core/logging.py` | `trace_id` / `span_id` in JSON logs |
| `app/main.py` | FastAPI telemetry with our provider; health excluded |
| `app/worker.py` | Worker provider; `job` span; `_run_job` extracted |
| `app/retrieval/service.py` | `search` and stage spans; latencies nested in the log line |
| `app/generation/service.py`, `schemas.py`, `costs.py` (new) | `answer` / `llm.call` spans; `usage.cost_usd` |
| `app/evaluation/answer_records.py`, `answer_runner.py`, `answer_report.py` | Run prices recorded; estimated run cost in reports |
| `pyproject.toml`, `uv.lock` | Dependencies; pytest plugin and `pythonpath` |
| `tests/telemetry_plugin.py`, `tests/conftest.py`, `tests/core/test_telemetry.py`, `tests/generation/test_answer_tracing.py` | Test provider; tests |
| `.claude/{architecture,api-spec,tasks,plan}.md`, this file | Docs |
