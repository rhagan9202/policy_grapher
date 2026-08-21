# Architecture

*Living document — edit in place. Last reviewed: 2026-08-20*

Describes the system as it is today, not as it's planned to be. Planned changes belong in
the [roadmap](../planning/roadmap.md); the reasoning behind past choices belongs in
[decision records](adr/).

## Overview

**DI-1 is complete.** A CSV of documents and their references is read by a FastAPI backend,
merged into a Neo4j graph, and served to a React UI as both a force-directed graph and a
searchable document table. Documents and reference edges can be created, edited and deleted
through the API, the graph can be emptied and reloaded, and raw Cypher can be run against
it. The full stack comes up with `./scripts/init-env.sh && docker compose up` and self-loads
the sample corpus on first run — two commands rather than one since secrets stopped being
committed ([ADR-010](adr/ADR-010-secrets-leave-the-repository.md)). See the
[README](../../README.md) for the quickstart.

```
CSV on disk  →  backend (FastAPI)  →  Neo4j  →  backend  →  frontend (React/Vite)
  /data/samples/  POST /ingest         bolt      GET /graph      force-graph
```

## Components

| Component | Responsibility |
| --- | --- |
| **Backend** (FastAPI, port 8000) | Serves every endpoint [SPEC-001](SPEC-001-di-1-policy-grapher.md) names: `POST /ingest` dispatches on file extension — a CSV manifest becomes many documents, a PDF issuance becomes one — and merges the result into Neo4j, `GET /graph` serves the render-capped corpus view, `GET`/`POST`/`DELETE` on `/documents` address documents by slug, `POST`/`DELETE` on `/documents/{slug}/references/{target_slug}` edit edges, `GET /documents/{slug}/versions` lists an instrument's editions oldest first with each one's `supersedes` link, `GET /documents/{slug}/chunks` serves the newest edition's section-aware text chunks unless `version_id` pins another edition, `GET /review/queue` lists proposed obligation links nobody has decided yet with both sides' citations, `POST /review/{source_id}/{target_id}` records a verdict as the authenticated principal and applies it, `GET /triage?to_version_id=` diffs an edition against the one it supersedes and ranks the clauses of ours that the changes reach, `POST /ask` answers a question from the corpus with citations or states that the corpus does not address it, `POST /reset` empties the graph and reports what it deleted, and `POST /query` executes read-only Cypher under a transaction timeout and a row cap. Auto-ingests the sample corpus at startup when the graph is empty (`AUTO_INGEST`, on by default). Mounts `./data` at `/data`, read-only. |
| **Neo4j** (`neo4j:2025.10`, ports 7474/7687) | Stores the graph. Auth enabled via environment variables in the generated `.env` — written by `./scripts/init-env.sh`, never committed ([ADR-010](adr/ADR-010-secrets-leave-the-repository.md)). Image pinned deliberately (STORY-018) — `latest` would make the database version depend on when it was last pulled. |
| **Frontend** (React + Vite, port 5173) | Two routes. `/` renders the force-directed graph from `GET /graph` via `react-force-graph`; clicking a node shows its name and whether it is a corpus or external document, and clicking a corpus document pulls in its external neighbours via `?expand={slug}`, while external nodes show detail only. `/documents` renders every document from `GET /documents` as a table — name, how many documents cite it, and outgoing references with slugs resolved to names from the same payload — filtered client-side by name as the user types. Vite dev server proxies `/api` to the backend. |

Typed fetch wrappers for the frontend-used endpoints live in `src/api/client.ts`.
`GET /documents/{slug}/versions` and `GET /documents/{slug}/chunks` are backend-only today,
until a corpus-management or review UI needs them. `request()` returns `undefined` on a `204`,
which the five body-less endpoints rely on.

Routes live in `routers/` — `admin.py` (`/health`, `/ingest`, `/reset`), `documents.py`
(document CRUD, reference edges, versions and chunks), `graph.py` (`/graph`, `/query`),
`review.py` (the obligation-link review queue), `triage.py` (`/triage`) and `ask.py` (`/ask`) — so `main.py` is
app assembly, CORS, and lifespan only. Routers reach the driver and settings through
`dependencies.py`, which resolves both from `request.app.state`; the lifespan is what puts
them there. Cypher lives beside the router that needs it: `graph.py`, `documents.py`, and
`query.py` at the package root.

