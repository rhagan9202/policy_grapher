# STORY-047: A reissued document's edits are recognised as edits, not as wholesale replacement

**Epic:** — · **Status:** Refining · **Estimate:** —

## User story

As a compliance reviewer, I want a reissued policy's diff to show me which obligations were
*edited*, so that I can read the change instead of re-reading the document.

## Context

Measured against the live stack on 2026-08-21, diffing the 2018 and 2020 editions of
DoDD 5000.01 produced:

| Kind | Count |
| --- | --- |
| MODIFIED | **0** |
| ADDED | 11 |
| REMOVED | 80 |

Nothing is malfunctioning. This is [ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md)'s
documented fallback working as designed: `MODIFIED` is detected structurally, by a
`section_path` holding exactly one unmatched obligation on each side, and a reissue that
renumbers its sections leaves no such path. ADR-015 names this under *Makes hard* —
"a clause relocated verbatim from 3.2 to 4.1 reads as a removal plus an addition" — and
accepts it on the reasoning that "DoD issuances renumber rarely and reword often".

**That reasoning did not survive contact with the corpus.** A full reissue renumbers
everything, and a reissue is exactly when someone asks what changed. The output is
technically correct and close to useless: "80 duties vanished and 11 appeared" tells a
reviewer to read the whole document, which is the work the tool exists to remove.

This matters beyond presentation. Triage ranks `REMOVED` above `MODIFIED` because an org
policy implementing something that no longer exists is a live compliance gap. When an edit is
reported as a removal, it manufactures 80 false gaps at the highest priority the ranking has.

## Acceptance criteria

- [ ] An obligation whose wording is unchanged but whose `section_path` differs between two
      editions is reported as neither ADDED nor REMOVED
- [ ] An obligation that was both moved *and* reworded is reported as one MODIFIED carrying
      both statements, or is left to the fallback with a summary saying which case applied —
      never silently paired
- [ ] Re-running the diff of the two DoDD 5000.01 sample editions reports substantially fewer
      than 80 REMOVED, and the residual REMOVED are spot-checked by a human as genuinely gone
- [ ] The pairing rule is stated in a superseding ADR, since it changes a decision ADR-015
      froze
- [ ] Triage ranking is re-checked against the new mix: the point of the fix is that false
      REMOVED stop out-ranking real ones

## Notes

The obvious approach is a second matching pass after the section-based one: among the
obligations still unmatched, pair those whose `normalize(statement)` is identical but whose
section differs (a pure move — arguably not a change at all, or a change of its own kind).
That is cheap, needs no threshold, and would absorb the relocated-verbatim case entirely.

What it will not absorb is *moved and reworded together*, which is likely the common case in a
genuine reissue. Catching that needs similarity, and similarity needs a threshold — the first
tunable number in a pipeline that has so far avoided them. ADR-015 is explicit that the
section rule was chosen because it "needs no threshold anyone would have to tune". Reopening
that is the substance of this story, not the code.

Worth noting the corpus already carries a cheaper signal: obligation identity is content-
derived, and the sample corpus has two editions where the *same sentence* appears under
different numbering. Measure how much of the 80 the exact-move pass alone recovers before
reaching for similarity.

## Open questions

- Is a verbatim clause that only moved a **change** at all? It has no effect on what anyone
  must do, but a citation to it is now wrong, and Phase 4 decisions are keyed on
  `(version_id, section_path, statement)` — so a move *does* orphan a human decision. That
  argues for a fourth kind, `MOVED`, rather than for silence.
- If similarity is introduced, what stops it pairing two genuinely different obligations that
  happen to share vocabulary? The lexical proposer already demonstrates how weak shared
  wording is as evidence — it paired an unrelated communications clause with an acquisition
  one at 87% overlap during the 2026-08-21 audit.
- Should a low-confidence pairing be surfaced to the review queue as a proposal rather than
  written as a `:Change`? That would reuse the human gate the project already trusts for
  links, instead of inventing a second confidence mechanism.
- Does this need to land before DI-3's coverage matrices? A matrix built on 80 false gaps
  would be wrong in a way that is hard to see.
