# STORY-082: A document says whether its derived layer was built, when, and with what

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As an operator returning to the app, I want each edition to say whether its derived layer has
been built, when, and with which extractor, so that I can tell "never built" apart from "built
and found nothing" without reading container logs — and so that a rebuild I started earlier is
still findable.

## Context

Two gaps with one cause: nothing durable records that a rebuild happened.

**A rebuild's result is unreachable without its run id.** `GET /rebuilds/{run_id}` needs an id,
and the only way to obtain one is to start a rebuild. The id lives in React state
(`frontend/src/views/DocumentDetail.tsx:145`) — no `localStorage`, no server-side list. Reload
the tab and the run becomes unreachable while still running.

This got sharper on 2026-08-26. `rebuild_job_timeout_seconds` was raised from 1800 to 28800
because the old value could not accommodate a real rebuild — the largest edition in
`data/samples` is 204 chunks at ~104 seconds each, close to six hours. `config.py` now says one
day of result TTL is "long enough for a person to start an overnight rebuild and read it in the
morning." That is currently false: they cannot, because the id is gone.

**An edition does not say what state it is in.** `DocumentOut` carries `is_external`, `name`,
`referenced_by`, `references`, `slug`, `version_count`. `DocumentVersionOut` carries
`version_id`, `effective_date`, `checksum`, `source_uri`, `supersedes`. Neither says anything
about the derived layer.

The consequence is concrete. An edition showing zero obligations has two possible causes that
need opposite actions: never rebuilt, or rebuilt with the `null` extractor — the default in
`config.py`, which writes chunks and no obligations by design
([ADR-028](../../specs/adr/ADR-028-the-default-stack-carries-its-models.md)). `RebuildStatus`
already reports `extractor_adapter` and `embedder_adapter` for exactly this reason, and its
comment says so: "With the default `null` extractor a run writes chunks and no obligations,
which is correct and looks exactly like a broken one unless the screen can say so." That
reporting exists only for the lifetime of one poll.

RQ is the wrong home for the fact. Its registries are explicitly ephemeral —
`rebuild_result_ttl_seconds` expires a result after a day, deliberately. The graph is where
durable facts live, and the precedent is already set: `ExtractionCache` is a graph label
([ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)).

## Acceptance criteria

- [ ] A rebuild that completes records on the `DocumentVersion` it built: when it finished, the
      extractor adapter, the embedder adapter, and the counts it wrote.
- [ ] `GET /documents/{slug}/versions` returns those fields, empty or null for an edition never
      built.
- [ ] A document's page shows, per edition, whether the derived layer was built, when, and with
      which extractor.
- [ ] Given an edition built with the `null` extractor, **When** a user views it, **Then** the
      page says the extractor wrote no obligations by design — not merely that there are zero.
- [ ] Given a rebuild is in flight and the user reloads the page, **When** the page loads,
      **Then** it finds that run and resumes reporting its progress without the user holding
      the run id.
- [ ] Given a rebuild failed, **When** a user returns later, **Then** the page says the last
      attempt failed and why, rather than showing the edition as merely unbuilt.
- [ ] A run whose worker died leaves the edition readable as "last build failed", not
      permanently "building".

## Notes

**Scope is the last build, not full run history.** One set of fields per edition, overwritten by
each rebuild. A durable log of every run that ever executed is a larger thing, needs a decision
about retention, and is not required by anything above — it belongs in Ideas if it is wanted.
Keeping this to last-build state is what holds the item at M.

Persisting to the graph rather than Redis is a choice this story takes, not one it defers. It
follows an established pattern (`ExtractionCache`) and the alternative is ruled out by an
existing decision — RQ's TTL is deliberately short, so it cannot answer "was this ever built".
Recording it does not warrant an ADR; if review disagrees, the ADR is the work and the item
becomes L, per the [estimation guidance](../README.md#estimation).

The reload criterion is satisfied by the same data: given the edition's last run and its state,
the page can re-attach to a run still in progress. It does not need a separate persistence
mechanism, which is why the two gaps are one story rather than two.

## Dependencies

- STORY-048 (the derived layer can be built from the running app) — **Done.**
- STORY-061 (the derived layer can be built from the UI) — **Done.** This story extends the
  screen that story built.
- `_record_adapters` in `backend/src/policy_grapher/jobs/rebuild.py` already computes the
  adapter names for `job.meta`; this story gives them a durable home.

## Open questions

- Does a rebuild that fails partway record its partial counts, or only that it failed? The
  2026-08-25 timeout wrote 30 of 37 chunks and reported `counts: {}` — the chunks were real and
  cached, but the run reported nothing. Recording partial progress is more honest; recording it
  as if it were a completed build is not. The criteria above require the failure to be visible
  and leave the shape of partial counts to implementation.
