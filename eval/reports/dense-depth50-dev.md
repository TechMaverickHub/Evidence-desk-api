# Run `dense-depth50-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-depth50","retriever":"dense","depth":50,"fusion_depth":50,"rrf_k":60,"rerank":false,"rerank_depth":50,"cutoffs":[10,50],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cosine`
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `7de5184920a4c3aa3fa586bd66c490eebd1a8132`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T07:01:33+00:00

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.110 | 0.686 | 0.552 | 0.529 |
| ambiguous | 4 | 0.000 | 0.000 | 0.000 | 0.000 |
| exact_identifier | 18 | 0.150 | 0.944 | 0.769 | 0.759 |
| factual | 12 | 0.108 | 0.708 | 0.525 | 0.488 |
| multi_passage | 11 | 0.109 | 0.545 | 0.485 | 0.410 |
| paraphrase | 12 | 0.083 | 0.417 | 0.206 | 0.259 |
| version_specific | 13 | 0.115 | 0.885 | 0.823 | 0.764 |

## Retrieval metrics @50

| query_type | n | P@50 | R@50 | MRR@50 | nDCG@50 |
|---|---|---|---|---|---|
| **all** | 70 | 0.031 | 0.855 | 0.561 | 0.571 |
| ambiguous | 4 | 0.055 | 0.792 | 0.062 | 0.238 |
| exact_identifier | 18 | 0.034 | 1.000 | 0.771 | 0.773 |
| factual | 12 | 0.025 | 0.792 | 0.530 | 0.508 |
| multi_passage | 11 | 0.036 | 0.788 | 0.501 | 0.479 |
| paraphrase | 12 | 0.025 | 0.667 | 0.213 | 0.308 |
| version_specific | 13 | 0.025 | 0.962 | 0.825 | 0.775 |

## By word overlap @50

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@50 | R@50 | MRR@50 | nDCG@50 |
|---|---|---|---|---|---|
| low | 35 | 0.029 | 0.790 | 0.482 | 0.504 |
| high | 35 | 0.033 | 0.919 | 0.640 | 0.638 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 29.5 | 39.1 |
| dense | 36.8 | 50.6 |
| total | 65.8 | 87.4 |

## Top-1 score: cosine (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 0.810 | 0.648 | 0.914 |
| unanswerable | 10 | 0.725 | 0.673 | 0.775 |

## Misses: nothing relevant in the top 50 (4)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0001@1`, `incidents/0017@1` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0008@1`, `incidents/0010@1` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `pydantic/errors/validation_errors@v2.14.2`, `fastapi/tutorial/body-fields@0.115.0`, `pydantic/concepts/experimental@v2.14.2` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/third-party-packages@1.10.0`, `fastapi/deployment/versions@0.162.0`, `uvicorn/concepts/asgi@0.54.0` |
