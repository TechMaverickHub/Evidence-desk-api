# Task 011 — Reliability: LLM failure taxonomy, bounded retries, stale jobs, failure scenarios

**Status:** ✅ Done
**Week:** W4 · **Modules:** `app/generation`, `app/core`, `app/jobs`, `app/worker.py`, `app/evaluation` ·
**Branch:** `task/011-reliability` (off `task/010-chunking`)

## Goal

Every failure the roadmap names has a defined behaviour and a test proving it:
- provider timeout
- rate limit
- invalid model output
- empty retrieval
- interrupted ingestion

This task also fixes the reliability gaps found in 009a, 009b and 010:
- **Daily quota:** a daily-quota 429 looks like a transient outage, gets retried pointlessly,
  and turns the rest of an evaluation run into errors.
- **Bad key:** returns "temporarily unavailable" and is retried.
- **`answer-judge`** exits with a raw traceback on provider errors.
- **Crashed workers** leave jobs `running` forever.

## Scope

In:
1. **LLM failure taxonomy at the gateway.** Three error classes: two new ones, both
   subclasses of `LLMUnavailableError`, so existing handlers keep working.

   | Error | HTTP | Code | When | Retry by client? |
   |---|---|---|---|---|
   | `LLMUnavailableError` | 503 | `LLM_UNAVAILABLE` | timeout, connection error, 5xx, short 429, after SDK retries | yes, with `Retry-After` when known |
   | `LLMQuotaExceededError` (new) | 503 | `LLM_QUOTA_EXCEEDED` | 429 whose `retry-after` > 60 s, or whose body names a per-day limit (TPD/RPD) | after `Retry-After` (minutes to hours) |
   | `LLMNotConfiguredError` (new) | 503 | `LLM_NOT_CONFIGURED` | no `GROQ_API_KEY`, or 401/403 (bad key, no access), or 404 (unknown model) | no; an operator must fix it |

   - A 503 gets a `Retry-After` header whenever the provider gave one.
   - The message never includes the key or provider text beyond the limit type.
