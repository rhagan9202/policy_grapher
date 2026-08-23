FROM python:3.14-slim

# Pinned deliberately, mirroring the Neo4j image (STORY-018): `latest` would make
# the build depend on when it was last pulled. 0.12.3 was the current uv release
# as of this pin.
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app

# UV_NO_SYNC is load-bearing, not tidiness. `uv run` syncs the project's default
# dependency groups before it runs anything, and `dev` is a default group — so a
# container built with `--no-dev` would re-add ruff, pytest and testcontainers to
# its writable layer on every start. Since STORY-052 that group also pulls the
# `local-embeddings` extra, which turns the same bug into a multi-gigabyte torch
# download at startup: a small image whose containers are not. Guarded by
# tests/test_image.py.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    PYTHONUNBUFFERED=1

# No extras by default, which is the whole of STORY-052: `local-embeddings` pulls
# torch and took this image from 399MB to 16.6GB, for a library the default
# EMBEDDER_ADAPTER=null never loads. An operator who wants a local embedder builds
# with `--build-arg EXTRAS="--extra local-embeddings"`, and compose reads that from
# BACKEND_EXTRAS. Configuring `local` without it fails at startup with a message
# naming this flag, rather than mid-rebuild with a ModuleNotFoundError. See ADR-021.
ARG EXTRAS=""

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${EXTRAS}

COPY src ./src
RUN uv sync --frozen --no-dev ${EXTRAS}

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "policy_grapher.main:app", "--host", "0.0.0.0", "--port", "8000"]
