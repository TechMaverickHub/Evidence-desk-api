# Run `d0-baseline-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d0-baseline","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,8,10],"query_instruction":null,"chunker":"tokens-300-overlap-50"}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T15:43:59+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.194 | 0.718 | 0.588 | 0.578 | 0.769 |
| ambiguous | 6 | 0.200 | 0.639 | 0.492 | 0.408 | 0.833 |
| exact_identifier | 12 | 0.183 | 0.792 | 0.674 | 0.654 | 0.833 |
| factual | 18 | 0.222 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.222 | 0.426 | 0.426 | 0.378 | 0.556 |
| paraphrase | 13 | 0.138 | 0.462 | 0.404 | 0.418 | 0.462 |
| version_specific | 7 | 0.200 | 0.929 | 0.445 | 0.550 | 1.000 |

## Retrieval metrics @8

| query_type | n | P@8 | R@8 | MRR@8 | nDCG@8 | Hit@8 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.133 | 0.774 | 0.595 | 0.595 | 0.815 |
| ambiguous | 6 | 0.167 | 0.806 | 0.515 | 0.447 | 1.000 |
| exact_identifier | 12 | 0.115 | 0.792 | 0.674 | 0.654 | 0.833 |
| factual | 18 | 0.139 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.153 | 0.500 | 0.426 | 0.402 | 0.556 |
| paraphrase | 13 | 0.106 | 0.615 | 0.428 | 0.471 | 0.615 |
| version_specific | 7 | 0.143 | 0.929 | 0.445 | 0.550 | 1.000 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| **all** | 65 | 0.114 | 0.813 | 0.599 | 0.608 | 0.846 |
| ambiguous | 6 | 0.133 | 0.806 | 0.515 | 0.447 | 1.000 |
| exact_identifier | 12 | 0.108 | 0.833 | 0.674 | 0.674 | 0.833 |
| factual | 18 | 0.111 | 0.944 | 0.833 | 0.810 | 0.944 |
| multi_passage | 9 | 0.122 | 0.500 | 0.426 | 0.402 | 0.556 |
| paraphrase | 13 | 0.108 | 0.769 | 0.445 | 0.517 | 0.769 |
| version_specific | 7 | 0.114 | 0.929 | 0.445 | 0.550 | 1.000 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.44) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| low | 32 | 0.106 | 0.734 | 0.484 | 0.516 | 0.750 |
| high | 33 | 0.121 | 0.889 | 0.710 | 0.698 | 0.939 |

## Latency (search service, ms, 70 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 25.7 | 44.2 |
| dense | 30.8 | 70.5 |
| rerank | 1219.6 | 1567.2 |
| total | 1283.6 | 1653.6 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 65 | 3.912 | -6.317 | 8.887 |
| unanswerable | 5 | -1.567 | -10.214 | 6.042 |
