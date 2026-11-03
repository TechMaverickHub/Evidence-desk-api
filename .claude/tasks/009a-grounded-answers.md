# Task 009a — Grounded answers: `POST /v1/answers` with validated citations and abstention

**Status:** ✅ Done
**Week:** W3 · **Modules:** `app/generation` (new), `app/core` (errors, settings) ·
**Branch:** `task/009a-grounded-answers` (off `task/008-rerank`)

## Why 009 is split

The roadmap row bundles two features:
- the answering pipeline: the first LLM call, structured output, citation checks and
  abstention
- answer-level evaluation over the benchmark: abstention rate, citation precision, answer
  correctness and faithfulness, plus calibrating an abstention threshold on dev

The second needs the first, adds LLM-judged metrics and costs real API calls across 150
questions. As with 005 and 006, each becomes its own PR.

| Task | Scope |
|---|---|
| **009a (this plan)** | `POST /v1/answers`: retrieval → context → Groq with a strict JSON schema → server-side validation → `answered` or `insufficient_evidence` |
| 009b | Answer evaluation runs over `evidencedesk-v1`: abstention on unanswerable questions, citation precision against evidence spans, LLM-judged correctness and faithfulness next to the deterministic metrics, and an abstention threshold calibrated on dev |

## Goal

An engineer asks a question and gets one of two results:
- an answer whose every citation the server has checked is one of the passages it actually
  sent to the model
- an explicit `insufficient_evidence`

Malformed or unsupported model output is never passed through.

## Scope

In:
- **`app/generation/prompts.md` + `prompts.py`:** the system and user prompts live in
  Markdown, are loaded and checked at startup, and are never written inline in Python.
- **`app/generation/llm_client.py`:** an `LLMClient` protocol, `complete_json(...)`, with a
  `GroqClient` gateway. The gateway applies the timeout and translates SDK errors into
  `LLMUnavailableError` (503).
- **`app/generation/service.py`:** `answer_question`.
  - retrieve → if nothing was retrieved, `insufficient_evidence` without an LLM call
  - number the passages → call the LLM
  - validate JSON against Pydantic → validate citations → at most one corrective retry →
    respond
- **`app/generation/router.py` and `schemas.py`:** `POST /v1/answers` (viewer).
- **New error classes:** `LLMUnavailableError` (503 `LLM_UNAVAILABLE`) and
  `LLMInvalidOutputError` (502 `LLM_INVALID_OUTPUT`). Both codes already exist in
  [api-spec.md](../api-spec.md).
- **Settings:**
  - `GROQ_API_KEY` (secret, optional, so tests and keyless dev still run)
  - `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_COMPLETION_TOKENS`
  - `ANSWER_CONTEXT_CHUNKS`
- **Logging:** one metadata line per LLM call (model, latency, tokens, outcome, attempt).
  Never the prompt, the passages or the answer text.

