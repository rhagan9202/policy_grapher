# ADR-038: The document table pages rather than caps

**Status:** Accepted · **Date:** 2026-09-08 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

Taken during sprint 12's acceptance walkthrough, against the running stack.

## Context

`GET /documents` is unbounded and returns all 438 documents on every call. STORY-070 bounded
what the browser *renders* rather than what the route returns, borrowing the idiom the graph
view had used since STORY-015 — draw the first N, report the truncation, and point the reader
at the filter:

> Showing 200 of 438. Filter to narrow the list and see the rest.

[architecture.md](../architecture.md) recorded the position as **"No pagination anywhere, by
design."**

Driving the corpus in a browser is what showed the cost. The table is ordered by name, so the
cap fell somewhere around "M" and every document after it was unreachable — not slow, not
hidden behind a click, *unreachable* — unless the reader could already guess enough of a name
to filter for it. That is a poor bet against this corpus: the names are things like
`Adaptive Acquisition Framework Documentation Identification (AAFDID) Tool`, and a reader
browsing to find out what is in the graph does not yet know what to type.

The idiom did not transfer, and the reason is a property of the two surfaces rather than an
oversight. A force-directed graph past a few hundred nodes is an unreadable picture, so
capping it is the kindest thing available and the filter genuinely is the way through. A table
is a list. Nothing about row 201 is less readable than row 200.

## Options considered

**Keep the cap and improve the wording.** Cheapest, and it fixes nothing: the rows are still
unreachable, and a clearer sentence about their unreachability is not access to them.

**Bound the route and page server-side.** The honest long-term shape, and what this project
will need eventually — `GET /documents` is the one unbounded route left, and at MVP corpus
sizes the response itself becomes the problem. Rejected *now* on sequencing: it is a route
change, a client change and a test change, it would need its own decisions about ordering and
cursor stability, and none of that is required to make row 201 reachable today. Bounding the
route while the client still sorts and filters in the browser would also be actively wrong —
the client would sort a page rather than the corpus, so "most cited" would mean "most cited
among the two hundred the server happened to send".

**Page, sort and filter the whole payload in the browser.** Chosen.

## Decision

The document table pages its already-complete payload: `PAGE_SIZE` rows at a time (200,
unchanged from the cap it replaces), with previous/next controls and "Showing 201–400 of 438".
Sorting by name, citation count and edition count happens over the whole filtered set before
the page is cut, so ordering means what it says rather than describing one page.

**The route stays unbounded.** This decision is about the client's use of a payload it already
holds, and deliberately does not touch `GET /documents`. The day the response itself is too
large is the day the route needs the bound — and on that day this table's client-side sort has
to move to the server in the same change, or the ordering quietly starts lying.

`architecture.md`'s "no pagination anywhere" is narrowed to the API rather than deleted, which
is what it was always describing.

## Consequences

**Makes easy.** Every document in the corpus is reachable by browsing, which is what a reader
who does not yet know the corpus actually does. Sorting answers "which documents are cited
most" and "which have text" — both already columns, neither previously orderable — over the
whole corpus rather than a slice of it.

**Makes hard.** Nothing about the payload changed, so the memory and transfer cost of 438
documents on every load is exactly what it was; this decision does not improve it and should
not be read as having addressed it. The `Showing`/`Page` controls are a third piece of state
alongside the filter and the sort, and all three have to agree about resetting — a filter
applied while on page 2 has to return to page 1, or the table renders empty over a non-zero
count, which is the blank-that-reads-as-broken [ADR-019](ADR-019-the-first-run-is-empty.md)
forbids. That is a test, not a comment.

**Commits us to.** Moving sort and filter to the server in the same change that bounds
`GET /documents`, and not before. A bounded route under a client-side sort is worse than
either end alone, because the ordering is wrong in a way nothing on screen reveals.
