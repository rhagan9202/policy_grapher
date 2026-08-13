FROM python:3.14-slim

# Pinned deliberately, mirroring the Neo4j image (STORY-018): `latest` would make
# the build depend on when it was last pulled. 0.12.3 was the current uv release
# as of this pin.
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "policy_grapher.main:app", "--host", "0.0.0.0", "--port", "8000"]
