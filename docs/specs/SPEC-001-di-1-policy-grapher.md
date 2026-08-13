# SPEC-001: DI-1 — Policy Grapher

*Living document — behavior changes here in the same pull request that changes the code.
Last reviewed: 2026-08-13*

Originated as `SPEC.md` at the repository root. Expanded 2026-08-12 with decisions from a
gap review against the sample corpus; sections marked **(gap review)** were added or changed
then. Rationale for the larger calls lives in [ADR-002](adr/ADR-002-external-references-and-corpus-first-graph.md),
[ADR-003](adr/ADR-003-slug-identifiers.md), and [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md).
Slug assignment was later amended by [ADR-005](adr/ADR-005-slug-assignment-over-the-name-set.md).

## Increment Scope
Development Increment 1 (DI-1): demonstrate end-to-end feasibility with a single structured
CSV input, Neo4j graph storage, a full CRUD API, and a React graph UI.

---

## Input

### CSV Format
- **Columns**: `Document Name`, `References`, `Type` (exactly these three, in this order)
- **References field**: a Python-style stringified list, e.g. `"['Policy A', 'Policy B']"` — parsed via `ast.literal_eval`
- **Source**: a bare **filename**, not a path. The backend joins it to `DATA_DIR`
  (`/data/samples`, mounted from `data/samples/`) and rejects
  anything that escapes that directory. **(gap review)**

### What the sample corpus actually contains **(gap review)**

`data/samples/dod_policy_references_08122026.csv`, measured:

| Measure | Count |
| --- | --- |
| Rows (corpus documents) | 23 |
| Distinct referenced names | 436 |
| Referenced names **not** in the corpus | 415 |
| Total `Document` nodes after merge | **438** |
| Documents referencing themselves | 4 |

Two consequences the original spec didn't account for: 95% of nodes are external, and a
single file exceeds the 300-node visualization figure — which is a **render cap**, not a
storage limit. Both are handled below.

### Ingest rules **(gap review)**

- **Self-references are skipped.** Four corpus documents cite themselves (`DoDI 4151.19`,
  `DoDD 5124.02`, `DoDD 5143.01`, `DoDD 5144.02`). No self-loop is created; the count is
  returned in the ingest response.
- **Near-duplicate names are flagged, never merged.** The corpus contains names that appear
  to denote one document, e.g. `National Security Presidential Directive (NSPD)-47/...` and
  `National Security Presidential Directive-47/...`. Since `name` is the unique key these
  become separate nodes. Ingest reports suspected duplicates; it does not resolve them.
  Entity resolution is out of DI-1 scope.
- **Ingest is additive.** `MERGE` creates and updates but never deletes. To make the graph
  match a changed file, reset first — see `POST /reset`.

---

## Graph Schema (Neo4j)

### Nodes

| Label | Properties | Constraints |
|---|---|---|
| `Document` | `slug: str`, `name: str` | `slug` unique, `name` unique |
| `Document:External` | `slug: str`, `name: str` | same, plus the `:External` label |

**(gap review)** Two changes from the original schema:

- **The CSV's `type` column is read but not stored.** Its four values — `Root Reference`,
  `Root Reference (Shared)`, `Sub-Reference`, `Sub-Reference (Shared)` — describe a
  document's position relative to other documents, which is a fact about edges.
  [ADR-006](adr/ADR-006-relational-facts-live-on-typed-edges.md) removed it from the graph:
  no derivation reproduces those four values, and the stored label went stale the moment
  edges became editable. "Root" and "shared" are now queries over in-degree.
- **Documents referenced but not in the corpus carry an additional `:External` label.**
  `MATCH (d:Document)` still returns everything;
  `MATCH (d:Document) WHERE NOT d:External` returns the 23 corpus documents.

### Slug generation **(gap review)**

Names contain slashes and commas (`United States Code, Title 10`, `National Security
Presidential Directive-47/Homeland Security Presidential Directive-16`), so `name` cannot go
in a URL path. Every node gets a `slug`:

1. Casefold; replace each run of non-alphanumeric characters with a single hyphen; trim
   leading and trailing hyphens; truncate to 80 characters.
2. On collision, append `-` plus the first 8 hex characters of the SHA-256 of the full name.

The hash suffix — rather than a counter — keeps slugs **deterministic and independent of
ingest order**, so re-ingesting the same corpus yields the same URLs.

**(ADR-005)** Which contender takes the suffix depends on the path. At ingest the whole name
set is slugged at once and *every* contender for a contested base is suffixed; at
`POST /documents` the incumbent keeps its bare slug and only the newcomer is suffixed. The
suffix is appended after truncation, so a slug can reach **89 characters**, not 80. See
[ADR-005](adr/ADR-005-slug-assignment-over-the-name-set.md).

