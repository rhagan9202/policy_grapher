# STORY-083: A graph can be exported before it is destroyed

**Epic:** — · **Status:** Done · **Estimate:** M

## User story

As an operator about to empty the graph, I want to take a snapshot of what is in it first, so
that hours of extraction and every review decision I made are not destroyed by one confirmed
click with no way back.

## Context

The Reset screen states the problem itself: *"Empties the graph: every document, edition, chunk,
obligation, proposal and recorded decision. There is no undo and no export."*
(`frontend/src/views/Reset.tsx:57`.) The warning is accurate. There is no export route anywhere
in the API and no export anywhere in the UI.

What that destroys is not cheap. A real-model rebuild of one 37-chunk edition took hours of CPU
inference on 2026-08-25; the largest edition in `data/samples` is 204 chunks. Review decisions
are worse, and the confirmation dialog already says why: decisions are *"including decisions,
which a rebuild replays and therefore cannot bring back once they are gone."* Extraction is
cached and a rebuild is therefore repeatable
([ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)); a human's judgment
about whether one clause implements another is not. Reset deletes the only copy of the one
thing in this system that a machine cannot regenerate.

Reset is deliberate, confirmed, and honestly labelled, so this is not a trap a user falls into.
It is a missing capability the product already tells them is missing.

## Acceptance criteria

- [ ] `GET /export` returns the whole graph as a single JSON document.
- [ ] The export contains documents, editions, chunks, obligations, proposals, recorded review
      decisions, and detected changes — every category the Reset screen names as deleted.
- [ ] Each exported record carries the identifiers the graph keys on — `version_id`,
      `chunk_id`, `obligation_id`, `decision_key` — so a reader can join the file back together
      and so a future import has something stable to match on.
- [ ] The route requires bearer auth, like every route except `/health`.
- [ ] The export is a single JSON object whose top-level keys name the categories above, each
      holding a list of records, so a reader can find a category without consulting the code
      that wrote it.

      *Revised at sprint 6 planning.* This first read "its structure is obvious without reading
      the source that produced it", which no test can fail — the exact defect sprint 5's
      retrospective made its number-one change three days before this was written.
- [ ] Given an empty graph, **When** the export is called, **Then** it returns a valid,
      well-formed document with empty collections rather than failing.
- [ ] The Reset screen offers the export before the destructive action, in the same flow.
- [ ] Reset's warning text is corrected in the same change: it currently says "no undo and no
      export", and half of that stops being true.

## Notes

**Export only. Restore is deliberately out of scope**, and that is the honest limit of this
item's value: it makes the loss inspectable and re-ingestable, not reversible. A user who
exports and then resets can read exactly what they had and rebuild deliberately from the source
PDFs; they cannot press undo.

That is a real capability and it is what the Reset warning literally promises is absent, which
is why it is worth landing on its own. But it does not make Reset safe, and the copy must not
imply that it does. If the team wants Reset to be genuinely reversible, restore is a separate
item — and it is **L**, not M: writing decisions back means deciding what happens when the
graph they refer to has changed underneath them, which is the same class of problem
[ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) had to solve for rebuilds
and had to solve carefully.

Sized **M** on the same reasoning as STORY-081: an endpoint plus the UI that reaches it, no
unmade decision inside it. The format question resolves to "JSON shaped like the API's existing
`*Out` models", which is the least surprising answer and needs no new vocabulary.

## Dependencies

- STORY-046 (a user can empty the graph from the UI) — **Done.** This story attaches to the
  screen that story built.
- No dependency on STORY-081 or STORY-082, though STORY-081 lands the read path for
  obligations, which overlaps this story's obligation serialisation and may make it cheaper if
  it lands first.

## Open questions

- Does the export need to stream? The graph today holds 50 documents — 48 of them `:External`
  references and 2 real corpus documents — and 113 obligations, which fits in memory
  comfortably. It has been much larger: `TABLE_RENDER_CAP` in
  `frontend/src/views/DocumentTable.tsx` was set against a table of **439 rows** (STORY-070),
  and that was before any edition had been rebuilt, so it carried no obligations or chunks at
  all. Building the whole document in memory before responding is the kind of thing that works
  until it doesn't. The criteria above do not require streaming; if measurement says otherwise
  it is a small change to the same route.
- Should an export be offered anywhere other than the Reset flow? Backing up before a
  destructive action is the acute case, but wanting the data out of the app is a general one.
