# Architecture

*Living document — edit in place. Last reviewed: 2026-08-13*

Describes the system as it is today, not as it's planned to be. Planned changes belong in
the [roadmap](../planning/roadmap.md); the reasoning behind past choices belongs in
[decision records](adr/).

## Overview

**DI-1 is complete.** A CSV of documents and their references is read by a FastAPI backend,
merged into a Neo4j graph, and served to a React UI as both a force-directed graph and a
searchable document table. Documents and reference edges can be created, edited and deleted
through the API, the graph can be emptied and reloaded, and raw Cypher can be run against
it. The full stack comes up with `docker compose up` and self-loads the sample corpus on
first run — see the [README](../../README.md) for the quickstart.

```
CSV on disk  →  backend (FastAPI)  →  Neo4j  →  backend  →  frontend (React/Vite)
  /data/samples/  POST /ingest         bolt      GET /graph      force-graph
```

## Components

| Component | Responsibility |
| --- | --- |
| **Backend** (FastAPI, port 8000) | Serves every endpoint [SPEC-001](SPEC-001-di-1-policy-grapher.md) names: `POST /ingest` dispatches on file extension — a CSV manifest becomes many documents, a PDF issuance becomes one — and merges the result into Neo4j, `GET /graph` serves the render-capped corpus view, `GET`/`POST`/`DELETE` on `/documents` address documents by slug, `POST`/`DELETE` on `/documents/{slug}/references/{target_slug}` edit edges, `POST /reset` empties the graph and reports what it deleted, and `POST /query` executes raw Cypher. Auto-ingests the sample corpus at startup when the graph is empty (`AUTO_INGEST`, on by default). Mounts `./data` at `/data`, read-only. |
| **Neo4j** (`neo4j:2025.10`, ports 7474/7687) | Stores the graph. Auth enabled via environment variables in the committed `.env`. Image pinned deliberately (STORY-018) — `latest` would make the database version depend on when it was last pulled. |
| **Frontend** (React + Vite, port 5173) | Two routes. `/` renders the force-directed graph from `GET /graph` via `react-force-graph`; clicking a node shows its name and whether it is a corpus or external document, and clicking a corpus document pulls in its external neighbours via `?expand={slug}`, while external nodes show detail only. `/documents` renders every document from `GET /documents` as a table — name, how many documents cite it, and outgoing references with slugs resolved to names from the same payload — filtered client-side by name as the user types. Vite dev server proxies `/api` to the backend. |

Typed fetch wrappers covering every endpoint live in `src/api/client.ts`. `request()`
returns `undefined` on a `204`, which the five body-less endpoints rely on.

Routes live in `routers/` — `admin.py` (`/health`, `/ingest`, `/reset`), `documents.py`
(document CRUD and reference edges), and `graph.py` (`/graph`, `/query`) — so `main.py` is
app assembly, CORS, and lifespan only. Routers reach the driver and settings through
`dependencies.py`, which resolves both from `request.app.state`; the lifespan is what puts
them there. Cypher lives beside the router that needs it: `graph.py`, `documents.py`, and
`query.py` at the package root.

Ingestion sources live in `sources/`: `__init__.py` dispatches on file extension,
`manifest.py` reads a CSV into many documents, `document.py` holds the shared
`ExtractedDocument`/`ExtractionReport` types, and `pdf.py` runs the five deterministic stages
— format detection, section location, entry splitting, identifier extraction, and
normalisation — that turn one PDF issuance into a document and its candidate references. See
the [PDF extraction design](../superpowers/specs/2026-08-13-story-016-pdf-extraction-design.md)
for the reasoning behind each stage.

## Data model

| Label | Properties | Constraints |
| --- | --- | --- |
| `Document` | `slug: str`, `name: str` | `slug` unique, `name` unique |
| `Document:External` | `slug: str`, `name: str` | same, plus the `:External` label |

| Type | Direction | Meaning |
| --- | --- | --- |
| `REFERENCES` | `(:Document)-[:REFERENCES]->(:Document)` | Document cites another document |

Nodes and relationships are created with `MERGE`, making ingestion idempotent — re-running
`/ingest` on the same file creates nothing new. Self-loops are never created.

**The corpus is mostly external.** Ingesting the 23-row sample CSV produces **438 nodes**:
415 of them are documents cited by the corpus but absent from it — public laws, MIL-STDs,
CFR titles, DHS and Joint Chiefs memoranda. These carry an extra `:External` label, so
`MATCH (d:Document) WHERE NOT d:External` is the corpus-only query.
`GET /graph` returns the corpus view by default; see
[ADR-002](adr/ADR-002-external-references-and-corpus-first-graph.md).

**Documents are addressed by `slug`, not name**, because names contain slashes and commas
that break URL paths. At ingest a slug is a deterministic function of the full set of names
being ingested together — the collision suffix goes to every contender for a contested base
slug, not just the second arrival — so slugs survive both a reset-and-reingest cycle and a
change in row order unchanged. See [ADR-003](adr/ADR-003-slug-identifiers.md), as amended by
[ADR-005](adr/ADR-005-slug-assignment-over-the-name-set.md).

That guarantee holds only within a single ingest: `assign_slugs` resolves collisions over
the names it is given and knows nothing of slugs a prior ingest committed. Two consequences,
both deliberate:

