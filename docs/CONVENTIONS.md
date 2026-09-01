# Documentation Conventions

The point of these rules is narrow: make it obvious where a piece of information belongs,
so nobody has to guess, and so the same fact never ends up in two places drifting apart.

## The one rule that matters

**One fact, one home.** Every piece of information has exactly one authoritative document.
Everywhere else links to it. If you catch yourself copying a paragraph from one doc into
another, replace the copy with a link — the copy will be wrong within a month and there's
no way to tell which version is right.

## Where things go

| You're writing... | It goes in | Named |
| --- | --- | --- |
| Why the project exists, who it serves | `planning/vision.md` | (fixed) |
| Milestones, themes, sequencing | `planning/roadmap.md` | (fixed) |
| A unit of work to be done | `backlog/backlog.md` (a row) | `STORY-042` |
| A large multi-sprint theme | `backlog/epics/` | `EPIC-007-billing.md` |
| Detail for a story too big for one row | `backlog/stories/` | `STORY-042-oauth-login.md` |
| How a feature should behave | `specs/` | `SPEC-011-oauth-login.md` |
| A choice with lasting consequences | `specs/adr/` | `ADR-004-postgres-over-mongo.md` |
| The shape of the system as a whole | `specs/architecture.md` | (fixed) |
| Sprint goal and committed work | `sprints/sprint-NN/plan.md` | (fixed) |
| What shipped, what didn't | `sprints/sprint-NN/review.md` | (fixed) |
| What we're changing about how we work | `sprints/sprint-NN/retrospective.md` | (fixed) |
| A design worked out before implementation | `superpowers/specs/` | `2026-08-20-di-2-design.md` |
| A step-by-step plan for building it | `superpowers/plans/` | `2026-08-20-di-2-phase-0-security-gate.md` |
| A diagram, export, or research note | `artifacts/` | descriptive kebab-case |

Filenames are lowercase kebab-case. IDs (`STORY-042`, `ADR-004`) are permanent — never
renumber them, even when work is cancelled. A dead ID with a "cancelled" note is a useful
record; a reused ID makes every historical reference ambiguous.

## Design documents and plans vs. specs

`superpowers/specs/` and `superpowers/plans/` hold the working documents a change is thought
through in: a design that weighs the options, then a plan that sequences the build. They are
named `YYYY-MM-DD-<slug>.md` and are **dated records** — frozen once the work lands, because
their value is showing what was known and decided at the time.

They are not the canonical answer to how the system behaves. That is `specs/SPEC-NNN-*.md`
and `specs/architecture.md`, which are living documents kept true to the code. When a design
document and a spec disagree, the spec is right and the design document is history. Link to a
design document for *why* and *what we considered*; never for *what it does now*.

A decision inside a design document that would be expensive to reverse also gets its own
[ADR](specs/adr/) — the design document is not a substitute, because nobody reads a dated
plan looking for the reason a constraint exists.

## When a backlog row graduates to a file

Keep items as single rows in `backlog.md` for as long as a row can hold them. Create a file
in `stories/` only when the item needs acceptance criteria, open questions, or discussion
that would bloat the table. Most items never need a file. Reaching for a file too early is
the most common way this structure turns into busywork.

## Living vs. dated documents

**Living documents** — vision, roadmap, backlog, architecture — are edited in place and
always describe the present. They carry a *Last reviewed* date. Never append changelogs to
them; that's what version control is for.

**Dated documents** — sprint plans, reviews, retrospectives, ADRs, and the design documents
and plans under `superpowers/` — are written once and then frozen. They're a record of what
was true at a moment. If a decision changes, don't edit the old ADR; write a new one and
mark the old one superseded.

Getting this distinction wrong is what makes docs untrustworthy: an edited retrospective is
worthless, and a roadmap with six months of appended updates is unreadable.

## What to update, when

- **Merging a change that alters behavior** → update the relevant spec in the same PR.
- **Making a call you'd have to re-litigate later** → write an ADR while the reasoning is fresh.
- **Sprint boundary** → close out `review.md` and `retrospective.md`, create the next sprint folder, update `velocity.md`.
- **Roadmap shifts** → update `roadmap.md` and refresh its *Last reviewed* date.
- **Anything contradicts a canonical doc** → the canonical doc wins, or gets corrected. Never both.

## Marking uncertainty

When something is assumed rather than known, say so inline:

> **Assumption:** Target users are internal support staff. Not yet validated with users.

Unmarked assumptions get read as facts by whoever arrives next. A visible marker is an
invitation to correct it; a confident sentence isn't.

Use `TODO:` for known gaps. Empty sections with no marker read as "nothing to say here,"
which is rarely what's meant.

## Deleting

A document that no longer describes reality should be deleted, not left to mislead. History
is in version control. If it's a dated record (sprint, ADR), it stays — those are supposed
to describe the past.
