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

**TODO:** Not yet decided. The team hasn't sized anything, so no item in the
[backlog](backlog.md) formally meets the Definition of Ready above.

Pick an approach at the first planning session — story points against a reference item, or
t-shirt sizes — and record it here. Whatever the unit, [velocity](../sprints/velocity.md)
only becomes useful once it's consistent across sprints.

## Writing an item

Describe the outcome, not the implementation. "Users can reset a forgotten password"
survives a change of approach; "Add a password reset endpoint" doesn't.

Acceptance criteria go in Given/When/Then form when behavior is conditional, and as a plain
checklist when it isn't. Don't force the format where it doesn't fit.
