# ADR-019: The first run is empty, and the app says so

**Status:** Accepted · **Date:** 2026-08-21 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

A UI audit against the running stack on 2026-08-21 found that `docker compose up` from a clean
volume produces 439 documents, zero chunks and zero obligations. The 439 come from auto-ingest
loading the sample CSV manifest, which by design records no edition and no text
([ADR-011](ADR-011-instruments-have-versions.md)). The three screens DI-2 added — Triage,
Review, Ask — are therefore empty, and nothing in the application can fill them: the audit had
to seed the graph by running Python against the container's Neo4j.

Planning the tech-debt surge to close that produced two proposals, and the project owner
rejected both:

**A deterministic baseline extractor as the demo default.** A modal-verb sentence matcher,
shipped as a third adapter beside `null` and `local`, so a cold start could produce obligations
with no model server. It would have worked.
[ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md) had already considered a modal-verb
rules engine as *the* extraction approach and rejected it on measured evidence — 0.5 precision
against its own mixed gold fixture, because "may result in new categories" and "may be
identified in the future" are predictions wearing a modal verb's clothes. Shipping one anyway,
as the default the stack runs with, would have overridden a decision on evidence in order to
make a demo look full.

**A synchronous rebuild route with the timeout documented as a known limitation.** One POST
driving extract → embed → propose → replay. Fast under `null`, and minutes under `local`,
where it would outlast any client timeout — knowingly, with the flaw written down rather than
fixed.

Both are the same move: ship something known to be wrong so the product presents better than
it is. Rejecting them twice, on the same grounds, is what this ADR records — because the
pressure that produced them recurs every time a screen is empty, and the reasoning will not be
obvious to whoever feels it next.

## Options considered

**Seed the corpus at startup.** Auto-ingest a sample PDF as well as the CSV, so a first run has
text. Rejected: it makes container startup do document parsing, and it means the first thing a
new arrival sees is a corpus they did not choose, which is a demo prop rather than their data.

**Leave auto-ingest on and accept blank screens.** No work. Rejected: blank screens read as
failure. The audit's own author could not tell, without querying Neo4j, whether Review was
empty because nothing was proposed or because the feature was broken. A user has less
information than that, not more.

**Start empty, and make the emptiness legible.** Chosen.

## Decision

**`AUTO_INGEST` defaults to false.** A first run holds nothing. The auto-ingest machinery stays
and still works when switched on — it is useful, and this is a change of default, not a
removal.

**Every screen distinguishes an empty corpus from an empty result.** These are different facts
and only one of them is a problem the user can act on:

| Screen | No corpus | Corpus, nothing to show |
| --- | --- | --- |
| Graph | "No documents yet" | (n/a — a corpus always has nodes) |
| Documents | "No documents yet" | "No documents match that filter" |
| Triage | "No documents yet" | "No obligation changed between these editions" |
| Review | "No documents yet" | "Nothing is waiting for review" |
| Ask | "No documents yet" | "Nothing in the corpus addresses that" |

Review's existing message is the case that motivates the rule: "Nothing is waiting for review"
is true when the graph is empty, and it tells the reader the queue has been worked through when
in fact nothing has ever been ingested.

**An empty state names the action, and does not pretend to be it.** Each says what to run —
`POST /ingest` with a sample filename. It is not a button: the ingest control is STORY-043 in
sprint 5. That is a real gap, accepted for two sprints and written down here rather than
discovered later.

**No adapter exists to make a demo look fuller than the corpus is.** `null` and `local` remain
the only extractors. A first run with no model configured produces no obligations, and the UI
says that rather than manufacturing some.

## Consequences

**Makes easy.** A new arrival can tell the difference between "nothing here yet" and "this is
broken", which is the single most common question a first run raises. Every later feature
inherits a rule for its own empty state instead of inventing one. And the extraction ratchet
keeps meaning something: no adapter is in the tree whose floors were set low to make a
screenshot work.

**Makes hard.** The demo is worse in the short term. Anyone expecting sprint 2's 439-document
graph now gets an empty app and an instruction they can only follow from a terminal. Between
this sprint and STORY-043, a user without a shell cannot get a corpus at all — that is the
honest cost of refusing the two rejected options, and it has a fixed expiry rather than an
open one.

**Commits us to.** Emptiness being a state the product explains rather than a state it hides.
The moment one screen fills itself with placeholder or synthetic data to avoid looking bare,
the distinction this ADR draws stops being reliable anywhere — a user who has seen one
fabricated row cannot trust that any row is real. That matters more here than in most
products, because every screen this applies to exists to tell someone what a policy obliges
them to do.
