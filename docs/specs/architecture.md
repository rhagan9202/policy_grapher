# Architecture

*Living document — edit in place. Last reviewed: 2026-08-13*

Describes the system as it is today, not as it's planned to be. Planned changes belong in
the [roadmap](../planning/roadmap.md); the reasoning behind past choices belongs in
[decision records](adr/).

## Overview

**DI-1's spine is built and running.** A CSV of documents and their references is read by a
FastAPI backend, merged into a Neo4j graph, and served to a React force-directed UI. The
full stack comes up with `docker compose up` and self-loads the sample corpus on first
run — see the [README](../../README.md) for the quickstart.

```
CSV on disk  →  backend (FastAPI)  →  Neo4j  →  backend  →  frontend (React/Vite)
  /data/          POST /ingest         bolt      GET /graph      force-graph
```

## Components

| Component | Responsibility |
| --- | --- |
| **Backend** (FastAPI, port 8000) | Parses the CSV, merges nodes and edges into Neo4j via `POST /ingest`, and serves the render-capped corpus view via `GET /graph`. Auto-ingests the sample corpus at startup when the graph is empty (`AUTO_INGEST`, on by default). Mounts `./data` at `/data`, read-only. Document CRUD, reference editing, `POST /reset`, and `POST /query` are specified in [SPEC-001](SPEC-001-di-1-policy-grapher.md) but not built in DI-1 — see the [backlog](../backlog/backlog.md). |
| **Neo4j** (`neo4j:2025.10`, ports 7474/7687) | Stores the graph. Auth enabled via environment variables in the committed `.env`. Image pinned deliberately (STORY-018) — `latest` would make the database version depend on when it was last pulled. |
| **Frontend** (React + Vite, port 5173) | One route: `/` renders the force-directed graph from `GET /graph` via `react-force-graph`. Clicking a node shows its name and reference role; clicking a corpus document pulls in its external neighbours via `?expand={slug}`, while external nodes show detail only. Vite dev server proxies `/api` to the backend. The `/documents` table route from SPEC-001 is not built. |

Typed fetch wrappers covering the three implemented endpoints (`/health`, `/graph`, `/ingest`)
live in `src/api/client.ts`.

## Data model

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
that break URL paths. A slug is a deterministic function of the full set of document names
being ingested together — including the collision suffix, which is now applied to every
contender for a contested base slug rather than only the second arrival — so slugs survive
both a reset-and-reingest cycle and a change in row order unchanged. See
[ADR-003](adr/ADR-003-slug-identifiers.md). That guarantee holds only within a single
ingest: `assign_slugs` resolves collisions over the names it's given and has no knowledge
of slugs a prior ingest already committed. Today, a later ingest whose name set newly
contests an existing bare slug does not re-suffix anything — it tries to create a second
node with an already-taken `name`, hits the `document_name_unique` constraint, and the
ingest rolls back atomically — all three statements run in one write transaction — and
cannot succeed until a reset lets the whole name set be re-slugged. Whether the incumbent
should keep its bare slug or be displaced is undecided; that rule is the amending ADR's job
before STORY-006 (document CRUD) lands.

`reference_role` is the CSV's `Type` column, renamed and stored verbatim: it describes a
document's position in the reference graph (`Root Reference`, `Sub-Reference`, and their
`(Shared)` variants), not what kind of document it is.

## External dependencies

- **Neo4j** — pinned to `2025.10` (STORY-018), so the database version no longer depends on
  when the image was last pulled.
- **Python packages** — FastAPI, Pydantic v2, `neo4j` driver, pytest, httpx, managed by `uv`.
- **npm packages** — React, Vite, TypeScript, vitest, `react-force-graph`, `react-router-dom`.
- No external network services, APIs, or model providers. The system is self-contained.

## Deployment

Docker Compose with three services: `neo4j`, `backend`, `frontend`. Configuration reaches
the backend through `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`,
`GRAPH_RENDER_CAP`, `SAMPLE_CSV`, and `AUTO_INGEST`, all supplied by the committed `.env`.
CORS allows all origins; there is no authentication. `backend` waits on Neo4j's HTTP
healthcheck before starting. `./data` is bind-mounted into `backend` read-only with an
SELinux private label (`:Z`) since only one container consumes it; `./frontend/src` is
bind-mounted into `frontend` with the shared label (`:z`) instead, because tooling
containers (`docker compose run`/`build`, ad-hoc `docker run`) also read that path and a
private label lets one steal exclusive access from the other.

> **Assumption:** Local developer machines are the only deployment target for DI-1. Nothing
> in the source material mentions a hosted environment or CI. Confirm before anyone builds
> a pipeline against it.

## Known weak points

Where the current design will strain, and roughly when. Writing these down early is what
turns a surprise outage into a planned piece of work.

- **`POST /query` is specified in SPEC-001 (STORY-008) but not built in DI-1.** When it
  lands it will execute arbitrary Cypher with no authentication, no read-only enforcement,
  no timeout, no row cap, and open CORS — any page in any browser that can reach the
  backend will then be able to drop the database. That's a deliberate, bounded risk
  acceptance made ahead of the endpoint existing —
  [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md) records the conditions that will
  make it defensible (local-only, disposable data, trusted audience), and it must not reach
  a shared environment in this form. The endpoint is also planned as the demo's entire query
  interface ([ADR-001](adr/ADR-001-demo-assumes-cypher-fluent-users.md)) and the eventual
  target of LLM-constructed queries, so its contract outlives the assumption that a trusted
  human is typing into it.
- **The committed `.env` makes the Neo4j password public by construction.** Accepted so a
  clean clone runs with one command. Same boundary as above: local-only.
- **Graph size grows with citation breadth, not corpus size.** One 23-row CSV yields 438
  nodes. The 300-node figure is a configurable render cap (`GRAPH_RENDER_CAP`), not a
  storage limit, so this is bounded rather than dangerous — but it means corpus size is a
  poor predictor of graph size, and capacity planning that assumes otherwise will be wrong.
- **`ast.literal_eval` on the `References` column.** Safer than `eval`, but it still means
  the ingest path is coupled to a Python-repr-shaped CSV field. A file exported from a
  different tool won't parse.
- **No pagination anywhere**, by design. `GET /graph` — the only read endpoint DI-1
  builds — is bounded by the render cap instead, and reports `truncated` so a partial view
  is never presented as the whole graph. `GET /documents` and `POST /query` are specified
  but not built; both are planned unbounded when they arrive. At DI-1's corpus size that
  would be fine, and it will stop being fine well before the corpus reaches its MVP target.
- **One node label, one relationship type.** The Policy Concierge capabilities in the
  [vision](../planning/vision.md) — policy points, applicable entities, enforcement
  ownership — don't fit this schema. Expect a migration, not an extension.
- **Auto-ingest only runs at startup.** It checks once, in `lifespan`, whether the graph is
  empty. A graph emptied at runtime — the only mechanism specified for that is the
  not-yet-built `POST /reset` — stays empty until the backend process restarts; nothing
  re-triggers the check.
