# Run `hybrid-rrf-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"hybrid-rrf","retriever":"hybrid","depth":10,"fusion_depth":50,"rrf_k":60,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `860c49bd1deeed71b1acb047835bec1a62b12c9d`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T06:30:46+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 65 | 0.145 | 0.595 | 0.516 | 0.472 |
| ambiguous | 6 | 0.133 | 0.500 | 0.500 | 0.371 |
| exact_identifier | 12 | 0.200 | 0.875 | 0.757 | 0.717 |
| factual | 18 | 0.178 | 0.833 | 0.659 | 0.654 |
| multi_passage | 9 | 0.178 | 0.463 | 0.583 | 0.393 |
| paraphrase | 13 | 0.062 | 0.231 | 0.154 | 0.174 |
| version_specific | 7 | 0.086 | 0.429 | 0.333 | 0.327 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 65 | 0.091 | 0.721 | 0.533 | 0.513 |
| ambiguous | 6 | 0.100 | 0.694 | 0.537 | 0.430 |
| exact_identifier | 12 | 0.108 | 0.917 | 0.757 | 0.738 |
| factual | 18 | 0.111 | 0.944 | 0.678 | 0.693 |
| multi_passage | 9 | 0.089 | 0.463 | 0.583 | 0.393 |
| paraphrase | 13 | 0.046 | 0.385 | 0.171 | 0.220 |
| version_specific | 7 | 0.086 | 0.786 | 0.385 | 0.430 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.44) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 32 | 0.075 | 0.583 | 0.383 | 0.378 |
| high | 33 | 0.106 | 0.854 | 0.679 | 0.644 |

## Latency (search service, ms, 70 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 38.5 | 68.5 |
| dense | 49.0 | 72.7 |
| keyword | 82.5 | 198.0 |
| fuse | 1.0 | 1.8 |
| total | 173.3 | 308.6 |

## Top-1 similarity (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 65 | 0.031 | 0.024 | 0.033 |
| unanswerable | 5 | 0.030 | 0.027 | 0.032 |
