# ADR-032: Merging two documents is a recorded decision, not an edit

**Status:** Accepted · **Date:** 2026-08-27 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

The decision [STORY-031](../../backlog/stories/STORY-031-near-duplicate-documents-are-reconciled.md)
was L for. Taken before the implementation, per the backlog's own guidance.

## Context

Ingest has flagged near-duplicate names since STORY-003 and nothing has ever acted on the flag.
It fires on the real corpus: the sample manifest produces two groups —
`Military Standard 882E` against `Military-Standard 882E`, and a presidential directive cited
once with a parenthetical and once without. Each is one document held as two nodes, with its
inbound references divided between them, so a reader browsing either sees half the picture.

Three questions had to be settled together, and leaving them to the implementation is how an item
discovers its own scope halfway through.

**Which survives.** Not a heuristic. The hard, unbounded part of entity resolution is deciding
*automatically* that two names denote one document; presenting a flagged pair to someone who
knows the corpus is bounded. This project already refuses to let a machine decide something a
human should — that is what `:LinkDecision` is for.

**What happens to what hangs off the loser.** The two live cases are `:External` nodes: no
editions, no chunks, no obligations, nothing but a name and inbound references. A corpus document
carrying text is a different problem — which edition survives, whether chunks merge, what happens
to obligations whose ids hash a `version_id` — and it is ADR-027's problem wearing a new hat.

**Whether it survives a re-ingest.** A CSV or XLSX manifest naming both spellings will recreate
the node that was merged away. An edit would be undone silently on the next ingest, which is
exactly the failure `:LinkDecision` exists to prevent for links.

## Decision

**A merge is recorded as a decision and replayed, the way a review verdict is.**

1. **A person chooses**, seeing both names, what cites each, and whether either carries text.
   Nothing merges on a similarity score alone.
2. **The decision is a `:DocumentMerge` node keyed on the pair of *names***, recording which
   name survives, who decided, and when — durable, and replayed after every ingest. An ingest
   that recreates the merged-away name immediately re-applies the merge.

   **Names, not slugs, and the difference is load-bearing.** [ADR-005](ADR-005-slug-assignment-over-the-name-set.md)
   gives the incumbent the bare slug and the newcomer a suffix, so deleting the loser frees a slug
   that the next ingest may hand to a different node. A merge recorded by slug stops matching the
   thing it merged away, and undoes itself on exactly the event this decision exists to survive.
   A name comes from the manifest and does not move. This was found by the re-ingest test rather
   than by reasoning, which is the only place it shows.
3. **"These are different" is recorded too**, and the pair is not offered again. A judgement made
   once is not re-asked, which is the same reason a rejection is stored beside an approval
   (ADR-014).
4. **Only documents with nothing hanging off them may be merged.** If either side has an edition,
   the merge is refused and says why. That is the whole of the scope this ADR takes.
5. **Inbound references repoint to the survivor**, and the loser is deleted. A merge that cannot
   complete applies nothing — a half-merged document is worse than two whole ones.

## Consequences

**What this buys.** The two real cases become one document each, with their references reunited,
and stay that way across re-ingests.

**What it defers, explicitly.** Merging documents that carry text is not attempted. That
restriction is the reason this is implementable now, and lifting it is a separate item that has
to answer ADR-027's questions about re-keying — obligations whose ids hash a `version_id` cannot
simply change owner.

**What it costs.** A second kind of replayed decision, and a second thing an ingest must do
afterwards. The alternative — merging as a direct edit — costs less today and is undone by the
next manifest ingest without saying so, which is the failure this project has already paid for
once in links.

**Why not resolve automatically above a similarity threshold.** `Military Standard 882E` and
`Military-Standard 882E` are obviously the same. `DoDD 5000.01` and `DoDD 5000.02` differ by one
character and are different documents. A threshold that merges the first will merge the second,
and a wrong merge destroys a document and redirects its references — far harder to notice, and to
undo, than leaving two nodes alone.
