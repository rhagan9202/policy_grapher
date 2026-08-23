# Sprint 5 — Review

**Date:** 2026-08-23

*Dated record — a snapshot of what happened.*

## Against the goal

Goal was: no backend capability is left without a way to reach it from the UI — the
corpus-management bar in [What success looks like](../../planning/vision.md#what-success-looks-like)
is met.

**Met.** All nineteen backend routes have a UI caller. `POST /query` is the single deliberate
exception at the screen level, on [ADR-008](../../specs/adr/ADR-008-authenticated-non-cypher-audience.md)'s
grounds; its client function exists.

Suites at close: **574 backend tests** (550 at sprint start) — 569 passing and **5 skipped by
design** — and **141 frontend tests** (90 at start), green, output pristine.

The five skips are named rather than left to be discovered. `tests/test_config_composition.py`
parametrises over every defaulted variable in `docker-compose.yml`; three are not `Settings`
fields at all (`EXTRAS` is a build argument, `RQ_REDIS_URL` is read by the `rq` CLI,
`VITE_ALLOWED_HOSTS` belongs to the frontend), and two — `EXTRACTOR_BASE_URL` and `REDIS_URL` —
are listed in `DELIBERATE_DIFFERENCES` because a container reaches those services by name and a
host reaches them on loopback. Each skip prints its reason. A skip nobody reads is how the
ADR-020 gap survived for a whole ADR's lifetime, so these say why they are skipping.

## Completed

| ID | Item | Est. |
| --- | --- | --- |
| STORY-059 | The stack coming up is proved by a check, not by a person | S |
| STORY-060 | No decision is enforced against a default the deployment overrides | S |
| STORY-044 | A user can create, delete and cross-reference documents from the UI | L |
| STORY-043 | A user can ingest a document from the UI | M |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | M |
| STORY-042 | A reviewer can work through the whole queue, not just its head | M |
| STORY-046 | A user can empty the graph from the UI | S |
| STORY-055 | Extraction recognises the modality this corpus actually uses | M |
| STORY-061 | The derived layer can be built from the UI | — *(found in-sprint)* |

**Delivered:** 8 of 8 committed, plus STORY-061 and two fixes that belong to earlier stories.
**The overcommit the plan recorded did not bite**, and the plan's own reasoning for why is what
held: five of the eight were UI work over an API that already existed, and STORY-044's L was
breadth rather than an unmade decision. STORY-055, named at planning as the item expected to
slip, did not.

**STORY-061 was not in the sprint and the goal could not be met without it.** The plan's
Definition of Done said "no client function in `api/client.ts` is left without a caller", and
that check passes trivially against a client that never modelled a route at all. Comparing the
*routers* against the client instead found `POST /documents/{slug}/versions/{version_id}/rebuild`
and `GET /rebuilds/{run_id}` — sprint 4's entire deliverable — with no client function, so the
application could not build its own derived layer. The same class of gap `listChunks` was, one
sprint newer. `architecture.md` now records the corrected check.

**STORY-060's audit found what ADR-020 said it would.** The default embedding model was
published by UKP Lab at TU Darmstadt, and ADR-020 had named it "the first thing to check if this
constraint is ever audited".
[ADR-024](../../specs/adr/ADR-024-embedding-weights-come-from-us-organisations-too.md) extends
the provenance rule to embedding weights and moves the default to
`Snowflake/snowflake-arctic-embed-s` — 384 dimensions, verified by loading it, so the index
geometry is unchanged. Nothing had ever been embedded, which made it the one moment the change
was free.

**STORY-057 was not finished when sprint 4 closed it, and re-reading its criteria is what
found that.** The count of rejected chunks shipped; "and why", and "visible to an operator
without reading container logs", did not. Reasons now ride on the job's meta — the mechanism
progress already uses, and for the same reason: meta is written *during* a run, so an operator
watching an hour-long rebuild sees failures as they happen.

**STORY-055 changed what a rebuild costs, and the number is worth recording.** Extraction went
from roughly 45 seconds per chunk to **104**, because the model now has far more to report. Not
a regression — it is the change working — but a full-corpus rebuild is now about twice the wall
clock it was, and any plan that assumes sprint 4's timings will be wrong.

## The walkthrough

Run against a wiped volume on 2026-08-23, **driven through a real browser**. That constraint was
added at planning precisely because a `curl`-driven walkthrough would pass while the thing being
claimed — that the API is reachable without a terminal — stayed untrue.

| State | Result |
| --- | --- |
| Empty | 0 documents; Graph, Triage, Review and Ask each explain emptiness rather than rendering blanks |
| Documents only | 438 documents via the Ingest screen; 2 suspected duplicate names surfaced |
| Documents with editions | both editions of DoDD 5000.01, ingested from the UI |
| Derived layer built through the product | **3 rebuilds against `llama3.1:8b`, all started from the UI** |
| Triage and Review filled | 264-proposal queue; **a ranked Triage row at score 12.0** |

Rebuild counts: the 2020 edition wrote 34 chunks and **115 obligations**, rejecting 2; the 2018
edition wrote 38 chunks and **96 obligations**, rejecting 3. Every rejection was survived rather
than fatal, which is [ADR-023](../../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)
doing the job it was written for a day earlier.

**The third rebuild is the one worth reading.** Re-running the 2020 edition with 2018 named as a
candidate produced **265 proposals in well under a minute**, because `CachedExtractor` called the
model zero times over unchanged content — [ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)'s
cache demonstrated end to end for the first time, and the difference between a minute and an
hour.

**Two defects found by the walkthrough, both fixed in-sprint.** A queued run rendered
`Building: 0 of 0 chunks`, which reads as a rebuild that found nothing to do rather than one
that had not started. And the rejection reasons above — found by re-reading acceptance criteria
rather than by any test failing.

**One thing the walkthrough taught that no test states.** Triage reported **204 changes and one
row**: 203 have no reviewed link to anything of ours, so they do not appear. That is correct — a
change stays unlinked until a proposal is approved — and it reads as a broken screen until you
know. The screen says the number out loud, which is the only reason it is legible.

## Not completed

Nothing. No item was dropped, deferred, or carried.

## Demo notes and feedback

**This is the first sprint whose result is visible without a terminal.** Every prior demo needed
`curl` to put anything in the graph. A person can now ingest a corpus, read a document's text by
edition, build its derived layer, work a review queue, and empty the graph, without leaving the
browser.

**Ready is empty.** Sprint 5 delivered every refined item, so sprint 6's planning session starts
from Refining and Ideas and has to meet the Definition of Ready before anything moves. That is
the expected end state of a three-sprint surge against a backlog written for it, not an
oversight.

**CI has still never run.** The workflow gained a third job this sprint and no run of it has
executed: the push carrying it was rejected for want of `workflow` scope on the OAuth token.
Everything in it has been run command-by-command locally. The first push remains the experiment.
