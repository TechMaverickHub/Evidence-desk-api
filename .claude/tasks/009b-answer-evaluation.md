# Task 009b — Answer evaluation: abstention, citations, judged correctness, calibrated gate

**Status:** ✅ Done (gate not adopted)
**Week:** W3 · **Modules:** `app/evaluation`, `app/generation` (small) ·
**Branch:** `task/009b-answer-evaluation` (off `task/009a-grounded-answers`)

## Goal

Measure the `/v1/answers` pipeline over `evidencedesk-v1`, the same way retrieval was
measured:
- **Deterministic metrics first:** abstention behaviour, citation precision and coverage,
  and whether a failure came from retrieval or from generation.
- **LLM-judged** correctness and faithfulness alongside them, with a documented procedure
  and a human spot-check of the judge.

Then calibrate, on dev only, an optional pre-LLM abstention gate on the top rerank score,
and report it once on test.

## Scope

In:
- **`answer-run` CLI:**
  - runs every question of a split through `generation.service.answer_question`, the
    code the API serves, with no HTTP
  - records each answer, its citations, context chunks, top-1 rerank score, tokens and
    latency
  - computes deterministic metrics
  - **is resumable:** answers are written as they arrive, and a rerun skips finished ids
  - is paced to stay inside Groq rate limits
- **`answer-judge` CLI:**
  - adds LLM verdicts to a run record: correctness against the reference answer, and
    faithfulness of the answer to its cited passages
  - resumable and paced, like `answer-run`
  - re-renders the report
- **Deterministic answer metrics** (`app/evaluation/answer_metrics.py`, pure functions):
  - abstention matrix (answered or abstained × answerable or unanswerable)
  - citation precision (cited chunks overlapping evidence)
  - evidence coverage (evidence items covered by citations)
  - context hit (evidence in the five context chunks)
  - failure attribution (retrieval miss vs generation)
  - threshold sweep for the gate
- **Judge prompts** in `app/generation/prompts.md` (CLAUDE.md: prompts live there), with a
  strict JSON verdict schema and a separate judge model.
- **A judge spot-check sheet** (`.cache/review/judge-dev.md`). You mark disagreements on
  20 random dev verdicts, and the agreement is reported next to the judged metrics.
- **The gate:** setting `ANSWER_MIN_RERANK_SCORE` (default off). Below it, the service
  abstains without an LLM call. The threshold is chosen on dev by a rule fixed here, and
  adopted only if the rule says so.
- **`RetrievalSummary` gains `top_score` and `score_kind`.** This is a small API addition;
  the gate and the calibration need the score.

Out:
- Persisting answer runs in the database or the API (the 006b equivalent). Files are enough
  until the dashboard needs them.
- Tuning prompts on the benchmark.
- Changing the generator model or context size (010).
- RAGAS or other evaluation frameworks: two judged criteria with our own prompts are
  enough, and avoid a dependency.

## Assumptions

1. **The generator is unchanged from 009a:** `openai/gpt-oss-20b`, retrieval dense with the
   top 20 reranked, 5 context chunks.
2. **Judge model: `openai/gpt-oss-120b`.** It is the other Groq production model with strict
   JSON schema. Using a larger model from the same family reduces, but does not remove,
   self-preference bias, which is stated as a limitation.
3. **Outbound calls.** Approving this plan approves Groq calls with your key. Rough count:

   | Split | Answer calls | Judge calls | Total |
   |---|---|---|---|
   | dev | 80 | about 2 × 60 | about 200 |
   | test | 70 | about 2 × 55 | about 180 |

   - **About 380 calls, roughly 0.5 M tokens.** On the free tier that costs nothing but may
     hit daily token limits.
   - **Runs are resumable,** so a limit pauses the work rather than wasting calls.
   - **The data sent is unchanged:** public corpus passages, benchmark questions and their
     reference answers (the reference goes to the judge).
4. **Pacing.** One request at a time, with at least 2 s between requests (`--pace`), plus the
   SDK's 429 backoff. That is roughly 15–25 minutes per split, run in the background.
