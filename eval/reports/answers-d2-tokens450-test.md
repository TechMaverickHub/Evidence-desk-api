# Answer run `answers-d2-tokens450-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d2-tokens450","mode":"dense","rerank":true}`
- **Generator:** `openai/gpt-oss-20b`, 5 context chunks, rerank depth 20, chunker `tokens-450-overlap-75`, gate during run: None
- **Judge:** `not judged`
- **Corpus:** 285 documents verified
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T16:02:28+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Outcomes

| query_type | n | answered (answerable) | correct abstention (unanswerable) | false abstention: retrieval / generation | errors |
|---|---|---|---|---|---|
| all | 70 | 59/65 91% | 5/5 100% | 5 / 1 | 0 |
| ambiguous | 6 | 6/6 100% | 0/0 – | 0 / 0 | 0 |
| exact_identifier | 12 | 12/12 100% | 0/0 – | 0 / 0 | 0 |
| factual | 18 | 17/18 94% | 0/0 – | 1 / 0 | 0 |
| multi_passage | 9 | 8/9 89% | 0/0 – | 1 / 0 | 0 |
| paraphrase | 13 | 10/13 77% | 0/0 – | 3 / 0 | 0 |
| unanswerable | 5 | 0/0 – | 5/5 100% | 0 / 0 | 0 |
| version_specific | 7 | 6/7 86% | 0/0 – | 0 / 1 | 0 |

## Citations and context

Answerable questions that were answered. Precision: cited chunks overlapping labelled evidence. Coverage: evidence items cited. Context hit: evidence in the 5 context chunks (all answerable questions).

| query_type | citations | citation precision | evidence coverage | context hit |
|---|---|---|---|---|
| all | 109 | 55% | 81% | 80% |
| ambiguous | 15 | 40% | 64% | 83% |
| exact_identifier | 20 | 55% | 79% | 83% |
| factual | 24 | 83% | 100% | 94% |
| multi_passage | 19 | 42% | 54% | 67% |
| paraphrase | 19 | 42% | 70% | 54% |
| unanswerable | 0 | – | – | – |
| version_specific | 12 | 58% | 100% | 100% |

## Cost and latency

- LLM calls: 70 for 70 questions
- Tokens: 116823 prompt, 16713 completion
- Total latency p50 12900 ms, p95 18633 ms
- LLM latency p50 11083 ms, p95 16715 ms

## Abstention gate (sweep; rule fixed in task 009b)

Abstain if the model abstains or the top cross-encoder score is below t. J = correct abstention (unanswerable) − false abstention (answerable). Adopt only if J improves by ≥ 0.10.

- No gate: J +0.91 (correct 100%, false 9%)
- Best t = None: J +0.91 (correct 100%, false 9%)
- Gain +0.00 → **do not adopt**
