# ADR-015: How a change is detected, and how it is ranked

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

This is the phase the increment was built for. [ADR-011](ADR-011-instruments-have-versions.md)
gave an instrument editions, [ADR-012](ADR-012-chunks-follow-sections.md) gave an edition text,
[ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md) turned that text into obligations, and
[ADR-014](ADR-014-proposals-and-decisions-are-different-things.md) let a human say which of our
obligations implements which of theirs. What remains is the question all of it exists to answer:
*a higher-level policy changed; which of our policies are affected, and how urgently?*

Two problems stand between the graph and that answer. The first is detecting the change at all.
The second is ordering the results, because a triage list that arrives unsorted is a list nobody
works through in priority order — they work through it in the order it happened to arrive, which
is no order at all.

## Options considered

**Diff the documents' text.** Compare the two PDFs, or the two chunk sets, and report the
textual delta. Rejected: a policy edit that reflows a paragraph, renumbers a section, or changes
a footer produces a large textual delta and no change in obligations, while a single word
swapped from "shall" to "should" produces a tiny delta and inverts a binding duty. The unit that
matters is the obligation, not the byte.

**Diff obligations by identity.** Match `obligation_id` across the two editions; equal ids are
unchanged. This is what the phase plan specified, and it cannot work. An `obligation_id` hashes
the version it belongs to (ADR-013), deliberately, so that a Phase 4 decision records which
*edition* a reviewer approved. The consequence is that a clause reproduced word for word in two
editions carries two different ids. Verified directly: the same statement in the same section of
a 2003 and a 2020 edition hashes to `ee0577cf…` and `c741ac71…`. Matching on id would report
every obligation in the document as a removal plus an addition — the failure the plan's own
next decision warns about, applied to the entire document rather than to reworded clauses.

**Diff obligations by their version-independent content.** Match on the part of the identity
that is not the edition: the section the clause sits in, and its normalized statement. Chosen.

## Decision

**The diff matches on `(section_path, normalize(statement))`.** `changes.diff.content_key`
builds it, using the same `normalize` that obligation identity uses — so a reflowed or re-cased
line is the same clause here exactly as it is there. `obligation_id` is left untouched, which
means every decision Phase 4 recorded keeps working. A key present on both sides is unchanged
and produces nothing; only on the new side is `ADDED`; only on the old, `REMOVED`.

**`MODIFIED` is found by section, not by text similarity.** Nothing in this module measures how
alike two sentences are. A section holding exactly one unmatched clause on each side has been
edited — that is a fact about the document's structure, not a judgement about its prose, and it
needs no threshold anyone would have to tune. The change carries both statements, because a
reviewer's first question is what actually changed.

**A section with several changed obligations falls back to `ADDED`/`REMOVED`, and says so.**
Pairing two against two is a guess. A wrong guess is worse than no guess here: it puts a
reviewer's attention on the wrong sentence while presenting itself as a specific finding. The
fallback writes an explicit summary — *"Section 3.2 holds more than one obligation that changed,
so this is reported as a removal and an addition rather than a guessed pairing"* — so the
reviewer knows the tool declined rather than that the document did something odd.

**`MODIFIED` affects the new obligation; `REMOVED` affects the old one.** The new one is what a
reviewer must now act on. For a removal there is no new one, and the old one is precisely what
our `IMPLEMENTS` edge still points at — which is what lets a removal surface at all.

**The diff drops its version pair before writing.** Change ids are deterministic
(`hash(from, to, kind, obligation_id)`), so re-running reproduces the same nodes. But a
re-extraction can make a change *stop* existing, and a `:Change` left behind shows a reviewer a
change that is no longer real. Drop-then-write is the same pattern chunks and obligations use.
`rebuild_derived` also drops a version's changes before its obligations, since a `:Change`
whose `AFFECTS` target was deleted underneath it would be visible and untraceable.

**Ranking is arithmetic over two named tables.**

```python
MODALITY_WEIGHT = {"SHALL": 4.0, "MUST": 4.0, "SHOULD": 2.0, "MAY": 1.0}
KIND_WEIGHT     = {"REMOVED": 3.0, "MODIFIED": 2.0, "ADDED": 1.0}
```

Named, and in Python rather than inlined into the Cypher, because a policy analyst who
disagrees with an ordering should be able to point at the number that caused it and argue about
that number. They are a starting position, not a measurement — nothing has yet validated them
against how a reviewer actually prioritises.