- **A later ingest that newly contests an existing bare slug fails rather than re-slugging.**
  It attempts a second node with an already-taken `name`, hits `document_name_unique`, and
  the whole ingest rolls back — all three statements run in one write transaction — so it
  cannot succeed until a reset lets the entire name set be re-slugged.
- **`POST /documents` favours the incumbent.** `allocate_slug` gives the newcomer the hash
  suffix and leaves the existing document's bare slug untouched, so live URLs never move.
  Ingest-time and creation-time assignment can therefore disagree, and a reset-and-reingest
  may produce different slugs than incremental creation did. ADR-005 accepts that trade for
  URL stability.

A suffixed slug reaches **89 characters**, not the 80 ADR-003 states: the suffix is appended
after truncation and nothing enforces a ceiling.

A `Document` carries no property describing its standing among other documents. The CSV's
`Type` column is read at parse time and discarded:
[ADR-006](adr/ADR-006-relational-facts-live-on-typed-edges.md) established that a position
relative to other documents is a fact about edges, that no derivation reproduced the CSV's
four values, and that the stored label was already stale — edge editing shipped before it
did. "Root" and "shared" are queries over in-degree, computed where a caller needs them.

`REFERENCES` is therefore the first member of a relationship vocabulary rather than the whole
of it. Types are directed verb phrases in `SCREAMING_SNAKE_CASE`, read source → target.

Because a `Document` now has no mutable field — renaming is delete-and-recreate under
[ADR-003](adr/ADR-003-slug-identifiers.md) — there is no `PUT /documents/{slug}`.

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
SELinux private label (`:Z`) since only one container consumes it, and `DATA_DIR` points at
`/data/samples` inside it; `./frontend/src` is
bind-mounted into `frontend` with the shared label (`:z`) instead, because tooling
containers (`docker compose run`/`build`, ad-hoc `docker run`) also read that path and a
private label lets one steal exclusive access from the other.

> **Assumption:** Local developer machines are the only deployment target for DI-1. Nothing
> in the source material mentions a hosted environment or CI. Confirm before anyone builds
> a pipeline against it.

## Checks

There is no CI, so every check hangs off one command per side and nothing sits behind a
command someone has to remember.

| Side | Command | Runs |
| --- | --- | --- |
| Backend | `uv run pytest` | The suite, with ruff among it as `test_lint.py`. pytest collects alphabetically, so lint lands mid-run — after the first integration test has already started the Neo4j container. For a fast lint-only answer use `-m "not integration"`, which runs the Docker-free subset, lint included |
| Frontend | `npm test` | `eslint . --max-warnings=0`, then `tsc -b`, then vitest — in that order, each gating the next |

Ruff takes its default rule set with one exemption: `Depends()` and `Query()` in a parameter
default are FastAPI's idiom, not the mutable-default bug B008 catches. ESLint runs
typescript-eslint's recommended set plus `react-hooks` and `react-refresh`, over `.js` as
well as `.ts`/`.tsx` so the lint config lints itself.

`--max-warnings=0` is load-bearing: four rules in the resolved ESLint config are
warn-level — `exhaustive-deps` among them — and ESLint exits 0 on warnings, so without it
the rule most likely to catch a stale closure could never fail the build.

Lint is enforced as a test rather than offered as a command because a check behind its own
command stops being run — the lesson STORY-032 recorded when a type error reached a commit.
Both linters are dev-only: ruff never enters the backend image (`uv sync --no-dev`), and
ESLint reaches the frontend container only through an image rebuild, since `package.json`
and `eslint.config.js` are baked in rather than bind-mounted.

## Known weak points

Where the current design will strain, and roughly when. Writing these down early is what
turns a surprise outage into a planned piece of work.

- **`POST /query` executes arbitrary Cypher** with no authentication, no read-only
  enforcement, no timeout, no row cap, and open CORS — any page in any browser that can
  reach the backend can drop the database. That is a deliberate, bounded risk acceptance:
  [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md) records the conditions that make it
  defensible (local-only, disposable data, trusted audience), all three confirmed to hold
  when the endpoint shipped, and it must not reach a shared environment in this form. The
  endpoint is also the demo's entire query interface
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
  `GET /documents` and `POST /query` are unbounded: the first returns all 438 documents on
  every call, the second returns whatever the query produces. At DI-1's corpus size that is
  fine, and it will stop being fine well before the corpus reaches its MVP target. The
  document table compounds it by rendering every row and filtering in the browser.
- **One node label, one relationship type.** The Policy Concierge capabilities in the
  [vision](../planning/vision.md) — policy points, applicable entities, enforcement
  ownership — don't fit this schema. Expect a migration, not an extension.
- **PDF extraction is partial by design.** The parser is deterministic and reports what it
  cannot attribute rather than guessing or dropping it — `references_unattributed` in the
  `POST /ingest` response is the record of what a document's references section contained
  but the extractor could not resolve to an identifier. Per-fixture match rates against the
  corpus CSV range from 75% to 100%; see
  [SPEC-001's Testing section](SPEC-001-di-1-policy-grapher.md#testing-gap-review) for the
  pinned floors.
- **Auto-ingest only runs at startup.** It checks once, in `lifespan`, whether the graph is
  empty. A graph emptied at runtime by `POST /reset` stays empty until the backend process
  restarts; nothing re-triggers the check. That is intentional rather than incidental —
  `test_reset_does_not_retrigger_auto_ingest` pins it — but it does mean the documented way
  to reload a changed file is reset, then ingest.