Every route except `GET /health` also depends on `require_principal` from `auth.py`, which
matches the SHA-256 digest of an `Authorization: Bearer` token against the `name:sha256hex`
pairs in `API_TOKENS` and returns a `Principal`, or `401`. Comparison is constant-time and
scans every configured entry; an empty `API_TOKENS` admits nobody. `/health` stays open
because the container healthcheck calls it. See
[ADR-008](adr/ADR-008-authenticated-non-cypher-audience.md), superseding
[ADR-001](adr/ADR-001-demo-assumes-cypher-fluent-users.md).

That "every route except `GET /health`" is **enumerated from the application, not asserted from
a list**. `test_auth.py` walks the app's routers, subtracts a one-entry `OPEN_ROUTES` set, and
requires a `401` from each remaining route for an unauthenticated caller. It replaced a
hand-maintained list that had already drifted — `GET /documents/{slug}/versions` and
`GET /documents/{slug}/chunks` shipped without ever being added to it, so nothing checked that
either needed a token. A list covers the routes somebody remembered, and the forgotten one is by
definition the one nobody is thinking about. A second test asserts the walk found the routes at
all, because a walker returning nothing would leave the property test with no parameters and the
whole application unguarded without a red suite to show for it.

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
| `Source` | `id: str`, `kind: str`, `filename: str` | `id` unique |
| `DocumentVersion` | `version_id: str`, `effective_date: str \| null`, `checksum: str`, `source_uri: str`, `ingested_at: datetime` | `version_id` unique |
| `Authority` | `slug: str`, `name: str` | `slug` unique |
| `Entity` | `slug: str`, `name: str`, `kind: str` | `slug` unique |
| `Chunk` *(derived)* | `chunk_id: str`, `text: str`, `page: int`, `section_path: list[str]`, `ordinal: int`, `embedding: list[float] \| null`, `embedding_model: str \| null` | `chunk_id` unique; full-text index `chunk_text` on `text` |
| `Obligation` *(derived)* | `obligation_id: str`, `statement: str`, `modality: str`, `actor: str \| null`, `deadline: str \| null`, `conditions: str \| null`, `confidence: float`, `section_path: list[str]` | `obligation_id` unique |
| `ExtractionCache` *(derived)* | `key: str`, `payload_json: str` | `key` unique |
| `EmbeddingIndex` *(derived)* | `name: str`, `model_id: str`, `dimensions: int` | none; one node, the vector index's recorded provenance |
| `Change` *(derived)* | `change_id: str`, `kind: str`, `section_path: list[str]`, `statement: str`, `previous_statement: str \| null`, `modality: str`, `summary: str` | `change_id` unique |
| `LinkDecision` *(canonical)* | `key: str`, `source_obligation_id: str`, `target_obligation_id: str`, `verdict: str`, `actor: str`, `rationale: str`, `at: datetime` | `key` unique |

| Type | Direction | Meaning |
| --- | --- | --- |
| `REFERENCES` | `(:Document)-[:REFERENCES]->(:Document)` | Document cites another document |
| `DESCRIBES` | `(:Source)-[:DESCRIBES]->(:Document)` | An ingest recorded this document first-hand |
| `HAS_VERSION` | `(:Document)-[:HAS_VERSION]->(:DocumentVersion)` | One edition of the instrument |
| `SUPERSEDES` | `(:DocumentVersion)-[:SUPERSEDES]->(:DocumentVersion)` | The newer edition replaces the older |
| `ISSUED_BY` | `(:DocumentVersion)-[:ISSUED_BY]->(:Authority)` | Who issued that edition |
| `HAS_CHUNK` | `(:DocumentVersion)-[:HAS_CHUNK]->(:Chunk)` | A passage of that edition's text |
| `MANDATES` | `(:DocumentVersion)-[:MANDATES]->(:Obligation)` | A duty that edition places on someone |
| `ANCHORED_IN` | `(:Obligation)-[:ANCHORED_IN]->(:Chunk)` | The passage the duty was read from |
| `IMPLEMENTS_PROPOSED` *(derived)* | `(:Obligation)-[:IMPLEMENTS_PROPOSED]->(:Obligation)` | A machine guess, carrying `confidence`, `rationale`, `proposer`. Never traversed by triage |
| `IMPLEMENTS` *(derived)* | `(:Obligation)-[:IMPLEMENTS]->(:Obligation)` | A human approved the link. Written **only** by `links.decisions.replay_decisions` |
| `FROM_VERSION` *(derived)* | `(:Change)-[:FROM_VERSION]->(:DocumentVersion)` | The earlier edition of the pair diffed |
| `TO_VERSION` *(derived)* | `(:Change)-[:TO_VERSION]->(:DocumentVersion)` | The later edition of the pair diffed |
| `AFFECTS` *(derived)* | `(:Change)-[:AFFECTS]->(:Obligation)` | The obligation the change is about — the new one for `MODIFIED`/`ADDED`, the old one for `REMOVED` |

