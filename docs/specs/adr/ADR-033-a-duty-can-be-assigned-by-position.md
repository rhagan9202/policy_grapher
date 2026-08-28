# ADR-033: A duty can be assigned by position, not only by word

**Status:** Accepted · **Date:** 2026-08-27 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-025](ADR-025-will-is-a-modality-and-bindingness-is-derived.md)**, which widened
`Modality` once and derived bindingness from the word used. Everything it decided about the five
existing values stands.

## Context

Sprint 8's [STORY-095](../../backlog/stories/STORY-095-the-rejection-rate-is-diagnosed.md) set
out to explain why roughly half of every document yields no obligation. Most of the answer was
benign — covers, contents pages and reference lists state no duties. This is the part that was
not.

DoD writes its **RESPONSIBILITIES** section as a role heading followed by lettered third-person
verbs:

> 2.2. UNDER SECRETARY OF DEFENSE FOR RESEARCH AND ENGINEERING (USD(R&E)). The USD(R&E):
> a. Executes the research and engineering responsibilities in DoDD 5137.02.
> b. Serves as a technical advisor in the preparation of MDAP AoA study guidance.
> c. Confirms that a materiel solution … is technically feasible and achievable.

Six duties, a named office, and **no modal verb anywhere**. `Modality` is closed and a statement
must contain the modality it is labelled with (sprint 7), so the extractor refuses them — 
correctly, under the rules as they stood. The consequence is that the product cannot read the
section of a DoD issuance most directly about who must do what, which is close to the question it
exists to answer.

**Measured across `data/samples`: 91 such duties**, against 164 obligations in the graph at the
time — a category worth about half again what the product currently sees. They concentrate in
`SECTION 2 / 2.1`, `2.2`, `2.3`, which is titled `SECTION 2: RESPONSIBILITIES`, and in the older
format's enclosures.

**The 2003 edition of DoDD 5000.01 contains none.** This is a modern drafting convention, and
that is the same evidence ADR-025 acted on for `WILL`: DoD's plain-language rewrite changed how
duties are written and the schema lagged it. The difference is that `WILL` was a word to add, and
here there is no word at all.

## Decision

**`Modality` gains a sixth value, `ASSIGNED`, meaning the duty was imposed by position rather
than graded by a word.**

1. **`Modality` stops being "the word the document used" and becomes "how the duty was
   imposed".** Five values name a word; `ASSIGNED` names a position. That is a real widening of
   what the enum means and it is stated here so nobody has to infer it from a sixth member.
2. **`ASSIGNED` is binding.** ADR-025 established that bindingness is *this project's reading*,
   derived rather than extracted. Here the reading is of the position: a responsibility assigned
   to a named office is not advice. `is_binding` is true.
3. **It weighs the same as `SHALL` in Triage.** ADR-025 refused to rank `WILL` below `SHALL` for
   a drafting convention, and ranking a standing responsibility below a stated duty would repeat
   the mistake it avoided. Recorded as a judgement, not a measurement — no reviewer has yet
   worked through positional changes in Triage, and if the ranking proves wrong the remedy is a
   new decision, not a quiet edit.
4. **Sprint 7's rule is restated, not exempted.** It becomes: *if a modality names a word, the
   statement must contain that word.* `ASSIGNED` names no word, so it falls outside the rule by
   construction rather than by exception — which matters, because an exception list is how that
   check would rot.
5. **`ASSIGNED` is structurally guarded, in two places, and this is the load-bearing part.**
   Without a guard it becomes the escape hatch that returns the product to recording
   `"Be Responsive."` as a duty.
   - **The schema** requires a non-null `actor`. A positional duty is an assignment *to somebody*;
     one with nobody to assign it to is not one.
   - **The adapter** accepts it only for a chunk whose `section_path` sits in a responsibilities
     section. The schema cannot enforce this — it validates an item without knowing where the
     item came from — so the guard lives where the section is known.

   `"Be Responsive."` fails both: it has no actor and it sits in `SECTION 1`.

## Consequences

**What this buys.** The product can read the section that assigns duties to organisations, which
is roughly half again what it currently extracts, and the part a compliance reader most wants.

**What it costs, honestly.** `Modality` was closed so that a model inventing a binding level fails
loudly, and a value that names no word cannot be checked against the passage the way the other
five now are. Its guarantee is structural rather than lexical, and structural guards are weaker —
a mis-sectioned chunk admits a duty that is not one. The mitigation is that both guards must hold,
and the ratchet measures the result.

**Three existing checks will fail when this lands, and all three are correct to.** They are named
here so the implementation is not surprised by its own safety net:

- `test_the_gold_set_covers_every_modality_the_schema_allows` (STORY-084) fails until the gold set
  has an `ASSIGNED` example. It must be transcribed from a real responsibilities section.
- `test_every_modality_the_schema_allows_has_a_weight` (ADR-025) fails until `MODALITY_WEIGHT`
  has an entry.
- `test_the_modality_weights_are_exactly_what_was_decided` (STORY-085) fails until its expected
  mapping records the new weight — which is the point of an explicit mapping.

**What it does not change.** The five word-modalities keep their meanings and their rule.
`obligation_id` still hashes the normalised statement, so nothing about identity or ADR-027's
re-pointing moves. Nothing on the triage path becomes a model call.

## Alternatives considered

**A separate `:Responsibility` node type.** Keeps `Modality`'s lexical guarantee perfectly
intact, which is its whole appeal. Rejected because ADR-014, ADR-015 and ADR-030 all assume
`:Obligation`: Triage, Review, the diff and the proposer would each need to learn a second type,
for something that is an obligation in every sense this product cares about. The cost falls on
four subsystems to protect a guarantee that a structural guard can hold.

**Narrowing the product's claim** to obligations stated with a modal verb. Cheapest and entirely
honest, and it was a real option rather than a straw one. Rejected because the
[vision](../../planning/vision.md) does not say that, and the gap it concedes — the
responsibilities section — is the part of an issuance most directly about who must do what.
