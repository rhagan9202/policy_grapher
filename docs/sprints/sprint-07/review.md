# Sprint 7 — Review

**Date:** 2026-08-27 · **Participants:** —

*Dated record. Written once, at the end of the sprint.*

## The goal

> Extraction stops silently losing a fifth of every document, and the loop it feeds is run end
> to end on what it produces.

**Both halves met, and the second half happened for the first time in this project's life.**

## Committed and delivered

| ID | Item | Est. | Delivered |
| --- | --- | --- | --- |
| STORY-087 | The blast radius of an unparseable item is decided | S | Yes — ADR-030 |
| STORY-088 | An unparseable item costs what the ADR says it costs | M | Yes |
| STORY-092 | The Authority and Entity helpers go | S | Yes |
| STORY-089 | The rebuild status poll backs off | S | Yes |
| STORY-090 | Review's empty queue names its upstream cause | S | Yes |
| STORY-091 | The README's corpus numbers describe what the product produces | S | Yes |

**Six of six.** Every acceptance criterion was read back line by line against what shipped
before this file was written.

## The loop, end to end

Run from the browser, every step a UI action:

    ingest -> build 2018 (38 chunks, 93 obligations)
           -> build 2020 naming 2018 a candidate (37 chunks, 56 obligations, 112 proposals)
           -> Review: "Proposal 1 of 50 ... 100% confidence"
           -> approve, with a rationale
           -> Triage: 149 changes, 148 unlinked, ONE ranked row
           -> Ask: the obligation returned with its edition, section and page

**The first `:LinkDecision` in this project's history** was recorded by that walkthrough:
`approve`, actor `dev` — the authenticated principal, never the request body — with a written
rationale. It then survived two rebuilds, one of each edition, reported as `promoted: 1,
unpromotable: 0`. [ADR-014](../../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md)
and [ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) have promised that since
sprint 4 and neither had been observed doing it with a human verdict behind it.

The Triage row is the product's whole purpose in one screen: a `SHALL` removed from the 2018
edition, scored 12.0, reaching the 2020 clause that answers for it — with the screen saying out
loud that 148 other changes reach nothing anyone has reviewed.

## The correction sprint 6 needs

**Sprint 6 reported that section headings had stopped being recorded as obligations. That was
false**, and finding out why is the most useful thing this sprint did.

The check compared five exact strings — `'Be Responsive'`, `'Focus on Affordability'` — and
returned zero. The same prompt change that stopped the model dropping sentence subjects had also
told it to keep the closing full stop, so the stored values were `'Be Responsive.'` and no longer
matched. The headings never went away; only the strings did.

Measured properly here, by *shape* rather than by string: **18 of 215 obligations were four words
or fewer.** "Be Responsive.", "e. Emphasize Competition.", each labelled SHALL by a model with no
SHALL to point at.

It is the same defect class this project keeps finding — a check that cannot fail in the way that
matters — committed by the person who had spent the previous sprint removing three of them, and
reported as a result in a dated record. The rule that stops it is not "check harder"; it is that
a check written against five literals is a check against five literals.

**The fix is enforced where it cannot drift.** A statement must contain the modality word it is
labelled with — word boundaries, so "General Marshall" is not a `shall`. The prompt had asked for
this since PROMPT_VERSION 2 and asking was not enough, which sprint 6 had already learned when
three prompt variants failed to move the rejection rate. ADR-030 is what made enforcing it
affordable: a week ago, rejecting those items would have destroyed every obligation sharing their
chunks.

## Extraction quality, measured three times

    sprint 6 start   precision 0.294   recall 0.385     the gate, once un-disarmed
    sprint 6 end     precision 0.625   recall 0.769     statements quote their passage
    sprint 7 end     precision 0.833   recall 0.769     junk no longer counts as a prediction

Each identical on three consecutive runs at temperature 0. Floors recorded exactly as observed,
as this file has always done. The gate passes against a live model and skips loudly under the
default `null` configuration.

## What the numbers cost, honestly

The corpus produces **fewer obligations than it used to and they are worth more**: 93 and 56
against the 96 and 115 the README claimed. On the 2020 edition, 20 of 37 chunks now yield nothing
and a further 85 statements are dropped.

That rate deserves to be read carefully. A rejected chunk is one where the model returned items
and *none* validated — so it is not a passage without duties, it is a passage the model
over-extracted from. Roughly half of this document is headings, scope statements and preamble,
and the model labels them all SHALL. The schema now refuses them; ADR-030 keeps the cost to the
statement rather than the chunk. Whether the remedy is a better prompt or a better model is
sprint 8's question, and the ratchet is now able to answer it.

## Four defects found while executing

Three of them came from this sprint's own changes meeting reality:

- **STORY-082's AC7 was built on a wrong assumption.** It expected a dead worker's job to become
  unknown, so the screen treated a 404 as "did not finish". Replacing a worker mid-rebuild left
  the job `STARTED` with progress frozen at 17 of 38 — RQ keeps it until the job timeout expires,
  and that is now eight hours. The screen would have shown a build in progress for a working day,
  and refused a second rebuild throughout. Now detected by asking whether the job's recorded
  worker is still alive.
- **ADR-030's first wiring made the report incoherent.** Drops routed through the rejection
  channel would have printed "0 chunks rejected" above a list of eight entries. Both numbers
  true, the pair meaningless — and the count is the entire condition ADR-030 attaches to dropping
  items at all.
- **The cache outlived the rules it was filled under.** Three entries held statements that no
  longer validate, and a hit re-validates: those chunks would have been rejected whole, losing
  the valid obligations cached beside them. ADR-030's blast radius, reappearing one layer up.
  **Found by asking what a rebuild would do before running one**, which is the cheaper order and
  not the one this project has usually managed.
- **`versions.py` held three writers nothing called** (STORY-092), which is what made an
  unreachable capability look delivered for a whole increment.

## Definition of done

- [x] **The loop completes once, end to end, through the UI.** Above.
- [x] **The first `:LinkDecision` recorded and surviving a rebuild.** Two rebuilds, in fact.
- [x] **Every acceptance criterion read back line by line.**
- [x] **The extraction gate runs against a real model, not merely skips.** Both behaviours
      observed.
- [x] **The ratchet re-measured after STORY-088** and its floors raised from the measurement.

## Numbers

- **304 backend unit, 345 backend integration, 192 frontend** — 841 tests, from 821 at sprint
  start.
- **~91 seconds a chunk**, unchanged, and now what the README says.
