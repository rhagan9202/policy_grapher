# Sprint 2 — Plan

**Dates:** 2026-08-13 → 2026-08-13 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

**TODO:** Estimates and owners are unset, as in sprint 1 — no item in the backlog has ever
carried a point estimate, so the [Definition of Ready](../../backlog/README.md) is still not
being met in practice. Fill the column in before the next sprint rather than carrying the
gap a third time.

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

Build every endpoint and UI route [SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md)
names but sprint 1 left unbuilt, closing EPIC-001 at 18 of 18 stories.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-032 | A TypeScript error fails the frontend test command | — | — |
| STORY-028 | An operator can wipe the graph and start clean | — | — |
| STORY-005 | A user can list all documents and read one with what it cites and what cites it | — | — |
| STORY-006 | A user can create, update, and delete documents through the API | — | — |
| STORY-027 | A user can add and remove a reference between two documents | — | — |
| STORY-008 | An agent can run a raw Cypher query against the graph | — | — |
| STORY-010 | A user can browse and filter the document table by name | — | — |

**Total committed:** Unestimated — see [the estimation TODO](../../backlog/README.md#estimation).

These are the six stories sprint 1 left below the line, plus STORY-032, which was raised
from Ideas and pulled to the front deliberately: it makes `npm test` run `tsc -b` first, and
this sprint's largest frontend change lands after it. A type error reaching a commit is a
thing that already happened once, during the graph-explorer work.

Two pieces of committed work are not stories, because neither changes behaviour:

- **A router refactor, first.** `main.py` currently holds every route inline. Nine more
  endpoints would make it the whole backend, so routes move into `routers/` — `admin.py`,
  `documents.py`, `graph.py` — with the driver and settings resolved through injectable
  dependencies backed by `request.app.state`. Doing this before the new endpoints means no
  route is written into `main.py` and then moved. The guard is that all 71 existing tests
  pass untouched.
- **ADR-005, before STORY-006.** Sprint 1's review recorded that an amending ADR is *owed*
  before document CRUD lands: ADR-003 describes slug assignment as a per-name function, but
  it is really a function of the whole name set, and a document created one at a time
  through `POST /documents` has no batch to join. STORY-006 cannot be specified without
  deciding what happens when a newly created document's base slug is already taken.

## ADR-004 conditions, checked before `POST /query` ships

[ADR-004](../../specs/adr/ADR-004-unrestricted-cypher-in-di-1.md) accepts an unauthenticated,
unrestricted Cypher endpoint only while three conditions hold, and requires that they be
confirmed rather than assumed at the point the endpoint exists. Confirmed at sprint start,
and restated here so the check is on the record and not merely in someone's head:

1. **Local-only.** The stack binds to localhost through Docker Compose. There is no hosted
   environment, no CI, and no shared deployment — architecture.md flags the absence of a CI
   target as an open question, not as a thing that exists.
2. **Disposable data.** The graph is built from a committed sample CSV and is rebuilt by
   `POST /ingest` from that same file. Nothing in it is authoritative and nothing is lost by
   dropping it — which `POST /reset`, committed this sprint, makes routine.
3. **Trusted, Cypher-fluent audience.** Per
   [ADR-001](../../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md), the demo's users
   write Cypher themselves. LLM-constructed queries are explicitly Later, and gated on
   STORY-019 (auth) and STORY-024 (query constraints).

All three hold today. **Any one of them ceasing to hold is what makes this endpoint a
defect rather than a decision** — the first shared deployment is the trigger.

## Stretch

Picked up only if committed work finishes early:

- STORY-033 — linting over both backend and frontend. Sprint 1 deliberately left unused
  imports and dead code unfixed on the grounds that a batch pass would be cheaper.

## Known risks

- **The refactor touches every route before any new one is written.** If it changes
  behaviour silently, every story after it is built on a moved foundation, and the failure
  surfaces somewhere unrelated. Mitigation: a characterisation test pinning the route table,
  written and passing *before* the move, plus the existing 71 tests as the real guard.
- **Slug assignment diverges between ingest and incremental creation.** ADR-005 accepts
  this: at ingest the whole name set is slugged at once and every contender for a contested
  base slug takes a suffix; at creation the incumbent keeps its bare slug and only the
  newcomer is suffixed. A reset-and-reingest can therefore produce different slugs than
  incremental creation did. Accepted for URL stability, but it is the kind of thing that
  looks like a bug a year from now.
- **`POST /query` is the sprint's one irreversible-feeling decision.** It is trivial to
  build and hard to walk back once anything depends on it — see the conditions above.
- **Nine endpoints in one sprint invites shallow tests.** The temptation is one happy-path
  test each. Idempotency, 404s, self-reference, name-mismatch, and the external-document
  cases are where the behaviour actually lives.
- **No headless browser.** The document table can be unit-tested and its route can be
  confirmed to serve, but nobody in this sprint can *see* it render. Any claim that it looks
  right would be unfounded.