Nodes and relationships are created with `MERGE`, making ingestion idempotent — re-running
`/ingest` on the same file creates nothing new. Self-loops are never created.

**Retrieval fuses three signals; answers select from templates.** `retrieval/hybrid.py` runs a
vector leg (Neo4j's native index, over embeddings from a port whose model identity the index
records), a full-text leg for exact designators, and a graph leg that follows human-approved
`IMPLEMENTS` edges to passages sharing no vocabulary with the question — fused by reciprocal
rank. `POST /ask` picks from a fixed set of parameterised queries in `retrieval/templates.py`
and composes its answer out of the retrieved quotations; it never authors Cypher and never
returns an uncited claim. See [ADR-016](adr/ADR-016-embeddings-are-a-port.md) and
[ADR-017](adr/ADR-017-answers-select-templates.md).

**A change is a change to an obligation, not to a document or a byte.** `changes/diff.py`
compares two editions clause by clause, matching on `(section_path, normalize(statement))` —
the version-independent part of an obligation's identity, since `obligation_id` hashes the
edition and so can never match across one. `changes/propagate.py` then walks `IMPLEMENTS` from
each change to the clauses of ours that answer for it, ranking by named weight tables rather
than by anything learned. See
[ADR-015](adr/ADR-015-changes-are-detected-and-ranked.md).

**A proposal and an approval are separate edge types, not one edge with a status.** The triage
traversal names `IMPLEMENTS` and therefore cannot see an unreviewed `IMPLEMENTS_PROPOSED` — the
mistake is unwriteable rather than merely discouraged. `:LinkDecision` is canonical precisely
because the edges are not: a rebuild drops both edge types and replays the decisions back onto
freshly proposed links, matching on a key derived from the two obligation ids. See
[ADR-014](adr/ADR-014-proposals-and-decisions-are-different-things.md).

**The labels marked *derived* are droppable and rebuildable; the rest are canonical.** A
canonical node records something an ingest read directly off a source. A derived one exists
because an algorithm — the chunker, or an extraction model — decided it should, so a better
algorithm landing later must be able to replace the whole layer without anyone treating the old
nodes as facts being revised. Both carry a content- or structure-derived identity so a rebuild
reproduces the same ids and anything anchored to them survives, and both are dropped before
being rewritten inside the same transaction as the rest of the ingest. See
[ADR-012](adr/ADR-012-chunks-follow-sections.md) and
[ADR-013](adr/ADR-013-extraction-is-a-port-with-a-ratchet.md).

**A `Document` is the instrument; a `DocumentVersion` is one edition of it.** A single-PDF
ingest records one edition (`versions.py`); the manifest path records none, since a CSV row
states no text, date or checksum. A version's id is `slug@discriminator` — the effective date
the cover page states, or a checksum prefix when it states none — so re-ingesting the same
file resolves to the edition it already made rather than duplicating it. A cover typically
states several dates, so only a *labelled* one counts (`Effective: …`, `Incorporating Change
N, …`) and the latest of those wins: the file on disk is whatever its last change made it,
and an unlabelled date is usually a cited predecessor's, not this edition's. Two files claiming
one date under different checksums raise `VersionConflictError` instead of overwriting, which
`POST /ingest` returns as a `409` carrying both checksums — the operator, not the graph, decides
whether that is a better scan or a genuine reissue.
`SUPERSEDES` is derived from the editions' dates and rebuilt from scratch on every ingest of
that instrument — the one place ingest is not purely additive, safe only because no human
judgement lives on those edges. Editions with no date sort as oldest, which is a real
limitation rather than a detail. See
[ADR-011](adr/ADR-011-instruments-have-versions.md).

`Authority` and `Entity` exist as constrained labels with additive merge helpers, but no
ingest path writes them yet — nothing today creates an `ISSUED_BY` edge outside the tests.

**The corpus is mostly external.** Ingesting the 23-row sample CSV produces **438 `Document`
nodes**: 415 of them are documents cited by the corpus but absent from it — public laws,
MIL-STDs, CFR titles, DHS and Joint Chiefs memoranda.
`MATCH (d:Document) WHERE NOT d:External` is the corpus-only query. `GET /graph` returns the
corpus view by default; see
[ADR-002](adr/ADR-002-external-references-and-corpus-first-graph.md).

