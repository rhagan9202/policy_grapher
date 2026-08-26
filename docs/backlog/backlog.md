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

**Ready holds six items, all committed to [sprint 6](../sprints/sprint-06/plan.md).** Three come
from a full walkthrough of every screen and endpoint on 2026-08-25, run against a stack with real
models after the first end-to-end rebuild this project has completed: obligations cannot be read
(STORY-081), an edition does not say whether it was ever built (STORY-082), and the graph cannot
be exported before Reset destroys it (STORY-083). The walkthrough's fourth finding — that there
is no search — was already filed as STORY-014 and stays in [Refining](#refining).

The other three come from sprint 6's planning review and are all gates that could not fail:
the extraction floors guard a gold set that has since doubled (STORY-084), the ranking weights
ADR-025 decided are enforced nowhere (STORY-085), and the route-reachability check sprint 5's
retrospective demanded was written as prose and never automated (STORY-086). All three of the
walkthrough items had their acceptance criteria repaired at planning before being committed —
one contradicted itself, one could not fail, and one needed a property the schema does not
store; each revision is marked in its file.

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
| STORY-081 | A user can read the obligations extracted from an edition | — | M | 6 | The product's central noun, with no endpoint and no screen. Reachable today only as a count in a rebuild report, two at a time in Review, or quoted in a Triage row. A 2026-08-25 rebuild wrote **113 obligations** and confirming that took `cypher-shell` — so extraction quality is unauditable from inside the app. Response shape already exists as `ObligationCitationOut`. See [STORY-081](stories/STORY-081-obligations-are-readable.md) |
| STORY-082 | A document says whether its derived layer was built, when, and with what | — | M | 6 | Zero obligations has two causes needing opposite actions — never built, or built with the `null` extractor — and nothing durable distinguishes them. `RebuildStatus` already reports both adapters for exactly this reason, but only for the lifetime of one poll. The run id lives in React state alone, so reloading the tab strands a run that is still going; raising the job timeout to eight hours on 2026-08-26 made that sharper, since `config.py` now promises an overnight rebuild can be read in the morning and it cannot. See [STORY-082](stories/STORY-082-a-document-says-whether-it-was-built.md) |
| STORY-083 | A graph can be exported before it is destroyed | — | M | 6 | Reset says it itself: "There is no undo and no export." Accurate — no export route exists. It destroys hours of inference and, worse, every review decision, which the confirm dialog already notes a rebuild replays and cannot bring back. Extraction is repeatable; human judgment is not. Export only — restore is a separate **L**, for the reasons [ADR-027](../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) had to work through. See [STORY-083](stories/STORY-083-the-graph-can-be-exported.md) |
| STORY-084 | The extraction floors are measured against the gold set that exists | — | S | 6 | Sprint 5's carried action, which [ADR-025](../specs/adr/ADR-025-will-is-a-modality-and-bindingness-is-derived.md) records was not done: floors set over 3 fixtures and 6 obligations, before `WILL` existed, now guard a 4-fixture 12-obligation gold set. `FLOORS`'s own comment says "**They pass by zero margin**" and that widening the gold set is the prerequisite. That prerequisite landed 2026-08-26 — `FLOORS["null"]` was `{0.0, 0.0, 0.0}`, which disarmed both of the gate's loud skips and made it report green while measuring nothing. See [STORY-084](stories/STORY-084-the-extraction-floors-measure-the-gold-set-that-exists.md) |
| STORY-085 | The ranking weights ADR-025 records are asserted, not just commented | — | S | 6 | `MODALITY_WEIGHT` carries a six-line ADR-025 justification that `WILL` is as binding as `SHALL`, and nothing asserts the value. The existing test checks the table's *keys* equal the enum's members — which correctly caught `WILL`'s addition — and says nothing about the values, so one character sends this corpus's dominant binding modality to the bottom of every Triage ranking with the suite green. Same shape as the ADR-020 defect. See [STORY-085](stories/STORY-085-the-modality-weights-are-asserted.md) |
| STORY-086 | Route reachability is a test, not a paragraph | — | S | 6 | Sprint 5's retrospective made this its number-one change and wrote it into `architecture.md` as prose; it was never automated. Run by hand at sprint 6 planning: 20 of 20 routes have a client function, 19 of 20 have a UI caller, `POST /query` the one deliberate [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md) exception. Compliant today, and nothing would notice when it stopped being. See [STORY-086](stories/STORY-086-route-reachability-is-a-test.md) |

## Refining

Understood well enough to discuss, not yet ready to start.

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| ~~STORY-013~~ | ~~Referenced documents that aren't in the corpus are distinguishable~~ | — | **Superseded by STORY-026.** Resolved by [ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md); ID retained per [CONVENTIONS](../CONVENTIONS.md) |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | — | MVP DoD item; broader than STORY-010's table filter. "ID" is the slug from STORY-025 |
| STORY-031 | Near-duplicate document names are reconciled | — | Ingest flags them (STORY-003); nothing merges them. Real entity resolution — deliberately out of DI-1 |
| STORY-035 | Ingestion accepts a DOCX issuance | — | Same `extract_document` protocol as STORY-016, own extraction rules. Blocked: no DOCX sample exists to design against. Likely easier than PDF — `python-docx` exposes heading styles, so locating the references section stops being the risky stage |
| STORY-036 | Ingestion accepts an XLSX manifest | — | The *manifest* path alongside CSV, not document extraction — a sibling of `sources/manifest.py`, far smaller than either extraction story |
| STORY-047 | A reissued document's edits are recognised as edits, not as wholesale replacement | — | Diffing the 2018 and 2020 editions of DoDD 5000.01 through the live stack produced **0 MODIFIED, 11 ADDED, 80 REMOVED**. That is [ADR-015](../specs/adr/ADR-015-changes-are-detected-and-ranked.md)'s documented fallback behaving exactly as designed — the two editions are structurally rewritten, so no `section_path` held exactly one unmatched obligation on each side and the section-based pairing never fired — but the result reads to a reviewer as "the whole document was replaced", which is the least actionable form the answer can take. Needs a second matching pass for obligations that moved between sections. See [STORY-047](stories/STORY-047-reissues-read-as-replacement.md) |
| STORY-073 | Each document edition is ratcheted against its own reference set, not its current successor's | — | **Est. L.** `RATCHETS` in `backend/tests/test_extraction_ratchet.py` covers five of the seven PDFs in `data/samples`. The corpus CSV holds one row per document *name*, describing the current edition's citations, so an older edition scores against a list that is not its own: 11 of `500001p_2003.pdf`'s 12 genuine citations read as "invented". Both absent fixtures are editions of DoDD 5000.01, the corpus's one multi-edition document — the 2003 edition (7% recall, 11 spurious) and the original 2020 issuance (93%, 2), against the Change-1 edition the CSV describes. The 2003 one is pinned instead by a direct test in `test_pdf_stages.py`, which proves extraction works but not that it holds a floor; the 2020 one is pinned by nothing. Needs a per-edition expected reference set, and a decision about where that set comes from and who maintains it as new editions are added — that open question is why this is L rather than a mechanical fix. See [STORY-073](stories/STORY-073-editions-ratchet-against-their-own-reference-set.md) |
| STORY-076 | A rebuild says how many *rejections* a re-key stranded, not only how many approvals | — | `UNPROMOTABLE` (`backend/src/policy_grapher/links/decisions.py`) filters `{verdict: 'approve'}`, so a rejection whose obligations a rebuild re-keyed beyond repair is counted by nothing: not replayed, not reported. [ADR-027](../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) records the gap in its consequences. Two things have to be decided together, which is why this is a row rather than a one-line change: a rejection means "do not write this edge", and a stranded one is therefore not a missing edge but a suppression nobody is applying — so is the right response a count, a distinct field, or a queue item asking the reviewer to re-decide? And `unpromotable` cannot hold it under that name, since a rejection was never going to promote anything |

## Ideas

Unrefined. No commitment implied.

| ID | Item | Notes |
| --- | --- | --- |
| STORY-020 | Model policy points as nodes rather than whole documents | The Policy Concierge direction in the [vision](../planning/vision.md); a schema migration |
| STORY-021 | Capture applicable entities and enforcement ownership as graph relationships | Same — new labels and relationship types |
| STORY-023 | A user can ask a question in natural language and get graph results | LLM constructs the Cypher and calls `POST /query`. The two gates it carried are now half-cleared: STORY-019 (auth) and STORY-024 (query constraints) have landed, so only the schema settling remains — see [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md), superseding [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) |
| STORY-045 | A user can run a bounded Cypher query from the UI | `POST /query` and `runQuery()` are built and unreachable. Deliberately parked in Ideas rather than Refining: [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md) superseded [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) precisely to stop assuming the audience writes Cypher, so putting a query box in front of them argues against a decision this project has already taken once. If it is built, it belongs behind an operator-facing route, not in the main navigation — and [STORY-023](#ideas) is the answer for the audience ADR-008 actually describes |
| STORY-075 | A chunk whose start lands exactly on a section join's newline is attributed to the right page | `_page_at` in `backend/src/policy_grapher/chunking.py` uses `offset <= cursor + len(line)`, so an offset equal to `cursor + len(line)` — the join's single newline — resolves to the earlier line's page rather than the one after it. Reachable only if a chunk's start offset lands on that one character, and the resulting chunk would begin with a stray newline either way. Real, but marginal enough that it isn't yet clear whether the fix is the boundary check or the leading newline |

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