Out:
- Answer evaluation and threshold calibration (009b).
- Score-based abstention gating (needs 009b's dev calibration first).
- Streaming.
- Conversation memory.
- Tuning the context budget (Experiment D, 010).
- Failure-scenario tests and retry tuning beyond the SDK's bounded retries (011).
- Token cost accounting (012).

## Assumptions

1. **Provider: Groq.** Already chosen in [architecture.md](../architecture.md).
   - **New dependency:** the official `groq` Python SDK, added with `uv add groq`.
     Approving this plan approves installing it from PyPI.
   - **API key:** you create the key and put `GROQ_API_KEY` in your own `.env`. I never
     handle or type the key, and `.env` stays untracked.
2. **Model: `openai/gpt-oss-20b`.** It is a Groq production model (131k context) that
   supports `json_schema` with `strict: true`, which means constrained decoding.
   Configurable via `LLM_MODEL`. `openai/gpt-oss-120b` is the stronger, slower option.
3. **Default retrieval for answers is Experiment C's choice:** dense, reranking the top 20.
   The top `ANSWER_CONTEXT_CHUNKS = 5` chunks (each ≤ 300 tokens) form the context. The
   request may override the mode, rerank flag and filters.
4. **Data leaving the machine:** the question and the five passages are sent to Groq. Corpus
   v1 is public documentation and synthetic incidents. A tenant with private documents
   would be sending them to a third party, so this is stated in the API docs.
5. **The manual check sends real requests.** After the code commit, it calls Groq with
   about 10 dev questions using your key. Approving this plan approves those calls, which
   cost cents or nothing on the free tier. 009b's full evaluation will ask again.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Output contract | Strict JSON schema: `{status: "answered" \| "insufficient_evidence", answer: string, citations: integer[]}`, all `required`, `additionalProperties: false` | Groq's strict mode requires every property `required`. Constrained decoding removes malformed-JSON failures on supported models; Pydantic still validates (never trust, even when constrained) |
| Passage IDs shown to the model | `[1]`–`[5]` labels, mapped back to chunk UUIDs on the server | Short integers are easier to copy correctly than UUIDs, and a cited number is checked against the label set |
| Citation validation | `answered` needs ≥ 1 citation, all labels in the sent set, deduplicated. `insufficient_evidence` must have no citations, and its answer text is ignored | The core trust guarantee ([PROJECT.md](../PROJECT.md)): a citation the server can't map to a sent passage is never returned |
| On invalid output | One corrective retry, with the validation problem stated in a short follow-up message (from `prompts.md`). Then: malformed JSON or schema → 502 `LLM_INVALID_OUTPUT`; still unsupported citations → `insufficient_evidence` | As specified in [architecture.md](../architecture.md). An unsupported answer is downgraded to abstention, never passed through |
| Abstention, before the LLM | No retrieved chunks → `insufficient_evidence` without an LLM call | Cheap and certain. A score threshold waits for 009b's dev calibration: Experiment C showed answerable and unanswerable top-1 scores overlap |
| Abstention, by the LLM | The prompt instructs `insufficient_evidence` when the passages don't support an answer; the schema makes it a first-class status | Lets the model refuse explicitly instead of hedging in prose |
| Prompt injection | Passages are wrapped in `<passage id="n">…</passage>` delimiters. The system prompt says passage content is untrusted data, never instructions | Corpus text (or a future tenant's documents) could contain instructions. Server-side citation checks bound the damage either way |
| Gateway errors | `GroqClient` sets SDK `timeout` and `max_retries` from settings. Timeout, connection, 429 and 5xx errors become `LLMUnavailableError`. A 400 schema failure becomes an invalid-output attempt | Services never see SDK exceptions ([coding-standards.md](../coding-standards.md)). Retry behaviour gets its failure-scenario tests in 011 |
| Missing key | `GROQ_API_KEY` unset → `/v1/answers` returns 503 `LLM_UNAVAILABLE` ("LLM not configured"); the app still starts | Search and evaluation keep working without a key. Tests never need one |
| Prompts | `prompts.md` has `## system`, `## user` and `## retry` sections with `{question}`, `{passages}` and `{problem}` placeholders. `prompts.py` loads it once and fails at startup if a section or placeholder is missing | Keeps prompts out of code (CLAUDE.md), and a broken prompt file fails fast |
| Separation | `generation/` depends on `retrieval.service.search` and the `LLMClient` protocol; nothing in retrieval knows about generation | AI services are separate from business services; one-way dependency |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `llm_client.py` talks to Groq; `prompts.py` loads prompts; `citations.py` validates; `service.py` orchestrates |
| DIP / ISP | The service depends on a one-method `LLMClient`; tests use a scripted fake, and nothing imports `groq` outside the gateway |
| DRY | Retrieval goes through `retrieval.service.search`, the same code that search and evaluation use |
| Flat flow | Guard clauses: no hits → abstain; invalid output → retry once → decide |

### Dependencies added
`groq` (official Groq Python SDK): the provider chosen in [architecture.md](../architecture.md).
It gives typed responses, `usage`, timeouts and bounded retries without hand-written HTTP.

## Files to create / modify

```
app/generation/__init__.py, prompts.md, prompts.py      new
app/generation/llm_client.py                            new: LLMClient protocol, GroqClient
app/generation/citations.py                             new: label map, validation
app/generation/service.py, schemas.py, router.py, deps.py   new
app/core/errors.py                 + LLMUnavailableError, LLMInvalidOutputError
app/core/config.py, .env.example   + LLM settings (dummy key value in the example only)
app/main.py                        + router; load prompts at startup
pyproject.toml, uv.lock            + groq
tests/generation/                  new: prompts, citations, service (fake LLM), API, gateway error mapping
tests/fakes.py                     + ScriptedLLMClient
.claude/{architecture,api-spec,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/009a-grounded-answers`; `uv add groq` (approved with this plan).
   Confirm the SDK's timeout, `max_retries` and exception class names against the installed
   package, since the docs pages didn't list them.
1. **Errors and settings.** `.env.example` gets dummy values only.
2. **`prompts.md` and `prompts.py`,** plus tests: load, missing section, missing placeholder.
3. **`citations.py`:** labels to chunk ids, and validation rules. Tests cover every rule.
4. **`LLMClient` protocol and `ScriptedLLMClient`.** `GroqClient` with error translation,
   tested by mocking the SDK client: no network.
5. **`answer_question` service:** retrieval options, no-hit abstention, context building,
   the one-retry policy, metadata logging. Tests use the fake.
6. **Router, schemas and deps;** register the router. API tests: roles, tenant isolation of
   the context, 503 without a key.
7. **Lint and the full suite;** docs; commit after you confirm.
8. **Manual check, after the commit.** You put `GROQ_API_KEY` in `.env`. I then send about
   10 dev questions through the API and report status, citation validity, retries, tokens
   and latency. Answers aren't scored yet; that is 009b.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| An unsupported citation reaches the user | Label outside the sent set, `answered` with no citations, duplicate labels: retry once, then `insufficient_evidence`; never returned as answered |
| Malformed output passed through | Invalid JSON or schema twice → 502 `LLM_INVALID_OUTPUT`; once, then valid → 200 with `attempts: 2` in the log |
| Cross-tenant context | A tenant's question never puts another tenant's chunk in the prompt (fake client records the prompt) |
| Unneeded LLM calls | No retrieved chunks → `insufficient_evidence` with zero LLM calls |
| Provider failures leak SDK errors | Gateway: timeout, connection error, 429 and 500 → `LLMUnavailableError`; a 400 schema failure → invalid output (mocked SDK) |
| Missing key breaks the app | App starts and search works without `GROQ_API_KEY`; `/v1/answers` → 503 |
| Prompt text in logs | `caplog`: the LLM log line has model, tokens, latency and outcome, and contains neither the question nor passage text |
| Broken prompt file | Missing `## user` section or `{passages}` placeholder → startup error naming it |

## Edge cases

- **The model says `insufficient_evidence` but includes citations:** citations are dropped,
  the status is kept, and the empty answer is returned.
- **The model answers `answered` with an empty answer string:** treated as invalid and
  retried once.
- **Fewer than 5 chunks retrieved:** only those are sent and labelled.
- **Very long questions** (≤ 1,000 chars, same limit as search) and five chunks of ≤ 300
  tokens: well inside the model's 131k context.
- **The retry hits a provider error:** 503 (provider failure takes precedence).

## Security

- **The API key** is read from settings as a `SecretStr`. It is never logged and never in
  the repo; `.env.example` has a dummy.
- **The prompt-injection posture:** delimiters, a system instruction, and server-side
  citation checks. Retrieval stays tenant-scoped, so another tenant's text can never reach a
  prompt (tested).
- **Logs** hold metadata only: no prompts, passages or answers.
- **Request limits:** question ≤ 1,000 chars, k fixed by settings, and each request makes at
  most two LLM calls.
- **Data sent to Groq is documented in the API spec:** the question and up to five passages.

## Risks

- **Model quality on technical docs.** 009a checks plumbing and safety, not quality; 009b
  measures quality.
- **Provider limits:** free-tier rate limits (RPM/TPM) and latency spikes. These are
  translated to 503, and their tests come in 011.
- **Reasoning tokens:** gpt-oss spends completion tokens on reasoning, and too low a
  `LLM_MAX_COMPLETION_TOKENS` could truncate the JSON. The default is 2,048, and the
  manual check reports actual usage.
- **Over-abstention:** too strict a prompt refuses answerable questions. 009b measures the
  rate on answerable vs unanswerable questions.

## Future improvements

- 009b: answer evaluation and a dev-calibrated abstention threshold on rerank scores.
- Streaming answers; context budget experiments (010); cost per request (012).

## Checklist

- [x] Branch `task/009a-grounded-answers`; `groq` added; SDK names confirmed
- [x] Error classes + LLM settings (`.env.example` dummies)
- [x] `prompts.md` / `prompts.py` + tests
- [x] `citations.py` + tests
- [x] `LLMClient`, `GroqClient` (mocked SDK tests), `ScriptedLLMClient`
- [x] `answer_question` + service tests (retry policy, abstention, logging)
- [x] Router/schemas/deps + API tests (roles, isolation, no key)
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit after confirmation
- [x] Manual check with your `GROQ_API_KEY` (about 10 dev questions); results in the handover

---

## Handover

### Summary
`POST /v1/answers` (viewer) answers a question from the tenant's documents, or returns
`insufficient_evidence`. It works like this:
1. Retrieve with dense search, reranking the top 20 (Experiment C).
2. Label the top 5 chunks `[1]`–`[5]`.
3. Call Groq `openai/gpt-oss-20b` with a strict JSON schema.
4. Check the reply on the server: every citation must be a passage that was sent, and an
   answer needs at least one.
5. Allow at most one corrective retry.

Malformed output ends in 502. An unsupported answer becomes `insufficient_evidence`. With
no retrieved passages, the LLM is not called.

Prompts live in `app/generation/prompts.md`. Code is in `0817f5c`. 247 tests pass (39 new)
with a scripted fake LLM.

A live check of 10 dev questions on the real API and Groq: 8 answered, all checked by hand
against the reference answers and correct, and 2 unanswerable questions correctly
abstained. One answerable question abstained because retrieval missed its evidence.

### Architecture Notes
- **Modules in `app/generation`:**

  | Module | Role |
  |---|---|
  | `prompts.md` + `prompts.py` | Sections `system`, `user`, `retry`; checked at startup |
  | `llm_client.py` | `LLMClient` protocol and the `GroqClient` gateway; the only `groq` import |
  | `citations.py` | Labelling, delimiting, `check_reply` |
  | `service.py` | Orchestration, retry policy, metadata logging |
  | `schemas.py` | `ModelAnswer` is both the strict JSON schema sent to Groq and the Pydantic validator, so the two can't drift |

- **Retry policy.** `InvalidReplyError.kind` decides what happens after the one retry:
  - `format` (bad JSON or schema, or the provider rejected the output with a 400) → 502
  - `unsupported` (no citations, an unknown label, an empty answer) → `insufficient_evidence`

  The retry message states the problem, using the `## retry` prompt.
- **Passages.** Each goes in a `<passage id source="slug@version">` block, so the model can
  see document versions. A passage can't open or close a block of its own.
- **Dependencies.** `get_llm_client` returns `None` without a key, so only answers return
  503. The test fixture always overrides it, and a test never builds `GroqClient`.
- **Logging.** One line per LLM call: model, attempt, outcome, tokens, latency. The test
  checks captured records and finds neither the question nor passage text.

### Deviations from the plan
- **A real logging bug fixed in `migrations/env.py`.** The tests migrate in-process, and
  Alembic's `fileConfig()` disabled every existing logger. That silently dropped all app
  logs in tests, so the "no prompt text in logs" test would have passed vacuously. Now
  `disable_existing_loggers=False`.
- **A blank `GROQ_API_KEY` counts as unset** (validator), because `.env.example` ships
  `GROQ_API_KEY=` empty.
- **The schema description is stripped** from what is sent to Groq; it was a code
  docstring, not a prompt.
- **The key was written by me, at your request.** The plan said you would put the key in
  `.env`. On your instruction I wrote the line into `.env` (git-ignored), without echoing
  it in any output. It appeared in the chat when you pasted it, so **rotate this key** in
  the Groq console.
- **The live check needed two attempts to find the key.**
  - **First attempt:** 10 × 401 `AuthenticationError`.
  - **Cause:** a user-level Windows environment variable `GROQ_API_KEY` held a stale value.
    This session inherited it, and environment variables override `.env` in
    pydantic-settings.
  - **Fix for the check:** the server was started with that variable removed from its own
    environment (`env -u GROQ_API_KEY`), so `.env` loads.
  - **Still to do on your side:** update or remove the Windows variable, or every new
    terminal will keep overriding `.env`.

### Database Changes
None.

### API Changes
- **Added:** `POST /v1/answers`. See [api-spec.md](../api-spec.md) for the request and
  response, the 502/503 codes, the data sent to Groq, and the guarantees.
- **New settings:** `GROQ_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`,
  `LLM_MAX_COMPLETION_TOKENS` and `ANSWER_CONTEXT_CHUNKS`.
- **New dependency:** `groq` 1.7.0.

### Evaluation Results
Not a metric run; that is 009b. A manual end-to-end check:
- **Setup:** tenant `eval-corpus-v1`, real models, `openai/gpt-oss-20b`, Groq free tier.
- **Questions:** 10 `dev` questions, the first of each type in dataset order:

  | Type | Questions |
  |---|---|
  | factual | 2 |
  | exact_identifier | 2 |
  | paraphrase | 2 |
  | multi_passage | 1 |
  | version_specific | 1 |
  | unanswerable | 2 |

| id | type | status | citations (on evidence) | answer vs reference |
|---|---|---|---|---|
| q-0001 | factual | answered | 2 (2) | correct |
| q-0006 | factual | answered | 3 (2) | correct |
| q-0002 | exact_identifier | answered | 3 (2) | correct; adds a detail from an incident passage |
| q-0007 | exact_identifier | answered | 3 (3) | correct (`['GET']`) |
| q-0036 | paraphrase | insufficient_evidence | — | abstained: retrieval missed (no evidence in the top 5) |
| q-0037 | paraphrase | answered | 2 (2) | correct |
| q-0062 | multi_passage | answered | 2 (1) | correct (`--forwarded-allow-ips`, default 127.0.0.1 and ::1) |
| q-0076 | version_specific | answered | 1 (1) | correct (0.135.0, EventSource) |
| q-0111 | unanswerable | insufficient_evidence | — | correct abstention |
| q-0112 | unanswerable | insufficient_evidence | — | correct abstention |

- **Correctness** was judged by me against the reference answers. Answer metrics come
  in 009b.
- **Citation validity:** every returned citation was a sent passage, which the server
  guarantees. 18 of 21 citations overlap a labelled evidence span; the other 3 cite related
  passages.
- **Calls:** every question needed exactly one LLM call. None needed the corrective retry.
- **Tokens per call:** prompt 1,135–1,690, completion 88–402. The completion count includes
  gpt-oss reasoning, well under the 2,048 cap.
- **Latency:** the LLM step went from 0.85 s to 11.8 s across the run, and the total from
  2.6 s to 13.4 s.
  - The growth is **rate limiting:** Groq returned **8 × 429**, and the SDK retried each one
    with backoff. All 10 requests ended with HTTP 200.
  - Requests were sent back to back, so free-tier limits dominate. A paced evaluation (009b)
    must expect this.
- **Security:** the key never appears in the server log (checked: 0 matches).

### Future Work
- **009b:** answer metrics over the benchmark and an abstention threshold calibrated on
  dev. Pace requests (or use a concurrency limit) to stay within Groq rate limits.
- **011:**
  - Report a misconfigured or invalid key (401/403) as a distinct, non-retryable error,
    instead of the "temporarily unavailable" message.
  - Failure-scenario tests for timeouts and 429 storms.
- **Retrieval misses cause abstention** (q-0036). Recall improvements (010) translate
  directly into answered questions.

### Modified Files
| File | Why |
|---|---|
| `app/generation/*` (new) | Prompts, gateway, citation checks, service, schemas, router, deps |
| `app/core/errors.py`, `app/core/config.py`, `.env.example` | LLM errors and settings (placeholder only) |
| `app/main.py` | Router; prompts loaded at startup |
| `migrations/env.py` | Keep existing loggers during in-process migrations |
| `pyproject.toml`, `uv.lock` | `groq` |
| `tests/generation/*` (new), `tests/fakes.py`, `tests/conftest.py` | Scripted LLM, no LLM by default, risk-based tests |
| `.claude/{architecture,api-spec,tasks,plan}.md`, this file | Docs |
