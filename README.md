# Policy Grapher

Feasibility demo and MVP for **Policy Concierge**: a knowledge graph over policy documents
and the references that connect them.

Policy corpora are dense webs of cross-references, but that structure exists only in prose.
Policy Grapher ingests the documents, builds a Neo4j graph of how they relate, and exposes
it through a query API and a lightweight visual explorer.

## Status

**DI-1 complete** — 18 of 18 stories. `./scripts/init-env.sh && docker compose up` ingests
the sample corpus and serves it as a navigable graph at http://localhost:5173, with the full
438-document corpus listed and searchable at http://localhost:5173/documents. Every endpoint
SPEC-001 names is built: document CRUD, reference editing, `POST /reset`, and read-only
Cypher via `POST /query` — read-routed, timed and row-capped since
[ADR-009](docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md).

## Quickstart

```bash
./scripts/init-env.sh      # once — generates .env and prints your API token
docker compose up --build
```

Then open http://localhost:5173. The API is at http://localhost:8000, the Neo4j browser at
http://localhost:7474.

**Upgrading a stack that predates the generated `.env`?** Run `docker compose down -v` before
`init-env.sh`. `NEO4J_AUTH` sets the password when the data volume is *created* and never
re-keys an existing one, so a fresh password against an old `neo4j-data` volume leaves the
backend failing to connect in a restart loop. The volume holds nothing but the sample corpus,
which re-ingests from the CSV.

**Every route but `/health` requires a bearer token.** A request needs an `Authorization:
Bearer <token>` header whose SHA-256 digest matches one of the `name:sha256hex` pairs in
`API_TOKENS`. `scripts/init-env.sh` generates one token (principal `dev`) and writes its
digest to `API_TOKENS`, so a clean clone authenticates that one token and every other
request gets `401` — the failure mode is universal denial, not universal access. The
browser app authenticates too: the vite dev proxy injects the same token server-side, so
the UI works without exposing it to JavaScript. The proxy forwards every method, but injects the
token only for requests carrying `x-policy-grapher-ui: 1` — a header a cross-origin page
cannot set, so a drive-by `POST /api/reset` from another site gets no credential. A local
process can set it, so the real bound is that the port publishes on `127.0.0.1` only. See
[ADR-018](docs/specs/adr/ADR-018-the-dev-proxy-forwards-writes.md).
CORS is limited to the origins `CORS_ALLOW_ORIGINS` lists (`http://localhost:5173` by
default), without credentials — the credential here is a header, not a cookie.
`/openapi.json`, `/docs` and `/redoc` are not published unless `ENABLE_API_DOCS=true`, since
they authenticate nobody. See
[ADR-008](docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md).

**Secrets are generated locally, not committed.** `./scripts/init-env.sh` writes a fresh
Neo4j password and API token into an untracked `.env`; nothing in the repository grants
access to anything. See
[ADR-010](docs/specs/adr/ADR-010-secrets-leave-the-repository.md).

## Stack

Python ≥ 3.14 · FastAPI · Pydantic · Neo4j · uv · pytest — React · Vite · vitest — Docker

## Documentation

Everything about this project — why it exists, what's being built, and in what order —
lives in [`docs/`](docs/README.md).

| If you're asking... | Read |
| --- | --- |
| Why does this project exist? | [Vision](docs/planning/vision.md) |
| What are we building, and in what order? | [Roadmap](docs/planning/roadmap.md) |
| What work is queued up? | [Backlog](docs/backlog/backlog.md) |
| How is the system put together? | [Architecture](docs/specs/architecture.md) |
| What exactly does DI-1 require? | [SPEC-001](docs/specs/SPEC-001-di-1-policy-grapher.md) |
| What are we doing right now? | [Latest sprint](docs/sprints/sprint-02/review.md) |
| Where does this new document go? | [Conventions](docs/CONVENTIONS.md) |

## Repository layout

```
backend/   FastAPI service: CSV ingest into Neo4j, document CRUD, graph and Cypher endpoints
data/      sample corpus (DoD directives and their references)
docs/      planning, backlog, specs, sprints, artifacts
frontend/  React + Vite: force-directed graph explorer and document table
```
