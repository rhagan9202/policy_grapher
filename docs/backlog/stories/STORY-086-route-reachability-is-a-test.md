# STORY-086: Route reachability is a test, not a paragraph

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As a maintainer adding a backend route, I want a test to fail when the browser application
cannot reach it, so that a capability cannot ship complete on the server and be unreachable by
the audience it was built for.

## Context

Sprint 5's retrospective made this its number-one change. Its Definition of Done had said "no
client function in `api/client.ts` is left without a caller", and the retrospective records why
that check was worthless: it passes trivially against a route the client never modelled at all —
which is exactly the state sprint 4's rebuild routes were in, and `GET /documents/{slug}/chunks`
before them. The claim was about *backend capability being reachable*; the check was about
*client functions being called*.

The corrective action was to compare the routers' declared paths against the client, and the
retrospective says "It is in `architecture.md` and it is three lines of Python."

**It was written as prose and never automated.** Run by hand at sprint 6 planning: 20 of 20
routes have a client function, 19 of 20 have a UI caller, and `POST /query` is the one deliberate
exception ([ADR-008](../../specs/adr/ADR-008-authenticated-non-cypher-audience.md)). The
project is compliant today, and nothing will notice when it stops being.

## Acceptance criteria

- [ ] A test compares the paths the FastAPI app declares against the routes `api/client.ts`
      models, and fails naming any route the client cannot reach.
- [ ] `POST /query` is the single declared exception, named in the test with its ADR.
- [ ] `/health` is exempt or covered deliberately, and the test says which.
- [ ] Given a new router is added with no client function, **When** the suite runs, **Then**
      this test fails and names the path.
- [ ] The test lives beside the existing route-policy test, which already has the right shape.

## Dependencies

- None.

## Open questions

- Should the check also assert a *caller* exists for each client function, or only that the
  client models the route? The caller half is what the old check did, and on its own it was the
  defective one — but together the two are stronger than either. The criteria above require the
  route half; adding the caller half is cheap if it does not produce false positives on
  deliberately parked functions.