### Relationships

| Type | Direction | Meaning |
|---|---|---|
| `REFERENCES` | `(:Document)-[:REFERENCES]->(:Document)` | Document cites another document |

- `MERGE` on `slug` for nodes and on the pair for relationships, so ingestion is idempotent.
- Self-loops are never created.

---

## Backend

### Stack
- Python ≥ 3.14, FastAPI, Pydantic v2, `neo4j` (official driver), `uv`, pytest, httpx
- `testcontainers` for integration tests **(gap review)**

### Environment Variables
| Variable | Description |
|---|---|
| `NEO4J_URI` | Bolt URI, e.g. `bolt://neo4j:7687` |
| `NEO4J_USER` | Default `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password |
| `NEO4J_DATABASE` | Database name. Default `neo4j` |
| `GRAPH_RENDER_CAP` | **(gap review)** Maximum nodes returned by `GET /graph`. Default `300` |
| `DATA_DIR` | Directory `POST /ingest` resolves filenames under. Default `/data/samples` |
| `SAMPLE_CSV` | Corpus file auto-ingest loads. Default `dod_policy_references_08122026.csv` |
| `AUTO_INGEST` | Whether an empty graph self-loads at startup. Default `true` |

`NEO4J_AUTH` also appears in `.env`; it configures the Neo4j container itself and is not
read by the backend.

**(gap review)** A `.env` file with a development default is **committed**, so a clean clone
runs with `docker compose up` and no manual step. The password is therefore public by
construction. This is acceptable only because DI-1 is local-only and unauthenticated; the
README must say so plainly, and it must change before any shared deployment.

### Startup behavior **(gap review)**
On boot the backend checks whether the graph is empty. If it is, it ingests the sample corpus
from `/data` automatically, so `docker compose up` → open the browser → see a graph. An empty
graph after an explicit `POST /reset` is still empty on the next request; auto-ingest runs at
startup only, never in response to a reset.

### API Endpoints

#### Admin
Served by `routers/admin.py`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe. Returns `{ "status": "ok" }`. Touches no database — it answers whether the API process is up, not whether Neo4j is reachable |
| `POST` | `/ingest` | Ingest a CSV. Body: `{ "filename": "dod_policy_references_08122026.csv" }`, resolved under `DATA_DIR`. Returns `{ nodes_created, relationships_created, self_references_skipped, suspected_duplicates }` |
| `POST` | `/reset` | **(gap review)** Delete every node and relationship. The explicit way to make the graph match a changed file, since ingest never removes |

#### Documents (CRUD)
Addressed by `slug`, never by raw name. **(gap review)**

| Method | Path | Description |
|---|---|---|
| `GET` | `/documents` | List all documents |
| `GET` | `/documents/{slug}` | Get one document with both `references` and `referenced_by` |
| `POST` | `/documents` | Create a document. Body: `DocumentIn`. Slug is generated, not supplied |
| `DELETE` | `/documents/{slug}` | Delete a document and all its relationships (`DETACH DELETE`) |

#### References **(gap review)**
The original spec had no way to create or remove an edge, leaving the graph's relationships
immutable after ingest.

| Method | Path | Description |
|---|---|---|
| `POST` | `/documents/{slug}/references/{target_slug}` | Create a `REFERENCES` edge. Idempotent. `400` if source and target are the same |
| `DELETE` | `/documents/{slug}/references/{target_slug}` | Remove the edge, leaving both nodes |

#### Graph & Query
| Method | Path | Description |
|---|---|---|
| `GET` | `/graph` | Return the graph for the UI. **(gap review)** `?include_external=false` (default) returns only the 23 corpus documents and edges among them; `?include_external=true` returns everything up to the render cap; `?expand={slug}` adds one document's external neighbors to the default view; `?limit=` overrides `GRAPH_RENDER_CAP` for one request |
| `POST` | `/query` | Execute a raw Cypher string. Body: `{ "cypher": "MATCH ..." }`. Returns a list of records. **No read-only enforcement, timeout, or row cap in DI-1** — see [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md) |

### Pydantic Models **(gap review — all changed)**
- `DocumentIn`: `name: str`
- `DocumentOut`: `slug: str`, `name: str`, `is_external: bool`, `references: list[str]`, `referenced_by: list[str]`
- `GraphNode`: `id: str` (slug), `label: str` (name), `is_external: bool`
- `GraphEdge`: `source: str` (slug), `target: str` (slug)
- `GraphOut`: `nodes: list[GraphNode]`, `edges: list[GraphEdge]`, `total_nodes: int`, `returned_nodes: int`, `truncated: bool`


`references` and `referenced_by` carry **slugs, not names** — the same identifiers the
reference endpoints and `GraphEdge` use, so a caller can follow one straight into
`GET /documents/{slug}` without a lookup. Resolving a slug to a display name is the
client's job, from the same payload.

### Render cap **(gap review)**

The MVP's 300-node figure is a **cap on what is drawn at once, not a limit on what is
stored**. The graph is expected to exceed it — one 23-row CSV already produces 438 nodes,
because node count tracks citation breadth rather than corpus size.

- Configured by `GRAPH_RENDER_CAP`, default `300`; overridable per request with `?limit=`.
- A cap of `0` means no cap, for deliberate large-graph testing.
- Applies to `GET /graph` only. `GET /documents`, `POST /query`, and ingest are unaffected —
  the cap is about legibility of the rendered view, not response size in general.

**Truncation is deterministic**, so the same request always returns the same subgraph:

1. Corpus documents (`WHERE NOT d:External`) are always included. There are 23; if the cap
   is ever set below that, corpus nodes still win and the cap is exceeded rather than
   dropping them — a view missing corpus documents would be actively misleading.
2. Remaining budget goes to external nodes by descending degree — the most-cited first,
   since those carry the most structural information.
3. Ties break on `slug`, ascending.
4. Edges are then filtered to those whose endpoints both survived.

`GraphOut` reports `total_nodes`, `returned_nodes`, and `truncated` so the UI can say
"showing 300 of 438" rather than silently presenting a partial graph as the whole one.
**Silent truncation is the failure mode to avoid**: a user who doesn't know the view is
partial will draw conclusions about a citation graph from missing edges.

### CORS
Allow all origins (no auth required for DI-1).

---

## Testing **(gap review)**

Integration tests run against a **throwaway Neo4j container** started per test session via
`testcontainers`. Mocking the driver would leave `MERGE` idempotency, the unique constraints,
and slug collision handling untested — which is most of what can go wrong.

This means **Docker is required to run the test suite**, including in any CI that gets built.

Minimum coverage for the Definition of Done:
- Ingesting the sample corpus twice produces identical counts the second time (0 created)
- Self-references produce no edges and a correct skip count
- Slug generation is stable across re-ingest, and collisions resolve deterministically
- `GET /graph` returns 23 nodes by default, and with `include_external=true` returns exactly
  `GRAPH_RENDER_CAP` nodes with `truncated=true` and `total_nodes=438`
- Truncation is deterministic: the same request twice returns the same node set, and every
  corpus document survives it

---

## Frontend

### Stack
- React, Vite, TypeScript, vitest, `react-force-graph` (2D), `react-router-dom`

### Pages / Views
| View | Route | Description |
|---|---|---|
| Graph Explorer | `/` | Force-directed graph from `GET /graph`. Defaults to the 23 corpus documents. Node click shows name and reference role, and expands that node's external neighbors via `?expand={slug}`. **(gap review)** |
| Document Table | `/documents` | Table of all documents from `GET /documents`. Client-side search/filter by name. Each row shows name, how many documents cite it (derived from `referenced_by`), and its outgoing references. |

### API Client
- Typed fetch wrappers in `src/api/client.ts` covering all backend endpoints.

---

## Deployment

### docker-compose Services
| Service | Image | Ports | Notes |
|---|---|---|---|
| `neo4j` | `neo4j:2025.10` | 7474, 7687 | Auth enabled via env vars from the committed `.env`. Pinned rather than `latest` so the database version is reproducible (STORY-018). |
| `backend` | Custom (uv-based) | 8000 | Mounts `./data:/data`; waits for Neo4j to be healthy before starting |
| `frontend` | Custom (Node/Vite) | 5173 | Proxies `/api` to backend for DI-1 |

---

## Out of DI-1 Scope
- PDF, DOCX, XLSX ingestion
- Authentication or authorisation
- RAG, LLM calls, vector embeddings
- Production multi-stage Docker builds
- Corpus management beyond the document table
- Pagination — the render cap bounds `GET /graph` instead

Added by the gap review:
- **Entity resolution** — near-duplicate names are flagged, not merged
- **Interpreting the CSV's `type` column** — read during parsing, never stored; see [ADR-006](adr/ADR-006-relational-facts-live-on-typed-edges.md)
- **Renaming documents** — delete and recreate instead
- **Query limits on `POST /query`** — deliberately deferred, see [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md)