**A document is `:External` when no `Source` describes it.** Every ingest — a CSV manifest, a
PDF issuance, or a document created through the API — records itself as a `Source` node and a
`DESCRIBES` edge to each document it describes first-hand; a name that is only cited, never
described, gets no edge. `:External` is a materialised view of that one rule, recomputed by
every write path for the documents it touched rather than set according to each path's own
opinion. See [ADR-007](adr/ADR-007-sources-describe-documents.md).

**Ingest is uniformly additive.** A document dropped from a later manifest keeps the
`DESCRIBES` edge an earlier ingest gave it and stays non-external — no ingest can un-describe
a document. `POST /reset` is the explicit way to make the graph match a changed file.

**Documents are addressed by `slug`, not name**, because names contain slashes and commas
that break URL paths. At ingest a slug is a deterministic function of the full set of names
being ingested together — the collision suffix goes to every contender for a contested base
slug, not just the second arrival — so slugs survive both a reset-and-reingest cycle and a
change in row order unchanged. See [ADR-003](adr/ADR-003-slug-identifiers.md), as amended by
[ADR-005](adr/ADR-005-slug-assignment-over-the-name-set.md).

That guarantee holds only within a single ingest: `assign_slugs` resolves collisions over
the names it is given and knows nothing of slugs a prior ingest committed. Two consequences,
both deliberate:

- **A slug already stored is never reassigned.** `reconcile_slugs` reads the graph before a
  manifest ingest writes: a name that already exists keeps the slug it holds, and only
  genuinely new names go through `assign_slugs` — with any whose base slug a stored document
  already holds taking the hash suffix instead. Without that, a corpus name a PDF ingest had
  placed at a bare slug would be re-slugged over the whole name set, attempting a second node
  under an already-taken `name`, hitting `document_name_unique`, and rolling the whole ingest
  back — all three statements run in one write transaction — permanently, until a reset. On an
  empty graph, the ordinary path, reconciliation is a no-op and slugs are `assign_slugs`'s
  alone.
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
- **Python packages** — FastAPI, Pydantic v2, `neo4j` driver, `pypdf` (PDF text extraction), pytest, httpx, managed by `uv`.
- **npm packages** — React, Vite, TypeScript, vitest, `react-force-graph`, `react-router-dom`.
- No external network services, APIs, or model providers. The system is self-contained.

## Deployment

Docker Compose with three services: `neo4j`, `backend`, `frontend`. Configuration reaches
the backend through `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`,
`GRAPH_RENDER_CAP`, `QUERY_ROW_CAP`, `QUERY_TIMEOUT_SECONDS`, `API_TOKENS`,
`CORS_ALLOW_ORIGINS`, `ENABLE_API_DOCS`, `SAMPLE_CSV`, and `AUTO_INGEST`; the `frontend`
service additionally takes `API_TOKEN`, the plaintext half of the same token, which only the
vite dev proxy reads. All of them come from the generated `.env` — `./scripts/init-env.sh`
writes it and it is not committed ([ADR-010](adr/ADR-010-secrets-leave-the-repository.md)).
CORS allows only the origins `CORS_ALLOW_ORIGINS` lists — `http://localhost:5173`, the Vite
dev server, by default — without credentials, since the credential is an `Authorization`
header rather than a cookie. `ENABLE_API_DOCS` is `false` by default, so `/openapi.json`,
`/docs` and `/redoc` are not published: they carry no authentication of their own.
`backend` waits on Neo4j's HTTP healthcheck before starting. `./data` is bind-mounted into `backend` read-only with an
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

- **`POST /documents` is not atomic, and its failure mode is silent.** Both ingest paths
  commit their writes in one `session.execute_write`; `create_document` runs four separate
  auto-commit statements instead. A crash between the first and the last leaves a document
  with no provenance and no `:External` label — a state nothing re-refreshes — and the next
  manifest citing that name demotes it, so it vanishes from the default graph view with no
  error anywhere. STORY-038.

- **Anything on this machine that reaches port 5173 acts as the dev principal, reads and
  writes alike.** The vite dev proxy adds `Authorization: Bearer $API_TOKEN` to requests
  carrying `x-policy-grapher-ui: 1`, so a caller needs no credential of its own — the port
  *is* the credential. Writes are forwarded deliberately (ADR-018): a review queue has to
  POST verdicts. The header keeps a *browser* out, since a cross-origin page cannot set a
  custom header without a preflight that `mode: 'no-cors'` forbids; it does not keep a local
  process out, and `curl -H 'x-policy-grapher-ui: 1' -X POST localhost:5173/api/reset` still
  wipes the graph. The only bound on that is the published port being `127.0.0.1`. This is a
  development affordance and it is the piece a real login flow replaces first.

