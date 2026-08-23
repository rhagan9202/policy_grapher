# Sprint 5 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next
> one ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)). Nothing below is committed:
> sprint 5 has not been planned, and the table is what
> [Ready](../../backlog/backlog.md#ready) holds on 2026-08-22, in its order.
>
> **TODO:** hold the planning session, then replace this file wholesale.

Third and last sprint in the [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge).

## What Ready holds today

| ID | Item | Est. |
| --- | --- | --- |
| STORY-055 | Extraction recognises the modality this corpus actually uses | M |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | M |
| STORY-042 | A reviewer can work through the whole queue, not just its head | M |
| STORY-043 | A user can ingest a document from the UI | M |
| STORY-044 | A user can create, delete and cross-reference documents from the UI | L |
| STORY-046 | A user can empty the graph from the UI | S |

## What sprint 4 asks this planning session to settle

Carried from sprint 4's [review](../sprint-04/review.md) and
[retrospective](../sprint-04/retrospective.md), so they survive the sprint boundary:

- **STORY-055 now has real numbers to argue from.** The first end-to-end run against
  `llama3.1:8b` extracted 120 and 121 obligations from the two editions of DoDD 5000.01 — a
  floor, not a measure, since `will` outnumbers `shall` 458 to 93 across the samples. Widening
  `Modality` needs a superseding ADR and its own ratchet leg.
- **Add "one rebuild against the real extractor" to the Definition of Done walkthrough.** Every
  walkthrough before sprint 4's closing one satisfied its derived-layer bullet with the `null`
  extractor, which is how the extraction path stayed unwalked for three sprints.
- **Audit for the ADR-020 gap:** constraints tested against an application default while
  `docker-compose.yml` supplies a different one. One instance was found and fixed; nobody has
  checked the other settings.
- **Add the compose-build CI job** deliberately left out of STORY-051. "Runs under
  `docker compose up` from a clean checkout" is the only Definition-of-Done gate nothing
  automated covers.
- **Reconsider what `unlinked_changes` looks like to a reviewer.** Sprint 4's walkthrough saw
  Triage report 234 changes and zero rows until a proposal was approved. That is correct — a
  change stays unlinked until something of yours implements the clause it touches — and it reads
  as a defect until you know. Worth a screen that says so.
