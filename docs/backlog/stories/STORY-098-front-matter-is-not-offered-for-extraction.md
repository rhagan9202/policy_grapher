# STORY-098: Front matter is not offered to the extractor

**Epic:** — · **Status:** Refining · **Estimate:** M

## User story

As someone paying for inference by the chunk, I want the cover, the table of contents and the
reference list to be skipped rather than sent to a model, so that a quarter of every run is not
spent asking for duties from pages that state none.

## Context

Found by [STORY-095](STORY-095-the-rejection-rate-is-diagnosed.md). Of the 21 chunks in DoDD
5000.01's 2020 edition that produced no valid obligation, **18 contain no modal verb at all** and
4 are table-of-contents pages — runs of dotted leaders and page numbers. The cover page and the
`REFERENCES` section are in there too.

Each one costs a model call of roughly ninety seconds, and the answer is knowable without one: a
page of dotted leaders states no duty. Worse, the model does not return nothing — it invents,
labelling headings `SHALL`, which is what the modality rule now refuses one item at a time.

This is not the *cause* of the rejection rate — [STORY-097](STORY-097-the-responsibilities-section-is-invisible.md)
is the part that matters — but it is the cheap half, and it is measurable: about 4 chunks in 37
here, more in longer documents.

## Acceptance criteria

- [ ] A chunk that is table-of-contents matter is not sent to the extractor, and the run reports
      how many it skipped — silent skipping is the same defect as silent dropping (ADR-030).
- [ ] Detection is structural rather than a keyword list: dotted leaders and page-number runs are
      what a contents page is, in any issuance.
- [ ] Given a document with no contents page, **Then** nothing is skipped and the counts say zero.
- [ ] A skipped chunk is still written as a `:Chunk` — it is part of the document's text and Ask
      retrieves from it. Only extraction is skipped.
- [ ] The extraction ratchet is re-measured afterwards; skipping input the model was failing on
      should not move recall, and if it does that is a finding.

## Dependencies

- None. It sits upstream of extraction and touches no decision ADR-030 or ADR-025 took.

## Open questions

- Should the `REFERENCES` section be skipped too? It is already parsed by
  `sources/pdf.py` for the reference graph, so extracting obligations from it is pure waste — but
  it is a named section rather than a structural shape, and skipping by section name is the
  keyword list this story's second criterion rejects.
