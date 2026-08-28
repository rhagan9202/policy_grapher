# STORY-099: Every declared route is reached by a real request

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a maintainer adding a route, I want the suite to fail if that route cannot be reached by an
actual HTTP request, so that a capability cannot ship unreachable while every test passes.

## Context

Asked for by name in [sprint 8's retrospective](../../sprints/sprint-08/retrospective.md). `GET
/documents/duplicates` answered 404 for an entire sprint and the whole suite stayed green, because
FastAPI matched `/{slug}` first and **nothing ever sent the request**. The frontend mocks the
client, so its tests never reach a server; the backend tests never called that path.

[STORY-086](STORY-086-route-reachability-is-a-test.md)'s check was written one sprint earlier to
prevent exactly this and did not, because it compares the routers' declared paths against
`client.ts` and **calls neither**. It was correct for its own purpose — is a route modelled by the
client — and structurally blind to whether the route answers.

**Measured at sprint 9 planning:** 25 declared routes over 22 distinct paths, and **2 paths have
no request literal anywhere in `backend/tests/`** — `POST /documents/duplicates/merge` and `POST
/documents/duplicates/different`, both added last sprint, both siblings of the route that broke.
All 22 currently resolve, checked by real request, so this is a coverage gap and not a live
defect. The gap is the point: the same two-route blind spot recurred one sprint after the check
meant to catch it.

## What this must and must not claim

**It proves reachability, not correctness.** One request per route, asserting the route resolves
rather than 404s. It does not prove the route does its job — that stays the route tests' work, and
this story must not be written in a way that suggests otherwise.

**It must observe, not declare.** The failure mode being fixed is a check that compares two
declarations. The test therefore iterates the *route registry* and issues real requests through
the app, so a route added tomorrow is covered the moment it is registered, with no list to update.
A curated mapping of route-to-test would reproduce STORY-086's blind spot in a new file.

**CI runs the suite in two halves** — `-m "not integration"` and `-m integration` — so no single
process sees every route exercised by the rest of the suite. This is why the test makes its own
requests rather than recording what other tests happened to send: self-contained, it gives the
same answer in either half and when run alone.

## Acceptance criteria

- [ ] A test enumerates registered routes through `test_routers.py`'s existing `_flatten_routes`
      helper — routers are included lazily, so a plain walk of `app.routes` yields nothing, which
      is a trap worth not falling into twice.
- [ ] For every registered route, it issues a real request through the app and asserts the
      response is not 404. Path parameters are filled with any placeholder; a route that resolves
      returns 401, 422 or 500 for a bad one, and only an unroutable path returns 404.
- [ ] It is watched failing: temporarily declare `GET /documents/{slug}` before `GET
      /documents/duplicates` and confirm the test names the shadowed route, reproducing sprint 8's
      defect exactly. Restore the order afterwards.
- [ ] The test needs no database. Overriding `get_driver` is enough to keep an unauthenticated
      request from reaching Neo4j, so it belongs in the unit half and runs on every push.
- [ ] The assertion message names the route that could not be reached and says a route declared
      after a matching path parameter is the usual cause — the next person to hit this should not
      have to rediscover why.
- [ ] `POST /documents/duplicates/merge` and `POST /documents/duplicates/different` are covered by
      it, closing the two gaps measured above.

## Dependencies

- None. `test_routers.py` already has the registry helper this needs.

## Notes

This does not replace STORY-086's check, and neither replaces the other: STORY-086 asks whether
the client models the route, this asks whether the server answers it. A capability needs both to
be reachable from the browser, and sprint 8 proved that passing one says nothing about the other.
