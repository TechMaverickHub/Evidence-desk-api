# INC-0001: 502 after deploy (synthetic)

## Symptoms

The load balancer returned 502 Bad Gateway for five minutes after a deploy.

## Root cause

Uvicorn workers were still starting while the health check already reported ready.
