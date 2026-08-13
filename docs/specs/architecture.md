# Architecture

*Living document — edit in place. Last reviewed: 2026-08-12*

Describes the system as it is today, not as it's planned to be. Planned changes belong in
the [roadmap](../planning/roadmap.md); the reasoning behind past choices belongs in
[decision records](adr/).

## Overview

**Nothing is implemented yet.** As of 2026-08-12 the repository contains a README, this
docs tree, and one sample corpus file — no application code, no `docker-compose.yml`, no
package manifests.

What follows is the *target* shape, taken from
[SPEC-001](SPEC-001-di-1-policy-grapher.md). Treat every statement below as a design
intent that has not yet met an implementation. Rewrite this document to describe what
actually exists as soon as it exists, and move anything that turns out to be aspirational
back into the roadmap.

The intended shape is a three-service pipeline: a CSV of documents and their references is
read by a FastAPI backend, merged into a Neo4j graph, and served to a React force-directed
UI.

```
CSV on disk  →  backend (FastAPI)  →  Neo4j  →  backend  →  frontend (React/Vite)
  /data/          POST /ingest         bolt      GET /graph      force-graph
```

## Components

*Target — not yet built.*

| Component | Responsibility |
| --- | --- |
| **Backend** (FastAPI, port 8000) | Parses the CSV, merges nodes and edges into Neo4j, exposes document CRUD, a `/graph` view for the UI, and a raw Cypher passthrough at `/query`. Mounts `./data` at `/data`. |
| **Neo4j** (`neo4j:latest`, ports 7474/7687) | Stores the graph. Auth enabled via environment variables. |
| **Frontend** (React + Vite, port 5173) | Two routes: `/` renders the force-directed graph from `GET /graph`; `/documents` renders a searchable table from `GET /documents`. Proxies `/api` to the backend. |

Typed fetch wrappers covering every endpoint are to live in `src/api/client.ts`.

## Data model

*Target — not yet built.*

| Label | Properties | Constraints |
| --- | --- | --- |
| `Document` | `slug: str`, `name: str`, `reference_role: str` | `slug` unique, `name` unique |
| `Document:External` | `slug: str`, `name: str` | same; no `reference_role` |

| Type | Direction | Meaning |
| --- | --- | --- |
| `REFERENCES` | `(:Document)-[:REFERENCES]->(:Document)` | Document cites another document |

Nodes and relationships are created with `MERGE`, making ingestion idempotent — re-running
`/ingest` on the same file creates nothing new. Self-loops are never created.

**The corpus is mostly external.** Ingesting the 23-row sample CSV produces **438 nodes**:
415 of them are documents cited by the corpus but absent from it — public laws, MIL-STDs,
CFR titles, DHS and Joint Chiefs memoranda. These carry an extra `:External` label and no
`reference_role`, so `MATCH (d:Document) WHERE NOT d:External` is the corpus-only query.
`GET /graph` returns the corpus view by default; see
[ADR-002](adr/ADR-002-external-references-and-corpus-first-graph.md).

**Documents are addressed by `slug`, not name**, because names contain slashes and commas
that break URL paths. Slugs are a deterministic function of the name — including the
collision suffix — so they survive a reset-and-reingest cycle unchanged. See
[ADR-003](adr/ADR-003-slug-identifiers.md).

`reference_role` is the CSV's `Type` column, renamed and stored verbatim: it describes a
document's position in the reference graph (`Root Reference`, `Sub-Reference`, and their
`(Shared)` variants), not what kind of document it is.

## External dependencies

- **Neo4j** — `latest` tag. Unpinned, so a container pull can change the database version
  underneath the project without a code change.
- **Python packages** — FastAPI, Pydantic v2, `neo4j` driver, pytest, httpx, managed by `uv`.
- **npm packages** — React, Vite, TypeScript, vitest, `react-force-graph`, `react-router-dom`.
- No external network services, APIs, or model providers. The system is self-contained.

## Deployment

*Target — not yet built.* Docker Compose with three services: `neo4j`, `backend`,
`frontend`. Configuration reaches the backend through `NEO4J_URI`, `NEO4J_USER`, and
`NEO4J_PASSWORD`. CORS allows all origins; there is no authentication.

> **Assumption:** Local developer machines are the only deployment target for DI-1. Nothing
> in the source material mentions a hosted environment or CI. Confirm before anyone builds
> a pipeline against it.

## Known weak points

Where the current design will strain, and roughly when. Writing these down early is what
turns a surprise outage into a planned piece of work.

- **`POST /query` executes arbitrary Cypher with no authentication, no read-only
  enforcement, no timeout, no row cap, and open CORS.** Any page in any browser that can
  reach the backend can drop the database. This is a deliberate, bounded risk acceptance —
  [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md) records the conditions that make it
  defensible (local-only, disposable data, trusted audience) and it must not reach a shared
  environment in this form. The endpoint is also the demo's entire query interface
  ([ADR-001](adr/ADR-001-demo-assumes-cypher-fluent-users.md)) and the eventual target of
  LLM-constructed queries, so its contract outlives the assumption that a trusted human is
  typing into it.
- **The committed `.env` makes the Neo4j password public by construction.** Accepted so a
  clean clone runs with one command. Same boundary as above: local-only.
- **Graph size grows with citation breadth, not corpus size.** One 23-row CSV yields 438
  nodes. The 300-node figure is a configurable render cap (`GRAPH_RENDER_CAP`), not a
  storage limit, so this is bounded rather than dangerous — but it means corpus size is a
  poor predictor of graph size, and capacity planning that assumes otherwise will be wrong.
- **`ast.literal_eval` on the `References` column.** Safer than `eval`, but it still means
  the ingest path is coupled to a Python-repr-shaped CSV field. A file exported from a
  different tool won't parse.
- **No pagination anywhere**, by design. `GET /graph` is bounded by the render cap instead,
  and reports `truncated` so a partial view is never presented as the whole graph.
  `GET /documents` and `POST /query` are unbounded — at DI-1's corpus size that's fine, and
  it stops being fine well before the corpus reaches its MVP target.
- **One node label, one relationship type.** The Policy Concierge capabilities in the
  [vision](../planning/vision.md) — policy points, applicable entities, enforcement
  ownership — don't fit this schema. Expect a migration, not an extension.
- **`neo4j:latest` is unpinned.** Reproducibility depends on whenever the image was last pulled.
