# STORY-101: Every edition is rebuilt under the rules the extractor now has

**Epic:** — · **Status:** Done · **Estimate:** M

## User story

As someone trusting what the graph says about who must do what, I want every edition re-extracted
under the rules now enforced, so that the obligations I read are the ones the current extractor
would produce rather than the ones an older one did.

## Context

[ADR-034](../../specs/adr/ADR-034-a-statement-is-a-quotation.md) and
[ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md) both landed after the
graph was last built, and both refuse items the graph currently holds. Measured 2026-08-28,
before the guards existed:

- **34 of 196 obligations (17%) hold a statement that is not in the chunk it was read from** —
  SHALL 10%, WILL 18%, MUST 11%, ASSIGNED 46%.
- **20 obligations carry the string `"null"` as their actor**, which `actor IS NOT NULL` counts
  as a name.
- **8 obligations attribute USD(A&S)'s duties to the DoD CIO, DOT&E and the CJCS**, none of which
  the document says.

The guards fix what is written next. They do not touch what is already there, and nothing in the
product tells a reader which obligations predate them.

**The cache does not stand in the way, and that is worth knowing before estimating.** Cache entries
are replayed through `validate_extracted`, so a rebuild re-validates them under the current rules
rather than trusting what was stored — the behaviour ADR-030 was extended for in sprint 8. A
rebuild will therefore drop the bad rows without re-running the model on chunks whose extraction
has not changed.

## Acceptance criteria

- [ ] Every edition with a source file is rebuilt: five editions across three documents.
- [ ] The obligation count before and after is recorded per edition, with the drop attributed to a
      reason — not a quotation, placeholder actor, ASSIGNED outside a responsibilities section.
- [ ] A query demonstrates that **no** obligation in the graph has a statement absent from the
      chunk it is anchored in. This is the acceptance test, and it is the same check
      `validate_extracted` makes, run over stored data rather than over an extractor's output.
- [ ] The three false attributions are gone: no obligation places USD(A&S)'s duties under the DoD
      CIO, DOT&E or the CJCS.
- [ ] `:LinkDecision` survives, and the count of decisions re-pointed or stranded is reported.
      ADR-027 exists for exactly this, and a rebuild that drops 17% of obligations is the largest
      test it has faced.
- [ ] If the rebuild strands a decision, that is a finding reported in the review, not a number
      buried in a count.

## Dependencies

- The quotation guard and the placeholder rule, both landed.
- A rebuild of five editions. Sprint 9 measured one at roughly 45 minutes with a cold cache and
  under 15 with a warm one. Size the session accordingly.

## Notes

This is the story that decides whether the derived layer is genuinely rebuildable under changed
rules, which the project has claimed since DI-2 phase 4 and has only ever tested against rule
changes that refused *nothing already stored*.
