# Roadmap

*Living document — edit in place. Last reviewed: 2026-08-27*

Sequencing and intent, not commitments with dates. Individual work items live in the
[backlog](../backlog/backlog.md); this is the altitude above that.

## Now

**DI-1 is complete** — 18 of 18 stories, closed on 2026-08-13 — and PDF ingestion
(STORY-016) has since landed on top of it. `./scripts/init-env.sh && docker compose up`
ingests `data/samples/dod_policy_references_08122026.csv` and renders its 23 documents as a
navigable graph at `/`, with the full 438-document corpus listed and searchable at `/documents`.
`POST /ingest` now also accepts a DoD issuance PDF, extracting the document and the
references it cites.

Every route but `/health` requires a bearer token, and the browser app sends one: the vite dev
proxy injects the token `./scripts/init-env.sh` generates, so a clean clone loads both views
after `./scripts/init-env.sh && docker compose up`. See
[ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md) and
[ADR-010](../specs/adr/ADR-010-secrets-leave-the-repository.md).

The feasibility question DI-1 existed to answer is answered: the pipeline holds end to end at
sample-corpus scale, and prose extraction works at 78–100% per document against the corpus as
an oracle. What remains untested is **scale** — every measurement so far is against five
documents and one 23-row manifest.

## Next

**Development Increment 2 is designed and approved** — see the
[DI-2 design](../superpowers/specs/2026-08-20-di-2-design.md), approved 2026-08-20. Phase 0, the
[security gate](../superpowers/plans/2026-08-20-di-2-phase-0-security-gate.md), has landed:
bounded `POST /query` (STORY-024), bearer-token authentication (STORY-019), and locally
generated secrets. Phase 1
([versioned schema](../superpowers/plans/2026-08-20-di-2-phase-1-versioned-schema.md)) has
landed: a `:Document` is now the instrument and its editions hang off it as
`:DocumentVersion` nodes with a content-derived identity and a derived `SUPERSEDES` chain. A
single-PDF ingest records one edition and `GET /documents/{slug}/versions` serves the chain;
the manifest path records none, because a CSV row describes no edition.

