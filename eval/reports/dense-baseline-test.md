# Run `dense-baseline-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-baseline","retriever":"dense","depth":10,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `cf8441ec6363e567cffe770786f555f8f7a5685a`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-02T09:01:20+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 65 | 0.175 | 0.649 | 0.547 | 0.520 |
| ambiguous | 6 | 0.133 | 0.444 | 0.450 | 0.305 |
| exact_identifier | 12 | 0.150 | 0.542 | 0.486 | 0.451 |
| factual | 18 | 0.222 | 0.944 | 0.824 | 0.805 |
| multi_passage | 9 | 0.200 | 0.389 | 0.444 | 0.348 |
| paraphrase | 13 | 0.123 | 0.462 | 0.281 | 0.323 |
| version_specific | 7 | 0.200 | 0.929 | 0.648 | 0.675 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 65 | 0.102 | 0.746 | 0.559 | 0.551 |
| ambiguous | 6 | 0.100 | 0.667 | 0.496 | 0.363 |
| exact_identifier | 12 | 0.092 | 0.708 | 0.507 | 0.504 |
| factual | 18 | 0.111 | 0.944 | 0.824 | 0.805 |
| multi_passage | 9 | 0.122 | 0.500 | 0.444 | 0.389 |
| paraphrase | 13 | 0.077 | 0.615 | 0.301 | 0.373 |
| version_specific | 7 | 0.114 | 0.929 | 0.648 | 0.675 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.44) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 32 | 0.094 | 0.672 | 0.471 | 0.489 |
| high | 33 | 0.109 | 0.818 | 0.644 | 0.610 |

## Latency (search service, ms, 70 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 25.8 | 40.3 |
| retrieve | 31.1 | 43.0 |
| total | 57.1 | 79.4 |

## Top-1 similarity (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 65 | 0.817 | 0.682 | 0.911 |
| unanswerable | 5 | 0.737 | 0.629 | 0.840 |