- **A bearer token is all or nothing.** Authentication answers *whether* a caller is known,
  not *what* it may do: every valid token drives every route, and the `Principal` a route
  receives is not read, logged, or used to scope results. `POST /query` is bounded in what it
  can do — read routing, a transaction timeout and a row cap
  ([ADR-009](adr/ADR-009-query-is-read-only-and-bounded.md), superseding
  [ADR-004](adr/ADR-004-unrestricted-cypher-in-di-1.md)) — and now in who may call it
  ([ADR-008](adr/ADR-008-authenticated-non-cypher-audience.md)), but one leaked token still
  reads the whole graph and there is no attribution afterward. The endpoint is also the
  demo's entire query interface
  ([ADR-001](adr/ADR-001-demo-assumes-cypher-fluent-users.md)) and the eventual target of
  LLM-constructed queries, so its contract outlives the assumption that a trusted human is
  typing into it.
- **Secrets are generated locally, not committed.** `scripts/init-env.sh` writes a fresh
  Neo4j password and API token into an untracked `.env`; nothing in the repository grants
  access to anything. The previously committed password remains in git history and is
  treated as compromised — harmless, since it protected only a local development database.
  The vite dev proxy (`frontend/vite.config.ts`) injects the generated token server-side, so
  a clean `./scripts/init-env.sh && docker compose up` loads the UI rather than erroring on
  every view. An existing stack needs `docker compose down -v` first: `NEO4J_AUTH` sets the
  Neo4j password when the data volume is created and never re-keys an existing one. See
  [ADR-010](adr/ADR-010-secrets-leave-the-repository.md).
- **Graph size grows with citation breadth, not corpus size.** One 23-row CSV yields 438
  nodes. The 300-node figure is a configurable render cap (`GRAPH_RENDER_CAP`), not a
  storage limit, so this is bounded rather than dangerous — but it means corpus size is a
  poor predictor of graph size, and capacity planning that assumes otherwise will be wrong.
- **`ast.literal_eval` on the `References` column.** Safer than `eval`, but it still means
  the ingest path is coupled to a Python-repr-shaped CSV field. A file exported from a
  different tool won't parse.
- **No pagination anywhere**, by design. `GET /graph` is bounded by the render cap instead,
  and reports `truncated` so a partial view is never presented as the whole graph.
  `POST /query` is bounded by its own row cap (`QUERY_ROW_CAP`) and reports `truncated` the
  same way. `GET /documents` is the one that stays unbounded — it returns all 438 documents
  on every call. At DI-1's corpus size that is fine, and it will stop being fine well before
  the corpus reaches its MVP target. The
  document table compounds it by rendering every row and filtering in the browser.
- **The schema is mid-migration.** DI-2's phase 1 added editions (`DocumentVersion`) and the
  `Authority`/`Entity` labels the Policy Concierge capabilities in the
  [vision](../planning/vision.md) will hang off, but the substance those capabilities need —
  policy points, applicable entities, enforcement ownership — is not modelled yet, and
  nothing populates the reference labels. Expect further schema change, not a settled model.
- **PDF extraction is partial by design.** The parser is deterministic and reports what it
  cannot attribute rather than guessing or dropping it — `references_unattributed` in the
  `POST /ingest` response is the record of what a document's references section contained
  but the extractor could not resolve to an identifier. Per-fixture match rates against the
  corpus CSV range from 75% to 100%; see
  [SPEC-001's Testing section](SPEC-001-di-1-policy-grapher.md#testing-gap-review) for the
  pinned floors.
- **Auto-ingest only runs at startup.** It checks once, in `lifespan`, whether the graph is
  empty — and "empty" means holding no `:Document` nodes, not no nodes at all. Provenance
  outlives what it describes, so a create-then-delete round trip leaves an orphan `:Source`
  behind; counting every node would let that invisible leftover read as content and skip the
  sample corpus. A graph emptied at runtime by `POST /reset` stays empty until the backend process
  restarts; nothing re-triggers the check. That is intentional rather than incidental —
  `test_reset_does_not_retrigger_auto_ingest` pins it — but it does mean the documented way
  to reload a changed file is reset, then ingest.
