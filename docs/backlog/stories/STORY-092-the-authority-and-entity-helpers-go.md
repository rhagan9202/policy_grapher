# STORY-092: The Authority and Entity helpers go

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As a maintainer reading this codebase, I want code that nothing calls to be absent rather than
present, so that the next person does not have to work out whether it is load-bearing.

## Context

`merge_authority`, `attach_authority` and `merge_entity` in
`backend/src/policy_grapher/versions.py` have no production caller. Verified twice during sprint
6: the only references outside their own definitions are in `backend/tests/test_versions.py`, and
the live graph holds zero `:Authority` and zero `:Entity` nodes.

The roadmap claimed DI-2 Phase 1 had landed them. Sprint 6 corrected that entry and moved the two
labels to [Later](../../planning/roadmap.md#later), where they sit with the richer metadata they
were written to serve. So the capability is *written* but not reachable — the same distinction
sprint 5's retrospective drew about client functions, and the tests are what made it look
delivered.

[CONVENTIONS](../../CONVENTIONS.md#deleting) says a document that no longer describes reality is
deleted rather than left to mislead, because history is in version control. The same argument
applies to roughly thirty lines of Cypher that describe a capability nothing offers.

## Acceptance criteria

- [ ] The three helpers and the queries they own are removed from `versions.py`.
- [ ] The tests whose only subject was those helpers are removed with them — a test for deleted
      code is the thing that made this look alive.
- [ ] No remaining test or module references them, and the suite is green without them.
- [ ] The roadmap's [Later](../../planning/roadmap.md#later) entry says the two labels will need
      writing rather than wiring, so a reader is not sent looking for code that was deleted.

## Dependencies

- None. Nothing calls them, which is the point.

## Open questions

- Deleting is the reading this story takes; keeping them behind a clear "not wired" marker is the
  alternative. It is rejected because a marker is what the roadmap entry already was, and it read
  as delivered for a whole increment. If the labels are wired within a sprint or two, thirty
  lines of Cypher is cheap to write again from a spec that will by then say what they must do.
