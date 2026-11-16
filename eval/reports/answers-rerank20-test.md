# Answer run `answers-rerank20-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"rerank20","mode":"dense","rerank":true}`
- **Generator:** `openai/gpt-oss-20b`, 5 context chunks, rerank depth 20, gate during run: None
- **Judge:** `openai/gpt-oss-120b`
- **Corpus:** 285 documents verified
- **Git:** `ec8653f35f6945127cd025e9df6535fc8614cf54`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T14:34:23+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Outcomes

| query_type | n | answered (answerable) | correct abstention (unanswerable) | false abstention: retrieval / generation | errors |
|---|---|---|---|---|---|
| all | 70 | 56/65 86% | 5/5 100% | 8 / 1 | 0 |
| ambiguous | 6 | 5/6 83% | 0/0 – | 1 / 0 | 0 |
| exact_identifier | 12 | 12/12 100% | 0/0 – | 0 / 0 | 0 |
| factual | 18 | 17/18 94% | 0/0 – | 1 / 0 | 0 |
| multi_passage | 9 | 7/9 78% | 0/0 – | 2 / 0 | 0 |
| paraphrase | 13 | 9/13 69% | 0/0 – | 4 / 0 | 0 |
| unanswerable | 5 | 0/0 – | 5/5 100% | 0 / 0 | 0 |
| version_specific | 7 | 6/7 86% | 0/0 – | 0 / 1 | 0 |

## Citations and context

Answerable questions that were answered. Precision: cited chunks overlapping labelled evidence. Coverage: evidence items cited. Context hit: evidence in the 5 context chunks (all answerable questions).

| query_type | citations | citation precision | evidence coverage | context hit |
|---|---|---|---|---|
| all | 101 | 58% | 82% | 77% |
| ambiguous | 12 | 50% | 77% | 83% |
| exact_identifier | 20 | 55% | 79% | 83% |
| factual | 26 | 77% | 100% | 94% |
| multi_passage | 15 | 53% | 55% | 56% |
| paraphrase | 17 | 47% | 67% | 46% |
| unanswerable | 0 | – | – | – |
| version_specific | 11 | 55% | 100% | 100% |

## LLM-judged (judge `openai/gpt-oss-120b`; human agreement not yet checked)

Correctness: answered answerable questions vs the reference answer. Faithfulness: every answer vs the passages it cited.

| correctness | correct | partial | incorrect | unjudged |
|---|---|---|---|---|
| all | 50 | 1 | 5 | 0 |
| ambiguous | 3 | 1 | 1 | 0 |
| exact_identifier | 12 | 0 | 0 | 0 |
| factual | 15 | 0 | 2 | 0 |
| multi_passage | 6 | 0 | 1 | 0 |
| paraphrase | 9 | 0 | 0 | 0 |
| unanswerable | 0 | 0 | 0 | 0 |
| version_specific | 5 | 0 | 1 | 0 |

| faithfulness | supported | partially_supported | unsupported | unjudged |
|---|---|---|---|---|
| all | 48 | 8 | 0 | 0 |
| ambiguous | 3 | 2 | 0 | 0 |
| exact_identifier | 12 | 0 | 0 | 0 |
| factual | 17 | 0 | 0 | 0 |
| multi_passage | 5 | 2 | 0 | 0 |
| paraphrase | 8 | 1 | 0 | 0 |
| unanswerable | 0 | 0 | 0 | 0 |
| version_specific | 3 | 3 | 0 | 0 |

## Cost and latency

- LLM calls: 70 for 70 questions
- Tokens: 99692 prompt, 15431 completion
- Total latency p50 10318 ms, p95 16344 ms
- LLM latency p50 7736 ms, p95 13998 ms

## With and without the dev-chosen gate (t = -4.766902446746826)

| | answered (answerable) | correct abstention | false abstention |
|---|---|---|---|
| no gate | 86% | 100% | 14% |
| gate t = -4.766902446746826 | 86% | 100% | 14% |