5. **Your spot-check takes about 15 minutes:** 20 verdicts, one reply with any ids you
   disagree with.

## Metrics (all per split and per `query_type`, with counts)

| Metric | Definition | Kind |
|---|---|---|
| Answer rate (answerable) | answered / answerable | deterministic |
| Correct abstention (unanswerable) | abstained / unanswerable | deterministic |
| False abstention | abstained / answerable, split into **retrieval miss** (no evidence in context) vs **generation** (evidence in context) | deterministic |
| Citation precision | cited chunks overlapping any evidence span / cited chunks (answered, answerable) | deterministic, uses `relevance.overlaps` |
| Evidence coverage | evidence items covered by ≥ 1 citation / evidence items (answered, answerable) | deterministic |
| Context hit | any evidence item within the 5 context chunks | deterministic (retrieval ceiling for answers) |
| Errors | 502 / 503 counts | deterministic |
| Tokens, LLM calls, latency | p50 / p95; total tokens as the cost proxy | measured |
| Correctness | judge: `correct` / `partial` / `incorrect` vs the reference answer, answered answerable only | LLM-judged |
| Faithfulness | judge: `supported` / `partially_supported` / `unsupported` by the **cited** passages only | LLM-judged |
| Judge agreement | % of 20 spot-checked dev verdicts you agree with | human |

## Gate calibration (rule fixed before any run)

- **Decision rule:** abstain if the model abstains **or** top-1 rerank score < t.
- **Candidates:** thresholds are swept on the recorded dev run, with no extra calls,
  because the gate acts before the LLM.
- **Choose:** t maximises
  **J = correct-abstention rate (unanswerable) − false-abstention rate (answerable)**,
  the gain over no gate; ties go to the lower t.
- **Adopt** only if J improves by **at least 0.10** over no gate. With 10 dev unanswerable
  questions, one extra correct abstention is 0.10, and anything less is noise.
- **Test:** report test with and without the dev-chosen t, applied to the single recorded
  test run. Set `ANSWER_MIN_RERANK_SCORE` only if adopted; the decision goes in the
  handover.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| What the run calls | `generation.service.answer_question` with real dependencies | Measures exactly what the API serves; no second pipeline (DRY) |
| Record format | `eval/reports/answers-<config>-<split>.json` (header with provenance as in 006a: dataset hash, split, models, settings, git SHA and dirty flag) plus `.md` rendered from it | Same discipline as retrieval runs; reviewable in git |
| Resumability | A run writes `.partial.jsonl` per answered question; rerunning with the same config, split and dataset hash skips finished ids; the final record is written when complete | Rate and daily limits are expected; no paid call is wasted |
| Judge | Same `LLMClient` gateway, model `LLM_JUDGE_MODEL`, strict schema `{verdict, reason}` with `reason` ≤ 200 chars; temperature 0; one call per criterion | Reuses the 009a gateway and validation. Separate criteria are easier to check than one combined score |
| Judge inputs | Correctness: question, reference answer, model answer. Faithfulness: model answer and the **cited** passages only | Faithfulness must not credit passages the answer didn't cite |
| Judge validity | Spot-check sheet of 20 random dev verdicts (fixed seed); agreement reported; judged metrics labelled "LLM-judged (agreement x/20)" | [coding-standards.md](../coding-standards.md): judged metrics are reported next to, never instead of, deterministic ones |
| Gate placement | `service.answer_question`: after retrieval, before the LLM: `top_score < ANSWER_MIN_RERANK_SCORE` → `insufficient_evidence`, 0 LLM calls | Cheapest possible abstention. Default off, so behaviour is unchanged unless adopted |
| `top_score` in the API | `RetrievalSummary.top_score` + `score_kind` (cross_encoder when reranked) | Needed for the gate and calibration; also useful to clients |
| Prompts | `prompts.md` gains `## judge_correctness` and `## judge_faithfulness`; a second loader validates them | Keeps every prompt in one reviewed file |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `answer_runner.py` runs and records; `answer_metrics.py` is pure scoring; `judge.py` judges; `report.py` renders |
| DRY | Reuses `answer_question`, `relevance.overlaps`, `verify_corpus`, `provenance`, the LLM gateway and the paired bootstrap |
| OCP | The judge is a new use of `LLMClient`, not a new gateway |
| Test by risk | Metric maths on hand-built records, resume logic, gate behaviour, judge parsing and failure handling |

