# How the backlog works

## Lifecycle

```
Idea → Refining → Ready → In sprint → Done
```

An item only moves to **Ready** when it meets the Definition of Ready. An item is only
**Done** when it meets the Definition of Done. These two gates are what stop half-understood
work from entering a sprint and half-finished work from leaving one.

## Definition of Ready

- [ ] The value is stated: who benefits and how
- [ ] Acceptance criteria are written and testable
- [ ] Dependencies are identified
- [ ] Estimated by the team
- [ ] Small enough to finish inside one sprint

## Definition of Done

- [ ] Acceptance criteria met
- [ ] Tests written and passing
- [ ] Reviewed and merged
- [ ] Documentation updated in the same change
- [ ] Runs under `docker compose up` from a clean checkout

The last gate is the only deployment target that exists today: DI-1 ships to local
developer machines via Docker Compose. There is no hosted environment and no CI.
**TODO:** revisit this line if either appears.

## Estimation

**T-shirt sizes: S, M, L.** Decided 2026-08-21, at the planning session for the tech-debt
surge, after two sprints in which nothing was sized and the Definition of Ready above was
therefore never actually met.

| Size | Means | Rough shape |
| --- | --- | --- |
| **S** | Understood, contained, one file or one obvious change | A defect with a known cause, a config fix |
| **M** | Understood, but touches several files or needs new tests to design | A new endpoint, a new screen, a wired-up pipeline stage |
| **L** | Contains a decision that is not yet made, or crosses backend and frontend | Anything needing an ADR first, or a rework of something already shipped |

Points were considered and rejected for now: [velocity](../sprints/velocity.md) has two data
points and one of them is known to be understated, so a numeric scale would imply a precision
the history cannot support. Sizes are comparable enough to stop a sprint being overcommitted,
which is the only job estimation has here.

**An L in a sprint is a warning, not a plan.** If an item is L because a decision is missing,
the decision is the work — split the ADR out as its own item rather than committing to the
implementation and discovering the question mid-sprint.

## Writing an item

Describe the outcome, not the implementation. "Users can reset a forgotten password"
survives a change of approach; "Add a password reset endpoint" doesn't.

Acceptance criteria go in Given/When/Then form when behavior is conditional, and as a plain
checklist when it isn't. Don't force the format where it doesn't fit.
