# Run `d2-tokens450-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d2-tokens450","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,8,10],"query_instruction":null,"chunker":"tokens-450-overlap-75"}`
- **Chunker:** `tokens-450-overlap-75`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T15:47:01+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.200 | 0.741 | 0.583 | 0.572 | 0.800 |
| ambiguous | 6 | 0.200 | 0.639 | 0.478 | 0.383 | 0.833 |
| exact_identifier | 12 | 0.183 | 0.792 | 0.649 | 0.613 | 0.833 |
| factual | 18 | 0.222 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.222 | 0.481 | 0.393 | 0.353 | 0.667 |
| paraphrase | 13 | 0.138 | 0.538 | 0.377 | 0.416 | 0.538 |
| version_specific | 7 | 0.257 | 0.929 | 0.540 | 0.622 | 1.000 |

## Retrieval metrics @8

| query_type | n | P@8 | R@8 | MRR@8 | nDCG@8 | Hit@8 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.137 | 0.790 | 0.588 | 0.589 | 0.831 |
| ambiguous | 6 | 0.167 | 0.806 | 0.506 | 0.444 | 1.000 |
| exact_identifier | 12 | 0.115 | 0.792 | 0.649 | 0.613 | 0.833 |
| factual | 18 | 0.139 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.181 | 0.611 | 0.393 | 0.398 | 0.667 |
| paraphrase | 13 | 0.096 | 0.615 | 0.390 | 0.443 | 0.615 |
| version_specific | 7 | 0.161 | 0.929 | 0.540 | 0.622 | 1.000 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.114 | 0.813 | 0.589 | 0.597 | 0.846 |
| ambiguous | 6 | 0.133 | 0.806 | 0.506 | 0.444 | 1.000 |
| exact_identifier | 12 | 0.100 | 0.833 | 0.649 | 0.632 | 0.833 |
| factual | 18 | 0.111 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.144 | 0.611 | 0.393 | 0.398 | 0.667 |
| paraphrase | 13 | 0.092 | 0.692 | 0.398 | 0.466 | 0.692 |
| version_specific | 7 | 0.129 | 0.929 | 0.540 | 0.622 | 1.000 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.44) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| low | 32 | 0.097 | 0.703 | 0.476 | 0.494 | 0.719 |
| high | 33 | 0.130 | 0.919 | 0.699 | 0.698 | 0.970 |

## Latency (search service, ms, 70 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 26.2 | 46.7 |
| dense | 25.8 | 33.9 |
| rerank | 2118.5 | 2288.3 |
| total | 2172.8 | 2351.3 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 65 | 3.841 | -6.317 | 8.887 |
| unanswerable | 5 | -1.782 | -9.832 | 6.042 |
