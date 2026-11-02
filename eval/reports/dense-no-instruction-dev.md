# Run `dense-no-instruction-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"dense-no-instruction","retriever":"dense","depth":10,"cutoffs":[5,10],"query_instruction":""}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `''`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `cf8441ec6363e567cffe770786f555f8f7a5685a`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-02T09:00:34+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 70 | 0.183 | 0.607 | 0.525 | 0.491 |
| ambiguous | 4 | 0.000 | 0.000 | 0.000 | 0.000 |
| exact_identifier | 18 | 0.289 | 0.972 | 0.761 | 0.762 |
| factual | 12 | 0.150 | 0.458 | 0.500 | 0.402 |
| multi_passage | 11 | 0.182 | 0.500 | 0.508 | 0.405 |
| paraphrase | 12 | 0.100 | 0.208 | 0.194 | 0.192 |
| version_specific | 13 | 0.200 | 0.885 | 0.701 | 0.697 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.106 | 0.648 | 0.532 | 0.507 |
| ambiguous | 4 | 0.025 | 0.125 | 0.031 | 0.048 |
| exact_identifier | 18 | 0.156 | 0.972 | 0.761 | 0.762 |
| factual | 12 | 0.075 | 0.458 | 0.500 | 0.402 |
| multi_passage | 11 | 0.109 | 0.530 | 0.521 | 0.425 |
| paraphrase | 12 | 0.075 | 0.375 | 0.215 | 0.250 |
| version_specific | 13 | 0.115 | 0.885 | 0.701 | 0.697 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 35 | 0.089 | 0.495 | 0.441 | 0.414 |
| high | 35 | 0.123 | 0.800 | 0.623 | 0.599 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 23.7 | 34.3 |
| retrieve | 30.5 | 44.1 |
| total | 55.4 | 82.4 |

## Top-1 similarity (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 0.824 | 0.663 | 0.938 |
| unanswerable | 10 | 0.750 | 0.697 | 0.791 |

## Misses: nothing relevant in the top 10 (18)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0006 | factual | Does allowing all origins with "*" in CORS work for requests that send cookies or an Authorization header? | `starlette/middleware@1.10.0`, `fastapi/tutorial/cors@0.162.0`, `starlette/middleware@1.10.0` |
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `fastapi/tutorial/cors@0.115.0`, `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `incidents/0009@1`, `incidents/0001@1` |
| q-0036 | paraphrase | Our item JSON comes back stuffed with default nulls the client never filled in. How do I return just the fields that were really provided? | `fastapi/tutorial/handling-errors@0.162.0`, `fastapi/advanced/additional-responses@0.162.0`, `fastapi/tutorial/handling-errors@0.162.0` |
| q-0040 | paraphrase | How do I stop the app from publishing its interactive API explorer and machine-readable spec at all? | `incidents/0003@1`, `fastapi/advanced/strict-content-type@0.162.0`, `incidents/0004@1` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0008@1`, `incidents/0010@1` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `incidents/0006@1`, `incidents/0006@1`, `incidents/0001@1` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `pydantic/errors/validation_errors@v2.14.2`, `fastapi/tutorial/body-fields@0.115.0`, `pydantic/concepts/experimental@v2.14.2` |
| q-0053 | paraphrase | Should my Python web app itself hold the certificates and decrypt incoming secure traffic? | `uvicorn/settings@0.54.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/middleware@0.115.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `incidents/0003@1`, `incidents/0003@1`, `incidents/0003@1` |
| q-0071 | multi_passage | The nightly scheduler crashed with "Instance is frozen". Which model setting causes that error, and how did the job change values instead? | `incidents/0018@1`, `incidents/0018@1`, `incidents/0018@1` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/tutorial/path-params@0.115.0` |
| q-0102 | ambiguous | What does max_age default to? | `pydantic/concepts/fields@v2.14.2`, `pydantic/errors/validation_errors@v2.14.2`, `pydantic/concepts/alias@v2.14.2` |
| q-0107 | ambiguous | How do I enable HTTPS? | `fastapi/deployment/https@0.162.0`, `fastapi/deployment/https@0.115.0`, `fastapi/deployment/https@0.115.0` |
| q-0110 | ambiguous | How many processes should I run? | `fastapi/deployment/concepts@0.162.0`, `fastapi/deployment/concepts@0.115.0`, `fastapi/deployment/concepts@0.162.0` |
| q-0128 | factual | In what order does Starlette's Config look for a configuration value? | `fastapi/tutorial/static-files@0.162.0`, `fastapi/tutorial/static-files@0.115.0`, `uvicorn/concepts/asgi@0.54.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/requests@1.10.0`, `starlette/third-party-packages@1.10.0`, `uvicorn/concepts/asgi@0.54.0` |
| q-0141 | factual | Is a ContextVar set during lifespan startup visible inside request handlers when running under Uvicorn? | `uvicorn/concepts/lifespan@0.54.0`, `fastapi/how-to/sql-databases-peewee@0.115.0`, `fastapi/how-to/sql-databases-peewee@0.115.0` |