2. **A bounded worst case.**
   - Defaults change to `LLM_TIMEOUT_SECONDS` 20 (was 30) and `LLM_MAX_RETRIES` 2.
   - The worst case per LLM call is documented: 3 × 20 s + backoff ≤ 1.5 s, about 62 s.
   - An answer makes at most 2 calls (009a's corrective retry), so about 124 s.
   - The real SDK retry behaviour is tested through an injected `httpx.MockTransport`: no
     network, and sleeps patched.
3. **Evaluation runs stop cleanly.**
   - **`answer-run`:**
     - **Stops** at the first `LLMQuotaExceededError` or `LLMNotConfiguredError`. Finished
       answers stay in the partial file, and it exits 1 with a message like "Groq daily
       quota reached; N/M answered; rerun the same command after ~X min to resume".
     - **Records** transient errors as before.
   - **`answer-judge`:** exits 1 on any LLM error with the same kind of message (progress is
     already saved per record), instead of a traceback.
4. **Stale-job recovery.**
   - The worker requeues `running` jobs whose `started_at` is older than
     `JOB_STALE_AFTER_SECONDS` (default 1800).
   - It does this at startup, then whenever the queue is empty, at most once per stale
     period.
   - **Attempt limit:** after `JOB_MAX_ATTEMPTS` (default 3) attempts, a stale job is marked
     `failed`, with the error "worker stopped while running (N attempts)", and its handler's
     `on_failure` runs (an ingest job then marks its document `failed`).
5. **A failure-scenario catalogue,** in this file and in [architecture.md](../architecture.md):
   each scenario, its defined behaviour, and the test that proves it. Existing tests are
   referenced, not rewritten; new tests are added only for new behaviour.

Out:
- DB statement timeouts, embedding or reranker failures, and circuit breakers. Noted as
  future work, because the roadmap's W4 list is about the LLM and jobs.
- Retrying inside `answer_question` beyond the SDK's own retries. A request-level retry
  would multiply worst-case latency.
- Async job heartbeats. A time threshold is enough for one worker and jobs of minutes.

## Failure-scenario catalogue (target)

| # | Scenario | Defined behaviour | Test |
|---|---|---|---|
| 1 | Provider timeout | SDK retries `LLM_MAX_RETRIES` times, then 503 `LLM_UNAVAILABLE`; exactly `max_retries + 1` requests | new: real SDK + MockTransport |
| 2 | Transient rate limit (429, short `retry-after`) | Retried after the given delay; success if a later attempt succeeds | new: real SDK + MockTransport |
| 3 | Persistent rate limit / 5xx | After retries, 503 `LLM_UNAVAILABLE` with `Retry-After` if provided | new |
| 4 | Daily quota (429 TPD) | 503 `LLM_QUOTA_EXCEEDED` + `Retry-After`; answer-run stops with a resume hint, finished answers kept | new (gateway + runner + CLI) |
| 5 | Bad key / no access / unknown model | 503 `LLM_NOT_CONFIGURED`, **no retries** (1 request); runs stop | new |
| 6 | No key configured | 503 `LLM_NOT_CONFIGURED`; search keeps working | 009a test, updated error code |
| 7 | Invalid model output | One corrective retry, then 502 `LLM_INVALID_OUTPUT` (format) or `insufficient_evidence` (unsupported) | 009a tests (existing) |
| 8 | Empty retrieval | `insufficient_evidence`, 0 LLM calls | 009a test (existing) |
| 9 | Ingestion fails mid-document | Rolled back; document and job `failed`; resubmit retries | 003 tests (existing) |
| 10 | Worker crashes mid-job (interrupted ingestion) | Stale job requeued, then processed; after max attempts, `failed` + document `failed` | new |
| 11 | Judge provider failure | `answer-judge` exits 1 with a message; judged records kept | new |
| 12 | DB unreachable | `/health` 503 `{database: unreachable}` | 001 test (existing) |

## Assumptions

1. **Classifying a quota error** uses what Groq sends:
   - status 429 plus a `retry-after` over 60 s (the SDK itself treats over 60 s as "not a
     short wait")
   - **or** an error message naming a per-day limit
   - The message check is a fallback, written in one function and tested with the real
     error text recorded in 009b ("Rate limit reached … on tokens per day (TPD) …").
2. **One worker process.**
   - Requeueing relies on time, not locks, because claims are committed before work
     starts, so no lock is held during a job.
   - With several workers, a stale period longer than the longest job keeps this safe. The
     longest observed job is an evaluate run of about 3 minutes, so 30 minutes leaves ample
     margin.
3. **No Groq calls in this task.** All tests use mock transports or fakes.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Error classes | Subclasses of `LLMUnavailableError` with their own `error_code` and message; `retry_after_seconds` on the instance → `Retry-After` header | Existing `except LLMUnavailableError` paths keep working (LSP); callers that care distinguish subclasses |
| Classification place | `llm_client._classify(exc)`: the only place that reads SDK exceptions | Services and runners never see SDK types ([coding-standards.md](../coding-standards.md)) |
| Retries | The SDK's own bounded retries (`max_retries`), with timeout per attempt from settings | Proven backoff and `retry-after` handling; our tests pin the count via MockTransport rather than re-implementing it |
| No-retry for config errors | The SDK doesn't retry 401/403/404 (it retries only 408/409/429/5xx), so a single request is checked | Verified against SDK source; the test pins it in case an SDK upgrade changes it |
| Run stopping | `answer_runner` catches the two non-transient subclasses and raises `RunStoppedError(answered, total, retry_after)`; the CLI prints a resume hint | Transient errors stay per-question records (rerun retries them); hopeless errors stop early instead of producing dozens of identical errors |
| Stale jobs | `jobs.repository.find_stale_jobs` + `worker.recover_stale_jobs(session, handlers)` (requeue or fail + `on_failure`) | Small, testable, no schema change. `attempts` already exists |
| Recovery timing | Startup + whenever the queue is empty, rate-limited to once per stale period | Bounded DB work; a crash is recovered within one period |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| OCP / LSP | New failure kinds are subclasses; no caller changes needed unless it wants the distinction |
| SRP | Classification in the gateway; stopping policy in the runner; recovery in the worker |
| Test by risk | Each scenario in the catalogue has a test; retries are tested through the real SDK |

### Dependencies added
None. `httpx`, needed for `MockTransport`, is already installed as the SDK's transport.

## Files to create / modify

```
app/core/errors.py                 LLMQuotaExceededError, LLMNotConfiguredError; instance Retry-After header
app/generation/llm_client.py       _classify; optional http_client injection (tests)
app/generation/deps.py, service.py missing key → LLMNotConfiguredError
app/core/config.py, .env.example   LLM_TIMEOUT_SECONDS 20; JOB_STALE_AFTER_SECONDS, JOB_MAX_ATTEMPTS
app/evaluation/answer_runner.py    stop on quota/config errors (RunStoppedError)
app/evaluation/answer_cli.py       resume hints; clean judge exit
app/jobs/repository.py, app/worker.py   stale-job detection and recovery
tests/generation/test_llm_retries.py (new: MockTransport), tests/jobs/test_stale_jobs.py (new),
tests/evaluation/test_answer_runner.py / test_answer_cli.py (stop + messages), API error-code tests
.claude/{architecture,api-spec,tasks,plan}.md   catalogue, error codes, settings
```

## Step-by-step implementation plan

0. `git switch -c task/011-reliability`.
1. **Error classes and per-instance `Retry-After` headers;** envelope tests.
2. **Gateway:**
   - `_classify` and `http_client` injection.
   - MockTransport tests for scenarios 1–5, with the SDK's sleep patched.
3. **Missing key → `LLMNotConfiguredError`;** update the 009a test (scenario 6).
4. **Runner stop policy and CLI messages;** tests for scenarios 4, 5 and 11.
5. **Stale-job recovery** in the repository and worker; tests for scenario 10, requeue and
   final failure.
6. **Catalogue in docs; lint and full suite;** handover; commit after you confirm.

## Tests (chosen by risk)

The catalogue above is the test list. Highest risk first:
1. **Scenario 4:** an evaluation run wastes the day's quota.
2. **Scenario 10:** jobs stuck forever.
3. **Scenarios 1–3:** latency and outage handling.
4. **Scenario 5:** a bad key is retried and mislabelled.

## Edge cases

- **429 without a `retry-after` header:** classify by message. If there is still no
  per-day text, treat it as transient.
- **`retry-after` as an HTTP date:** the SDK parses dates. Our classifier reads the SDK's
  parsed value only when it's numeric seconds, and otherwise falls back to the message.
- **A stale job whose document was deleted:** the handler raises `IngestionError`, and the
  normal failure path records it.
- **A recovered job runs twice:** both handlers are idempotent. Ingest replaces chunks per
  chunker; an evaluate run writes results only in the success transaction.

## Security

- **Error messages and logs** carry the error class and limit type, never the key or the
  raw provider body.
- **`Retry-After`** comes from the provider's header only; it is never echoed from request
  input.

## Risks

- **Message-based quota detection may break** if Groq changes its wording. Mitigations:
  the header rule comes first, and the misclassification is safe (a quota error treated as
  transient just wastes retries, as before).
- **Stale period vs long jobs:** documented, and configurable.

## Future improvements

- DB `statement_timeout` and translation to 503.
- Embedding and reranker failure handling.
- A circuit breaker if the provider is down for long periods.
- Heartbeats for long jobs, and multi-worker leases.

## Checklist

- [x] Branch `task/011-reliability`
- [x] Error classes + `Retry-After` + tests
- [x] Gateway classification + MockTransport retry tests (1–5)
- [x] Missing key → `LLM_NOT_CONFIGURED` (6)
- [x] Runner stop + CLI messages + judge clean exit (4, 5, 11)
- [x] Stale-job recovery + tests (10)
- [x] Catalogue in docs; `ruff check`, `ruff format --check`, full test suite clean
- [x] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit after confirmation

---

## Handover

### Summary
**Every failure the roadmap names now has a defined behaviour and a test.** The catalogue of
12 scenarios is in [architecture.md](../architecture.md) under "Failure scenarios".

**Provider failures are classified at the gateway** into three 503 errors:

| Code | Meaning | Retried |
|---|---|---|
| `LLM_UNAVAILABLE` | Transient | Yes, by the SDK |
| `LLM_QUOTA_EXCEEDED` | Daily quota | No point until it resets |
| `LLM_NOT_CONFIGURED` | Missing or bad key, no access, unknown model | Never |

Every one carries a `Retry-After` header when Groq sent one.

**Evaluation runs:**
- `answer-run` stops at the first quota or configuration error, keeps finished answers, and
  prints how to resume.
- `answer-judge` exits cleanly with the same hint instead of a traceback.

**Workers** requeue jobs orphaned by a crash, and fail them (with their documents) after
3 attempts.

**Latency:** the LLM timeout per attempt drops from 30 s to 20 s.

295 tests pass (17 new). No Groq calls were made.

### Architecture Notes
- **Error classes.** `LLMQuotaExceededError` and `LLMNotConfiguredError` subclass
  `LLMUnavailableError`.
  - Every existing `except LLMUnavailableError` keeps working.
  - Callers that care (the runners) catch the subclasses first.
  - `retry_after_seconds` becomes a per-instance `Retry-After` header through the existing
    error envelope.
- **Classification.** `llm_client._classify` is the only code that reads SDK exceptions,
  and runs after the SDK's own retries:
  - 401/403/404 → not configured
  - 429 with `retry-after` > 60 s (the SDK's own "short wait" limit) **or** a per-day
    message (TPD/RPD) → quota
  - everything else (timeouts, connection errors, 5xx, short 429) → unavailable
  - Logs record the error class and kind only, never the key or the provider's message.
- **Retry behaviour is tested, not re-implemented.**
  - `GroqClient` accepts an optional `httpx.Client`.
  - The tests run the real SDK over `httpx.MockTransport` with its sleep patched, pinning:
    3 requests for a timeout or 503, 2 for a 429-then-200, and **1 for 401/403/404**.
  - An SDK upgrade that changes retries fails there first.
- **Run stopping.**
  - `run_answers` lets the two hopeless errors propagate as a `RunError` carrying a
    `stop_message`: the reason, the code, done/total, the progress file, and "rerun after
    about N min" or "fix the configuration".
  - Transient errors are still recorded per question and retried on a rerun.
  - The judge reuses `stop_message`.
- **Stale jobs.**
  - `recover_stale_jobs` runs at worker start, then at most once per stale period.
  - It finds `running` jobs started before `now − JOB_STALE_AFTER_SECONDS`, locked with SKIP
    LOCKED.
  - Under the attempt limit, they are requeued, keeping `attempts`. At the limit, the
    handler's `on_failure` runs and the job is marked `failed` with "worker stopped while
    running (N attempts)".
  - It is time-based, because claims are committed before work starts, so no lock is held
    during a job.

### Deviations from the plan
- **A shell-quoting slip, caught before it shipped.** The quota regex's `\b` word
  boundaries were written as literal backspace characters. A behavioural check caught it
  (the regex didn't match "TPD" as a word) and it was fixed. A scan of every `.py` and
  `.md` file in `app/`, `tests/` and `.claude/` found no other control characters.
- **One existing 009a test updated:** the missing-key test now checks
  `error_code == "LLM_NOT_CONFIGURED"`.
- **The catalogue lives in `architecture.md`.** The task file's draft table is superseded
  by it, with the real test names.
- **Otherwise as planned.**

### Database Changes
None. Stale-job recovery uses the existing `jobs.status`, `attempts` and `started_at`.

### API Changes
- **New error codes**, both 503: `LLM_QUOTA_EXCEEDED` and `LLM_NOT_CONFIGURED`. Clients
  treating any 503 as "try later" keep working.
- **`Retry-After` header** on LLM 503s when the provider gave a delay.
- **Settings:**
  - `LLM_TIMEOUT_SECONDS` default 30 → 20
  - new `JOB_STALE_AFTER_SECONDS` (1800) and `JOB_MAX_ATTEMPTS` (3)
- See [api-spec.md](../api-spec.md).

### Evaluation Results
None: this task changes failure handling, not retrieval or answers.

**Worst-case latency per LLM call:** 3 attempts × 20 s + backoff ≈ 62 s, down from about
92 s. An answer makes at most 2 calls.

### Future Work
- **DB `statement_timeout`** and translation of slow queries to 503.
- **Embedding and reranker failures,** e.g. model load errors at startup.
- **A circuit breaker** for long provider outages.
- **Leases or heartbeats** for multi-worker deployments and long jobs.
- **Docker Compose and CI (task 013)** should run the worker as a supervised process, so
  stale-job recovery has a worker to run in.

### Modified Files
| File | Why |
|---|---|
| `app/core/errors.py` | Quota / not-configured errors; per-instance `Retry-After` |
| `app/generation/llm_client.py` | `_classify`, `_retry_after_seconds`, `http_client` injection |
| `app/generation/service.py` | Missing key → `LLMNotConfiguredError` |
| `app/evaluation/answer_runner.py`, `answer_cli.py` | Stop on hopeless errors; `stop_message`; clean judge exit |
| `app/jobs/repository.py`, `app/worker.py` | `find_stale_jobs`, `requeue_job`, `recover_stale_jobs` in the worker loop |
| `app/core/config.py`, `.env.example` | `LLM_TIMEOUT_SECONDS` 20; `JOB_STALE_AFTER_SECONDS`, `JOB_MAX_ATTEMPTS` |
| `tests/generation/test_llm_retries.py`, `tests/jobs/test_stale_jobs.py` (new); `test_answers_api.py`, `test_answer_runner.py`, `test_answer_cli.py` | Scenarios 1–6, 10, 11 |
| `.claude/{architecture,api-spec,tasks,plan}.md`, this file | Catalogue, codes, settings |
