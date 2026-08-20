# Policy Grapher

Feasibility demo and MVP for **Policy Concierge**: a knowledge graph over policy documents
and the references that connect them.

Policy corpora are dense webs of cross-references, but that structure exists only in prose.
Policy Grapher ingests the documents, builds a Neo4j graph of how they relate, and exposes
it through a query API and a lightweight visual explorer.

## Status

**DI-1 complete** — 18 of 18 stories. `docker compose up` ingests the sample corpus and
serves it as a navigable graph at http://localhost:5173, with the full 438-document corpus
listed and searchable at http://localhost:5173/documents. Every endpoint SPEC-001 names is
built: document CRUD, reference editing, `POST /reset`, and raw Cypher via `POST /query`.

## Quickstart

```bash
docker compose up --build
```

Then open http://localhost:5173. The API is at http://localhost:8000, the Neo4j browser at
http://localhost:7474.

**Every route but `/health` requires a bearer token.** A request needs an `Authorization:
Bearer <token>` header whose SHA-256 digest matches one of the `name:sha256hex` pairs in
`API_TOKENS`; `API_TOKENS` ships **empty** in the committed `.env`, so a clean clone
authenticates nobody and every route but `/health` answers `401` until an operator puts a
digest there — the failure mode is universal denial, not universal access. CORS is limited
to the origins `CORS_ALLOW_ORIGINS` lists (`http://localhost:5173` by default), with
credentials permitted. See
[ADR-008](docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md).

**The Neo4j password is still committed in `.env` and this stack is still local-only by
design.** Do not expose it on a shared network.

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