### Dependencies added
None.

## Files to create / modify

```
app/evaluation/answer_runner.py     new: run, pace, resume, record
app/evaluation/answer_metrics.py    new: pure deterministic metrics + threshold sweep
app/evaluation/judge.py             new: correctness / faithfulness verdicts
app/evaluation/answer_records.py    new: AnswerRunConfig, AnswerRecord, AnswerRunReport
app/evaluation/report.py            + answer report and spot-check sheet rendering
app/evaluation/cli.py               + answer-run, answer-judge
app/generation/prompts.md, prompts.py   + judge sections and loader
app/generation/service.py, schemas.py   + gate, RetrievalSummary.top_score / score_kind
app/core/config.py, .env.example    + LLM_JUDGE_MODEL, ANSWER_MIN_RERANK_SCORE
tests/evaluation/test_answer_metrics.py, test_answer_runner.py, test_judge.py   new
tests/generation/test_answers_api.py    + gate, top_score
eval/configs/answers-rerank20.yaml  new
eval/reports/answers-*              generated (second commit)
.claude/{architecture,api-spec,tasks,plan}.md
```

## Step-by-step implementation plan

0. `git switch -c task/009b-answer-evaluation`.
1. **`RetrievalSummary.top_score` / `score_kind` and the gate** (default off), with tests.
2. **`answer_records.py` and `answer_metrics.py`,** with tests on hand-built records: every
   metric, the attribution split, and the sweep with ties.
3. **`answer_runner.py`:** pacing, resume and corpus check; tests with the scripted LLM and
   the fixture corpus, including resume after an interruption.
4. **Judge prompts and loader, and `judge.py`;** tests for parsing, an invalid verdict that
   is retried once and then recorded as `unjudged`, and that only cited passages are sent.
5. **Report rendering and spot-check sheet; CLI commands; the config file.**
6. **Lint and the full suite;** docs; commit 1 (code) after you confirm.
7. **From the clean tree, on dev:**
   1. `answer-run` in the background.
   2. `answer-judge`.
   3. Spot-check sheet → your 20-verdict review → agreement.
   4. Gate sweep → decision by the rule above.
8. **Then on test, once:** `answer-run --allow-test`, `answer-judge`, then report with and
   without the dev gate.
9. **Handover** (and `ANSWER_MIN_RERANK_SCORE` only if adopted), then commit 2 (reports)
   after you confirm.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Metric maths wrong | Hand-built records: abstention matrix, attribution (retrieval miss vs generation), citation precision with alternative spans, coverage per item, unanswerable excluded from citation metrics |
| Paid calls wasted on restart | Interrupted run (fake raises midway) → rerun calls the LLM only for unfinished ids; a mismatched config or dataset hash refuses to resume |
| Gate misbehaves | Score below threshold → abstain with 0 LLM calls; at or above → normal path; setting unset → no gating |
| Judge sees the wrong context | Faithfulness prompt contains only the cited passages (scripted client records prompts) |
| Judge output trusted blindly | Invalid verdict JSON → one retry → `unjudged` (counted and reported, never guessed) |
| Calibration overfits | Sweep tie-break and the 0.10 adoption rule on hand-built scores |
| Test-split discipline | `answer-run --split test` without `--allow-test` exits non-zero and writes nothing |

## Edge cases

- **Provider errors mid-run** (503 after SDK retries): recorded per question as `error`, not
  retried in a loop; the rerun resumes them.
- **502 invalid output:** recorded as an error outcome and counted.
- **No evidence in context and the model still answers:** a candidate hallucination. It
  shows in citation precision and faithfulness, and is listed in the dev report.
