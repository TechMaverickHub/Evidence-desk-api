# Run `hybrid-rrf-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"hybrid-rrf","retriever":"hybrid","depth":10,"fusion_depth":50,"rrf_k":60,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `860c49bd1deeed71b1acb047835bec1a62b12c9d`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T06:29:37+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 70 | 0.163 | 0.543 | 0.444 | 0.422 |
| ambiguous | 4 | 0.000 | 0.000 | 0.000 | 0.000 |
| exact_identifier | 18 | 0.244 | 0.833 | 0.613 | 0.612 |
| factual | 12 | 0.150 | 0.542 | 0.419 | 0.421 |
| multi_passage | 11 | 0.218 | 0.545 | 0.518 | 0.422 |
| paraphrase | 12 | 0.067 | 0.125 | 0.111 | 0.098 |
| version_specific | 13 | 0.154 | 0.692 | 0.615 | 0.590 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.099 | 0.626 | 0.458 | 0.451 |
| ambiguous | 4 | 0.100 | 0.333 | 0.090 | 0.139 |
| exact_identifier | 18 | 0.144 | 0.944 | 0.625 | 0.645 |
| factual | 12 | 0.083 | 0.542 | 0.419 | 0.421 |
| multi_passage | 11 | 0.118 | 0.591 | 0.530 | 0.440 |
| paraphrase | 12 | 0.050 | 0.292 | 0.135 | 0.154 |
| version_specific | 13 | 0.077 | 0.692 | 0.615 | 0.590 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 35 | 0.071 | 0.457 | 0.286 | 0.295 |
| high | 35 | 0.126 | 0.795 | 0.631 | 0.607 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| embed_query | 36.0 | 55.3 |
| dense | 45.1 | 63.8 |
| keyword | 70.1 | 160.5 |
| fuse | 1.0 | 1.6 |
| total | 160.0 | 264.7 |

## Top-1 similarity (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 0.031 | 0.016 | 0.033 |
| unanswerable | 10 | 0.028 | 0.016 | 0.032 |

## Misses: nothing relevant in the top 10 (22)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0006 | factual | Does allowing all origins with "*" in CORS work for requests that send cookies or an Authorization header? | `starlette/middleware@1.10.0`, `starlette/middleware@1.10.0`, `fastapi/tutorial/cors@0.162.0` |
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `starlette/middleware@1.10.0`, `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.115.0` |
| q-0022 | exact_identifier | How do you start several worker processes with the fastapi or uvicorn command? | `fastapi/deployment/server-workers@0.162.0`, `uvicorn/deployment/index@0.54.0`, `fastapi/deployment/server-workers@0.115.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `incidents/0009@1`, `starlette/exceptions@1.10.0`, `fastapi/tutorial/handling-errors@0.162.0` |
| q-0036 | paraphrase | Our item JSON comes back stuffed with default nulls the client never filled in. How do I return just the fields that were really provided? | `fastapi/tutorial/body-updates@0.115.0`, `fastapi/advanced/additional-status-codes@0.162.0`, `fastapi/tutorial/body-updates@0.115.0` |
| q-0040 | paraphrase | How do I stop the app from publishing its interactive API explorer and machine-readable spec at all? | `fastapi/how-to/conditional-openapi@0.162.0`, `fastapi/how-to/conditional-openapi@0.115.0`, `fastapi/advanced/sub-applications@0.162.0` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `incidents/0010@1`, `incidents/0010@1`, `fastapi/how-to/sql-databases-peewee@0.115.0` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `fastapi/tutorial/cookie-param-models@0.162.0`, `starlette/middleware@1.10.0`, `fastapi/tutorial/cookie-param-models@0.115.0` |
| q-0044 | paraphrase | A partner's webhook calls started bouncing as invalid as soon as we made our input checks stricter. What triggered it? | `fastapi/advanced/openapi-webhooks@0.162.0`, `incidents/0005@1`, `pydantic/errors/errors@v2.14.2` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `fastapi/how-to/custom-request-and-route@0.115.0`, `fastapi/how-to/custom-request-and-route@0.162.0`, `fastapi/how-to/custom-request-and-route@0.162.0` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `pydantic/concepts/json@v2.14.2`, `fastapi/tutorial/schema-extra-example@0.162.0`, `fastapi/tutorial/body-multiple-params@0.162.0` |
| q-0053 | paraphrase | Should my Python web app itself hold the certificates and decrypt incoming secure traffic? | `fastapi/deployment/https@0.162.0`, `fastapi/deployment/https@0.115.0`, `fastapi/advanced/security/http-basic-auth@0.115.0` |
| q-0062 | multi_passage | Why did generated URLs switch to http:// after catalog-api moved behind a new TLS proxy, and which Uvicorn setting decides whose forwarded headers are believed? | `fastapi/deployment/https@0.162.0`, `uvicorn/deployment/index@0.54.0`, `fastapi/deployment/docker@0.162.0` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `fastapi/how-to/custom-docs-ui-assets@0.115.0`, `incidents/0003@1`, `incidents/0003@1` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `pydantic/concepts/unions@v2.14.2`, `pydantic/concepts/unions@v2.14.2`, `pydantic/concepts/validators@v2.14.2` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/advanced-dependencies@0.115.0` |
| q-0090 | version_specific | Starting with which FastAPI version can a group of query parameters be declared as a Pydantic model? | `fastapi/tutorial/query-param-models@0.162.0`, `fastapi/tutorial/query-param-models@0.115.0`, `fastapi/tutorial/query-param-models@0.162.0` |
| q-0091 | version_specific | Since which FastAPI version can HTML form fields be declared with a Pydantic model? | `fastapi/tutorial/request-form-models@0.162.0`, `fastapi/tutorial/request-form-models@0.115.0`, `fastapi/tutorial/request-form-models@0.115.0` |
| q-0094 | version_specific | In FastAPI 0.162.0, how do you stream raw binary data such as a video from a path operation? | `fastapi/tutorial/server-sent-events@0.162.0`, `fastapi/advanced/custom-response@0.162.0`, `fastapi/advanced/custom-response@0.115.0` |
| q-0102 | ambiguous | What does max_age default to? | `pydantic/concepts/fields@v2.14.2`, `pydantic/concepts/fields@v2.14.2`, `fastapi/tutorial/query-params-str-validations@0.162.0` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `starlette/config@1.10.0`, `fastapi/deployment/versions@0.162.0`, `starlette/third-party-packages@1.10.0` |
| q-0141 | factual | Is a ContextVar set during lifespan startup visible inside request handlers when running under Uvicorn? | `uvicorn/concepts/lifespan@0.54.0`, `starlette/lifespan@1.10.0`, `starlette/lifespan@1.10.0` |
