# Run `dense-rerank20-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-rerank20","retriever":"dense","depth":10,"fusion_depth":50,"rrf_k":60,"rerank":true,"rerank_depth":20,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Hit score:** `cross_encoder` (reranker `cross-encoder/ms-marco-MiniLM-L6-v2`)
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `7de5184920a4c3aa3fa586bd66c490eebd1a8132`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T07:04:24+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 70 | 0.211 | 0.664 | 0.627 | 0.579 |
| ambiguous | 4 | 0.150 | 0.250 | 0.333 | 0.230 |
| exact_identifier | 18 | 0.289 | 0.944 | 0.880 | 0.837 |
| factual | 12 | 0.200 | 0.625 | 0.528 | 0.525 |
| multi_passage | 11 | 0.200 | 0.545 | 0.530 | 0.431 |
| paraphrase | 12 | 0.117 | 0.292 | 0.267 | 0.272 |
| version_specific | 13 | 0.231 | 0.885 | 0.872 | 0.788 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.116 | 0.693 | 0.631 | 0.589 |
| ambiguous | 4 | 0.075 | 0.250 | 0.333 | 0.230 |
| exact_identifier | 18 | 0.156 | 0.944 | 0.880 | 0.837 |
| factual | 12 | 0.108 | 0.708 | 0.540 | 0.552 |
| multi_passage | 11 | 0.109 | 0.545 | 0.530 | 0.431 |
| paraphrase | 12 | 0.083 | 0.375 | 0.281 | 0.304 |
| version_specific | 13 | 0.115 | 0.885 | 0.872 | 0.788 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 35 | 0.103 | 0.571 | 0.481 | 0.470 |
| high | 35 | 0.129 | 0.814 | 0.781 | 0.709 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 42.5 | 76.7 |
| dense | 52.9 | 89.7 |
| rerank | 1598.8 | 1836.0 |
| total | 1696.6 | 1947.1 |

## Top-1 score: cross_encoder (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 3.736 | -6.089 | 8.084 |
| unanswerable | 10 | -2.234 | -5.822 | 1.912 |

## Misses: nothing relevant in the top 10 (15)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.115.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0022 | exact_identifier | How do you start several worker processes with the fastapi or uvicorn command? | `fastapi/deployment/concepts@0.115.0`, `fastapi/deployment/concepts@0.162.0`, `fastapi/deployment/server-workers@0.115.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0001@1`, `incidents/0017@1` |
| q-0040 | paraphrase | How do I stop the app from publishing its interactive API explorer and machine-readable spec at all? | `incidents/0003@1`, `fastapi/advanced/behind-a-proxy@0.162.0`, `fastapi/tutorial/sql-databases@0.162.0` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0010@1`, `incidents/0010@1` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `incidents/0011@1`, `fastapi/tutorial/cookie-params@0.162.0`, `fastapi/tutorial/cookie-param-models@0.115.0` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `incidents/0006@1`, `incidents/0007@1`, `fastapi/how-to/custom-request-and-route@0.115.0` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `fastapi/tutorial/body-nested-models@0.162.0`, `fastapi/tutorial/body-fields@0.115.0`, `fastapi/tutorial/body-multiple-params@0.115.0` |
| q-0053 | paraphrase | Should my Python web app itself hold the certificates and decrypt incoming secure traffic? | `fastapi/advanced/middleware@0.115.0`, `fastapi/advanced/middleware@0.162.0`, `uvicorn/settings@0.54.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `incidents/0003@1`, `incidents/0003@1`, `incidents/0003@1` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `pydantic/concepts/validators@v2.14.2`, `incidents/0004@1`, `incidents/0004@1` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/tutorial/path-params@0.115.0` |
| q-0107 | ambiguous | How do I enable HTTPS? | `fastapi/deployment/https@0.115.0`, `fastapi/deployment/https@0.162.0`, `uvicorn/concepts/http2@0.54.0` |
| q-0110 | ambiguous | How many processes should I run? | `fastapi/deployment/concepts@0.162.0`, `fastapi/deployment/concepts@0.115.0`, `uvicorn/deployment/docker@0.54.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/config@1.10.0`, `starlette/config@1.10.0`, `starlette/responses@1.10.0` |
