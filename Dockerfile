# One image for the API, the worker and migrations (task 013); compose picks the command.
# Build stage: resolve dependencies from uv.lock into /app/.venv (CPU-only torch, see
# pyproject.toml). Same Python base as the runtime stage, so the venv's paths stay valid.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies only, so code changes don't invalidate this (large) layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim-bookworm
# Models are downloaded into /models at first use; compose mounts a volume there so the
# api and worker share one download and the image stays free of model weights.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models
RUN useradd --create-home --uid 1000 app \
    && mkdir /models \
    && chown app:app /models
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
# Evaluation-run jobs (task 006b) read the corpus texts and the benchmark datasets.
COPY corpus ./corpus
COPY eval/datasets ./eval/datasets
COPY eval/configs ./eval/configs
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
