# STORY-016 — PDF ingestion design

*Design document. Written 2026-08-13. Behavioural authority remains
[SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md); this covers one story and amends
nothing until implemented.*

**Goal:** `POST /ingest` accepts a DoD issuance PDF, creates the document it describes, and
creates `REFERENCES` edges to the documents it cites — reporting what it could not attribute
rather than discarding it.

**Related:** [ADR-005](../../specs/adr/ADR-005-slug-assignment-over-the-name-set.md) (slug
assignment on the incremental path), [ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)
(no `reference_role` to extract). Splits STORY-035 (DOCX) and STORY-036 (XLSX) out of the
original story text.

---

## Evidence base

Every structural claim here was measured against five DoD issuance PDFs committed at
`data/samples/`, using the corpus CSV as an oracle: for each of the 23 corpus documents the
CSV states the references that document should yield, so extraction is *scored*, not judged
by eye.

Measurements come from a throwaway probe, not from production code, and the probe was
discarded. What it established:

| Document | Format | Matched | Note |
| --- | --- | --- | --- |
| DoDD 5000.01 | modern | 13/15 (87%) | 0 spurious |
| DoDM 8180.01 | modern | 14/24 (58%) | |
| DoDI 5000.88 | modern | 14/27 (52%) | |
| DoDI 8500.01 | legacy | 91/114 (80%) | first attempt at lettered entries |
| DoDD 5143.01 | legacy | 0/70 | section located, slice boundary wrong |

**The dominant failure mode is locating the references section, not parsing entries.** Both
zero scores were section-location bugs; within a correctly located section, entry parsing
reached 80–87% on a first attempt. This shapes the whole design: stage 2 below is isolated
and tested independently because it is where catastrophic failure lives.

## Two source protocols, not one

A CSV and a PDF are not the same kind of input:

| | CSV (manifest) | PDF (document) |
| --- | --- | --- |
| Documents per file | 23 | 1 |
| Reference targets | Given, pre-extracted | Recovered, partially |
| Slug assignment | Whole name set at once | One document joining an existing graph |

The pipeline therefore exposes two operations, both feeding the existing merge layer:

- `parse_corpus(path) -> ParsedCorpus` — a manifest becomes many documents. CSV; XLSX later.
- `extract_document(path) -> ExtractedDocument` — one file becomes one document, its
  candidate references, and an extraction report. PDF; DOCX later.

Forcing these into one protocol would mean pretending a PDF is a one-row spreadsheet.

**Slug consequence, from ADR-005.** The manifest path assigns slugs over the whole name set,
suffixing every contender for a contested base. A PDF arrives alone, so it takes the
*incremental* path — `allocate_slug`, where the incumbent keeps its bare slug and the
newcomer is suffixed. Ingesting twenty PDFs in a different order can therefore produce
different slugs where base slugs contest. ADR-005 accepted that trade for URL stability; this
design inherits it rather than reopening it.

## Module layout

```
backend/src/policy_grapher/sources/
  __init__.py       dispatch by extension
  manifest.py       parse_corpus — moved verbatim from csv_source.py
  document.py       extract_document protocol, ExtractedDocument, ExtractionReport
  pdf.py            the five stages below
  docx.py           STORY-035 — not written
```

`csv_source.py` moves to `sources/manifest.py` with no behaviour change: same functions, same
exceptions, existing tests untouched. `ingest.py` keeps the merge layer and gains a second
entry point for the single-document path.

## Extraction, stage by stage

**Text layer: `pypdf`.** Pure Python, BSD-licensed, no system libraries, proven against all
five fixtures. `pymupdf` extracts better but is AGPL — a licensing decision nobody has asked
for. `pdfplumber` brings layout precision this does not need.

**1 — Detect format by structure.** Legacy documents mark entries `(a) (b) … (aa) (ab)`;
modern documents use a flat list. Detection keys on the presence of lettered markers
following a references heading, *not* on the heading text: three heading spellings appeared
across five documents (`REFERENCES`, `ENCLOSURE 1` + `REFERENCES`, `ENCLOSURE` + `REFERENCES`),
while the entry markers were consistent.

**2 — Locate the section.** The risky stage, isolated and independently tested. It returns an
explicit *not found* rather than an empty string, because those two outcomes are
indistinguishable downstream and mean entirely different things. Both catastrophic failures
measured were here: one from matching a body-text mention of "References" (a legacy document
contains about thirty), one from a wrong end boundary.

**3 — Split entries.** Legacy splits on the lettered markers. Modern splits on
identifier-prefix boundaries.

**4 — Take the identifier**: the text preceding the quoted title. Entries carrying no quoted
title — `Title 10, United States Code` — need their own rule; they were a measured miss.

**5 — Normalise** to the vocabulary the corpus uses:

| Source text | Normalised |
| --- | --- |
| `DoD Directive 5000.01` | `DoDD 5000.01` |
| `DoD Instruction 8500.01` | `DoDI 8500.01` |
| `DoD Manual 8180.01` | `DoDM 8180.01` |
| `Title 10, United States Code` | `United States Code, Title 10` |
| `Public Law 116-283`, `Military-Standard 882E` | unchanged |

The word-order reversal on US Code entries is a real difference between what the documents
say and what the corpus records, not a tidy-up.

