# Run `d2-tokens450-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d2-tokens450","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,8,10],"query_instruction":null,"chunker":"tokens-450-overlap-75"}`
- **Chunker:** `tokens-450-overlap-75`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T15:38:26+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.220 | 0.714 | 0.666 | 0.609 | 0.814 |
| ambiguous | 4 | 0.150 | 0.375 | 0.562 | 0.373 | 0.750 |
| exact_identifier | 18 | 0.300 | 0.972 | 0.907 | 0.854 | 1.000 |
| factual | 12 | 0.200 | 0.708 | 0.611 | 0.608 | 0.750 |
| multi_passage | 11 | 0.200 | 0.545 | 0.530 | 0.407 | 0.818 |
| paraphrase | 12 | 0.150 | 0.417 | 0.294 | 0.314 | 0.500 |
| version_specific | 13 | 0.231 | 0.885 | 0.872 | 0.788 | 0.923 |

## Retrieval metrics @8

| query_type | n | P@8 | R@8 | MRR@8 | nDCG@8 | Hit@8 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.148 | 0.719 | 0.668 | 0.612 | 0.829 |
| ambiguous | 4 | 0.156 | 0.458 | 0.604 | 0.422 | 1.000 |
| exact_identifier | 18 | 0.201 | 0.972 | 0.907 | 0.854 | 1.000 |
| factual | 12 | 0.135 | 0.708 | 0.611 | 0.608 | 0.750 |
| multi_passage | 11 | 0.136 | 0.545 | 0.530 | 0.407 | 0.818 |
| paraphrase | 12 | 0.094 | 0.417 | 0.294 | 0.314 | 0.500 |
| version_specific | 13 | 0.144 | 0.885 | 0.872 | 0.788 | 0.923 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.121 | 0.726 | 0.668 | 0.615 | 0.829 |
| ambiguous | 4 | 0.150 | 0.458 | 0.604 | 0.422 | 1.000 |
| exact_identifier | 18 | 0.167 | 1.000 | 0.907 | 0.866 | 1.000 |
| factual | 12 | 0.108 | 0.708 | 0.611 | 0.608 | 0.750 |
| multi_passage | 11 | 0.109 | 0.545 | 0.530 | 0.407 | 0.818 |
| paraphrase | 12 | 0.075 | 0.417 | 0.294 | 0.314 | 0.500 |
| version_specific | 13 | 0.115 | 0.885 | 0.872 | 0.788 | 0.923 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| low | 35 | 0.103 | 0.586 | 0.510 | 0.493 | 0.686 |
| high | 35 | 0.140 | 0.867 | 0.826 | 0.738 | 0.971 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 23.9 | 42.0 |
| dense | 25.5 | 38.1 |
| rerank | 1884.7 | 2107.3 |
| total | 1933.5 | 2161.4 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 3.663 | -6.089 | 8.082 |
| unanswerable | 10 | -1.750 | -5.422 | 1.923 |

## Misses: nothing relevant in the top 10 (12)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.115.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0001@1`, `incidents/0017@1` |
| q-0036 | paraphrase | Our item JSON comes back stuffed with default nulls the client never filled in. How do I return just the fields that were really provided? | `fastapi/how-to/separate-openapi-schemas@0.115.0`, `fastapi/how-to/separate-openapi-schemas@0.162.0`, `fastapi/tutorial/handling-errors@0.162.0` |
| q-0040 | paraphrase | How do I stop the app from publishing its interactive API explorer and machine-readable spec at all? | `incidents/0003@1`, `fastapi/tutorial/cookie-param-models@0.115.0`, `fastapi/how-to/conditional-openapi@0.115.0` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0010@1`, `incidents/0010@1` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `incidents/0011@1`, `starlette/middleware@1.10.0`, `fastapi/tutorial/cookie-param-models@0.162.0` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `incidents/0006@1`, `incidents/0007@1`, `incidents/0005@1` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `fastapi/tutorial/body-nested-models@0.115.0`, `fastapi/tutorial/body-nested-models@0.115.0`, `fastapi/tutorial/body-nested-models@0.162.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `incidents/0003@1`, `incidents/0003@1`, `incidents/0003@1` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `pydantic/concepts/validators@v2.14.2`, `incidents/0004@1`, `incidents/0004@1` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/tutorial/server-sent-events@0.162.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/config@1.10.0`, `starlette/authentication@1.10.0`, `starlette/config@1.10.0` |
