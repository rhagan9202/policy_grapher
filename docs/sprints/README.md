# Sprints

One folder per sprint: `sprint-01/`, `sprint-02/`, and so on. Each holds a plan written at
the start, and a review and retrospective written at the end. All three are dated records —
write them once and leave them alone. An edited retrospective tells you nothing about what
the team actually thought at the time.

## Cadence

Set 2026-08-21, at the tech-debt surge planning session. This project is worked in
agent-driven sessions rather than by a standing team, so the cadence is written in terms of
sessions rather than days — a calendar cadence nobody keeps is worse than an honest one.

- **Length:** one working session per sprint. Sprints 1 and 2 each ran this way and
  delivered 13 and 7 stories respectively, which is the only throughput evidence there is.
- **Planning:** before any code, and it produces `plan.md` with a one-sentence goal and every
  committed item sized. A plan written after the work is a report.
- **Standup:** not applicable to a single-session sprint. The equivalent is that a change of
  plan mid-session gets written into the review, not silently absorbed.
- **Review and retro:** at the end of the same session, before the next sprint's plan is
  written. Both are frozen once written.

**Sprint plans are written at sprint start, one at a time.** A multi-sprint surge records its
*arc* in the [roadmap](../planning/roadmap.md), which is a living document; it does not
pre-write dated records for sprints that have not begun. Sprint 3's plan exists because
sprint 3 has begun.

## Ceremonies, briefly

**Planning** — pick a sprint goal first, then pull items from the top of the backlog that
serve it. Capacity is the constraint; velocity is the guide.

**Standup** — blockers and changes to the plan. Not a status broadcast.

**Review** — demonstrate what's done against acceptance criteria. Anything not done goes
back to the backlog rather than silently carrying over.

**Retrospective** — one or two changes the team will actually make. A retro that generates
ten action items generates zero.

## Velocity

Tracked in [velocity.md](velocity.md). It's a planning aid — a rough sense of how much fits
in a sprint. It is not a productivity measure and comparing it across teams is meaningless.

## Closing out a sprint

1. Write `review.md` — what shipped, what didn't, why
2. Write `retrospective.md` — what changes
3. Update `velocity.md`
4. Move incomplete items back to the backlog, re-prioritized
5. Create the next sprint folder and update the docs index link
