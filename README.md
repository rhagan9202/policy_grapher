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

Since sprint 5 every one of the API routes has a screen behind it, so the whole
product is reachable from the browser: ingest a corpus, read a document's text edition by
edition, build its derived layer, work the review queue, and empty the graph. `POST /query` is
the one deliberate exception — read-routed, timed and row-capped since
[ADR-009](docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md), and kept off the
navigation by [ADR-008](docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md).

## Setting up and running

Two commands. You need Docker with the Compose plugin, and nothing else — no Python, no Node,
no database. The lean stack below needs Compose 2.24 or newer: `docker-compose.lean.yml` uses
a `!override` YAML tag that earlier Compose can't parse, and the failure is an opaque YAML-tag
parse error, not a message that says what's wrong; the default stack below doesn't use the tag
and isn't affected. The second one is expensive on a cold cache: `docker compose up --build` brings
up the whole product, model server included, and that means roughly 13GB of pulls —
`ollama` at 8.43GB, `llama3.1:8b` at about 4.9GB — on top of two 16.6GB image builds, backend
and worker sharing a layer. Budget tens of minutes for the first build. A long silent wait
here is normal, not a hang
([ADR-028](docs/specs/adr/ADR-028-the-default-stack-carries-its-models.md),
[ADR-029](docs/specs/adr/ADR-029-the-default-image-carries-the-model-runtime.md)). A stack
without any of that cost is one command away — see [Running the lean
stack](#running-the-lean-stack) below.

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

> **If you already have an `.env` from before this change, read this first.** `init-env.sh`
> writes whatever `.env.example` held on the day it ran, and every default described here
> applies only to lines your `.env` does not have. An `.env` written before the models moved
> into the default stack says `EXTRACTOR_ADAPTER=null` and `EMBEDDER_ADAPTER=null` outright,
> and those lines win — so a rebuild writes chunks and nothing else, and Triage, Review and
> Ask's semantic leg stay empty exactly as before. What it does **not** turn off is `ollama`
> and `ollama-pull`: those are services, not variables, so they start anyway and still pull
> roughly 13GB for a model nothing will call. Either set both adapters to `local`, or delete
> `.env` and re-run `init-env.sh` for a fresh set of secrets, or — if what you wanted was the
> old model-free stack — use [the lean stack](#running-the-lean-stack), which stops those two
> services as well as setting the adapters.

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
3. **Triage**, **Review** and **Ask** stay empty until a derived layer exists — see [Filling
   Triage and Review](#filling-triage-and-review) below.

Seven services come up by default: `neo4j`, `redis`, `backend`, `worker`, `frontend`, and the
model server and its one-shot puller, `ollama` and `ollama-pull`. `EXTRACTOR_ADAPTER` and
`EMBEDDER_ADAPTER` both default to `local`, so a rebuild produces real obligations and
embeddings, not just chunks, without any further setup.

### Stopping it

```bash
docker compose down        # stop; the graph survives in a volume
docker compose down -v     # stop and wipe the graph
```

## Running the lean stack

A stack with none of the model cost above — no `ollama`, no pull, smaller images,
`EXTRACTOR_ADAPTER` and `EMBEDDER_ADAPTER` both back to `null` — is one command away:

```bash
docker compose -f docker-compose.yml -f docker-compose.lean.yml up --build
```

`--build` is not optional: `EXTRAS` is a build argument, and both stacks produce the same
image tags, so without it the previous stack's image is reused. This is the stack CI builds
and measures: `policy_grapher-backend` and `policy_grapher-worker` at **399MB** each, against
**16.6GB** for the default path
([ADR-021](docs/specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md),
[ADR-029](docs/specs/adr/ADR-029-the-default-image-carries-the-model-runtime.md)). With no
extraction model, a rebuild still runs and still writes chunks, but no obligations, so Triage
and Review stay empty; Ask still has its lexical and graph legs, but not its semantic one
([ADR-016](docs/specs/adr/ADR-016-embeddings-are-a-port.md)). Setting `EXTRACTOR_ADAPTER=local`
and/or `EMBEDDER_ADAPTER=local` back in `.env` and rebuilding with the default compose file
alone (no `-f docker-compose.lean.yml`) turns either back on.

## Filling Triage and Review

Ingest gives you a document, an edition and its text. Everything downstream — obligations,
proposed links, embeddings — is *derived*, and a **rebuild** is what produces it. Triage and
Review stay empty until one has run, and a rebuild only produces obligations when a real
extraction model is configured — true by default now; on the lean stack, do the setting above
first.

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

**Expect it to be slow.** With a real model a rebuild is one call per chunk: measured at ~91
seconds a chunk on CPU across sprint 6 and 7's runs, so a 37-chunk edition is around an hour. A *second* rebuild over unchanged
content calls the model zero times and finishes in under a minute — extraction is cached
([ADR-013](docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)).

A rebuild job is given eight hours, sized for the largest edition in `data/samples` — DoDM
8180.01 at 204 chunks, roughly six hours on CPU. Set `REBUILD_JOB_TIMEOUT_SECONDS` to lower it
if your host runs inference faster. Each individual model call is bounded separately by
`EXTRACTOR_TIMEOUT_SECONDS` (ten minutes), so a wedged Ollama still surfaces quickly rather
than sitting inside the eight-hour budget.

**Measured on 2026-08-27**, running the two editions of DoDD 5000.01 through the product from
the browser: **38 and 37 chunks**, **93 and 56 obligations**, **112 proposals**, and one
approved link. Triage then showed 149 changes and **one row** — the other 148 have no reviewed
link to anything of ours, so they stay off the ranked list. That is deliberate, and it reads as
a broken screen until you know it, which is why the screen says the number out loud.

**Expect roughly half of each document to yield nothing, and expect that to be right.** That run
rejected 20 of 37 chunks and 11 of 38, and dropped a further 85 and 16 individual statements.
Almost all of it is the model labelling something a duty that names none: section headings like
"e. Emphasize Competition." reported as SHALL, and preamble fragments. The schema requires a
statement to contain the modality it is labelled with, so those are refused — a rejected
statement costs itself and a rejected chunk costs its chunk, never the run
([ADR-030](docs/specs/adr/ADR-030-a-rejected-item-costs-itself-not-its-chunk.md),
[ADR-023](docs/specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)). The screen
reports both counts and why.

*The numbers above replace ones measured before that check existed. They were higher — 96 and
115 obligations, 265 proposals — and the difference is not a regression: it is the headings no
longer being counted as duties. A smaller honest number is worth more than a larger one nobody
can trust, and this project spent a sprint learning that the earlier figures described a defect.*

On the lean stack, where `EXTRACTOR_ADAPTER=null`, every step still works and writes chunks,
but no obligations, so Triage and Review stay empty. **The document's own page says so** — each
edition reports whether its derived layer was built, when, and with which extractor, so "no
obligations" is never left ambiguous between "nobody built this", "a `null` extractor built it",
and "a run died partway". The obligations themselves are listed there too, with the section and
page each was read from, which is the only way to judge from inside the app whether extraction
found what the document actually requires.

**Take a copy before you empty the graph.** `Reset` deletes every document, edition, chunk,
obligation, proposal and recorded decision, and the export button beside it writes the lot to a
JSON file first. It is a readable snapshot, not a restore: extraction is cached and a rebuild
reproduces it, but a reviewer's verdict about whether one clause implements another is the one
thing here nothing can regenerate.

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
