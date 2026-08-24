# Policy Grapher

Feasibility demo and MVP for **Policy Concierge**: a knowledge graph over policy documents
and the references that connect them.

Policy corpora are dense webs of cross-references, but that structure exists only in prose.
Policy Grapher ingests the documents, builds a Neo4j graph of how they relate, and exposes
it through a query API and a lightweight visual explorer.

## Status

**DI-1 complete** — 18 of 18 stories. **DI-2 complete**: versioned editions, section-aware
chunking, obligation extraction behind a port, human-reviewed links, edition diffing and
hybrid retrieval are all built and tested — and, since
[STORY-048](docs/backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) landed in
sprint 4, all of it is reachable from the running application. `POST
/documents/{slug}/versions/{version_id}/rebuild` queues a rebuild of one edition's derived
layer — chunks, obligations, proposed links and embeddings — onto a Redis-backed RQ queue that
a `worker` service drains, and `GET /rebuilds/{run_id}` reports its progress chunk by chunk.
See [Building an edition's derived layer](#building-an-editions-derived-layer).

Since sprint 5 every one of the nineteen API routes has a screen behind it, so the whole
product is reachable from the browser: ingest a corpus, read a document's text edition by
edition, build its derived layer, work the review queue, and empty the graph. `POST /query` is
the one deliberate exception — read-routed, timed and row-capped since
[ADR-009](docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md), and kept off the
navigation by [ADR-008](docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md).

## Setting up and running

Two commands. You need Docker with the Compose plugin, and nothing else — no Python, no Node,
no database.

```bash
git clone https://github.com/rhagan9202/policy_grapher.git && cd policy_grapher
./scripts/init-env.sh      # once: writes .env with fresh secrets, prints your API token
docker compose up --build
```

`init-env.sh` generates a random Neo4j password and a random API token, writes both into an
untracked `.env`, and prints the token once — it is stored nowhere else, so save it if you plan
to call the API directly. It refuses to overwrite an existing `.env`; delete the file first if
you want new secrets. Nothing in the repository grants access to anything
([ADR-010](docs/specs/adr/ADR-010-secrets-leave-the-repository.md)).

Then open **http://localhost:5173**. The API is at http://localhost:8000 and the Neo4j browser
at http://localhost:7474.

**The app starts empty on purpose** ([ADR-019](docs/specs/adr/ADR-019-the-first-run-is-empty.md)).
Every screen says so rather than rendering a blank that reads as a failure, and links to the
Ingest screen. From there:

1. **Ingest** — `dod_policy_references_08122026.csv` builds the 438-document reference graph;
   `500001p_2020.pdf` adds one issuance with its text. Both ship in `data/samples/`, and the
   field takes a filename because the backend reads from its own container.
2. **Graph** and **Documents** — browse what you loaded. A document's name opens its detail
   page: its text, by edition, and the control that builds its derived layer.
3. **Triage**, **Review** and **Ask** stay empty until a derived layer exists, which needs a
   real extraction model — see below. Without one you get chunks and no obligations.

Four services come up by default (`neo4j`, `redis`, `backend`, `worker`, plus `frontend`).
The model server is **not** among them; it sits behind a compose profile because it is 8.4GB.

### Stopping it

```bash
docker compose down        # stop; the graph survives in a volume
docker compose down -v     # stop and wipe the graph
```

If you have used the model profile, `docker compose down` leaves `ollama` running — profiled
services are only stopped when their profile is named: `docker compose --profile models down`.

## Running a real extraction model

The default extractor is `null` — it produces no obligations, so Review and Triage stay empty
even after a rebuild. To extract for real, bring up the model profile:

```bash
docker compose --profile models up -d     # pulls ollama (8.4GB) + llama3.1:8b (4.9GB), once
```

Then set `EXTRACTOR_ADAPTER=local` in `.env` and restart the worker:

```bash
docker compose up -d --force-recreate worker
```

An `.env` generated before these settings existed will not have the line — `init-env.sh`
writes whatever `.env.example` holds at the time it runs. Add it, or delete `.env` and
re-run the script for a fresh set of keys and secrets.

Model weights are constrained to US-published models
([ADR-020](docs/specs/adr/ADR-020-model-weights-come-from-us-organisations.md)); the default is
Llama 3.1 8B. Neither the image nor the model is on the default startup path — a plain
`docker compose up` pulls neither.

## Running a real embedding model

Embeddings are separate from extraction and off by the same principle. `sentence-transformers`
is not in the backend image: it pulls torch, and carrying it took the image from 399MB to
**16.6GB** for a library the default `EMBEDDER_ADAPTER=null` never loads
([ADR-021](docs/specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md)). Turning it
on therefore takes a rebuild as well as a setting:

```bash
echo 'BACKEND_EXTRAS=--extra local-embeddings' >> .env   # adds ~16GB to backend and worker
docker compose up -d --build backend worker
```

Then set `EMBEDDER_ADAPTER=local` in `.env` and restart. If you set it without the rebuild the
container refuses to start and says so, naming this flag — the failure is deliberate, because
the library is imported lazily and would otherwise surface as a `ModuleNotFoundError` inside a
queued rebuild long after startup reported itself healthy.

## Filling Triage and Review

Ingest gives you a document, an edition and its text. Everything downstream — obligations,
proposed links, embeddings — is *derived*, and a **rebuild** is what produces it. Triage and
Review stay empty until one has run, and a rebuild only produces obligations when a real
extraction model is configured, so do the model profile above first.

**From the UI**, which is the shortest path and the one verified end to end on 2026-08-23 from
a wiped volume against `llama3.1:8b`:

1. **Ingest** both editions of an issuance — `500001p_2003.pdf` and `500001p_2020.pdf`.
2. Open **Documents → DoDD 5000.01**. Pick an edition, tick the other under *Propose links
   against*, and press **Build derived layer**. Progress reports chunk by chunk.
   Naming candidates is the only thing that produces proposals: nothing in the graph records
   which documents are higher-tier ([ADR-015](docs/specs/adr/ADR-015-changes-are-detected-and-ranked.md)),
   so you say so and the route does not guess.
3. Do the same for the other edition. Both sides need obligations before anything can be
   proposed between them.
4. **Review** shows the queue. Approve one — and that is what puts a row in **Triage**, because
   a change is only actionable once it reaches a clause something of yours implements.

**Expect it to be slow.** With a real model a rebuild is one call per chunk: measured at ~104
seconds a chunk on CPU, so 34 chunks is around an hour. A *second* rebuild over unchanged
content calls the model zero times and finishes in under a minute — extraction is cached
([ADR-013](docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)).

Measured on that run: **38 and 34 chunks**, **96 and 115 obligations**, **265 proposals**, and
2–3 chunks per run rejected by the schema — which costs those chunks and not the run
([ADR-023](docs/specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)); the screen
reports how many and why. Triage then showed 204 changes and **one row**: the other 203 have no
reviewed link to anything of ours, so they stay off the ranked list. That is deliberate, and it
reads as a broken screen until you know it — which is why the screen says the number out loud.

With the default `EXTRACTOR_ADAPTER=null` every step still works and writes chunks, but no
obligations, so Triage and Review stay empty.

### The same thing through the API

Every screen above is a route, and nothing about the UI is privileged. With `$TOKEN` set to the
API token `init-env.sh` printed:

```bash
TOKEN=$(grep -E '^API_TOKEN=' .env | cut -d= -f2)
H="Authorization: Bearer $TOKEN"

curl -sX POST localhost:8000/ingest -H "$H" -H 'Content-Type: application/json' \
     -d '{"filename": "500001p_2020.pdf"}'

# 202 with a run_id; the worker does the work. GET /documents/{slug}/versions
# gives you the version ids.
curl -sX POST "localhost:8000/documents/dodd-5000-01/versions/dodd-5000-01@2020-09-09/rebuild" \
     -H "$H" -H 'Content-Type: application/json' \
     -d '{"candidate_version_ids": ["dodd-5000-01@2018-08-31"]}'

# state goes queued → started → finished, with chunks_done/chunks_total moving
# while it runs, counts landing when it does, and `rejections` saying what the
# schema turned away.
curl -H "$H" localhost:8000/rebuilds/<run_id>

curl -H "$H" localhost:8000/review/queue
curl -sX POST "localhost:8000/review/<source_id>/<target_id>" -H "$H" \
     -H 'Content-Type: application/json' -d '{"verdict": "approve"}'

curl -H "$H" "localhost:8000/triage?to_version_id=dodd-5000-01@2020-09-09"
```

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
