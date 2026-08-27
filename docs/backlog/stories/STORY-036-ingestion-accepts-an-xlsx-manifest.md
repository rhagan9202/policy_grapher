# STORY-036: Ingestion accepts an XLSX manifest

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As someone with a corpus listed in a spreadsheet, I want to ingest it directly, so that a
manifest has to be converted to CSV before this product will read it only if I choose to convert
it.

## Context

One of the four file types the [vision](../../planning/vision.md#what-success-looks-like) names
in its definition of done — "Processes PDF, DOCX, XLSX, and CSV file types" — and the only one of
the two open ones that can actually be started.

**It is not blocked the way [STORY-035](../backlog.md#refining) is, and the difference matters.**
A DOCX issuance is a real DoD document whose structure we would have to discover; no sample
exists in the repo and inventing one means fitting extraction rules to a document we made up.
An XLSX *manifest* is our own format — the same three columns `sources/manifest.py` already
requires, `["Document Name", "References", "Type"]` — so a fixture built from the CSV that
already ships is a faithful sample, not a fabrication.

This is the manifest path, not document extraction. A manifest row describes a document and the
references between documents; it carries no text and records no edition
([ADR-011](../../specs/adr/ADR-011-instruments-have-versions.md)), so nothing here touches
chunking, obligations or the derived layer.

`sources/__init__.py` dispatches on file suffix and `sources/manifest.py` is 116 lines of
CSV-to-dataclass parsing with no Neo4j in it. The shape to copy is right there.

## Acceptance criteria

- [ ] `POST /ingest` accepts an `.xlsx` file in the data directory and produces the same
      documents and references a CSV of the same rows produces.
- [ ] A test asserts that equivalence directly — the same corpus expressed both ways ingests to
      the same result — rather than asserting the XLSX path alone works.
- [ ] Given an XLSX whose header row is not the three expected columns, **When** it is ingested,
      **Then** it fails naming the columns it found, the way `CsvSourceError` already does.
- [ ] `GET /ingest/sources` lists `.xlsx` files and labels them as manifests, so the Ingest
      screen offers them (STORY-077).
- [ ] A fixture `.xlsx` is committed, generated from the existing sample CSV so the two describe
      the same corpus, and the script or method that generated it is recorded.
- [ ] Given a `.xlsx` that is not a spreadsheet at all, **Then** the failure names the file
      rather than surfacing a library traceback.

## Dependencies

- A library that reads XLSX. `openpyxl` is the obvious choice and is not currently a dependency;
  adding it is part of this item and it belongs in the default runtime rather than a dev extra,
  because ingesting is a product action rather than a test one.
- No dependency on STORY-014 or anything else in sprint 8.

## Open questions

- Should a `.xls` (the older binary format) be accepted too? The criteria above say no —
  `openpyxl` does not read it, the vision says XLSX, and supporting it means a second library
  for a format nobody has asked for.

## Notes

Sized **M**, against the **S** sprint 6's backend review gave it. That review costed the parser
and the dispatch line correctly and did not account for the fixture: an XLSX has to be generated,
committed, and kept faithful to the CSV it mirrors, and the equivalence test above is what keeps
it honest. Still contained, still one new module.
