# Run `d3-header-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d3-header","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,8,10],"query_instruction":null,"chunker":"tokens-300-overlap-50-ctx"}`
- **Chunker:** `tokens-300-overlap-50-ctx`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T15:40:54+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.243 | 0.748 | 0.650 | 0.628 | 0.843 |
| ambiguous | 4 | 0.050 | 0.125 | 0.062 | 0.066 | 0.250 |
| exact_identifier | 18 | 0.311 | 0.972 | 0.826 | 0.816 | 1.000 |
| factual | 12 | 0.267 | 0.833 | 0.833 | 0.762 | 0.833 |
| multi_passage | 11 | 0.273 | 0.621 | 0.477 | 0.449 | 0.909 |
| paraphrase | 12 | 0.150 | 0.417 | 0.406 | 0.412 | 0.583 |
| version_specific | 13 | 0.246 | 0.962 | 0.788 | 0.769 | 1.000 |

## Retrieval metrics @8

| query_type | n | P@8 | R@8 | MRR@8 | nDCG@8 | Hit@8 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.170 | 0.819 | 0.657 | 0.653 | 0.886 |
| ambiguous | 4 | 0.031 | 0.125 | 0.062 | 0.066 | 0.250 |
| exact_identifier | 18 | 0.215 | 1.000 | 0.826 | 0.823 | 1.000 |
| factual | 12 | 0.177 | 0.917 | 0.845 | 0.789 | 0.917 |
| multi_passage | 11 | 0.216 | 0.803 | 0.492 | 0.522 | 1.000 |
| paraphrase | 12 | 0.115 | 0.542 | 0.419 | 0.452 | 0.667 |
| version_specific | 13 | 0.154 | 0.962 | 0.788 | 0.769 | 1.000 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.139 | 0.840 | 0.659 | 0.660 | 0.914 |
| ambiguous | 4 | 0.025 | 0.125 | 0.062 | 0.066 | 0.250 |
| exact_identifier | 18 | 0.172 | 1.000 | 0.826 | 0.823 | 1.000 |
| factual | 12 | 0.142 | 0.917 | 0.845 | 0.789 | 0.917 |
| multi_passage | 11 | 0.173 | 0.803 | 0.492 | 0.522 | 1.000 |
| paraphrase | 12 | 0.108 | 0.667 | 0.436 | 0.495 | 0.833 |
| version_specific | 13 | 0.123 | 0.962 | 0.788 | 0.769 | 1.000 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| low | 35 | 0.137 | 0.795 | 0.616 | 0.622 | 0.914 |
| high | 35 | 0.140 | 0.886 | 0.703 | 0.699 | 0.914 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 24.6 | 38.1 |
| dense | 30.9 | 45.8 |
| rerank | 1415.3 | 1887.9 |
| total | 1472.4 | 1981.6 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 3.929 | -7.808 | 8.460 |
| unanswerable | 10 | -2.626 | -7.844 | 2.421 |

## Misses: nothing relevant in the top 10 (6)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0009@1`, `incidents/0009@1` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `incidents/0011@1`, `fastapi/tutorial/cookie-params@0.162.0`, `fastapi/tutorial/cookie-param-models@0.115.0` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `pydantic/concepts/json@v2.14.2`, `pydantic/concepts/models@v2.14.2`, `pydantic/errors/usage_errors@v2.14.2` |
| q-0102 | ambiguous | What does max_age default to? | `pydantic/concepts/fields@v2.14.2`, `pydantic/concepts/fields@v2.14.2`, `pydantic/concepts/dataclasses@v2.14.2` |
| q-0107 | ambiguous | How do I enable HTTPS? | `fastapi/deployment/https@0.115.0`, `fastapi/deployment/https@0.162.0`, `fastapi/deployment/https@0.162.0` |
| q-0110 | ambiguous | How many processes should I run? | `fastapi/deployment/concepts@0.115.0`, `fastapi/deployment/concepts@0.162.0`, `uvicorn/deployment/docker@0.54.0` |
