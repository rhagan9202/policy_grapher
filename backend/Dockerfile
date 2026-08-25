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

# Empty by default, and that default is now the *lean* path rather than the usual
# one. STORY-052 took this image from 16.6GB to 399MB by moving `local-embeddings`
# — torch and friends — out of the image, because the then-default
# EMBEDDER_ADAPTER=null never loaded it (ADR-021). ADR-029 supersedes that: the
# default stack carries its models, so docker-compose.yml passes
# `--extra local-embeddings` and the image built by a plain `docker compose up`
# is the 16.6GB one again. What is left empty here is the Dockerfile's own
# fallback, which is what `docker-compose.lean.yml` relies on by passing EXTRAS="".
#
# So: do not "restore" a default here to match compose. Building this Dockerfile
# directly still gets the small image, and configuring EMBEDDER_ADAPTER=local
# without the extra still fails at startup with a message naming this flag, rather
# than mid-rebuild with a ModuleNotFoundError.
ARG EXTRAS=""

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${EXTRAS}

COPY src ./src
RUN uv sync --frozen --no-dev ${EXTRAS}

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "policy_grapher.main:app", "--host", "0.0.0.0", "--port", "8000"]
