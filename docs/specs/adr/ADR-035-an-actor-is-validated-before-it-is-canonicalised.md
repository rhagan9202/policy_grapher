# ADR-035: An actor is validated before it is canonicalised

**Status:** Accepted · **Date:** 2026-08-28 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

Decides [STORY-100](../../backlog/stories/STORY-100-an-office-is-one-actor-not-several-spellings.md).

## Context

STORY-100 was filed after sprint 9's rebuild recorded one office two ways — `USD(A&S)` twelve
times and `The USD(A&S)` twice — and asked whether actor fragmentation is one problem or two. It
proposed three shapes: normalise on the way in, resolve to an `:Entity` node, or narrow the claim.

**All three assume the field contains office names.** Reading all 80 distinct values across 154
obligations, on 2026-08-28, shows it does not:

| What it is | Examples |
| --- | --- |
| A named office, sometimes spelled two ways | `USD(A&S)` (12), `The USD(A&S)` (2), `USD(R&E)`, `The CJCS`, `CJCS` |
| A real class of party | `The DoD Components`, `Contractors`, `PMs`, `Acquisition managers` |
| An abstract noun that bears no duty | `Competition`, `Advanced technology`, `Acquisition strategies`, `The S&T program`, `DoD Issuances`, `documents` |
| A conditional clause | `When using performance-based strategies` |
| A pronoun | `They` |
| A description of the prompt's own machinery | `the passage` (3) |
| A truncated fragment | `gers`, `e systems` |

Folding case, articles and whitespace merges **10 of 80**. The other seventy are not spelling
variants of each other, and no normalisation rule reaches them.

**The measurable defect is different from the one the story assumed.** The prompt says *"actor is
the party the duty falls on, copied from the statement"*. Measured against that rule, excluding
`ASSIGNED` — where [ADR-033](ADR-033-a-duty-can-be-assigned-by-position.md) deliberately takes the
office from the heading above the item and not from the statement — **14 of 123 actors, 11%, are
not present in the statement they were supposedly copied from.**

One of those fourteen is worth quoting in full, because it is the clearest thing this project has
found about what the model is actually doing:

> statement: `"WILL is a duty here, not a prediction."` · actor: `"the passage"`

**That sentence is from the extraction prompt.** The model returned an obligation extracted from
its own instructions. [ADR-034](ADR-034-a-statement-is-a-quotation.md) makes that impossible going
forward, because the sentence occurs in no chunk — but it stood in the graph, and nothing noticed.

The underlying confusion is that the model reports the **grammatical subject** of the sentence
rather than the **party the duty falls on**. "Competition will be used to the maximum extent"
has a subject and no duty-bearer, and the correct answer is null.

## Decision

**The field's validity is fixed before its identity is canonicalised. Normalisation and `:Entity`
resolution are deferred, and not because they are hard.**

1. **For a word modality, the actor must occur in the statement**, matched as a sequence of word
   tokens rather than as a substring. `gers` is a substring of "managers" and is not an actor; a
   token-sequence match rejects it and accepts `The USD(AT&L)`, whose trailing bracket defeats a
   naive word-boundary regex. Checked in `validate_extracted`.
2. **`ASSIGNED` is exempt, by construction rather than by exception.** ADR-033 requires its actor
   to come from the role heading *above* the item, so absence from the statement is the correct
   state and 31 of 31 such obligations are correctly absent. The prompt states the "copied from
   the statement" rule generally and is wrong to; the rule is modality-specific and is recorded
   here as such.
3. **A placeholder actor is no actor**, already landed with ADR-034's commit: the strings `null`,
   `none`, `n/a`, `no actor specified` and the empty string become `None` before any other rule
   sees them, so an `ASSIGNED` duty naming `"null"` is refused rather than accepted.
4. **No normalisation, no `:Entity`, no canonical list — yet.** Canonicalising a field that is 11%
   invalid produces confident junk: `The USD(A&S)` and `USD(A&S)` would merge, and `gers`,
   `the passage` and `Competition` would each become a durable node with an id, which is worse
   than a messy string because it looks authoritative. **Identity is a question you ask about
   values you trust.**
5. **What "grammatical subject, not duty-bearer" costs is not yet measured, because nothing
   measures actors at all.** The ratchet scores precision, recall and modality accuracy; actor is
   not scored on any leg. That is the gap to close before this decision is revisited, and it is
   the honest prerequisite for any canonicalisation.

## Consequences

**Roughly one word-modality actor in nine is refused on the next rebuild**, and the obligation with
it, since an obligation whose actor names the wrong party is worse than one naming none. Under
ADR-030 each costs itself.

**The real classes of party stay exactly as the document wrote them.** `The DoD Components`,
`Contractors` and `Acquisition managers` are who those duties fall on. A canonicalisation scheme
built to unify office names would have had to decide what to do with them, and the likely answer —
map them to nothing, or invent an entity — would have lost information the document actually
states. Deferring means not having to be wrong about it yet.

**The abstract-noun actors are not fixed by this.** `Competition` occurs in its statement, so the
token rule accepts it. Only a measurement of actor accuracy against a gold set can price that, and
that measurement does not exist.

**STORY-100 does not close.** Its question — what is an actor, canonically — is deferred with a
stated prerequisite rather than answered. What closes is the premise it was filed on: this is a
validity problem before it is an identity problem.

## Alternatives considered

**Normalise on the way in.** The story's cheapest option. It merges 10 of 80 values and leaves the
other seventy, including every fragment and every abstract noun. Rejected as an answer, not as a
future step.

**Resolve to an `:Entity` node now.** What the roadmap's *richer metadata and relationships* wants,
and what STORY-092 deleted the last unreachable version of. Rejected because it would be built over
a field with a measured 11% invalidity rate and no way to score the rest — the same mistake, one
layer up, that ADR-034 was written to undo.

**Refuse an actor that is not a duty-bearer.** The rule everyone actually wants. Rejected because
it is not deterministically checkable: distinguishing "Competition" from "Contractors" needs
judgement, and putting judgement in a validator makes the answer vary by whoever wrote the list.
