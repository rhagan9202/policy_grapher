# STORY-073: Each document edition is ratcheted against its own reference set, not its current successor's

**Epic:** — · **Status:** Refining · **Estimate:** L

## User story

As a maintainer changing the extraction pipeline, I want every fixture in the extraction
ratchet — including a superseded edition — to guard a real recall/invention floor, so that a
regression in legacy-cover parsing is caught the same way a regression in current parsing is.

## Context

`backend/tests/test_extraction_ratchet.py` scores each fixture's extracted references against
`data/samples/dod_policy_references_08122026.csv`, which the ratchet's own docstring describes
as one row per document *name*, holding the *current* edition's citation list. `RATCHETS`
carries five fixtures. A sixth, `500001p.pdf` (the 2020 edition of DoDD 5000.01), has a floor
of 1.00 — every citation the CSV lists, found.

`500001p_2003.pdf`, the 2003 edition of the same directive, is not in `RATCHETS`. The comment
above the dict explains why: the 2003 edition cites a cancelled DoD Directive 5000.1, DoD
Instruction 5000.2, and other since-superseded issuances that the CSV's row — describing the
2020 edition's references — does not list. Scoring the 2003 edition's genuine citations against
that row would find roughly 7% "recall", which is not a measurement of the 2003 edition's
extraction quality; it is a measurement of how much the reference lists of two editions,
fifteen years apart, disagree. A floor set from that number would certify a false 7% as
real, and a ceiling would license inventions that are not inventions — the 11-of-12 citations
scored as "invented" are simply citations the 2020 edition doesn't carry.

The legacy-cover path this fixture exercises — the one STORY-065 built — is pinned instead by
a direct, non-ratchet test: `test_a_legacy_inline_cover_yields_its_full_reference_set` in
`test_pdf_stages.py`. That proves extraction runs and returns something, not that a future
change couldn't quietly drop half of what it finds. It is the one fixture in the sample corpus
with no regression floor.

This is a real gap, not a decision already made. Building it needs a *per-edition* expected
reference set — the 2003 edition's actual citation list, not the 2020 edition's — and that set
does not exist yet anywhere in the repo. `dod_policy_references_08122026.csv` is generated
from (or hand-built against) current editions; extending it to carry one row per edition rather
than per document name is a schema change to a file the corpus-wide ratchet also depends on,
and touches whether other tooling that reads that CSV assumes one row per name.

## Notes

Two shapes are plausible and neither is obviously right:

- **Extend the existing CSV** to key on `(document name, edition)` instead of document name
  alone. Simplest to wire into `expected_references()`, but changes a shared file's schema and
  needs every existing row audited to confirm none of them are silently edition-ambiguous
  already.
- **A second, small CSV** scoped to editions that have a ratchet fixture — just the 2003
  edition today. Smaller blast radius, but a second source of the same kind of fact, which
  `docs/CONVENTIONS.md`'s "one fact, one home" argues against on principle.

Either way, the actual 2003-edition reference list has to be transcribed by hand from the
document once, the same way the current CSV was presumably built — there's no shortcut that
avoids someone reading the cover and writing down what it cites.

## Open questions

- Where does a per-edition expected set live, and does it replace or sit alongside the
  document-name-keyed CSV the corpus-wide ratchet already depends on?
- Who maintains it as new editions are added to the sample corpus — is transcribing an
  edition's reference list part of the same step that adds the fixture, or a separate one
  that's easy to skip?
- Is `500001p_2003.pdf` the only edition this affects today, or does the sample corpus already
  contain other multi-edition documents whose non-current edition is silently unratcheted the
  same way?
