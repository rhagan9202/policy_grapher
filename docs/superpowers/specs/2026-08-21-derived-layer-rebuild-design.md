# Derived-Layer Rebuild — Design

**Date:** 2026-08-21 · **Story:** [STORY-048](../../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) · **Sprint:** 4

## The problem

DI-2 built extraction, linking, diffing, embedding and retrieval, each with tests and an ADR.
An AST sweep of `src/` on 2026-08-21 found that four of the pieces have **no caller anywhere
in the application**: `rebuild_derived`, `embed_chunks`, `CachedExtractor` and
`GraphCacheStore`. `build_extractor` and `build_embedder` are called in `lifespan`, but only
to validate the configured name — both instances are put on `app.state` and never read.

So no obligation can exist, no embedding can exist, and Triage, Review and Ask are empty by
construction. The UI audit that found this could only exercise those screens by running Python
against the container's Neo4j. Every unit is correct in isolation and nothing composes them,
which is the specific kind of gap a green suite cannot see.

The missing piece is a caller. The reason it is a design rather than a one-line route is that
extraction with a real model is one call per chunk over ~38 chunks — minutes — so how the call
is made is the whole question.

## What was rejected, and why it matters

Sprint 3's planning produced two proposals and the project owner rejected both:

**A deterministic modal-verb extractor as the demo default**, so a cold start could produce
obligations with no model server. [ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)
had already considered a modal-verb rules engine as *the* extraction approach and rejected it
on measured evidence — 0.5 precision against its own gold fixture.

**A synchronous rebuild route with the timeout documented as a known limitation.** Fast under
`null`, minutes under `local`, wrong the moment a real model is configured — and the `null`
default makes that invisible in every test.

Both were the same move: ship something known to be wrong so the product presents better than
it is. [ADR-019](../../specs/adr/ADR-019-the-first-run-is-empty.md) records the principle. This
design exists because rejecting them left no cheap option.

## Decisions

### A real queue, on Redis

Considered: run state in a `:RebuildRun` Neo4j node behind a port, swapping to Redis when
concurrency demands it; run state in Postgres; run state in the browser.

Rejected — **client-side state is not a job store.** Zustand and similar hold state in a
browser tab. The server itself needs to know what is running, to refuse a duplicate rebuild of
the same edition; a second tab would see nothing; a `curl` caller would have no record at all.
Zustand remains a reasonable future choice for *UI* state, which is a different decision.

Rejected — **Postgres** is the right home for durable audit history, and that is a speculative
requirement rather than a present one. It would put a second source of truth into a project
that has deliberately had one, against [ADR-014](../../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md),
which put canonical human decisions in the graph precisely so they sit beside what they
describe.

Chosen — **Redis with a real queue, now.** The alternative was Neo4j-behind-a-port with Redis
as a documented upgrade path; the project owner chose to pay the infrastructure cost once
rather than migrate later. It buys queuing, retries, TTL cleanup and a natural home for
per-chunk progress immediately, and it is the shape the problem takes as soon as re-extracting
a whole corpus matters — 7 PDFs at ~40 chunks each, with model latency per chunk, is a worker
pool and not a request.

### RQ, not Celery or arq

**Celery is disqualified on this project's hard floor.** Python `>=3.14` is a stated
constraint, and Celery 5.6.3 declares support only to 3.13. RQ 2.11 and `redis` 8.1 both
declare 3.14.

**RQ over arq** because the work is synchronous throughout — the Neo4j driver is sync, `pypdf`
is sync, and `sentence-transformers` is sync and CPU-bound. RQ workers are processes running
sync functions, which is a direct fit. arq is asyncio-native and would need every one of those
calls pushed into an executor to avoid blocking its loop, which is machinery bought for
nothing.

### Progress is per chunk

The caller needs more than running/done/failed: a run takes minutes and someone is watching.
`rebuild_derived` gains **one optional `on_progress(done, total)` callback** — additive, not a
restructure of tested phase-4 code — and the job function passes one that increments RQ's
`job.meta`. One small Redis write per chunk, ~38 per edition.

### Validation happens before enqueueing

STORY-048 requires that a missing source document produce a 4xx naming the edition rather than
a 500. The route therefore checks synchronously, before any job exists:

| Condition | Response |
| --- | --- |
| No such `version_id` | `404`, naming it |
| `source_uri` does not resolve to a readable file | `409`, naming the file |
| A run for this edition is already queued or started | `409`, naming the existing `run_id` |
| Otherwise | `202` with `run_id` |

A dead job reporting "file not found" ten seconds later would satisfy the letter of that
criterion and not its intent.

## Architecture

