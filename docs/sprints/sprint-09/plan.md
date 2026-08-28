# Sprint 9 — Plan

**Dates:** 2026-08-28 → TBD · **Capacity:** one working session

*Dated record — written at sprint start, not edited afterward.*

## Goal

**The product can see the duties DoD actually writes.**

Extraction has been measured, ratcheted and trusted for three sprints, and every one of those
measurements was taken against the half of a document the extractor can currently read. Sprint 8
found the other half: DoD assigns duties by *position* — a role heading followed by lettered
third-person verbs — and the schema refuses every one of them, correctly, because there is no
modal verb to point at. This sprint makes the product read that half, and stops it paying for the
part that states no duties at all.

The measurable claim: **91 positional duties across `data/samples`, against 164 obligations in the
graph today.** If this sprint lands, the product sees roughly half again as many duties as it ever
has, and they are the ones a compliance reader asks for first.

## Why this goal, and not the two obvious alternatives

**Not "prove it at scale."** The roadmap is right that scale is untested — every number this
project has ever published is against 23 documents while the manifest names 438. But measuring
throughput of an extractor that cannot see the responsibilities section would produce a large,
confident number describing half the truth. Scale is the sprint *after* this one.

**Not "start the Policy Concierge schema."** STORY-020 and STORY-021 are the honest answer to what
the project is for now the MVP is met, and neither is refined, specified, or safe to design
against an extractor about to change shape underneath it.

**And the two are less opposed than the roadmap makes them look.** An `ASSIGNED` obligation
carries a named office in its `actor` field, because
[ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md) requires one. That is
precisely the raw material STORY-021 wants — *which entities a policy applies to, who is
responsible for enforcing it* — produced as a side effect of this sprint rather than as a schema
migration. This sprint does not commit to the Policy Concierge direction. It stops that direction
being blocked on data nobody has.

## Committed

Four items: 2M + 2S. No L — ADR-033 removed the only one this backlog held.

| ID | Item | Size | Why it is here |
| --- | --- | --- | --- |
| [STORY-097](../../backlog/stories/STORY-097-the-responsibilities-section-is-invisible.md) | The responsibilities section of an issuance is invisible | M | The goal. Implements ADR-033: `Modality` gains `ASSIGNED`, guarded by a named actor in the schema and a responsibilities section in the adapter |
| [STORY-098](../../backlog/stories/STORY-098-front-matter-is-not-offered-for-extraction.md) | Front matter is not offered to the extractor | M | The cheap half of the same finding. Stops ~4 chunks in 37 costing a 90-second call to be told nothing — and stops the model inventing headings as `SHALL` |
| [STORY-099](../../backlog/stories/STORY-099-every-route-is-reached-by-a-real-request.md) | Every declared route is reached by a real request | S | Sprint 8's retrospective action, by name. 2 of 22 paths have no test that requests them |
| [STORY-075](../../backlog/stories/STORY-075-a-chunk-on-a-section-join-is-attributed-to-the-right-page.md) | A chunk starting on a section join is attributed to the right page | S | A known defect, filed instead of fixed since sprint 7. The standing rule prohibits that |

**No stretch item is named.** Sprints 4 and 5 both carried one and both landed it, so this is a
departure and the reason is specific: the two M items each *end* in a measurement, and a
measurement that comes back wrong becomes the sprint. That is not hypothetical — STORY-084 was
committed as S and delivered as L for exactly this reason, when the re-measurement it asked for
failed and the work became fixing the extractor.

## What this sprint is deliberately not doing

- **Not re-measuring the corpus at scale.** One edition rebuilt is the demonstration; 23 is a
  later sprint's question.
- **Not touching `:Authority` or `:Entity`.** STORY-092 removed them for being unreachable, and
  the `actor` data this sprint produces is the argument for writing them again from a spec — next
  sprint, not this one.
- **Not answering STORY-098's fifth criterion in advance.** If skipping input the model was
  failing on moves recall, that is a finding to report, not a number to explain away.

## Risks, and what each would cost

**The rebuild is the schedule.** STORY-097's last acceptance criterion cannot be met without a
full rebuild of DoDD 5000.01 (2020), and the last measured run did 30 of 37 chunks in 30 minutes
before sprint 5's timeout fix — call it 45 minutes an edition, plus three ratchet re-measurements
at temperature 0. If the session runs short, this is what runs long. Four items rather than seven
is the mitigation, chosen at planning rather than discovered at review.

**`ASSIGNED` becomes an escape hatch.** The whole risk ADR-033 accepted is that a value naming no
word cannot be checked against the passage the way the other five can. Both guards must hold, and
the regression test naming `"Be Responsive."` and both guards it fails is the one test in this
sprint that must not be allowed to pass vacuously.

**Three existing checks will fail, correctly.** STORY-084's gold-set coverage, ADR-025's
weights-cover-the-enum, and STORY-085's explicit mapping all break the moment `Modality` gains a
member. **None may be loosened to go green** — each is satisfied by supplying what it asks for.
If any of them is edited to accommodate the change, the sprint has traded its safety net for a
green tick and should not close.

**A prompt change moves every number.** `PROMPT_VERSION` bumps, so the extraction cache misses
and the floors are re-measured from scratch. Sprint 7 showed a prompt change shifting results the
author did not predict — including invalidating a check written against five exact strings. Any
floor that moves down gets said out loud in the review, with the reason.

## Definition of Done

The project's [standing gates](../../backlog/README.md#definition-of-done) apply unchanged:
acceptance criteria met, tests written and passing, reviewed and merged, documentation updated in
the same change, and the stack runs under `docker compose up` from a clean checkout.

Two things this sprint adds to the read-back, both from sprint 8's retrospective:

- **The acceptance criteria are read back one at a time against the code**, not against the tests.
  Sprint 8 found two criteria satisfied in letter and not substance at exactly this step, on items
  already called done.
- **Every new test is mutated before it is believed.** Three sprints running have produced a guard
  that did not guard, and the tell was the same each time: it passed the first run.

## What sprint 8 asked this session to settle

**The product cannot see the responsibilities section of a DoD issuance.** Settled before this
session opened, on 2026-08-27, by
[ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md): `Modality` gains
`ASSIGNED`, meaning a duty imposed by position rather than graded by a word — binding, weighing
the same as `SHALL`, guarded structurally rather than lexically. Deciding it turned up evidence
the sprint 8 review did not have: 91 positional duties across `data/samples`, and **none at all in
the 2003 edition of DoDD 5000.01**, which is what makes this a modern drafting convention rather
than a permanent gap. STORY-097 therefore enters this sprint Ready at M rather than Refining at L.

**A route can exist, be modelled by the client, and still 404.** STORY-099, committed above.
Measured at planning: all 22 paths resolve today, and 2 of them are reached by no test.

**The MVP is met, so what is this project for?** Answered above under *Goal* and argued under *Why
this goal*: for the next sprint, it is for reading the duties it currently cannot see — which is
also what unblocks the Policy Concierge direction without committing to it.

## What the backlog holds after this

[Ready](../../backlog/backlog.md#ready) is this sprint's four items and nothing else.

[Refining](../../backlog/backlog.md#refining) holds STORY-035, still unstartable because no
`.docx` exists in `data/samples` to design against, and the superseded STORY-013.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023 and STORY-045.
The first two are the Policy Concierge schema this sprint feeds without committing to.
