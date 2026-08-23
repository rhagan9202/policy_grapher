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

`./scripts/init-env.sh && docker compose up` serves the app at http://localhost:5173. **It
starts empty on purpose** ([ADR-019](docs/specs/adr/ADR-019-the-first-run-is-empty.md)): every
screen says so and names what to run. Load the sample corpus with
`POST /ingest` — `dod_policy_references_08122026.csv` for the 438-document reference graph,
or `500001p.pdf` for one issuance with its text. Every endpoint SPEC-001 names is built:
document CRUD, reference editing, `POST /reset`, and read-only Cypher via `POST /query` —
read-routed, timed and row-capped since
[ADR-009](docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md).

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

The derived layer — chunks, obligations, proposed links — is built by the application, not by
running Python. This is the sequence, verified end to end on 2026-08-22 from a wiped volume
against `llama3.1:8b`. Every step is a product action; nothing here touches Bolt directly.

```bash
TOKEN=$(grep -E '^API_TOKEN=' .env | cut -d= -f2)      # printed by init-env.sh
H="Authorization: Bearer $TOKEN"

# 1. Load the corpus, then two editions of one document
curl -X POST -H "$H" -H 'Content-Type: application/json' \
  -d '{"filename":"dod_policy_references_08122026.csv"}' localhost:8000/ingest
curl -X POST -H "$H" -H 'Content-Type: application/json' \
  -d '{"filename":"500001p_2003.pdf"}' localhost:8000/ingest
curl -X POST -H "$H" -H 'Content-Type: application/json' \
  -d '{"filename":"500001p_2020.pdf"}' localhost:8000/ingest

# 2. Build each edition's derived layer. Naming candidates is what produces proposals.
curl -X POST -H "$H" -H 'Content-Type: application/json' -d '{}' \
  "localhost:8000/documents/dodd-5000-01/versions/dodd-5000-01@2018-08-31/rebuild"
curl -X POST -H "$H" -H 'Content-Type: application/json' \
  -d '{"candidate_version_ids":["dodd-5000-01@2018-08-31"]}' \
  "localhost:8000/documents/dodd-5000-01/versions/dodd-5000-01@2020-09-09/rebuild"

# 3. Each returns a run_id. Poll it — with a real model this takes tens of minutes.
curl -H "$H" localhost:8000/rebuilds/<run_id>

# 4. Approve a proposal in Review. This is what puts a row in Triage: a change is
#    only actionable once it reaches a clause something of yours implements.
curl -H "$H" localhost:8000/review/queue
curl -X POST -H "$H" -H 'Content-Type: application/json' \
  -d '{"verdict":"approve"}' localhost:8000/review/<source_id>/<target_id>

curl -H "$H" "localhost:8000/triage?to_version_id=dodd-5000-01@2020-09-09"
```

Measured on that run: **38 and 34 chunks**, **120 and 121 obligations**, **313 proposals**, and
one chunk rejected by the schema — which costs that chunk and not the run
([ADR-023](docs/specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)). Triage
reports 234 changes; they stay *unlinked*, and therefore off the ranked list, until a proposal
is approved. That is deliberate — a change nothing of yours implements is not yet your problem.

With the default `EXTRACTOR_ADAPTER=null` every step still works and produces chunks, but no
obligations, so Triage and Review stay empty.

## Quickstart

```bash
./scripts/init-env.sh      # once — generates .env and prints your API token
docker compose up --build
```

Then open http://localhost:5173. The API is at http://localhost:8000, the Neo4j browser at
http://localhost:7474.

### Building an edition's derived layer

Ingest gives you a document, an edition and its text. Everything downstream — obligations,
proposed links, embeddings — is *derived*, and a rebuild is what produces it. The sequence,
with `$TOKEN` set to the API token `init-env.sh` printed:

```bash
# 1. Ingest two PDFs: the issuance to rebuild, and the higher-tier one it
#    implements. `GET /documents/{slug}/versions` gives you the version ids.
curl -sX POST localhost:8000/ingest -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"filename": "500001p_2020.pdf"}'
curl -sX POST localhost:8000/ingest -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"filename": "500088p.pdf"}'

# 2. Rebuild that edition's derived layer. 202 with a run_id; the worker does the work.
#    candidate_version_ids names the higher-tier editions to propose links against —
#    omit it and the rebuild produces no proposals (see below).
curl -sX POST "localhost:8000/documents/dodi-5000-88/versions/dodi-5000-88@2020-11-18/rebuild" \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"candidate_version_ids": ["dodd-5000-01@2020-09-09"]}'

# 3. Poll it. state goes queued → started → finished, with chunks_done/chunks_total
#    moving while it runs and counts landing when it does.
curl -s localhost:8000/rebuilds/<run_id> -H "Authorization: Bearer $TOKEN"
```

Then `GET /triage`, `GET /review/queue` and `POST /ask` have something to work with, and the
Triage, Review and Ask screens stop being empty.

**Two things worth knowing before you expect results.** The default `EXTRACTOR_ADAPTER=null`
extracts nothing, on purpose — it needs no model server, so the stack still comes up on one
command ([ADR-013](docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)). Set
`EXTRACTOR_ADAPTER=local` with an Ollama-compatible endpoint to get real obligations, and with
them real proposals. And **`candidate_version_ids` is required for proposals**: nothing in the
graph records which documents are higher-tier
([ADR-015](docs/specs/adr/ADR-015-changes-are-detected-and-ranked.md) drops tier distance for
that reason), so the caller names them and the route never guesses.

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
