# Run `dense-rerank20-test`

- **Dataset:** evidencedesk-v1, split `test`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-rerank20","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `7de5184920a4c3aa3fa586bd66c490eebd1a8132`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T07:13:39+00:00

> Test split: a final comparison run. Do not tune on these numbers.

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 65 | 0.194 | 0.718 | 0.588 | 0.578 |
| ambiguous | 6 | 0.200 | 0.639 | 0.492 | 0.408 |
| exact_identifier | 12 | 0.183 | 0.792 | 0.674 | 0.654 |
| factual | 18 | 0.222 | 0.944 | 0.833 | 0.810 |
| multi_passage | 9 | 0.222 | 0.426 | 0.426 | 0.378 |
| paraphrase | 13 | 0.138 | 0.462 | 0.404 | 0.418 |
| version_specific | 7 | 0.200 | 0.929 | 0.445 | 0.550 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 65 | 0.114 | 0.813 | 0.599 | 0.608 |
| ambiguous | 6 | 0.133 | 0.806 | 0.515 | 0.447 |
| exact_identifier | 12 | 0.108 | 0.833 | 0.674 | 0.674 |
| factual | 18 | 0.111 | 0.944 | 0.833 | 0.810 |
| multi_passage | 9 | 0.122 | 0.500 | 0.426 | 0.402 |
| paraphrase | 13 | 0.108 | 0.769 | 0.445 | 0.517 |
| version_specific | 7 | 0.114 | 0.929 | 0.445 | 0.550 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.44) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 32 | 0.106 | 0.734 | 0.484 | 0.516 |
| high | 33 | 0.121 | 0.889 | 0.710 | 0.698 |

## Latency (search service, ms, 70 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 47.2 | 153.3 |
| dense | 51.8 | 108.1 |
| rerank | 1872.9 | 2973.0 |
| total | 1981.3 | 3224.5 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 65 | 3.912 | -6.317 | 8.887 |
| unanswerable | 5 | -1.567 | -10.214 | 6.042 |
