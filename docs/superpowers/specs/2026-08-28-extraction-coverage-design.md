# Extraction coverage: positional duties, and front matter that costs nothing

**Status:** Design · **Date:** 2026-08-28 · **Sprint:** [9](../../sprints/sprint-09/plan.md)

Implements [ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md) as
[STORY-097](../../backlog/stories/STORY-097-the-responsibilities-section-is-invisible.md), and
[STORY-098](../../backlog/stories/STORY-098-front-matter-is-not-offered-for-extraction.md)
alongside it. The two share this document because they share a pipeline stage, a prompt version
and a ratchet re-measurement — separating them would mean measuring the extractor twice for one
set of changes.

The two small items in sprint 9,
[STORY-099](../../backlog/stories/STORY-099-every-route-is-reached-by-a-real-request.md) and
[STORY-075](../../backlog/stories/STORY-075-a-chunk-on-a-section-join-is-attributed-to-the-right-page.md),
are bounded changes to code that already exists and need no design. They are in the plan, not
here.

## The problem, restated in one paragraph

DoD assigns duties by position: a role heading, then lettered third-person verbs. `Modality` is
closed, a statement must contain the word it is labelled with, and there is no word — so the
extractor refuses all of them. ADR-033 decided the answer: a sixth modality, `ASSIGNED`, binding,
weighing what `SHALL` weighs, guarded structurally rather than lexically. This document is how.

## What the code review changed about ADR-033

**ADR-033's clause 5 says the adapter accepts `ASSIGNED` "only for a chunk whose `section_path`
sits in a responsibilities section". `section_path` cannot answer that question.**
`chunking.NAMED` is `^(?P<kind>CHAPTER|SECTION|APPENDIX|ENCLOSURE)\s+(?P<id>[\dIVXA-Z]+)\b`, so
the path element for the section titled `SECTION 2:  RESPONSIBILITIES` is the string
`"SECTION 2"`. **The title is captured and discarded.** A chunk in that section has
`section_path == ["SECTION 2", "2.2"]`, which names a position in the document and says nothing
about what the section is.

The decision ADR-033 took stands unchanged — the guard is still the section, not a vocabulary.
What this design adds is the mechanism it assumed existed.

**The title is recoverable structurally, in both formats, and they differ:**

| Format | Heading line | Where the title is |
| --- | --- | --- |
| Modern (`500001p.pdf`, `500088p.pdf`) | `SECTION 2:  RESPONSIBILITIES` | On the heading line, after the colon |
| Older (`850001_2014.pdf`) | `ENCLOSURE 2` | The next non-blank line: `RESPONSIBILITIES` |

Verified against the samples: the older format's enclosures resolve to `REFERENCES`,
`RESPONSIBILITIES` and `PROCEDURES` respectively, and the modern format's running header repeats
the heading with a page number appended (`SECTION 2:  RESPONSIBILITIES 11`), which the existing
`_page_furniture` machinery already suppresses for heading *detection* and which the title parse
must strip anyway.

### `section_title` is a new attribute, and it must not be part of any identity

This is the constraint that shapes the whole change. `section_path` is hashed into **both**
`_chunk_id` and `obligation_id`. Putting the title into the path would re-key every chunk and
every obligation in the graph, orphaning every human decision recorded against them — the exact
failure ADR-012 exists to prevent, and the reason its ids are keyed on structure rather than on
offsets.

So: `Chunk` gains a `section_title: str | None` field, stored on `:Chunk`, threaded to the
extractor, and hashed into nothing. A document whose format hides its titles yields `None`
everywhere and simply never produces an `ASSIGNED` obligation, which is the correct conservative
failure.

## What the guard costs, measured

A responsibilities-only guard does not capture every positionally assigned duty. Counting lettered
third-person items across `data/samples` and bucketing by the enclosing section's title:

| Where | Count | Share |
| --- | ---: | ---: |
| A section titled RESPONSIBILITIES | 151 | 75% |
| Elsewhere — chiefly PROCEDURES in `850001_2014.pdf` (26) | 49 | 25% |

That detector is deliberately coarse and over-counts: it matches any lettered item opening with a
third-person verb, including prose that states no duty. The hand count of *actual* positional
duties is 91. Read the table as a ratio, not as totals.

**Roughly a quarter of positionally-shaped items sit outside a responsibilities section and this
design refuses them all.** That is a deliberate first cut, precision over recall, consistent with
how this project has treated every extraction question so far — and it is measurable, so a later
decision to widen it can argue from a number. It is not a defect to be fixed quietly during
implementation; widening the guard is a new decision and needs its own ADR.

The coarse detector also produces the best evidence that the guard works: `818001m.pdf`, a records
management manual, contributes 16 lettered third-person items spread across eleven small sections
titled `OVERVIEW`, `METADATA`, `CAPTURE`, `DISPOSITION` and the like. Almost none of them are
duties assigned to an office, and the guard refuses every one.

## Design

### 1. The schema

```python
class Modality(StrEnum):
    SHALL = "SHALL"
    MUST = "MUST"
    WILL = "WILL"
    SHOULD = "SHOULD"
    MAY = "MAY"
    ASSIGNED = "ASSIGNED"
```

- The class docstring stops saying "the word the document used" and says the enum records *how* a
  duty was imposed — by word, or by position.
- `WORD_MODALITIES = frozenset(Modality) - {Modality.ASSIGNED}` names the five that quote a word.
  Derived, not listed, so a sixth word added later cannot be forgotten here.
