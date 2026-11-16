# Run `d1-tokens150-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"d1-tokens150","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,8,10],"query_instruction":null,"chunker":"tokens-150-overlap-30"}`
- **Chunker:** `tokens-150-overlap-30`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `ba5a15ecf2a4eebbf88c5ef1313530d94fb76670`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-16T15:35:24+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 | Hit@5 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.206 | 0.629 | 0.566 | 0.524 | 0.743 |
| ambiguous | 4 | 0.250 | 0.375 | 0.417 | 0.307 | 0.750 |
| exact_identifier | 18 | 0.244 | 0.806 | 0.769 | 0.708 | 0.833 |
| factual | 12 | 0.150 | 0.542 | 0.458 | 0.445 | 0.583 |
| multi_passage | 11 | 0.200 | 0.455 | 0.439 | 0.367 | 0.727 |
| paraphrase | 12 | 0.167 | 0.417 | 0.253 | 0.297 | 0.583 |
| version_specific | 13 | 0.231 | 0.885 | 0.827 | 0.754 | 0.923 |

## Retrieval metrics @8

| query_type | n | P@8 | R@8 | MRR@8 | nDCG@8 | Hit@8 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.138 | 0.664 | 0.572 | 0.538 | 0.786 |
| ambiguous | 4 | 0.156 | 0.375 | 0.417 | 0.307 | 0.750 |
| exact_identifier | 18 | 0.167 | 0.861 | 0.778 | 0.727 | 0.889 |
| factual | 12 | 0.094 | 0.542 | 0.458 | 0.445 | 0.583 |
| multi_passage | 11 | 0.136 | 0.455 | 0.439 | 0.367 | 0.727 |
| paraphrase | 12 | 0.125 | 0.542 | 0.274 | 0.344 | 0.750 |
| version_specific | 13 | 0.144 | 0.885 | 0.827 | 0.754 | 0.923 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| **all** | 70 | 0.113 | 0.679 | 0.573 | 0.542 | 0.800 |
| ambiguous | 4 | 0.125 | 0.375 | 0.417 | 0.307 | 0.750 |
| exact_identifier | 18 | 0.133 | 0.861 | 0.778 | 0.727 | 0.889 |
| factual | 12 | 0.083 | 0.625 | 0.467 | 0.469 | 0.667 |
| multi_passage | 11 | 0.109 | 0.455 | 0.439 | 0.367 | 0.727 |
| paraphrase | 12 | 0.108 | 0.542 | 0.274 | 0.344 | 0.750 |
| version_specific | 13 | 0.115 | 0.885 | 0.827 | 0.754 | 0.923 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 | Hit@10 |
|---|---|---|---|---|---|---|
| low | 35 | 0.100 | 0.571 | 0.416 | 0.419 | 0.714 |
| high | 35 | 0.126 | 0.786 | 0.731 | 0.664 | 0.886 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 24.1 | 34.6 |
| dense | 51.3 | 70.7 |
| rerank | 564.6 | 696.5 |
| total | 642.0 | 785.7 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 3.942 | -6.089 | 8.405 |
| unanswerable | 10 | -2.227 | -5.912 | 1.961 |

## Misses: nothing relevant in the top 10 (14)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0006 | factual | Does allowing all origins with "*" in CORS work for requests that send cookies or an Authorization header? | `starlette/middleware@1.10.0`, `fastapi/tutorial/cors@0.115.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0001@1`, `incidents/0017@1` |
| q-0026 | exact_identifier | What does response_model_exclude_unset=True do on a path operation? | `fastapi/tutorial/response-model@0.162.0`, `fastapi/tutorial/response-model@0.115.0`, `fastapi/tutorial/response-model@0.162.0` |
| q-0028 | exact_identifier | What happens if you create the FastAPI app with openapi_url=None? | `fastapi/how-to/conditional-openapi@0.162.0`, `fastapi/how-to/conditional-openapi@0.115.0`, `fastapi/tutorial/frontend@0.162.0` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0010@1`, `incidents/0010@1` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `incidents/0006@1`, `incidents/0007@1`, `incidents/0005@1` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `fastapi/tutorial/body-fields@0.115.0`, `fastapi/tutorial/body-multiple-params@0.115.0`, `fastapi/tutorial/schema-extra-example@0.162.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `incidents/0003@1`, `incidents/0003@1`, `incidents/0003@1` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `incidents/0004@1`, `pydantic/errors/validation_errors@v2.14.2`, `pydantic/concepts/validation_decorator@v2.14.2` |
| q-0071 | multi_passage | The nightly scheduler crashed with "Instance is frozen". Which model setting causes that error, and how did the job change values instead? | `incidents/0018@1`, `incidents/0018@1`, `pydantic/errors/validation_errors@v2.14.2` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/tutorial/path-params@0.115.0` |
| q-0107 | ambiguous | How do I enable HTTPS? | `fastapi/deployment/https@0.115.0`, `fastapi/deployment/https@0.162.0`, `fastapi/deployment/https@0.162.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/config@1.10.0`, `starlette/routing@1.10.0`, `starlette/responses@1.10.0` |
| q-0141 | factual | Is a ContextVar set during lifespan startup visible inside request handlers when running under Uvicorn? | `uvicorn/settings@0.54.0`, `starlette/lifespan@1.10.0`, `uvicorn/concepts/lifespan@0.54.0` |
