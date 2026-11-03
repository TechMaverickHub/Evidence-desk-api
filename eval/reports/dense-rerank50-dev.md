# Run `dense-rerank50-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-rerank50","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":50,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `7de5184920a4c3aa3fa586bd66c490eebd1a8132`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T07:10:04+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 70 | 0.223 | 0.686 | 0.635 | 0.587 |
| ambiguous | 4 | 0.200 | 0.250 | 0.312 | 0.219 |
| exact_identifier | 18 | 0.311 | 0.972 | 0.898 | 0.846 |
| factual | 12 | 0.200 | 0.625 | 0.528 | 0.525 |
| multi_passage | 11 | 0.200 | 0.545 | 0.530 | 0.431 |
| paraphrase | 12 | 0.117 | 0.292 | 0.267 | 0.272 |
| version_specific | 13 | 0.246 | 0.962 | 0.897 | 0.818 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.126 | 0.736 | 0.643 | 0.604 |
| ambiguous | 4 | 0.125 | 0.375 | 0.354 | 0.274 |
| exact_identifier | 18 | 0.167 | 0.972 | 0.898 | 0.846 |
| factual | 12 | 0.100 | 0.625 | 0.528 | 0.525 |
| multi_passage | 11 | 0.118 | 0.545 | 0.530 | 0.431 |
| paraphrase | 12 | 0.100 | 0.542 | 0.297 | 0.353 |
| version_specific | 13 | 0.123 | 0.962 | 0.897 | 0.818 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 35 | 0.111 | 0.629 | 0.492 | 0.489 |
| high | 35 | 0.140 | 0.843 | 0.793 | 0.718 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 42.4 | 73.8 |
| dense | 56.3 | 106.5 |
| rerank | 3636.5 | 4675.9 |
| total | 3725.0 | 4816.3 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 3.766 | -6.089 | 8.084 |
| unanswerable | 10 | -1.739 | -5.493 | 3.002 |

## Misses: nothing relevant in the top 10 (11)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.115.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0001@1`, `incidents/0017@1` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0010@1`, `incidents/0010@1` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `incidents/0011@1`, `fastapi/tutorial/cookie-params@0.162.0`, `fastapi/tutorial/cookie-param-models@0.115.0` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `incidents/0006@1`, `incidents/0007@1`, `fastapi/how-to/custom-request-and-route@0.162.0` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `pydantic/concepts/json@v2.14.2`, `fastapi/tutorial/body-nested-models@0.115.0`, `fastapi/tutorial/body-nested-models@0.162.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `incidents/0003@1`, `incidents/0003@1`, `incidents/0003@1` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `incidents/0004@1`, `pydantic/concepts/validators@v2.14.2`, `incidents/0004@1` |
| q-0107 | ambiguous | How do I enable HTTPS? | `fastapi/deployment/https@0.115.0`, `fastapi/deployment/https@0.162.0`, `uvicorn/concepts/http2@0.54.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/config@1.10.0`, `fastapi/advanced/additional-status-codes@0.115.0`, `starlette/config@1.10.0` |
| q-0141 | factual | Is a ContextVar set during lifespan startup visible inside request handlers when running under Uvicorn? | `starlette/lifespan@1.10.0`, `uvicorn/concepts/lifespan@0.54.0`, `uvicorn/concepts/lifespan@0.54.0` |
