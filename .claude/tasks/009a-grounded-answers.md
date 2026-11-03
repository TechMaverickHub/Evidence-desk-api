# Task 009a — Grounded answers: `POST /v1/answers` with validated citations and abstention

**Status:** 🔨 Code done; manual Groq check pending the commit
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
- [ ] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [ ] Commit after confirmation
- [ ] Manual check with your `GROQ_API_KEY` (about 10 dev questions); results in the handover

---

## Handover

*(Filled in after implementation.)*

### Summary
### Architecture Notes
### Deviations from the plan
### Database Changes
### API Changes
### Evaluation Results
### Future Work
### Modified Files