- **A reference answer the judge disagrees with:** the spot-check catches systematic issues;
  individual verdicts are not overridden.

## Security

- **The key** is read from settings, never logged, never in records. The records contain
  questions, answers, citations and verdicts: public corpus content.
- **Judge prompt injection:** passages and answers are delimited as data in the judge
  prompts. The verdict is schema-constrained and only enters metrics.
- **Outbound data** is unchanged in kind from 009a, plus reference answers sent to the
  judge.

## Risks

- **Rate and daily token limits:** pacing, the SDK's 429 backoff, resumable runs, and
  background execution. If daily limits stop a split, it resumes the next day; this is
  reported, not hidden.
- **Judge bias and variance:** a same-family model, temperature 0, two narrow criteria,
  human agreement reported. Judged numbers are labelled as such and never used to tune.
- **Small groups:** 10 dev and 5 test unanswerable questions. The abstention rates come
  with counts. The gate's 0.10 adoption bar reflects that one question is 0.10.
- **Retrieval misses look like abstentions.** The attribution split keeps generation
  quality separate from retrieval quality.

## Future improvements

- Persist answer runs (DB and API) for the dashboard (014).
- A second judge model, or a larger human-labelled sample, to estimate judge reliability.
- Use failure attribution to target 010 (chunking and context budget).

## Checklist

- [x] Branch `task/009b-answer-evaluation`
- [x] `top_score` / `score_kind` + gate (default off) + tests
- [x] `answer_records`, `answer_metrics` + tests
- [x] `answer_runner` (pace, resume, corpus check) + tests
- [x] Judge prompts/loader + `judge.py` + tests
- [x] Reports, spot-check sheet, CLI, config
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Commit 1 (code) after confirmation
- [x] Dev: answer run, judge, spot-check by you (agreement), gate decision
- [x] Test: one answer run + judge; report with and without the dev gate
- [x] Update [architecture.md](../architecture.md), [api-spec.md](../api-spec.md), [tasks.md](../tasks.md), [plan.md](../plan.md), handover below
- [x] Commit 2 (reports + handover) after confirmation


---

## Handover

### Summary
The `/v1/answers` pipeline is now measured over `evidencedesk-v1`:
- `answer-run`: paced and resumable.
- `answer-judge`: correctness and faithfulness, from `gpt-oss-120b`.
- `answer-report`: report, spot-check sheet, recorded agreement, gate comparison.

Deterministic metrics come first; LLM-judged metrics sit next to them, with human agreement
recorded. An optional pre-LLM abstention gate (`ANSWER_MIN_RERANK_SCORE`) exists and was
calibrated on dev by a rule fixed in advance. **It was not adopted.** `/v1/answers` now also
returns `retrieval.top_score` and `score_kind`.

268 tests pass. Code is in `ec8653f`; every report was generated from that commit with a
clean tree.

**Results, test split (70 questions, one run):**

| Measure | Result |
|---|---|
| Answered (answerable) | 56/65 (86 %) |
| Correctly refused (unanswerable) | 5/5 |
| Judged correct (answered) | 50/56 |
| Unsupported | 0 |
| Errors | 0 |

**The main limit is retrieval, not generation.** 8 of 9 wrong refusals are retrieval misses.
Paraphrase questions have their evidence in the context only 46 % of the time.

### Architecture Notes
- **Modules in `app/evaluation`:**

  | Module | Role |
  |---|---|
  | `answer_runner.py` | Pacing, resume, recording |
  | `answer_records.py` | Raw-fact record format |
  | `answer_metrics.py` | Pure metrics and gate sweep |
  | `judge.py` | Verdicts via the 009a `LLMClient` gateway |
  | `answer_report.py` | Markdown and spot-check sheet |
  | `answer_cli.py` | Commands on `python -m app.evaluation.cli` |

- **Records store raw facts, not metrics:** outcome, answer, citations and context with the
  evidence items each overlaps, top score, tokens, latency. Every metric is recomputed from
  them, so report changes never need a re-run.
