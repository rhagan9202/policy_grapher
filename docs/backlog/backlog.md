# Backlog

*Living document — edit in place. Last reviewed: 2026-08-26*

Ordered by priority: the top row is the next thing to pick up. See
[README](README.md) for how items move through this list, and
[CONVENTIONS](../CONVENTIONS.md) for when an item earns its own file.

All items below are derived from [SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md) and
the MVP definition of done in the [vision](../planning/vision.md).

## Ready

Refined, estimated, and pickable right now.

The tech-debt surge, planned 2026-08-21 and sequenced across sprints 3–5 — see the
[roadmap](../planning/roadmap.md#the-tech-debt-surge). **Every row below carries a size**,
using the [t-shirt scale](README.md#estimation) adopted at the same session, so the
[Definition of Ready](README.md#definition-of-ready) is met here for the first time.

Sprint 3 closed on 2026-08-21 with all seven of its items delivered; they are recorded in
[sprint 3's review](../sprints/sprint-03/review.md), which is where the Done table's trim rule
sends older history. Sprint 4's spine, STORY-048, has since landed and moved there too: `POST
/documents/{slug}/versions/{version_id}/rebuild` queues a rebuild onto a Redis-backed RQ
queue that a `worker` service drains, and `GET /rebuilds/{run_id}` reports its progress —
so `rebuild_derived`, `embed_chunks`, `CachedExtractor` and `GraphCacheStore` all have a
caller in the running application now, and Triage, Review and Ask can be filled without
running Python by hand. STORY-052 has since landed too: the backend and worker images are
**399MB** against the 16.6GB measured at sprint start, and `sentence-transformers` is an
optional extra ([ADR-021](../specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md)).
STORY-051 landed too: `.github/workflows/ci.yml` runs both suites on every push and pull
request, with the integration half as its own marker-selected step so it cannot go quiet
([ADR-022](../specs/adr/ADR-022-both-suites-run-on-every-push.md)).

**Ready holds sprint 10's slate.** Sprint 9's four items are all in [Done](#done), and the MVP is met. All ten of sprint 8's items are in [Done](#done) — the
largest commitment this project has made, delivered whole. Every bar in the
[vision](../planning/vision.md#what-success-looks-like)'s definition of done is now closed or
recorded as blocked, and [STORY-094](stories/STORY-094-the-definition-of-done-is-checked.md)
fails a build when one stops being true. The corpus bar had silently fallen to 2 documents
against a bar of 20; it is back to 23.


[Sprint 9's planning session](../sprints/sprint-09/plan.md) starts from the finding sprint 8
could not have predicted: **the product cannot see the responsibilities section of a DoD
issuance**, because DoD writes the part that assigns duties to organisations without modal verbs.
That was the largest open question about whether this product does what it says, and it is a
decided one as of 2026-08-27 — ADR-033 answered it, and STORY-097 moved from Refining to Ready
with the decision discharged and its estimate down from L to M.

**STORY-035 remains the one item that cannot be started.** No `.docx` exists in this repository
to design extraction against, and rules fitted to a document we invented would be measured by a
ratchet that could not tell us they were wrong. STORY-093 made that blocker visible in the vision
where the bar is stated.

The two open MVP bars — STORY-036 (XLSX) and STORY-014 (search) — are deliberately **not** in
this sprint. Both are real and neither serves this goal, and planning picks the goal first.

Sprint 6 delivered all six of its own items rather than leaving Ready empty for want of refining. They are in [Done](#done): obligations became readable (STORY-081),
an edition says whether it was built (STORY-082), the graph can be copied before Reset destroys
it (STORY-083), and three gates that could not fail now can (STORY-084, 085, 086).

[Sprint 7's planning session](../sprints/sprint-07/plan.md) starts from
[Refining](#refining) and [Ideas](#ideas), and carries three questions sprint 6 raised and did
not answer — see its stub.

Before those, Ready had been empty for a reason worth keeping. Between the surge's close and
2026-08-25, an eleven-item audit of the running app — citation page numbers, back matter,
rebuild identity, legacy-cover ingestion, ingest and triage reporting, the document table, and
two network-exposure gaps — was found and fixed directly, the same way STORY-057 and STORY-058
were in sprint 4: landed as work, not filed as a queue for someone else. All eleven are in
[Done](#done). The audit also surfaced three items that were genuinely still open work, in
[Refining](#refining) (STORY-073) and [Ideas](#ideas) (STORY-075) — the third, STORY-074, has
since been fixed inside the same function as the ambiguous-statement defect a whole-branch
review found, and is in [Done](#done). That review added STORY-076 in its place. The same
pattern produced the rebuild job timeout fix on 2026-08-26, also landed rather than filed.

Sprint 6's planning session no longer starts from nothing, but three items is not a sprint:
[Refining](#refining) and [Ideas](#ideas) are still where the rest of its capacity has to come
from, and the [Definition of Ready](README.md#definition-of-ready) still has to be met before
anything else moves into this one.

Two things sprint 5 found and closed that were never in it: **STORY-061**, because sprint 4's
rebuild routes had no client function and so the app could not build its own derived layer; and
the **embedding model's provenance**, which [ADR-020](../specs/adr/ADR-020-model-weights-come-from-us-organisations.md)
had named as the first thing to check if its constraint were ever audited, and STORY-060 was
that audit ([ADR-024](../specs/adr/ADR-024-embedding-weights-come-from-us-organisations-too.md)).

**Sprint 4 closed on 2026-08-22**, but only after its Definition-of-Done walkthrough found two
defects and both were fixed rather than filed — STORY-057 and STORY-058
([ADR-023](../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)). With those in,
a wiped volume reaches **38 and 34 chunks, 241 obligations, 313 proposals and a ranked Triage
row** through product actions alone; the sequence is in the
[README](../../README.md#filling-triage-and-review). What remains is sprint 5.

| ID | Item | Epic | Est. | Sprint | Notes |
| --- | --- | --- | --- | --- | --- |

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| STORY-101 | Every edition is rebuilt under the rules the extractor now has | — | **Est. M.** ADR-033 and ADR-034 both refuse items the graph already holds, and neither touches what is stored. Measured before the guards: 34 of 196 obligations (17%) misquote their chunk, 20 carry the string `"null"` as an actor, and 8 attribute USD(A&S)'s duties to the DoD CIO, DOT&E and the CJCS. Acceptance is a query over stored data, not a test of the extractor. See [STORY-101](stories/STORY-101-the-graph-is-rebuilt-under-the-rules-it-now-has.md) |
| STORY-102 | A prompt rule nobody checks is not a rule | — | **Est. L.** Three sprints, three rules the prompt stated and nothing enforced — the modality word, word-for-word quoting, and no placeholder actor — each unenforced for at least a sprint, each found in the data rather than by a test, each then fixed deterministically in under an hour. A prompt is not executable and nothing connects it to the validators. The decision is the work. See [STORY-102](stories/STORY-102-a-prompt-rule-nobody-checks-is-not-a-rule.md) |
| STORY-100 | An office is one actor, not several spellings | — | **Est. L.** Found by sprint 9's rebuild, the first run of ADR-033 against a real document: of 31 duties assigned by position, one office is recorded as both `USD(A&S)` (12) and `The USD(A&S)` (2), and one actor is the fragment `acquisition executive`. `actor` is free text on every modality and nothing claims it is canonical, so this is a limitation rather than a defect — but a positional duty is *defined* by the office it is assigned to, and **richer metadata and relationships** in the roadmap's Later section builds `:Entity` over exactly this field. L because the shape is undecided: normalise on the way in, resolve to an `:Entity`, or narrow the claim. See [STORY-100](stories/STORY-100-an-office-is-one-actor-not-several-spellings.md) |
| STORY-103 | The prompt stops contradicting itself about ASSIGNED | — | **Est. S.** Found by ADR-036 while enumerating the prompt's rules: two general sentences that ADR-033 falsified and nobody noticed, because reading the prompt top to bottom does not surface a contradiction between paragraph three and paragraph nine. A statement must include its subject (an `ASSIGNED` statement begins at the verb) and an actor is copied from the statement (an `ASSIGNED` actor comes from the heading above it). Not fixed when found: correcting the prompt bumps `PROMPT_VERSION` and discards the extraction cache, and three rebuilds were in flight. See [STORY-103](stories/STORY-103-the-prompt-stops-contradicting-itself.md) |

## Refining

Understood well enough to discuss, not yet ready to start.

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| ~~STORY-013~~ | ~~Referenced documents that aren't in the corpus are distinguishable~~ | — | **Superseded by STORY-026.** Resolved by [ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md); ID retained per [CONVENTIONS](../CONVENTIONS.md) |
| STORY-035 | Ingestion accepts a DOCX issuance | — | Same `extract_document` protocol as STORY-016, own extraction rules. Blocked: no DOCX sample exists to design against. Likely easier than PDF — `python-docx` exposes heading styles, so locating the references section stops being the risky stage |

## Ideas

Unrefined. No commitment implied.

| ID | Item | Notes |
| --- | --- | --- |
| STORY-020 | Model policy points as nodes rather than whole documents | The Policy Concierge direction in the [vision](../planning/vision.md); a schema migration |
| STORY-021 | Capture applicable entities and enforcement ownership as graph relationships | Same — new labels and relationship types |
| STORY-023 | A user can ask a question in natural language and get graph results | LLM constructs the Cypher and calls `POST /query`. The two gates it carried are now half-cleared: STORY-019 (auth) and STORY-024 (query constraints) have landed, so only the schema settling remains — see [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md), superseding [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) |
| STORY-045 | A user can run a bounded Cypher query from the UI | `POST /query` and `runQuery()` are built and unreachable. Deliberately parked in Ideas rather than Refining: [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md) superseded [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) precisely to stop assuming the audience writes Cypher, so putting a query box in front of them argues against a decision this project has already taken once. If it is built, it belongs behind an operator-facing route, not in the main navigation — and [STORY-023](#ideas) is the answer for the audience ADR-008 actually describes |

## Done

Closed items, most recent first. Trim to the last two sprints — older history lives in
sprint reviews.

A `—` in the Sprint column means the item was not delivered inside a sprint. The rule above
trims to sprint reviews, so a row with no sprint behind it has nowhere to be trimmed to and
stays here.

Sprint 3's rows were trimmed on 2026-08-24, seven of eleven: [sprint 3's
review](../sprints/sprint-03/review.md) records STORY-038, 039, 040, 041, 049, 050 and 053, so
removing them here loses nothing. Four more had been carrying a `3` that was never true —
STORY-016, STORY-033, STORY-034 and STORY-037 — and they now carry `—` instead. Git dates all
four to **2026-08-13**: sprint 2's review was written at 05:51 that morning and STORY-033
closed at 06:16, twenty-five minutes after the record was frozen. Sprint 3 did not begin until
2026-08-21 and delivered a disjoint set. The `3` was written on 2026-08-13, before
`docs/sprints/sprint-03/` existed, and has pointed at the wrong sprint ever since.

Neither review is wrong and neither was edited. Sprint 2's names STORY-033 as a stretch item
that was never started, which was true when it was written. These four are the DI-1 completion
work done between the two sprints, and they are documented — see
[the DI-1 completion design](../superpowers/specs/2026-08-13-di-1-completion-design.md), [the
PDF extraction design](../superpowers/specs/2026-08-13-story-016-pdf-extraction-design.md) and
the implementation plans beside them.

| ID | Item | Sprint |
| --- | --- | --- |
| STORY-099 | Every declared route is reached by a real request | 9 |
| STORY-098 | Front matter is not offered to the extractor | 9 |
| STORY-097 | The responsibilities section of an issuance is invisible | 9 |
| STORY-075 | A chunk starting on a section join is attributed to the right page | 9 |
| STORY-096 | How a reissue's edits are recognised is decided | 8 |
| STORY-095 | The rejection rate is diagnosed | 8 |
| STORY-094 | The MVP's definition of done is checked, not attested | 8 |
| STORY-093 | The vision says which of its bars cannot be started | 8 |
| STORY-076 | A rebuild says how many rejections a re-key stranded | 8 |
| STORY-073 | Each document edition is ratcheted against its own reference set, not its current successor's | 8 |
| STORY-047 | A reissued document's edits are recognised as edits, not as wholesale replacement | 8 |
| STORY-036 | Ingestion accepts an XLSX manifest | 8 |
| STORY-031 | Near-duplicate documents can be reconciled | 8 |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | 8 |
| STORY-092 | The Authority and Entity helpers go | 7 |
| STORY-091 | The README's corpus numbers describe what the product produces | 7 |
| STORY-090 | Review's empty queue names its upstream cause | 7 |
| STORY-089 | The rebuild status poll backs off | 7 |
| STORY-088 | An unparseable item costs what the ADR says it costs | 7 |
| STORY-087 | The blast radius of an unparseable item is decided | 7 |
| STORY-086 | Route reachability is a test, not a paragraph | 6 |
| STORY-085 | The ranking weights ADR-025 records are asserted, not just commented | 6 |
| STORY-084 | The extraction floors are measured against the gold set that exists | 6 |
| STORY-083 | A graph can be exported before it is destroyed | 6 |
| STORY-082 | A document says whether its derived layer was built, when, and with what | 6 |
| STORY-081 | A user can read the obligations extracted from an edition | 6 |
| STORY-080 | CI builds and measures the lean stack, and says which stack it measured | — |
| STORY-079 | A lean stack with no models is one documented command | — |
| STORY-078 | `docker compose up --build` brings up the whole product | — |
| STORY-077 | The Ingest screen offers the files the backend can read, instead of asking for a name | — |
| STORY-074 | A rebuild's colliding re-points are skipped, not left to abort the whole transaction | — |
| STORY-071 | No service listens beyond loopback | — |
| STORY-072 | No developer's own hostname is a committed default | — |
| STORY-070 | The document table is bounded, and says when it truncated | — |
| STORY-069 | A document's references are named and reachable from its own page | — |
| STORY-068 | The document table says which documents have text | — |
| STORY-067 | Triage distinguishes "nothing changed" from "nothing was extracted" | — |
| STORY-066 | An ingest says which edition it recorded and how much text it read | — |
| STORY-065 | Ingestion finds the references on a legacy cover | — |
| STORY-064 | A rebuild carries review decisions across a change of identity | — |
| STORY-063 | Back matter is its own section, not the tail of the last numbered one | — |
| STORY-062 | A citation names the page the quoted text is on | — |
| STORY-061 | The derived layer can be built from the UI | 5 |
| STORY-055 | Extraction recognises the modality this corpus actually uses | 5 |
| STORY-046 | A user can empty the graph from the UI | 5 |
| STORY-042 | A reviewer can work through the whole queue, not just its head | 5 |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | 5 |
| STORY-043 | A user can ingest a document from the UI | 5 |
| STORY-044 | A user can create, delete and cross-reference documents from the UI | 5 |
| STORY-060 | No decision is enforced against a default the deployment overrides | 5 |
| STORY-059 | The stack coming up is proved by a check, not by a person | 5 |
| STORY-057 | One unparseable item does not destroy the whole rebuild | 4 |
| STORY-058 | The extractor's per-call timeout is configurable, and long enough for CPU inference | 4 |
| STORY-051 | Both suites run on a check nobody has to remember | 4 |
| STORY-052 | The backend image carries only what it needs to run | 4 |
| STORY-056 | A model server is available without installing anything on the host | 4 |
| STORY-054 | The extraction ratchet has been run against a real model at least once | 4 |
| STORY-048 | An ingested edition's derived layer can be built from the running app | 4 |
| STORY-019 | Authentication on the API | — |
| STORY-024 | `POST /query` constrains what a generated query may do | — |
| STORY-037 | A CSV re-ingest stops demoting a PDF-ingested document to `:External` | — |
| STORY-016 | Ingestion accepts a PDF issuance and extracts its references | — |
| STORY-034 | Relational facts move off `Document` and onto typed edges | — |
| STORY-033 | Linting runs over both backend and frontend | — |
| STORY-010 | A user can browse and filter the document table by name | 2 |
| STORY-008 | An agent can run a raw Cypher query against the graph | 2 |
| STORY-027 | A user can add and remove a reference between two documents | 2 |
| STORY-006 | A user can create, update, and delete documents through the API | 2 |
| STORY-005 | A user can list all documents and read one with what it cites and what cites it | 2 |
| STORY-028 | An operator can wipe the graph and start clean | 2 |
| STORY-032 | A TypeScript error fails the frontend test command | 2 |
| STORY-015 | The rendered graph is bounded by a configurable cap, and says when it truncated | 1 |
| STORY-004 | Ingest rejects a malformed CSV with a clear error instead of a stack trace | 1 |
| STORY-012 | The sample DoD corpus loads and renders end to end | 1 |
| STORY-030 | Integration tests run against a real, disposable Neo4j | 1 |
| STORY-029 | The stack comes up with the sample corpus already loaded | 1 |
| STORY-011 | The frontend talks to the backend through one typed API client | 1 |
| STORY-009 | A user can see the corpus as a force-directed graph, click a node, and expand its external references | 1 |
| STORY-007 | The UI can fetch a legible graph in one call | 1 |
| STORY-026 | External documents are distinguishable from corpus documents in the graph | 1 |
| STORY-003 | A CSV of documents and references becomes a graph, and re-ingesting it changes nothing | 1 |
| STORY-025 | Every document gets a stable, URL-safe slug that survives re-ingest | 1 |
| STORY-002 | Backend connects to Neo4j and enforces unique constraints on `slug` and `name` | 1 |
| STORY-001 | A developer can bring the full stack up with one command | 1 |
