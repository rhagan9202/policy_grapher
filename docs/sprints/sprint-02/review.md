# Sprint 2 — Review

**Date:** 2026-08-13

*Dated record — a snapshot of what happened.*

## Against the goal

Goal was: Build every endpoint and UI route
[SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md) names but sprint 1 left unbuilt,
closing EPIC-001 at 18 of 18 stories.

Met. Nine endpoints and one UI route shipped:
`GET`/`POST`/`PUT`/`DELETE` on `/documents`, `POST`/`DELETE` on
`/documents/{slug}/references/{target_slug}`, `POST /reset`, `POST /query`, and the
`/documents` table route. `test_di1_complete.py` walks every endpoint the spec names in one
test and asserts each one's status code; a second test creates a document, adds a reference,
deletes it, and asserts the full 438-node, 672-edge graph is byte-identical to how it
started.

Verified from a cold start (`docker compose down -v` then `up -d --build`), against the
running stack through the frontend's `/api` proxy:

```
curl -s localhost:5173/api/graph       -> returned_nodes 23, total_nodes 23, 72 edges, truncated false
curl -s localhost:5173/api/documents   -> 438 entries
curl -s -X POST localhost:5173/api/query -d '{"cypher":"MATCH (d:Document) RETURN count(d) AS total"}'
                                       -> [{"total":438}]
curl -s -X POST localhost:5173/api/reset -> {"nodes_deleted":438,"relationships_deleted":672}
```

Suites at close: **110 backend tests** (71 at sprint start), **34 frontend tests** (21 at
sprint start), all passing, output pristine. 36 backend tests still run without Docker via
`-m "not integration"`, up from 31 — the container-free path was preserved, not just
tolerated.

## Completed

| ID | Item | Est. |
| --- | --- | --- |
| STORY-032 | A TypeScript error fails the frontend test command | — |
| STORY-028 | An operator can wipe the graph and start clean | — |
| STORY-005 | A user can list all documents and read one with what it cites and what cites it | — |
| STORY-006 | A user can create, update, and delete documents through the API | — |
| STORY-027 | A user can add and remove a reference between two documents | — |
| STORY-008 | An agent can run a raw Cypher query against the graph | — |
| STORY-010 | A user can browse and filter the document table by name | — |

**Delivered:** 7 of 7 committed. Both non-story commitments also landed: the router refactor
(`main.py` is now app assembly, CORS and lifespan only; routes live in `routers/admin.py`,
`documents.py` and `graph.py`, reaching state through `dependencies.py`) and
[ADR-005](../../specs/adr/ADR-005-slug-assignment-over-the-name-set.md), written before
STORY-006 as sprint 1's review required.

**EPIC-001 closes at 18 of 18.** That count includes STORY-004 (malformed CSV rejected
cleanly) and STORY-015 (render cap with truncation reporting), which were **recognised as
complete after sprint 1's review was written**. Both were built during sprint 1 and neither
was noticed at the time, so sprint 1's review undercounts its own delivery by two and its
velocity row reads 11 rather than 13. Sprint 1's review is a frozen dated record and has not
been edited; the correction lives here instead. The backlog credits both to sprint 1, where
the work actually happened.

## Not completed

Each with where it went — back to the backlog, cancelled, or split.

| ID | Item | Why | Disposition |
| --- | --- | --- | --- |
| STORY-033 | Linting over both backend and frontend | Stretch. Committed work used the session; never started | Stays in Ideas |

## Demo notes and feedback

**The document table was never seen rendering.** There is no headless browser in this
environment. What was verified: 7 unit tests over the component against a mocked client,
`tsc -b` clean, `vite build` clean, and `GET localhost:5173/documents` returning 200 — which
proves the route resolves and the SPA shell serves, not that the page looks right. It should
be opened by a human before anyone demos it.

**A test specified in the plan was silently missing, and the count is what surfaced it.**
The plan predicted 111 backend tests; the suite collected 109. Reconciling file by file
found `test_reset_does_not_retrigger_auto_ingest` — written out in full in the plan, absent
from `test_reset.py`. It was restored, and it passes. The remaining one-test gap is the
plan's own arithmetic: its task-by-task additions sum to 110, not 111. Worth noting that the
predicted count was the only reason anyone looked; a plan that had said "expect a lot of
tests" would have hidden a real omission behind a green suite.

**One planned test was wrong and had to be corrected rather than copied.** The plan's
document-table test selected a row by accessible name `/Public Law 116-92/`, which matches
two rows — the external document's own row, and the `DoDD 5000.01` row that cites it in its
References cell, exactly as the very next test asserts. Anchoring the pattern to the start of
the row fixed it without weakening the assertion. Copying a plan's test code verbatim is not
the same as the test being right.

**`POST /query` shipped with ADR-004's three conditions confirmed, not assumed** — recorded
in [this sprint's plan](plan.md#adr-004-conditions-checked-before-post-query-ships). The
follow-on is now live rather than hypothetical: `architecture.md`'s weak-point entry has been
returned to present tense, because an unauthenticated endpoint that can drop the database
exists today. STORY-019 (auth) and STORY-024 (query constraints) are the gates before this
reaches anything shared.

**DI-1's feasibility question is answered, and its scale question is untouched.** 23 corpus
rows produce 438 nodes and 672 edges — citation breadth, not corpus size, drives the graph.
`GET /documents` returns all 438 on every call and the table filters them in the browser.
Fine here; the roadmap's next milestone swaps a column of pre-extracted references for PDFs
and DOCX files that have to be parsed, and neither number survives that change untested.
