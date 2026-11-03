# Run `keyword-dev`

- **Dataset:** evidencedesk-v1, split `dev`, sha256 `b77c981ff46376d25f7c81eb3f60b520df64a6566b584234d688a0b8cbcf9920`
- **Config:** `{"name":"keyword","retriever":"keyword","depth":10,"fusion_depth":50,"rrf_k":60,"cutoffs":[5,10],"query_instruction":null}`
- **Chunker:** `tokens-300-overlap-50`
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Query instruction:** `'Represent this sentence for searching relevant passages: '`
- **Span match:** overlap ≥ 0.5 × the shorter range
- **Corpus:** 285 documents verified against `corpus/`
- **Git:** `860c49bd1deeed71b1acb047835bec1a62b12c9d`
- **Environment:** python 3.12.12, os Windows-11, processor Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, cpu_count 8, postgres 16.14 (Debian 16.14-1.pgdg12+1)
- **Created:** 2026-11-03T06:28:49+00:00

## Retrieval metrics @5

| query_type | n | P@5 | R@5 | MRR@5 | nDCG@5 |
|---|---|---|---|---|---|
| **all** | 70 | 0.137 | 0.412 | 0.309 | 0.292 |
| ambiguous | 4 | 0.200 | 0.333 | 0.417 | 0.292 |
| exact_identifier | 18 | 0.189 | 0.556 | 0.324 | 0.357 |
| factual | 12 | 0.083 | 0.292 | 0.278 | 0.285 |
| multi_passage | 11 | 0.182 | 0.455 | 0.439 | 0.337 |
| paraphrase | 12 | 0.067 | 0.125 | 0.125 | 0.107 |
| version_specific | 13 | 0.123 | 0.577 | 0.342 | 0.343 |

## Retrieval metrics @10

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| **all** | 70 | 0.084 | 0.481 | 0.316 | 0.314 |
| ambiguous | 4 | 0.150 | 0.417 | 0.417 | 0.306 |
| exact_identifier | 18 | 0.106 | 0.611 | 0.331 | 0.370 |
| factual | 12 | 0.050 | 0.333 | 0.278 | 0.288 |
| multi_passage | 11 | 0.127 | 0.591 | 0.464 | 0.393 |
| paraphrase | 12 | 0.033 | 0.125 | 0.125 | 0.107 |
| version_specific | 13 | 0.077 | 0.692 | 0.353 | 0.389 |

## By word overlap @10

Questions below vs at-or-above the median overlap (0.32) between the question's words and its evidence text.

| query_type | n | P@10 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| low | 35 | 0.051 | 0.271 | 0.156 | 0.167 |
| high | 35 | 0.117 | 0.690 | 0.477 | 0.462 |

## Latency (search service, ms, 80 queries)

| stage | p50 | p95 |
|---|---|---|
| keyword | 49.4 | 113.0 |
| total | 49.4 | 113.0 |

## Top-1 similarity (input for abstention, task 009)

| questions | n | mean | min | max |
|---|---|---|---|---|
| answerable | 70 | 2.089 | 0.700 | 3.900 |
| unanswerable | 10 | 1.550 | 1.100 | 2.400 |

## Misses: nothing relevant in the top 10 (33)