**`REMOVED` outranks `MODIFIED`, which outranks `ADDED`.** A policy of ours implementing
something that no longer exists is a live compliance gap: we are performing a duty the authority
has withdrawn, or claiming coverage that has evaporated. A modified obligation is work. A new
one is work we have not yet been asked to do.

**Tier distance is absent, not silently one.** The design sketched ranking as *modality weight ×
change kind × tier distance*. Nothing in the graph records a policy tier — there is no notion of
"this issuance sits two levels above that one" anywhere in the schema — so including it would
mean multiplying by a constant and calling it a factor. It is omitted, and this paragraph is the
record of why, so that adding a tier later is a deliberate act rather than a rediscovery.

**Triage traverses `IMPLEMENTS` and only `IMPLEMENTS`.** This is the return on ADR-014's two
edge types. An unreviewed `IMPLEMENTS_PROPOSED` is invisible to this query by construction, not
by a filter someone has to remember, and a test asserts that a change linked only by a proposal
produces no row.

**Unlinked changes are counted, never dropped.** `TriageResult` carries `total_changes` and
`unlinked_changes` beside the rows. Without them, "nothing you own is affected" and "nothing has
been reviewed yet, so this query cannot see anything" are the same empty response — and one of
them is a false all-clear, which is the single most dangerous output this tool can produce.

**An unknown edition is a 404, not an empty answer,** for the same reason. A mistyped version id
would otherwise render as an authoritative all-clear. Likewise, asking to triage the oldest
edition — one that supersedes nothing — is a 400 rather than a comparison against emptiness,
which would report every obligation in it as newly added.

**Omitting `from_version_id` compares against the superseded edition, and the response says
which was used.** The `SUPERSEDES` chain is derived (ADR-011), so the default is the graph's own
view of what came before. Echoing it back matters: a caller who did not choose still needs to
know what the answer is about.

**One citation per side, not one row per anchor.** Chunk overlap repeats a sentence across a
section split, so an obligation can legitimately anchor to more than one chunk — measured at 5 of
88 obligations on `500001p_2003.pdf`. A plain traversal emits a row per combination, inflating
the count and showing the same clause twice. Each side cites its earliest anchoring chunk in
reading order. The review queue needed the identical fix.

**The diff runs inside `GET /triage`.** This is a deliberate compromise and the weakest decision
here. A GET that writes derived nodes is not a safe method in the HTTP sense. The alternatives
were a separate write endpoint, which leaves the documented triage route returning stale or
empty answers unless a caller remembers to refresh first, or a lazy refresh only when no changes
exist, which lets stale ones persist indefinitely. The diff is deterministic and drops-then-writes
its own version pair, so repeating the request converges on the same `:Change` set rather than
accumulating — a test pins that. If concurrency on this route ever matters, splitting the write
out is the change to make.

## Consequences

**Makes easy.** The deliverable is one request. A change to a higher-tier issuance produces a
ranked, fully cited list of our own clauses that have to answer for it, and every row is
explained by a path a person can walk: this change, to this obligation, along an edge a named
reviewer approved, to this clause of ours. Nothing on the path is a model call, so the answer
cannot contain an obligation the corpus does not state, and the ranking can be argued with
rather than merely trusted.

**Makes hard.** The diff is blind to an obligation that moved between sections: the content key
includes `section_path`, so a clause relocated verbatim from 3.2 to 4.1 reads as a removal plus
an addition. That is the price of detecting `MODIFIED` structurally, and it is the right price
for this corpus — DoD issuances renumber rarely and reword often — but a corpus that reorganises
heavily would need a second matching pass. The ranking weights are also unvalidated: they encode
a plausible prioritisation, not a measured one, and nothing yet tells us whether a reviewer
agrees that a removed `SHOULD` (6.0) deserves to outrank a modified `MAY` (2.0).

**Commits us to.** The obligation, not the byte and not the document, being the unit of change
in this system, permanently — every later feature that wants to say "what changed" inherits that
definition. It also commits the project to the version-independent content key as a second,
parallel notion of obligation sameness alongside `obligation_id`: one answers "is this the same
clause across editions", the other "is this the same clause in this edition". They are both
needed and they must not be conflated, because collapsing them in either direction breaks
something — merge them toward the id and the diff stops working, merge them toward the content
key and Phase 4's decisions stop knowing which edition they approved.