- **Failure attribution.** A wrong refusal is a *retrieval miss* when no context chunk
  overlaps labelled evidence; otherwise it is *generation*.
- **The judge:**
  - Faithfulness sees only the cited passages; correctness sees question, reference and
    answer.
  - Verdicts use a strict schema and are retried once, otherwise recorded as `unjudged`.
  - Judge prompts live in `prompts.md`.
- **The gate.** In `generation.service`, it applies only to cross-encoder scores (rerank on),
  before the LLM call. Off by default.
- **Shared rule.** `retrieval.service.score_kind(mode, rerank)` is now the one rule for what
  a score means, shared by search, answers and evaluation records.

### Deviations from the plan
- **The test run spanned two days.**
  - **2026-11-03:** stopped at 48/70. Groq's free tier allows 200,000 tokens/day per model
    (rolling 24 h); the error read "Limit 200000, Used 198858". The judge hit the same limit
    on `gpt-oss-120b`.
  - **2026-11-16:** resumed. The resume retried only the 22 failed questions, then judged
    them.
  - **Same code (`ec8653f`) and configuration throughout.** The 22 later questions were
    answered by the same Groq model ID 13 days later; provider-side changes cannot be ruled
    out, and this is stated as a limitation.
  - **Run-time-only changes during the resume:** pacing 8 s instead of 2 s, and
    `LLM_MAX_RETRIES=5`. These affect waiting, not what is asked or scored.
- **A clean tree for the resume.** Uncommitted doc notes (the resume instructions) were
  stashed during the run, so the report records a clean tree. They were restored afterwards.
- **`answer_report.py` and `answer_cli.py` are new modules,** not extensions of
  `report.py` and `cli.py`, which were already large.
- **The human spot-check covers dev only (20/20 agreement), as planned.** The test report
  shows "agreement not yet checked" because no test spot-check was done.
- **The gate comparison on test** uses the dev sweep's best threshold (t = −4.767), shown
  for transparency even though it was not adopted. On test it changes nothing.
- **Found, not fixed** (they would have changed code mid-experiment):
  - `answer-judge` exits with a raw traceback on `LLMUnavailableError`.
  - `answer-run` records each remaining question as an error after a daily-limit 429,
    instead of stopping with "resume after the limit resets".

  Both are for task 011.
- **Environment.** A stale Windows user variable `GROQ_API_KEY` overrides `.env`, so every
  run used `env -u GROQ_API_KEY`.

### Database Changes
None.

### API Changes
- `/v1/answers` `retrieval` gains `top_score` and `score_kind`.
- New settings: `ANSWER_MIN_RERANK_SCORE` (empty = off) and `LLM_JUDGE_MODEL`.
- New CLI commands: `answer-run`, `answer-judge`, `answer-report`. See
  [api-spec.md](../api-spec.md).

### Evaluation Results
**Setup:**
- Dataset `evidencedesk-v1` (sha256 `b77c981f…cbcf9920`), tenant `eval-corpus-v1`.
- Generator `openai/gpt-oss-20b`; retrieval dense, rerank top 20
  (`cross-encoder/ms-marco-MiniLM-L6-v2`), 5 context chunks.
- Judge `openai/gpt-oss-120b`.
- Git `ec8653f` (clean); Groq free tier.

| | dev (80) | test (70) |
|---|---|---|
| Answered (answerable) | 61/70 (87 %) | 56/65 (86 %) |
| Correctly refused (unanswerable) | 9/10 | 5/5 |
| Wrong refusals: retrieval miss / generation | 8 / 1 | 8 / 1 |
| Citation precision | 59 % | 58 % |
| Evidence coverage (answered) | 73 % | 82 % |
| Context hit (answerable) | 76 % | 77 % |
| Judged correctness: correct / partial / incorrect | 50 / 8 / 3 | 50 / 1 / 5 |
| Judged faithfulness: supported / partial / unsupported | 53 / 9 / 0 | 48 / 8 / 0 |
| Errors | 0 | 0 |
| LLM calls | 81 | 70 |
| Tokens (prompt / completion) | 108,629 / 16,872 | 99,692 / 15,431 |
| Total latency p50 / p95 | 11.3 s / 15.4 s | 10.3 s / 16.3 s |

