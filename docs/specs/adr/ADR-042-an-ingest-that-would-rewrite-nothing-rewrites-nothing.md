# ADR-042: An ingest that would rewrite nothing rewrites nothing

**Status:** Proposed · **Date:** 2026-09-17 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-039](ADR-039-a-re-ingest-discards-the-derived-layer.md)**, which made a re-ingest
discard the derived layer built on the chunks it replaces. This narrows *when* that happens — not at
all, when the rewrite would produce the same chunks — and keeps everything else ADR-039 decided.

## Context

ADR-039 is right about the case it was written for. `drop_chunks` is a `DETACH DELETE`, it takes the
`:ANCHORED_IN` edges with it, and obligations survive unanchored — counts unchanged, citations
pointing nowhere, and the damage visible only to a screen that asks for the obligations themselves.
Dropping the derived layer with the chunks it is built on is the honest answer whenever those chunks
are actually being replaced.

What has changed is not the hazard but the traffic. ADR-039 already noted that re-ingesting is
routine, because [ADR-007](ADR-007-sources-describe-documents.md) makes ingest uniformly additive
precisely so that running it again is safe. Planned work now makes adding a document the product's most prominent
action rather than a maintenance step, with a file picker that still offers files already ingested
and marks them as such. Under that traffic, the most likely re-ingest is not a chunker change — it
is somebody adding the same document twice. Today that costs roughly an hour of extraction and every
human verdict resting on it, and says nothing while doing so.

ADR-039 considered two ways to protect that artefact and rejected both for good reasons.
Re-anchoring surviving obligations was rejected because *"the case the drop exists for is precisely
a chunker that has changed"*, and reattaching extraction to text it was not read from is worse than
losing it. Refusing to re-ingest an edition holding obligations was rejected because it makes a safe
additive operation fail for reasons about a layer above it.

It did not consider a third option, because the framing did not raise it: not performing the rewrite
at all when the rewrite would change nothing. That option inherits neither rejection. Nothing is
reattached, because nothing is detached. Nothing fails, because the ingest succeeds and says what it
did.

It does inherit the constraint buried in the first rejection, and that constraint is the whole
difficulty. "Unchanged" has to mean the chunks would come out the same — not merely that the file
did. The stored checksum covers the source bytes. Chunk content is a function of those bytes, the
library that turns them into text, and the chunker that divides it. The text-extraction dependency is
floored with no upper bound, so it can change what a chunk contains with no code in this repository
moving at all.

## Options considered

**Key the skip on the source checksum alone.** Cheap, and the checksum already exists. Rejected: it
answers "is this the same file", and the question is "would this produce the same chunks". A
dependency upgrade would pass as unchanged and leave stale chunks standing behind a report saying
nothing was done — ADR-039's exact failure, reached by a route its reasoning does not cover and its
reader would not expect.

**Key it on a hand-maintained pipeline version.** Rejected: a constant someone must remember to bump
gives the skip a silent failure mode, and the failure is invisible in the direction that matters —
it skips when it should rewrite. A comment in `config.py` would have been forgotten inside a year,
and so would this.

**Key it on a stamp derived from the whole path between the source bytes and the stored chunks.**
Chosen. A dependency bump invalidates it without anyone deciding to.

## Decision

**An ingest that would rewrite nothing rewrites nothing.** When the source checksum and the pipeline
stamp both match what the edition already carries, the chunks are not replaced, the derived layer is
not discarded, the build record is not cleared, and the result says the document was already present
and nothing was done. It is not reported as a successful write whose counts happen to be zero.

**The stamp covers the whole path from source bytes to stored chunks**, and is derived from the
installed pipeline rather than declared by hand. What it must capture is every stage that can change
a chunk's content without a change to the source file.

**The stamp is written wherever chunks are written.** Ingest is not the only path that re-chunks an
edition; a rebuild re-reads the source and rewrites chunks too. A stamp written at only one of them
would read as stale on editions carrying the most expensive derived work, which is the loss this ADR
exists to prevent, arriving through the door it opened.

**An absent stamp is a mismatch.** Editions written before this exists are rewritten exactly as they
are today. The safe direction for an unknown is the old behaviour, not the new one.

**The skip covers the chunk-and-derived-layer rewrite only.** The document write, its reference
edges, and the record of what its references section yielded refresh on every ingest. Otherwise a
document whose references could not be read would be frozen in that state permanently — a later
parser fix could never reach it, and the graph would keep asserting an unknown that had since become
knowable.

**Everything else ADR-039 decided stands.** When a rewrite does happen, the derived layer goes with
the chunks in the order it already established — changes, then obligations, then chunks — and the
edition's build record is cleared, because `build_state IS NULL` is the encoding for never-built and
that is what a freshly re-chunked edition is.

## Consequences

The expensive artefact survives the most likely accident, at the moment the product makes that
accident easiest to have.

It commits the project to deriving the stamp rather than declaring it, and that derivation becomes
load-bearing: a stamp that fails to move when the pipeline moves reintroduces ADR-039's failure
silently, so it needs a test of its own rather than being an implementation detail of the skip.

It adds a state the ingest surface did not have. "Nothing was done" is a third outcome beside success
and refusal, and anything that reports on an ingest has to be able to say it — including anything
that assumed a successful ingest always rewrote chunks.

It narrows ADR-039 rather than reversing it, which means the reasoning in ADR-039 stays live. Anyone
widening what the stamp ignores is reopening the question that ADR answered, and should say so.