```
POST /documents/{slug}/versions/{id}/rebuild
   │  validate synchronously (404 / 409)
   ▼
 RQ queue (Redis) ──────────► worker process (same backend image)
   │                              │
   │  202 {run_id}                ├─ pdf.extract_document(source_uri)
   ▼                              ├─ chunk_pages
GET /rebuilds/{run_id}            ├─ CachedExtractor.extract per chunk ──► on_progress ──► job.meta
   state, chunks_done/total,      ├─ embed_chunks
   counts, error                  └─ one execute_write: drop → write → propose → replay
```

**New modules.** `jobs/queue.py` builds the queue from settings and is the only place `redis`
is imported. `jobs/rebuild.py` holds the job function. `routers/rebuilds.py` holds both routes.

**New services.** `redis` (alpine, ~50MB) and `worker` — the same backend image running
`rq worker`, so whatever STORY-052 removes from that image benefits both. Both are **default**
services: "the stack comes up on one command" is a vision constraint, and a rebuild that needed
a second command to become possible would breach it. Ollama stays profile-gated at 8.43GB.

**The worker is configured exactly like the backend, and needs the same data mount.**
`rebuild_derived` re-reads the source PDF from the edition's `source_uri`, which ingest wrote
as `file:///data/samples/...` — a path *inside* a container. The worker therefore mounts
`./data` at `/data` read-only just as the backend does, and carries the same `NEO4J_*`,
`EXTRACTOR_*` and `EMBEDDER_*` variables. A worker without the mount would fail every job with
a file-not-found that the route's synchronous check had already passed, because that check runs
in the backend where the file *is* present. This is the sharpest edge in the design.

**Extraction is cached.** The job builds `CachedExtractor(build_extractor(settings),
GraphCacheStore(driver, database))`, which is what makes a second run over an unchanged edition
call the model zero times — and closes the dead-code half of STORY-050.

## Failure, restart and idempotency

**A dying worker cannot corrupt the graph.** Extraction runs outside the transaction and every
mutation lands in one `execute_write` (phase 4's shape, unchanged), so a worker killed
mid-extraction leaves the derived layer exactly as it was.

**A dying worker cannot leave a run "running" forever.** The job carries a 1800-second timeout;
RQ moves a timed-out job to the failed registry, and `GET /rebuilds/{run_id}` reports it as
failed rather than in progress.

**Re-running is safe and cheap.** Chunk and obligation ids are content- and structure-derived,
so a second run reproduces the same ids; the cache means it calls the model zero times; and the
409 above stops two runs racing over one edition.

**Redis being down fails only the rebuild routes.** The queue connection is lazy. Everything
else in the application is Neo4j and keeps working, rather than the app refusing to boot over
a subsystem most requests never touch.

## Testing

Following this project's rule that integration tests use the real thing and never mock the
driver:

- **A real Redis via testcontainers** for the queue tests, as Neo4j already is.
- **Route validation** — 404, both 409s, and the 202 — against a real queue on that Redis with
  no worker running, so the tests observe exactly what a caller sees between enqueue and
  completion. A recording fake was considered and dropped: this project does not mock its
  drivers, and the in-flight check reads RQ's own registries, which a fake would have to
  reimplement to be meaningful.
- **The job function itself** through RQ's synchronous mode (`Queue(is_async=False)`), which
  executes the real function in-process with no worker. With the `null` extractor this is fast
  and needs no model.
- **Progress** — a job over a real multi-chunk edition asserting `chunks_total` matches the
  chunk count and `chunks_done` reaches it.
- **The auth enumeration** in `test_auth.py` picks both routes up automatically; neither may
  appear in `OPEN_ROUTES`.

## What this design does not do

- **No UI.** The rebuild is reachable by an authenticated API call. A button belongs with
  [STORY-043](../../backlog/backlog.md#ready)'s ingest control in sprint 5, and ADR-019 already
  accepted that instructions are commands until then.
- **No scheduling, no retries on failure, no fan-out over a whole corpus.** RQ supports all
  three; none is built now. The queue exists so they are available when wanted, not so they
  are configured before anyone needs them.
- **No live push.** Progress is polled. Redis pub/sub would allow streaming, and nothing here
  forecloses it.

## Consequences

**Makes easy.** Triage, Review and Ask can be filled from a cold start by API calls alone,
which is the surge's original goal. Re-extracting after an extractor change becomes routine
rather than a script. Any future long-running derived-layer operation — a corpus-wide
re-embed, a batch diff — has a pattern and a place to live.

**Makes hard.** Two more containers on every start, and a second store holding derived state
alongside Neo4j's extraction cache. A developer now has to understand that some work happens
in a process they did not start, and a failure can surface in a worker log rather than a
response body.

**Commits us to.** A queue being part of this system's shape. The first feature that quietly
does long work in a request handler instead — because the queue felt like ceremony — puts the
project back where it started, with the difference that there will then be two ways to do
background work and only one of them observable.