**Document identity** comes from the header and differs by format: modern puts it on one line
(`DOD DIRECTIVE 5000.01`), legacy splits it across two (`DIRECTIVE` … `NUMBER 5143.01`). Both
pass through the same normalisation, which is what lets the CSV serve as an oracle at all.

**Self-references stay skipped**, and the mechanism is now known. A reissuing document lists
its own cancelled prior version *as an entry in its own references enclosure* — `DoDD 5143.01`
carries `(a) DoD Directive 5143.01, "...," November 23, 2005 (hereby cancelled)`. It is not
the header's `Reissues and Cancels` line, which stage 2 never reads.

This is verified against the oracle in both directions: `DoDD 5143.01` lists itself and the
CSV records it as self-citing; `DoDD 5000.01` does not appear in its own `REFERENCES` and the
CSV records no self-citation for it. That the two agree is also the strongest evidence the
corpus CSV was built from these enclosures — which is what makes it a legitimate oracle.

The `(hereby cancelled)` marker is a usable signal for a superseding relationship, but
STORY-016 does not act on it: `SUPERSEDES` is one of the typed edges
[ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md) records as
direction rather than schema, and it needs its own design.

## Endpoint

`POST /ingest` keeps its request shape and dispatches on extension. The path-resolution and
traversal-refusal logic is unchanged and unduplicated. The response becomes a discriminated
union on `source`:

```
{"filename": "dod_policy_references_08122026.csv"}
  -> {source: "manifest", nodes_created, relationships_created,
      self_references_skipped, suspected_duplicates}

{"filename": "500001p.pdf"}
  -> {source: "document", format: "modern",
      document: {slug, name},
      nodes_created, relationships_created,
      references_attributed: 13,
      references_unattributed: ["Summary of the 2018 National Defense Strategy ..."],
      self_references_skipped: 0}
```

The figures illustrate the *shape*; real counts follow from the built parser. The
unattributed entry shown is genuine, though: that entry opens with a quoted title and carries
no identifier, so the stage-4 rule cannot attribute it — and the corpus CSV omits it too.
`DoDD 5000.01` skips no self-reference because it does not cite itself.

The manifest response is byte-identical to today's, so existing tests and the typed frontend
client need no changes for this story.

**One file per call.** A directory loop belongs in the client: ADR-005 means order affects
slugs where bases contest, and burying that inside one call makes it invisible.

## Failure handling

| Outcome | Behaviour |
| --- | --- |
| Section not found | Document created, zero references, report says `section_not_found` |
| Entry unparseable | Reported verbatim, no edge created |
| Identifier parsed, no matching document | Edge to a new `:External` node — existing behaviour |

Nothing is silently dropped. The graph stays a subset of the truth rather than a distortion
of it, and `references_unattributed` is the input STORY-017's review screen consumes.

## Extraction is deterministic, deliberately

No spaCy, no local model, no hosted model in the extraction path. Two reasons, both concrete:

**Idempotency is a tested invariant.** STORY-003 asserts that re-ingesting a file creates
nothing new, and the `MERGE` design rests on it. A nondeterministic extractor breaks it — the
same PDF could yield different edges on different days.

**Failure visibility.** A deterministic parser fails *visibly*: an entry it cannot attribute
appears in `references_unattributed`. A small model fails *invisibly*, returning
`DoDI 8510.01` where the page says `DoDI 8510.01A` — a silently wrong edge in a graph whose
meaning lives entirely in its edges ([ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)).
Missing beats wrong-but-plausible here.

The measured headroom also does not justify a model: 59% of the misses came from one
section-slicing bug. Estimated gain from spaCy is +2–5%, from a local small model +5–10% over
a working parser — against an invariant, a heavyweight dependency, and an invisible failure
class.

**A local model remains attractive one layer up**, proposing candidate matches for the
unattributed residue in STORY-017's review screen, where a human confirms before the graph
changes. That sidesteps both objections and is where the deferred decision lives.

## Testing

Fixtures are the five committed PDFs; the oracle is the corpus CSV.

- **Per-stage tests.** Format detection, section location, entry splitting, identifier
  extraction and normalisation are tested independently. Section location gets the most,
  including the three heading variants and a document with no section at all.
- **A ratchet test.** Per-document minimum match rates, set from what the parser actually
  achieves once written, asserted as floors that can only be raised. This turns "extraction
  quality" from a claim in a document into a number that fails the build when it regresses.
  The floors are deliberately not fixed in this design: writing a target the implementation
  must then hit is how specs become fiction.
- **Idempotency per format.** Re-ingesting the same PDF yields `nodes_created: 0`.
- **The manifest path is unchanged**, so the existing suite is the regression guard for it.

Tests requiring a container stay marked `integration`; extraction itself needs no database
and belongs in the Docker-free subset.

## Out of scope

Storing document text (STORY-017 decides where it lives), reconciling extracted names against
near-duplicates (STORY-031), directory ingestion, model-assisted extraction, and DOCX
(STORY-035) and XLSX (STORY-036).

## Open question

**The ratchet floors are unset until the parser exists.** The probe reached 53% overall with
known bugs; per-format best-case was 80–87%. A real parser should land at or above that, but
this design deliberately does not commit to a number it has not measured. First
implementation task is to fix section location and measure; the floors follow from that.
