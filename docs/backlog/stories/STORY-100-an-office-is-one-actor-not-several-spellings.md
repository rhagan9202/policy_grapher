# STORY-100: An office is one actor, not several spellings

**Epic:** — · **Status:** Ready · **Estimate:** L

## User story

As someone asking what a named office is responsible for, I want that office's duties to be
reachable under one identity, so that the answer is not split across two spellings of its name.

## Context

Found by sprint 9's rebuild of DoDD 5000.01 (2020), the first run of ADR-033 against a real
document. Of 31 duties assigned by position, the same office appears twice:

| Actor as recorded | Duties |
| --- | ---: |
| `USD(A&S)` | 12 |
| `The USD(A&S)` | 2 |
| `acquisition executive` | 2 |

`actor` is free text on every modality and always has been. Nothing in the code claims it is
canonical, so this is a limitation rather than a defect, and it is recorded as one in
[sprint 9's review](../../sprints/sprint-09/review.md).

It matters more than it used to. Before ADR-033 the actor was a by-product; a duty was found by
its modal verb and the actor was whatever noun phrase carried it. A positional duty is
*defined* by the office it is assigned to — that is the whole content of "assigned by position" —
so the field has become load-bearing for the category this project just made visible.

It is also the field the roadmap's [Later](../../planning/roadmap.md#later) section depends on:
**richer metadata and relationships — which entities a policy applies to, who is responsible for
enforcing it.** A `:Entity` built over a field with two spellings of one office inherits the
problem into the schema.

## The decision this needs

**L because the decision is not made, per the [estimation scale](../README.md#estimation).** At
least three shapes exist and the choice is not obvious:

- **Normalise on the way in.** Strip leading articles, fold whitespace and case. Cheap, and it
  would merge `The USD(A&S)` with `USD(A&S)` today. It would not merge `acquisition executive`
  with anything, and it silently rewrites what the document said.
- **Resolve to an `:Entity` node**, with the recorded string kept as written and the node carrying
  the canonical name. This is what the roadmap's Later section wants anyway, and it makes the
  question "what is this office responsible for" answerable by traversal. It is a schema
  migration, and STORY-092 deleted the last `:Entity` code for being unreachable — writing it
  again needs a spec that says what an ingest path does with it.
- **Leave it and say so**, narrowing the claim to "the actor as the document wrote it". Honest,
  and it makes the Policy Concierge direction wait.

**Whichever is chosen, the recorded string must survive.** `obligation_id` hashes the statement
and not the actor, so normalising the actor moves no identity — but a document that wrote
"The USD(A&S)" said that, and a product that quotes policy has to be able to show what was
written.

## Dependencies

- None to start refining. It should not enter a sprint before the shape above is decided, and
  that decision is an ADR.

## Open questions

- Is this one problem or two? Article-stripping and `acquisition executive` are different
  failures — one is a spelling of a name, the other is an incomplete extraction, and a
  normalisation rule that "fixes" the second would be inventing an office the model did not name.
- How many offices does the corpus actually have? Nobody has counted across all seven samples, and
  the answer decides whether a canonical list is maintainable by hand or has to be derived.