**Judge reliability:**
- You agreed with all 20 spot-checked dev verdicts. 20/20 is a small sample: it shows no
  systematic judge error, not a precise agreement rate.
- **Judged numbers are labelled as such and were never used to tune anything.**

**Per type (test, answered of answerable / context hit):**

| Type | Answered | Context hit |
|---|---|---|
| exact_identifier | 12/12 | 83 % |
| factual | 17/18 | 94 % |
| version_specific | 6/7 | 100 % |
| multi_passage | 7/9 | 56 % |
| paraphrase | 9/13 | 46 % |
| ambiguous | 5/6 | 83 % |

**Abstention gate (rule fixed in the plan):**
- **The dev sweep:** without a gate, J = +0.77. The best threshold, t = −4.767, gives
  J = +0.86, a gain of **+0.09**.
- **Why it falls short.** That threshold would have caught the one dev hallucination
  candidate (q-0123, about the non-existent pool-exhaustion incident), but also refused one
  answerable question.
- **Decision: not adopted.** The gain is below the 0.10 bar.
- **Test:** the model alone refused all 5 unanswerable questions, and the gate changed
  nothing.
- `ANSWER_MIN_RERANK_SCORE` stays unset.

**Reading:**
- **Generation is reliable when the evidence is in the context.** Only 1 wrong refusal per
  split had its evidence in the context (q-0072 dev, q-0077 test). No answer was judged
  unsupported on either split.
- **Retrieval limits answer quality.** About 9 in 10 wrong refusals are retrieval misses.
  Multi-passage and paraphrase questions have context hit rates of 56 % and 46 % on test,
  in line with the retrieval findings from 006a to 008. Task 010 (chunking and context
  budget) is the lever.
- **Citation precision is about 58 % while coverage is 73–82 %.** Answers usually cite their
  evidence, but also cite neighbouring related chunks. That is acceptable, since faithfulness
  holds, but citation-pruning prompts could tighten it.
- **Small groups.** There are 10 dev and 5 test unanswerable questions; rates like "5/5" are
  indicative only.

### Future Work
- **010:** raise context hit for paraphrase and multi-passage questions, using chunk size,
  heading context, more context chunks, and version awareness from 008.
- **011:**
  - stop cleanly on daily-limit 429s with a resume hint
  - clean exit from `answer-judge` on provider errors
  - a distinct error for an invalid key (009a)
- **The gate:** revisit once there are more unanswerable questions (benchmark v2).
- **Persistence:** store answer runs in the database and API for the dashboard (014).
- **Budget:** the Groq free tier fits about one split per model per day. Larger evaluations
  need the paid tier.

### Modified Files
| File | Why |
|---|---|
| `app/evaluation/answer_runner.py`, `answer_records.py`, `answer_metrics.py`, `judge.py`, `answer_report.py`, `answer_cli.py` (new) | Answer evaluation |
| `app/evaluation/cli.py`, `repository.py` (`chunks_by_id`), `runner.py` (`evidence_items`), `records.py` (`run_score_kind`) | Wiring and shared helpers |
| `app/generation/service.py`, `schemas.py`, `prompts.md`, `prompts.py`, `deps.py` | Gate, `top_score`/`score_kind`, judge prompts, `build_llm_client` |
| `app/retrieval/service.py` | Shared `score_kind` rule |
| `app/core/config.py`, `.env.example` | `ANSWER_MIN_RERANK_SCORE`, `LLM_JUDGE_MODEL` |
| `tests/evaluation/test_answer_*.py`, `test_judge.py`, `tests/generation/test_answers_api.py`, `tests/evaluation/test_runner.py` | Risk-based tests |
| `eval/configs/answers-rerank20.yaml` | Run configuration |
| `eval/reports/answers-rerank20-{dev,test}.{json,md}` | Results |
| `.claude/{architecture,api-spec,tasks,plan}.md`, this file | Docs |
