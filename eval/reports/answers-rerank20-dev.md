# Answer run `answers-rerank20-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"rerank20","mode":"dense","rerank":true}`
- **Generator:** `openai/gpt-oss-20b`, 5 context chunks, rerank depth 20, gate during run: None
- **Judge:** `openai/gpt-oss-120b`, human agreement 20/20
- **Corpus:** 285 documents verified
- **Git:** `ec8653f35f6945127cd025e9df6535fc8614cf54`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T09:22:55+00:00

## Outcomes

| query_type | n | answered (answerable) | correct abstention (unanswerable) | false abstention: retrieval / generation | errors |
|---|---|---|---|---|---|
| all | 80 | 61/70 87% | 9/10 90% | 8 / 1 | 0 |
| ambiguous | 4 | 3/4 75% | 0/0 – | 1 / 0 | 0 |
| exact_identifier | 18 | 18/18 100% | 0/0 – | 0 / 0 | 0 |
| factual | 12 | 9/12 75% | 0/0 – | 3 / 0 | 0 |
| multi_passage | 11 | 10/11 91% | 0/0 – | 0 / 1 | 0 |
| paraphrase | 12 | 9/12 75% | 0/0 – | 3 / 0 | 0 |
| unanswerable | 10 | 0/0 – | 9/10 90% | 0 / 0 | 0 |
| version_specific | 13 | 12/13 92% | 0/0 – | 1 / 0 | 0 |

## Citations and context

Answerable questions that were answered. Precision: cited chunks overlapping labelled evidence. Coverage: evidence items cited. Context hit: evidence in the 5 context chunks (all answerable questions).

| query_type | citations | citation precision | evidence coverage | context hit |
|---|---|---|---|---|
| all | 116 | 59% | 73% | 76% |
| ambiguous | 4 | 75% | 33% | 50% |
| exact_identifier | 39 | 67% | 94% | 94% |
| factual | 13 | 77% | 78% | 67% |
| multi_passage | 22 | 36% | 50% | 82% |
| paraphrase | 19 | 37% | 39% | 42% |
| unanswerable | 0 | – | – | – |
| version_specific | 19 | 74% | 92% | 92% |

## LLM-judged (judge `openai/gpt-oss-120b`; human agreement 20/20)

Correctness: answered answerable questions vs the reference answer. Faithfulness: every answer vs the passages it cited.

| correctness | correct | partial | incorrect | unjudged |
|---|---|---|---|---|
| all | 50 | 8 | 3 | 0 |
| ambiguous | 0 | 3 | 0 | 0 |
| exact_identifier | 18 | 0 | 0 | 0 |
| factual | 7 | 2 | 0 | 0 |
| multi_passage | 7 | 2 | 1 | 0 |
| paraphrase | 7 | 0 | 2 | 0 |
| unanswerable | 0 | 0 | 0 | 0 |
| version_specific | 11 | 1 | 0 | 0 |

| faithfulness | supported | partially_supported | unsupported | unjudged |
|---|---|---|---|---|
| all | 53 | 9 | 0 | 0 |
| ambiguous | 3 | 0 | 0 | 0 |
| exact_identifier | 18 | 0 | 0 | 0 |
| factual | 8 | 1 | 0 | 0 |
| multi_passage | 7 | 3 | 0 | 0 |
| paraphrase | 7 | 2 | 0 | 0 |
| unanswerable | 0 | 1 | 0 | 0 |
| version_specific | 10 | 2 | 0 | 0 |

## Cost and latency

- LLM calls: 81 for 80 questions
- Tokens: 108629 prompt, 16872 completion
- Total latency p50 11327 ms, p95 15359 ms
- LLM latency p50 9670 ms, p95 13492 ms

## Abstention gate (sweep; rule fixed in task 009b)

Abstain if the model abstains or the top cross-encoder score is below t. J = correct abstention (unanswerable) − false abstention (answerable). Adopt only if J improves by ≥ 0.10.

- No gate: J +0.77 (correct 90%, false 13%)
- Best t = -4.766902446746826: J +0.86 (correct 100%, false 14%)
- Gain +0.09 → **do not adopt**

## Answered although unanswerable (hallucination candidates)

- q-0123: Which incident was caused by database connection-pool exhaustion, and how was it fixed?

## Abstained although the evidence was in the context

- q-0072 (multi_passage): Why were admin users logged out after scaling to four workers, and what does Starlette say the session secret should be?