| id | query_type | question | top hits |
|---|---|---|---|
| q-0006 | factual | Does allowing all origins with "*" in CORS work for requests that send cookies or an Authorization header? | `starlette/middleware@1.10.0`, `fastapi/tutorial/cors@0.162.0`, `fastapi/tutorial/cors@0.115.0` |
| q-0008 | exact_identifier | What does the max_age option of CORSMiddleware control, and what is its default? | `pydantic/concepts/fields@v2.14.2`, `starlette/requests@1.10.0`, `fastapi/tutorial/query-params-str-validations@0.115.0` |
| q-0009 | factual | Which parts of a URL together define its origin for CORS purposes? | `fastapi/how-to/custom-docs-ui-assets@0.162.0`, `fastapi/tutorial/cors@0.162.0`, `starlette/middleware@1.10.0` |
| q-0015 | exact_identifier | What does the Pydantic validation error type int_parsing mean? | `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/models@v2.14.2`, `pydantic/errors/errors@v2.14.2` |
| q-0016 | exact_identifier | When does Pydantic raise an extra_forbidden validation error? | `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/models@v2.14.2` |
| q-0022 | exact_identifier | How do you start several worker processes with the fastapi or uvicorn command? | `fastapi/tutorial/extra-data-types@0.115.0`, `fastapi/tutorial/extra-data-types@0.115.0`, `fastapi/tutorial/extra-data-types@0.162.0` |
| q-0023 | factual | What caused the intermittent 502 errors in incident INC-0009? | `pydantic/errors/errors@v2.14.2`, `starlette/exceptions@1.10.0`, `pydantic/errors/errors@v2.14.2` |
| q-0024 | exact_identifier | Which Uvicorn flag caused the 503 responses during the marketing campaign in INC-0016? | `fastapi/advanced/custom-response@0.162.0`, `fastapi/advanced/additional-responses@0.115.0`, `fastapi/advanced/custom-response@0.115.0` |
| q-0025 | factual | How was the session logout problem in INC-0020 fixed? | `fastapi/advanced/advanced-dependencies@0.162.0`, `starlette/middleware@1.10.0`, `fastapi/tutorial/sql-databases@0.162.0` |
| q-0028 | exact_identifier | What happens if you create the FastAPI app with openapi_url=None? | `fastapi/how-to/conditional-openapi@0.162.0`, `fastapi/tutorial/body-nested-models@0.115.0`, `fastapi/how-to/conditional-openapi@0.115.0` |
| q-0031 | exact_identifier | Which Pydantic validation error type is reported when a required field is absent from the input? | `pydantic/errors/errors@v2.14.2`, `pydantic/concepts/unions@v2.14.2`, `pydantic/concepts/validators@v2.14.2` |
| q-0036 | paraphrase | Our item JSON comes back stuffed with default nulls the client never filled in. How do I return just the fields that were really provided? | `fastapi/tutorial/body-updates@0.115.0`, `fastapi/tutorial/body-updates@0.115.0`, `fastapi/tutorial/stream-json-lines@0.162.0` |
| q-0040 | paraphrase | How do I stop the app from publishing its interactive API explorer and machine-readable spec at all? | `fastapi/tutorial/stream-json-lines@0.162.0`, `fastapi/advanced/openapi-callbacks@0.115.0`, `fastapi/advanced/openapi-callbacks@0.162.0` |
| q-0042 | paraphrase | Our notification pods kept getting OOM-killed every few hours. What was actually going on, and was recycling processes the real fix? | `uvicorn/deployment/index@0.54.0`, `fastapi/tutorial/extra-data-types@0.115.0`, `fastapi/deployment/concepts@0.162.0` |
| q-0043 | paraphrase | Right after we switched the dashboard to cookie-based logins, the browser refused every call to the API. Why? | `fastapi/tutorial/cookie-param-models@0.162.0`, `starlette/responses@1.10.0`, `fastapi/tutorial/cookie-param-models@0.115.0` |
| q-0044 | paraphrase | A partner's webhook calls started bouncing as invalid as soon as we made our input checks stricter. What triggered it? | `pydantic/errors/errors@v2.14.2`, `pydantic/concepts/unions@v2.14.2`, `pydantic/concepts/unions@v2.14.2` |
| q-0045 | paraphrase | Once one handler began doing a price lookup, every route on the service became sluggish, not only that one. What explains it? | `fastapi/how-to/custom-request-and-route@0.162.0`, `fastapi/how-to/custom-request-and-route@0.115.0`, `starlette/routing@1.10.0` |
| q-0049 | paraphrase | If a client's JSON body leaves out an attribute my model insists on, what kind of complaint will Pydantic raise? | `fastapi/how-to/migrate-from-pydantic-v1-to-pydantic-v2@0.162.0`, `pydantic/concepts/models@v2.14.2`, `pydantic/concepts/json_schema@v2.14.2` |
| q-0053 | paraphrase | Should my Python web app itself hold the certificates and decrypt incoming secure traffic? | `fastapi/deployment/https@0.162.0`, `fastapi/deployment/https@0.115.0`, `fastapi/advanced/security/http-basic-auth@0.115.0` |
| q-0056 | paraphrase | If a client sends the text '123' for a field typed as a number, will Pydantic accept it? | `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/serialization@v2.14.2` |
| q-0059 | paraphrase | Customers couldn't send contracts above 1 MB, yet our application logs showed no failing requests at all. How? | `fastapi/tutorial/body@0.162.0`, `fastapi/tutorial/body@0.115.0`, `pydantic/concepts/validation_decorator@v2.14.2` |
| q-0063 | multi_passage | Why was the Swagger page blank once the gateway started stripping /api, and what does the documented fix do? | `fastapi/tutorial/extra-data-types@0.115.0`, `fastapi/tutorial/extra-data-types@0.115.0`, `fastapi/tutorial/extra-data-types@0.162.0` |
| q-0064 | multi_passage | For the 422 spike from mobile 7.3, which validation error type was raised, what does it mean, and how did the API start making these errors visible? | `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/unions@v2.14.2`, `pydantic/concepts/experimental@v2.14.2` |
| q-0072 | multi_passage | Why were admin users logged out after scaling to four workers, and what does Starlette say the session secret should be? | `fastapi/tutorial/sql-databases@0.115.0`, `fastapi/tutorial/sql-databases@0.115.0`, `fastapi/tutorial/sql-databases@0.115.0` |
| q-0083 | version_specific | What kind of attack is FastAPI 0.162.0's strict Content-Type checking meant to prevent? | `fastapi/advanced/strict-content-type@0.162.0`, `fastapi/advanced/advanced-dependencies@0.115.0`, `fastapi/advanced/strict-content-type@0.162.0` |
| q-0090 | version_specific | Starting with which FastAPI version can a group of query parameters be declared as a Pydantic model? | `fastapi/tutorial/query-param-models@0.162.0`, `fastapi/tutorial/query-param-models@0.162.0`, `fastapi/how-to/migrate-from-pydantic-v1-to-pydantic-v2@0.162.0` |
| q-0091 | version_specific | Since which FastAPI version can HTML form fields be declared with a Pydantic model? | `fastapi/tutorial/request-form-models@0.162.0`, `fastapi/tutorial/request-form-models@0.162.0`, `fastapi/tutorial/request-form-models@0.162.0` |
| q-0094 | version_specific | In FastAPI 0.162.0, how do you stream raw binary data such as a video from a path operation? | `fastapi/advanced/behind-a-proxy@0.162.0`, `fastapi/advanced/generate-clients@0.162.0`, `fastapi/tutorial/server-sent-events@0.162.0` |
| q-0102 | ambiguous | What does max_age default to? | `starlette/requests@1.10.0`, `pydantic/concepts/fields@v2.14.2`, `pydantic/concepts/fields@v2.14.2` |
| q-0128 | factual | In what order does Starlette's Config look for a configuration value? | `pydantic/concepts/json_schema@v2.14.2`, `starlette/config@1.10.0`, `pydantic/concepts/validators@v2.14.2` |
| q-0129 | factual | How do you read the real value held by a Starlette Secret? | `pydantic/concepts/json_schema@v2.14.2`, `pydantic/concepts/validators@v2.14.2`, `pydantic/concepts/unions@v2.14.2` |
| q-0140 | factual | With several Uvicorn workers, how many times does the application's lifespan startup run? | `uvicorn/concepts/lifespan@0.54.0`, `fastapi/deployment/server-workers@0.162.0`, `starlette/lifespan@1.10.0` |
| q-0141 | factual | Is a ContextVar set during lifespan startup visible inside request handlers when running under Uvicorn? | `fastapi/tutorial/handling-errors@0.162.0`, `fastapi/tutorial/handling-errors@0.115.0`, `fastapi/how-to/custom-request-and-route@0.162.0` |
