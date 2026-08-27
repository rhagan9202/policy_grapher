# STORY-031: Near-duplicate documents can be reconciled

**Epic:** — · **Status:** Done · **Estimate:** L

## User story

As someone maintaining the corpus, I want two records of the same issuance to be merged into one,
so that a document cited under two spellings does not appear twice in the graph and split its own
references between the copies.

## Context

Ingest already flags near-duplicate names (STORY-003) and nothing acts on the flag. The corpus
makes this easy to produce: a manifest cites "DoDD 5000.01" and a PDF cover says "DoD Directive
5000.01", and the slug derived from each differs, so the graph holds two documents where the
world holds one. Their references divide between them, and a reader browsing either sees half the
picture.

This was deliberately left out of DI-1 as "real entity resolution", and that framing is what has
kept it out of four sprints: entity resolution in general is unbounded.

**The scope that makes it tractable is deciding a person does the resolving.** The hard,
unbounded part is deciding automatically that two names denote one document. Presenting a
flagged pair to someone who knows the corpus, and applying what they say, is bounded — and it is
the same shape as Review, which exists precisely because this project does not let a machine
decide something a human should.

## Acceptance criteria

- [ ] The decision is taken and recorded first: what merging two documents *means* for the graph
      — which slug survives, what happens to the loser's editions, chunks, obligations and
      inbound references, and whether the merge is reversible. **This item is L because that is
      unmade**, and it is the first work.
- [ ] Given two documents the ingest flagged as near-duplicates, a person can see them side by
      side with enough to tell whether they are the same issuance: both names, both slugs, what
      cites each, and whether either carries text.
- [ ] Given a person confirms they are the same, **When** the merge is applied, **Then** one
      document remains and every reference that pointed at either points at it.
- [ ] Given a person says they are different, **Then** the pair is not offered again — a
      judgement recorded once is not re-asked, which is what `:LinkDecision` does for links.
- [ ] Nothing is merged without a person saying so. No heuristic threshold decides on its own.
- [ ] A merge that cannot be applied completely fails without applying part of it — a half-merged
      document is worse than two whole ones.

## Dependencies

- STORY-003 (ingest flags near-duplicates) — **Done.** It produces the input.
- The decision in the first criterion. Nothing else.

## Open questions

- Does a merge survive re-ingest? A CSV re-ingest recreating the losing document would undo the
  work silently, which is the same failure `:LinkDecision` was built to prevent for links — and
  suggests a merge has to be recorded as a decision rather than performed as an edit. That is the
  substance of the first criterion and the reason this is not an M.
