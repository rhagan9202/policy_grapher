# Sprint 3 — Review

**Date:** 2026-08-21

*Dated record — a snapshot of what happened.*

## Against the goal

Goal was: the app tells the truth about its own state — it starts empty, says so on every
screen instead of rendering blanks that read as failure, and carries none of the UI defects
the 2026-08-21 audit found.

Met. All seven committed items are closed, one of them by deciding no change was warranted.

Suites at close: **512 backend tests** (509 at sprint start), **90 frontend tests** (76 at
start), both green, output pristine.

## The cold-start walkthrough

The sprint's extra Definition of Done, and the only check that could have caught what it
caught. Run against a wiped volume:

```
docker compose down -v && docker compose up -d --build
```

| Check | Result |
| --- | --- |
| Nodes in the graph | **0** |
| Graph, Documents, Triage, Review, Ask | all five show the empty state |
| Console errors | none — the `favicon.ico` 404 is gone |
| Graph detail panel | `x=1056` in a 1400px window — **visible**, was `x=1425` |
| Horizontal overflow | none, at any width tested |

Then with the sample CSV ingested (438 documents, no editions), and again with two editions
of DoDD 5000.01 ingested: the Triage picker offered **1 document of 439**, and one edition of
three — the oldest omitted, and no 400 alert where the audit had seen one.

**The walkthrough found a defect seven unit tests had missed.** With 438 documents and zero
editions — exactly what ingesting the CSV manifest alone produces, because a manifest records
no text (ADR-011) — Triage rendered a document picker with no options and no explanation. The
STORY-040 dead end in a second guise, reached by a path no test covered because no test had a
corpus without editions. Fixed with a failing test first. This is the second sprint running in
which an observation, not the suite, was what surfaced a real defect.

## Completed

| ID | Item | Est. |
| --- | --- | --- |
| STORY-049 | A cold start is empty, and the app says so instead of looking broken | M |
| STORY-039 | The graph view fits the window it is drawn in | S |
| STORY-040 | Triage only offers comparisons it can actually carry out | S |
| STORY-041 | The app has a favicon | S |
| STORY-038 | Creating a document through the API is one transaction | S |
| STORY-050 | The codebase contains no code the application cannot reach | S |
| STORY-053 | Planning documents describe the running app, not its library | S |

**Delivered:** 7 of 7 committed. First sprint in this project's history where every committed
item carried an estimate, and the first where the Ready column met its own Definition of Ready.

**STORY-050 closed as no change required, and that is the outcome worth reading.** The AST
sweep that produced it was right that four public symbols have no caller in `src/`, and wrong
that this made them defects. `text_of` is called 15 times by `test_pdf_stages.py` to feed the
whole-text stage functions — my own claim that `pages_of` superseded it was simply false, and
checking took one grep. `attach_authority`, `merge_authority` and `merge_entity` were staged
deliberately: [ADR-011](../../specs/adr/ADR-011-instruments-have-versions.md) introduces them,
records that ingest does not exercise them, and names the future task that will call
`attach_authority`. Deleting them to satisfy a story title would have contradicted a frozen
decision. Nothing was deleted.

**STORY-038 needed a test that could tell the difference.** Proving a transaction rolls back
needs a real failure inside a real transaction. Mocking the driver to raise would have tested
the mock. What works: monkeypatch the *last* of the four statements to invalid Cypher, so the
server raises partway through. Under the original code the `:Document` is already committed
when that lands, and the test fails on a surviving node — which is precisely the silent
corruption `architecture.md` listed first under *Known weak points*, now removed from that
list.

## Not completed

Nothing. The stretch item was not started.

| ID | Item | Why | Disposition |
| --- | --- | --- | --- |
| STORY-051 | Both suites run on a check nobody has to remember | Stretch. Committed work used the session | Stays in Ready, sprint 4 |

## Demo notes and feedback

**The app is worse to demo than it was yesterday, on purpose.** Anyone opening it now sees an
empty graph and an instruction. That is
[ADR-019](../../specs/adr/ADR-019-the-first-run-is-empty.md) working as intended, and it will
stay uncomfortable until [STORY-043](../../backlog/backlog.md#ready) gives the instruction a
button, in sprint 5. Two sprints is the stated cost.

**Two proposals were rejected during planning and both deserve recording.** A deterministic
modal-verb extractor as the demo default, and a synchronous rebuild route with its timeout
documented as a known limitation. Both would have shipped this sprint and both were the same
move — present the product as fuller or more finished than it is. ADR-013 had already
rejected a modal-verb rules engine on measured evidence. The project owner rejected both, and
ADR-019 exists so the reasoning survives the next time a screen looks bare.

**The plan was rewritten once, before any code.** The STORY-048 design session invalidated its
first draft: the derived-layer route needs an execution model that could not be settled in
passing, so STORY-048 moved to sprint 4 with a spec, and STORY-039/040/041 pulled forward to
fill the space. Amending a plan we had agreed was wrong beat executing it, but it happened at
planning time and is noted at the top of the plan itself.

**`version_count` was added to `DocumentOut` rather than solving STORY-040 in the client.**
Filtering client-side would have meant 440 calls to `/documents/{slug}/versions` to populate a
dropdown. It is computed at read time from `HAS_VERSION`, not stored, so nothing can drift.

**Still no CI.** Seven items closed this sprint and every check that verified them ran because
someone chose to run it. STORY-051 is sprint 4.
