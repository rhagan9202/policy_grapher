# STORY-097: The responsibilities section of an issuance is invisible

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As a policy analyst asking who must do what, I want the section of an issuance that assigns
duties to organisations to be extractable, so that the product can see the part of a DoD document
most directly about its own question.

## Context

Found by [STORY-095](STORY-095-the-rejection-rate-is-diagnosed.md), which set out to explain why
roughly half of every document yields no obligation. Most of the answer is benign — covers,
tables of contents, reference lists and definitions state no duties, and refusing them is right.
This is the part that is not benign.

DoD writes its **Responsibilities** section as a role heading followed by lettered third-person
verbs, with no modal verb anywhere:

> 2.2. UNDER SECRETARY OF DEFENSE FOR RESEARCH AND ENGINEERING (USD(R&E)). The USD(R&E):
> a. Executes the research and engineering responsibilities in DoDD 5137.02.
> b. Serves as a technical advisor in the preparation of MDAP AoA study guidance.
> c. Confirms that a materiel solution … is technically feasible and achievable.
> d. Conducts and approves independent technical risk assessments for ACAT ID Programs.

Those are six duties assigned to a named actor, and the schema cannot express any of them:
`Modality` is closed, a statement must contain the modality it is labelled with, and there is no
modal verb to point at. So the product refuses them — correctly, under its own rules — and cannot
see the section of the document that most directly answers "who must do what".

Measured across `data/samples`: 6 such chunks in DoDD 5000.01's 2020 edition, 7 in the Change 1
edition, 13 in DoDI 8500.01, 3 in DoDI 5000.88, 2 in DoDD 5143.01.

## The decision, now made

**[ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md) decided it**, on
2026-08-27, and this story is what implements that decision. Both questions this story was filed
open are answered there: a positional duty **is binding**, and it **weighs the same as `SHALL`**
in Triage. The evidence the ADR argues from was measured while resolving this story — **91
positional duties across `data/samples`** against 164 obligations in the graph, concentrated in
`SECTION 2: RESPONSIBILITIES`, and **none at all in the 2003 edition of DoDD 5000.01**, which is
what makes this a modern drafting convention rather than a permanent gap.

The size drops from L to M because the L was the unmade decision, and it is made. What remains
touches several files and needs new tests to design, which is the M row exactly.

## Acceptance criteria

- [ ] `Modality` has a sixth member, `ASSIGNED`, and its docstring says the enum records *how* a
      duty was imposed — by word or by position — rather than "the word the document used".
- [ ] The statement-must-contain-its-modality rule is **restated, not exempted**: if a modality
      names a word, the statement must contain that word. A test asserts each of the five word
      values is still inside the rule, and that `ASSIGNED` falls outside it by naming no word.
- [ ] The schema refuses an `ASSIGNED` item with a null actor. A duty assigned to nobody is not a
      positional duty.
- [ ] The adapter refuses an `ASSIGNED` item from a chunk whose `section_path` is outside a
      responsibilities section. This guard cannot live in the schema, which validates an item
      without knowing where it came from.
- [ ] A test asserts `"Be Responsive."` is still refused, naming both guards it fails — no actor,
      and `SECTION 1`. This is the regression the whole guard exists to prevent.
- [ ] `is_binding` is true for `ASSIGNED`, asserted directly rather than inferred.
- [ ] `MODALITY_WEIGHT[ASSIGNED] == 4.0`, and STORY-085's explicit expected mapping records it.
      ADR-025's keys-equal-members test must pass **without being loosened**.
- [ ] The gold set gains at least one `ASSIGNED` example transcribed from a real responsibilities
      section, so STORY-084's coverage test passes without being loosened.
- [ ] The prompt teaches the positional form, `PROMPT_VERSION` is bumped, and the extraction cache
      therefore misses rather than replaying entries written before the rule existed.
- [ ] The ratchet floors are re-measured at temperature 0 **three times** after the change, and
      the numbers recorded. If any floor moves down, the sprint review says so and says why — a
      floor quietly lowered to accommodate a prompt change is how this gate would die.
- [ ] A full rebuild of DoDD 5000.01 (2020) yields `ASSIGNED` obligations attributed to named
      offices, and the count is recorded against the **21 counted by hand** in that edition.

## Dependencies

- [ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md) — satisfied. It was
  the blocker, and writing it was the L this story used to carry.
- A rebuild is needed to demonstrate the last criterion, and a rebuild of one edition takes hours
  on this hardware. Size the sprint expecting that, not a unit test.

## Notes

ADR-033 names three existing checks that **will fail when this lands, and are correct to** —
STORY-084's gold-set coverage, ADR-025's weights-cover-the-enum, and STORY-085's explicit
mapping. They are the safety net working. None of them may be loosened to go green; each is
satisfied by supplying what it asks for.