**`:Authority` and `:Entity` are written by no code path that runs.** This paragraph claimed
them as landed until sprint 6's planning review checked: `merge_authority`, `attach_authority`
and `merge_entity` exist in `backend/src/policy_grapher/versions.py` and are called only by
`backend/tests/test_versions.py`; no router and no ingest path reaches them, and the live graph
holds zero of each. The functions and their tests are real, so the capability is *written* but
not *reachable* — the same distinction sprint 5's retrospective drew about client functions, one
level up. Corrected 2026-08-26; the two labels belong under [Later](#later) with the richer
metadata they were meant to serve, and nothing should cite them as delivered until an ingest
path calls them. **The code went in sprint 7 (STORY-092)**: roughly thirty lines of Cypher and
the tests that were their only caller, which are what made an unreachable capability look
delivered. Writing them again from a spec that says what they must do will be cheaper than
maintaining a version that never ran. See
[ADR-011](../specs/adr/ADR-011-instruments-have-versions.md). Phase 2
([text storage and section-aware chunking](../superpowers/plans/2026-08-20-di-2-phase-2-text-and-chunking.md))
has landed: a PDF ingest now keeps the page text it used to discard, chunks it along the
document's own section hierarchy, and writes the result as `:Chunk` nodes hanging off the
edition they came from. `GET /documents/{slug}/chunks` serves them, newest edition by default.
`:Chunk` is the first *derived* label — droppable and rebuildable, with an identity keyed on a
chunk's place in the document's structure so a chunker improvement only moves the ids of the
sections it actually changes. See
[ADR-012](../specs/adr/ADR-012-chunks-follow-sections.md). Phase 3
([obligation extraction port](../superpowers/plans/2026-08-20-di-2-phase-3-extraction-port.md))
has landed: obligations are extracted from chunk text behind a provider-agnostic
`ObligationExtractor` port and written as `:Obligation` nodes that hang off the edition
mandating them and anchor to the chunk they were read from. The default adapter extracts
nothing and needs no model server, so a fresh clone still passes `uv run pytest`; a local
HTTP adapter is the development option. Schema validation lives in our code on every adapter,
results are cached on chunk *content* rather than chunk id, and a hand-labelled gold set
ratchets precision, recall and modality accuracy per adapter — so a provider swap is a tested
property rather than a hope. The gate announces loudly when it did not run. See
[ADR-013](../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md). Phase 4
([typed links and the review queue](../superpowers/plans/2026-08-20-di-2-phase-4-links-and-review.md))
has landed: an obligation of ours is linked to the higher-level obligation it implements —
proposed by machine as `IMPLEMENTS_PROPOSED`, promoted to `IMPLEMENTS` only by a human verdict,
and surviving a full rebuild of the derived layer. Verdicts live in a canonical `:LinkDecision`
keyed on the two obligation ids, so a re-extraction replays them instead of discarding them;
rejections are stored as well as approvals, and a rebuild reports approvals it could no longer
apply rather than passing over them. `GET /review/queue` and
`POST /review/{source_id}/{target_id}` serve the queue, with the actor taken from the
authenticated principal and never from the request body. See
[ADR-014](../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md). Phase 5
([change detection and propagation](../superpowers/plans/2026-08-20-di-2-phase-5-diff-and-propagation.md))
has landed, and with it the increment's deliverable: `GET /triage?to_version_id=` diffs an
edition against the one it supersedes into `:Change` nodes, then walks `IMPLEMENTS` to the
clauses of ours that have to answer for them, ranked by modality and change kind. A reworded
obligation in the same section is one `MODIFIED` rather than a remove-plus-add; a section with
several changes falls back and says so rather than guessing a pairing. Nothing on the path is a
model call, so every row is explained by a path a person can walk, and unlinked changes are
counted so an empty answer is never mistaken for an all-clear. See
[ADR-015](../specs/adr/ADR-015-changes-are-detected-and-ranked.md).
and Phase 6
([retrieval, question answering and the UI](../superpowers/plans/2026-08-20-di-2-phase-6-retrieval-and-ui.md))
has landed, and with it DI-2 — **as a library**. Its backend brought the embedding port and vector index,
three-signal hybrid retrieval, and grounded question answering at `POST /ask` — see
[ADR-016](../specs/adr/ADR-016-embeddings-are-a-port.md) and
[ADR-017](../specs/adr/ADR-017-answers-select-templates.md). Its UI brought Triage, Review and
Ask screens, and the navigation DI-1 never shipped: routes and links are declared from one
list, so a screen cannot exist without a way to reach it. A `SPEC-002` is not yet written.

**What DI-2 did not deliver, found on 2026-08-21 — now closed.** None of that machinery was
reachable from the running application: `rebuild_derived`, `embed_chunks`, `CachedExtractor`
and `GraphCacheStore` had no caller in `src/`, only in tests, and auto-ingest loads a CSV
manifest, which by design records no edition and no text. A clean `docker compose up` yielded
439 documents, zero chunks and zero obligations, with Triage, Review and Ask empty and no
product action that could fill them. Every phase's tests passed; nothing composed them. That
was the reason for the surge below, and
[STORY-048](../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) has since
closed it: `POST /documents/{slug}/versions/{version_id}/rebuild` validates an edition and
queues a rebuild of its derived layer onto a Redis-backed RQ queue, a `worker` service runs
it, and `GET /rebuilds/{run_id}` reports progress chunk by chunk and the counts it produced.
Proposals are generated for the candidate editions the caller names — the graph records no
tier information, so the route asks rather than guesses. See the
[README quickstart](../../README.md#building-an-editions-derived-layer) for the command
sequence.

## The tech-debt surge

Planned 2026-08-21, revised 2026-08-23. Three sequenced sprints against one standing goal: **a stable, runnable
base, combed for bugs, that does what these planning documents say it does.** Every item is
in [Ready](../backlog/backlog.md#ready) with a size. The arc lives here, in a living
document; each sprint's plan is written at its own start and frozen
([why](../sprints/README.md#cadence)).

| Sprint | Goal | Items |
| --- | --- | --- |
| **3 — Truth and reachability** ✅ | The app tells the truth about its own state: starts empty, says so, and carries none of the audit's UI defects | STORY-038, 039, 040, 041, 049, 050, 053 |
| **4 — The app can fill its own screens** ✅ | The derived layer is buildable from the application, and a check exists that would catch the next regression | STORY-048 ✅, 051 ✅, 052 ✅, 056 ✅, plus stretch 054 ✅ and two defects found by its own walkthrough, 057 ✅ and 058 ✅ |
| **5 — The UI reaches the whole API** ✅ | No backend capability is left without a way to reach it; the corpus-management bar in [What success looks like](vision.md#what-success-looks-like) is met | STORY-017, 042, 043, 044, 046, plus 055 pulled forward and 059, 060 from sprint 4's retrospective |

**The surge is over.** Sprint 5 closed on 2026-08-23 with all eight committed items plus STORY-061, and [Ready](../backlog/backlog.md#ready) is now empty — the backlog written for this surge is exhausted, so sprint 6 plans from Refining and Ideas.

**It was three sprints after all, and the fourth row is gone.** It was planned as three
and drawn as four. STORY-054 landed as sprint 4's stretch and STORY-055 moved into sprint 5 at
that sprint's planning session — the retrospective asked for it once there were real numbers to
argue from, and nothing else was left in the row. Sprint 5 is therefore the last of the surge,
and it carries the largest commitment this project has made: eight items against a session that
has delivered six item-equivalents. That is recorded as a deliberate overcommit in the
[sprint 5 plan](../sprints/sprint-05/plan.md#committed), with STORY-055 named as the item
expected to slip if one has to.

**What the surge deliberately does not close.** Two MVP bars in the
[vision](vision.md#what-success-looks-like) stayed open past it, because they are feature work
rather than debt: DOCX ingestion and XLSX manifests. **Sprint 8 closes one and cannot close the
other.** XLSX landed as [STORY-036](../backlog/backlog.md#done); DOCX
([STORY-035](../backlog/backlog.md#refining)) remains unstartable because no `.docx` exists in
`data/samples` to design against, and the vision now says so where the bar is stated rather than
leaving the reason in a backlog note.
[STORY-047](../backlog/stories/STORY-047-reissues-read-as-replacement.md) — a reissue's edits
reading as wholesale replacement — also stays in Refining: its open questions reopen a frozen
decision in [ADR-015](../specs/adr/ADR-015-changes-are-detected-and-ranked.md), and that is an
ADR to write, not a sprint item to commit. DI-2 builds the
semantic substrate that turns DI-1's bibliographic graph into a policy knowledge graph —
document text, the obligations inside that text, and version supersession — proven by one
deliverable, **impact triage**: *a higher-level policy changed; which of our policies are
affected, and how urgently?* Several items in [Later](#later) fall inside that scope, notably
policy point extraction and richer metadata and relationships.

Closing the gap between DI-1 and the MVP definition of done in the [vision](vision.md):

- **Multi-format ingestion** — DOCX and XLSX alongside CSV and PDF (STORY-035, STORY-036).
  PDF landed in STORY-016; DOCX and XLSX are their own problems, not an extension of it —
  parsing prose documents differs from reading a column of pre-extracted references, and an
  XLSX manifest is closer in shape to the CSV path than to either extraction story.
- **Corpus management** — tables of ingested documents allowing review of extracted text
  and metadata, beyond DI-1's read-only document table.
- **Scale to the MVP bar** — 20 documents, and a graph that stays explorable at the render
  cap (300 nodes by default, configurable). The stored graph will be several times that.
- **Search by document name or ID** as a first-class capability rather than client-side
  table filtering.

## Later

The Policy Concierge capabilities that DI-1's graph schema doesn't yet reach. DI-1 models a
document and one relationship type (`REFERENCES`); the program intent needs considerably more:

- **Policy point extraction** — the unit of interest becomes the individual policy, not the
  document that contains it.
- **Richer metadata and relationships** — which entities a policy applies to, who is
  responsible for enforcing it. Both imply new node labels and relationship types.
- **Lineage views** — showing a policy's ancestry and descendants, not just direct neighbors.
- **External reference handling beyond a label.** DI-1 settled the immediate question:
  cited documents absent from the corpus carry an `:External` label and no `reference_role`
  ([ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md), STORY-026),
  and they are 415 of the graph's 438 nodes. What stays open is what they should *become* —
  they exist only as a name, so they cannot be ingested, browsed, or reasoned about until
  something resolves them to real documents.
- **LLM-constructed queries.** The demo assumes users write Cypher
  ([ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md)); as development
  matures, queries get constructed via LLM instead. This is what opens the system to the
  non-technical audience the corpus implies. Two things gated it. The security half is
  closed: `POST /query` is authenticated, read-only, timed and row-capped
  ([ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md),
  [ADR-009](../specs/adr/ADR-009-query-is-read-only-and-bounded.md)), so generated Cypher no
  longer runs anonymously against an unbounded endpoint. What still gates it is the graph
  schema settling — a natural-language layer over a schema still in migration is wasted work.

## Not in the initial surge

Carried from the [vision](vision.md#explicit-non-goals): RAG, vector embeddings, LLM calls,
multi-stage Docker builds, and pagination are all out of scope while the demo definition of
done is the target. Auth has since left this list — DI-2's security gate landed it (see
[Now](#now)), because a hosted target made it a prerequisite rather than a nicety.

Every one of these is deferred, not excluded. This section is a statement about *now*, not
about the life of the project — LLM-constructed queries already have a place in
[Later](#later), and the rest can earn one the same way.
