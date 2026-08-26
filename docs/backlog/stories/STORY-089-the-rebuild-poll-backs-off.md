# STORY-089: The rebuild status poll backs off

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As an operator watching an overnight rebuild, I want the page to stop asking every two seconds,
so that leaving a tab open does not put fourteen thousand requests through the API for one run.

## Context

`frontend/src/views/DocumentDetail.tsx` polls `GET /rebuilds/{run_id}` on a flat two-second
`setTimeout` while a run is queued or started — no backoff, no ceiling. Its own comment explains
why there is no attempt limit, and that reasoning is sound: "a poll budget would time out on
exactly the runs worth watching."

What changed is the length of those runs. `rebuild_job_timeout_seconds` went from 1800 to 28800
on 2026-08-26 so that a 204-chunk edition could finish, and the comment above the poll still says
a rebuild "takes tens of minutes". At eight hours a single open tab issues roughly **14,400
polls**, each a `Job.fetch` plus `latest_result()` round trip to Redis.

Found by sprint 6's planning review, and not committed to that sprint. Nothing is broken — the
run completes and the screen is correct throughout — which is why it is an S and why it waited.

## Acceptance criteria

- [ ] The poll interval grows as a run continues rather than staying flat.
- [ ] Given a run that has just been queued, **When** the screen first reports it, **Then** the
      first few polls are still frequent enough that a short run does not look frozen — the
      cheap case must not be made worse to fix the expensive one.
- [ ] The interval is capped, so a long run settles at a bounded rate rather than growing until
      the screen stops feeling live.
- [ ] A test asserts the interval actually changes between successive polls, rather than
      asserting a timer was set.
- [ ] The stale comment saying a rebuild "takes tens of minutes" is corrected in the same change.

## Dependencies

- None.

## Open questions

- Should progress arriving (`chunks_done` advancing) reset the interval? A run that is visibly
  moving is one a person is more likely to be watching, and one whose next update is worth
  having sooner. It is a nicety rather than a requirement, and the criteria above do not ask
  for it.
