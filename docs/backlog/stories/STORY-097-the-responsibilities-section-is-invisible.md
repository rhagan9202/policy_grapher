# STORY-097: The responsibilities section of an issuance is invisible

**Epic:** — · **Status:** Refining · **Estimate:** L

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

## The decision this needs

`Modality` is closed *on purpose* — "SHALL misread as SHOULD downgrades a binding duty to advice,
silently" — and [ADR-025](../../specs/adr/ADR-025-will-is-a-modality-and-bindingness-is-derived.md)
widened it once, for `WILL`, on the evidence that DoD's plain-language drafting had replaced
`shall` with it. This is the same shape of question and a harder instance: there is no word to
add. A bare imperative under a role heading is a duty by *position*, not by vocabulary.

Three shapes are visible and none is obviously right:

- **A sixth modality** meaning "assigned by position, no modal verb". Honest about what the
  document does, and it makes `is_binding` a question ADR-025's reasoning does not answer.
- **A separate node type** for role assignments, leaving `:Obligation` alone. Keeps the modality
  guarantee intact and doubles what Triage and Review have to understand.
- **Leave it.** Defensible only if the product's claim is narrowed to "obligations stated with a
  modal verb", which the vision does not currently say.

**That decision is the work.** This is L for exactly the reason the backlog's estimation note
gives, and it should be split into an ADR before any implementation.

## Dependencies

- None. The evidence is in sprint 8's review.

## Open questions

- Does `is_binding` mean anything for a positional duty? ADR-025 derives bindingness from the
  word used, and there is no word here.
- Would Triage rank these? `MODALITY_WEIGHT` has no entry for something with no modality, and
  ADR-025's test asserts the weight table's keys equal the enum's members.