- `BINDING` gains `ASSIGNED`.
- `_modality_word_is_in_the_statement` becomes: if `self.modality in WORD_MODALITIES`, the
  statement must contain it. `ASSIGNED` is outside the rule **because it names no word**, not
  because it is listed as an exception.
- A new validator: `ASSIGNED` requires a non-null `actor`. A duty assigned to nobody is not one.

### 2. The section guard, and where it lives

The schema validates an item without knowing where it came from, so the section half of the guard
cannot live there. It goes in one function, called by both adapters that validate items:

```python
def is_responsibilities_section(section_title: str | None) -> bool:
    """Whether a section's own title says it assigns responsibilities."""
```

Matched on the title naming responsibility — `RESPONSIBILITIES`, and the singular — case
insensitively, against the title the document itself wrote. This is not the keyword list
STORY-098's criterion forbids: it reads one word out of the document's own heading rather than
enumerating which sections of which issuances count.

Both `local.py` and `cache.py` currently call `ExtractedObligation.model_validate(item)` directly.
Both change to call one shared helper that takes the item and the section title, so the rule
exists once:

```python
def validate_extracted(item: dict, *, section_title: str | None) -> ExtractedObligation:
    """Schema validation, plus the part of ADR-033 that needs to know the section."""
```

The cache key already includes `section_path`, so a replayed item is always replayed into the
section it was extracted from; applying the guard there too costs nothing and means the rule
cannot be bypassed by a cache hit.

**A refused `ASSIGNED` is a dropped item, not a rejected chunk.** ADR-030 governs: it costs itself
and the other obligations from that chunk survive, with the reason reported through the existing
`on_drop` channel.

### 3. The prompt

`PROMPT_VERSION` goes to 3, so the cache misses rather than replaying answers produced under a
prompt that told the model the opposite.

The current prompt actively teaches the behaviour this sprint reverses:

> - Bare task lists. A role followed by lettered items — "ISSOs: a. Assist the ISSMs..." —
>   instructs without a modal verb.
>
> Omit all three.

That instruction is removed from the omit-list and replaced with a rule that reports the form as
`ASSIGNED`, with the actor taken from the role heading. **Scope and headings stay in the omit
list** — they are still not duties, and this is exactly where a careless edit would reopen the
`"Be Responsive."` regression.

### 4. Triage

`MODALITY_WEIGHT["ASSIGNED"] = 4.0`, with a comment giving ADR-033's reason rather than restating
the number. `EXPECTED_MODALITY_WEIGHT` in `test_triage.py` records it — that test exists to make
the value a decision rather than a default, so it is updated deliberately and not to go green.

### 5. The gold set

A new fixture transcribed by hand from a real responsibilities section, with `ASSIGNED`
obligations carrying their actors. `test_the_gold_set_covers_every_modality_the_schema_allows`
fails until it exists, which is the check working.

The fixture must come from a document already in `data/samples` and be transcribed from the actual
text — a fabricated example would ratchet the extractor against prose no document contains.

### 6. STORY-098: what is not sent to the model

Three kinds of matter are skipped, all located by structure this repository already trusts:

| Matter | Located by | Already used for |
| --- | --- | --- |
| Cover | the cover-matter bound in `sources/pdf.py` | deciding which citations are the document's own |
| References | `locate_references(full)` | building the reference graph since STORY-016 |
| Contents pages | runs of dot leaders — `chunking.DOT_LEADER` | suppressing contents rows as false headings |

**A skipped chunk is still written as a `:Chunk`.** It is part of the document's text and Ask
retrieves over it; only the model call is skipped. The rebuild reports how many were skipped and
why, through the same reporting path ADR-030 established for drops — a silent skip is the defect
that ADR made a rejected chunk announce itself to avoid.

## Testing

Every claim below is a test, and each names the production change that would make it fail.

| What | Fails if |
| --- | --- |
| Each of the five word modalities still requires its word in the statement | the restated rule is written as an exception list and a word modality slips out of it |
| `ASSIGNED` validates with no modal verb in the statement | the rule is applied to all six |
| `ASSIGNED` with a null actor is refused | the actor validator is missing |
| `"Be Responsive."` is refused, naming both guards it fails | either guard is dropped — **the regression test of this sprint** |
| An `ASSIGNED` item outside a responsibilities section is refused | the section guard is not consulted, or consults `section_path` instead of the title |
| A refused `ASSIGNED` costs itself, not its chunk | the drop is routed as a chunk rejection, which is the mistake ADR-030's first wiring made |
| `section_title` is absent from `_chunk_id` and `obligation_id` inputs | the title is threaded into a path or a key |
| A modern and an older-format heading both yield their title | only one format's parse is implemented |
| A skipped chunk is still written as a `:Chunk` | skipping is applied before chunk storage instead of before extraction |
| A document with no contents page skips nothing and counts zero | detection matches something other than dot leaders |

**Mutation is required, not optional.** Three sprints running have produced a guard that did not
guard, and the tell was identical each time: it passed the first run. Every test above is watched
failing before its implementation exists.

## What this design refuses to do

- **It does not loosen the three checks that will break.** STORY-084's gold-set coverage,
  ADR-025's weights-cover-the-enum and STORY-085's explicit mapping all fail the moment `Modality`
  gains a member. Each is satisfied by supplying what it asks for. Editing any of them to
  accommodate the change trades the safety net for a green tick.
- **It does not widen the guard to catch the PROCEDURES cases.** Measured at 25% above; widening
  is a new decision, and this sprint's job is to produce the number that decision would argue
  from.
- **It does not touch `:Authority` or `:Entity`.** The `actor` data this produces is the argument
  for writing them again from a spec; that is not this sprint.
