# ADR-012: Chunks follow sections, and the derived layer is rebuildable

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-011](ADR-011-instruments-have-versions.md) gave every edition of an instrument a stable
node — `:DocumentVersion` — to attach state against, but attached nothing to it. Phase 3
(obligation extraction) and phase 6 (grounded question answering) both need the instrument's
actual text, addressable at a finer grain than "the whole PDF": an obligation is extracted from
a passage, and an answer has to cite a passage a reviewer can go read. `sources/pdf.py` reads
every page's text via `pypdf` today and immediately discards the page boundary — `text_of` joins
every page with a newline and hands back one string — so nothing in the graph today can say
"page 14" of anything, and nothing splits that string into pieces smaller than one whole
document.

Fixed-size character windows are the obvious way to split it, and the wrong one for policy
text. A window drawn purely by character count has no notion of where an obligation's own
conditions and scope qualifiers end — "Contractors shall report a data breach within 72 hours"
is one sentence, but the exception two sentences later ("unless the breach involves only
publicly available information") is what actually governs whether the 72-hour clock applies at
all. A window boundary falling between the two produces a chunk that reads as an unconditional
obligation. Retrieval built on top of that chunk answers confidently, and wrongly, because it
retrieved half the rule and had no way to know the other half existed. Any chunking design for
this corpus has to answer, first, what "half the rule" even means structurally — and a DoD
issuance already answers that: it is organised into numbered sections and subsections, and an
obligation's conditions live in the same section as the obligation, not in an arbitrary window
of prose.

## Options considered

**Fixed-size windows with overlap.** Split the flattened text every `max_chars` characters,
with an overlapping tail carried into the next chunk so a boundary-straddling sentence appears
whole in at least one chunk. Simple, and the default nearly every chunking library ships.
Rejected for the reason above: overlap reduces the chance a *sentence* gets cut in half, but
does nothing about an obligation's conditions landing in a different chunk than the obligation
itself, because a window has no notion of "this text is still part of the same rule" — only of
character count.

**Paragraph-bounded chunking.** Split on blank lines, treating each paragraph as a chunk.
Rejected: DoD issuances routinely state one obligation across several paragraphs (a lead-in
sentence, then a lettered sub-list of conditions, each its own paragraph), so this still
separates an obligation from what limits it, just at a different granularity than a fixed
window. It also carries no section hierarchy — a chunk's only handle on "where in the document
is this" is its raw position, which is not what a citation needs to point a reviewer at the
right place.

**Section-bounded chunking, splitting only within an oversized section.** Never let a chunk
boundary fall inside a section unless the section itself is too large to be one chunk, in which
case fixed-size splitting with overlap applies *within* that section only. Chosen.

## Decision

**Chunks follow the document's own section hierarchy.** `chunking.section_heading` recognises a
line that opens a numbered section (`3.2.1.`) or a named one (`CHAPTER 4`, `ENCLOSURE 2`), and
`chunk_pages` closes the section in progress and opens a new one whenever it sees one. A chunk
never spans two sections — the boundary a fixed window draws by character count, this design
draws by the document's own structure, so an obligation and the conditions the same section
states around it stay in the same chunk.

**Oversized sections split with overlap; undersized ones are never merged.** A section under
`max_chars` (2000, by default) becomes exactly one chunk. A section over that limit splits at a
paragraph or sentence boundary where one exists near the midpoint, with `overlap_chars` (200) of
trailing context carried into the next piece — the fixed-window mechanism, demoted to operating
*within* a section instead of across the whole document. A short section is left as its own
small chunk rather than merged into a neighbour: merging two sections into one chunk would mean
a single `section_path` value speaking for text that is not actually under that heading, which
corrupts the citation the next paragraph depends on.

**`section_path` is a list because a citation needs the hierarchy, not just the leaf.** `_push`
nests a heading under its numeric ancestors (`"3.2.1"` nests under `["3","3.2"]`), so a stored
chunk carries `["3", "3.2", "3.2.1"]`, not merely `"3.2.1"`. A reviewer citing a passage needs
to know it lives under Section 3.2, which lives under Section 3 — the leaf number alone is not
self-describing outside the document it came from. A path is not, however, *unique* within a
document: `850001_2014.pdf` opens 9 of its paths more than once (`["ENCLOSURE 3","1"]` four
separate times), because a numbered list restarting at 1 inside an enclosure re-opens the same
path — see the known limitation below. A path therefore locates a passage only together with
which opening of it is meant, which is why the occurrence counter is part of a chunk's identity.

**Text is stored verbatim.** `write_chunks` sets `c.text` to exactly what `chunk_pages`
produced — no whitespace normalisation, no re-flowing. A citation has to be able to quote the
passage exactly as the source document states it; a chunk that had been "cleaned up" would not
reliably match what a reader finds on the actual page.

**Page numbers are carried through extraction rather than reconstructed.** `sources/pdf.py`
already read every page separately via `pypdf` before this task; it just never kept the
boundary. `pages_of` now returns the per-page list `text_of` used to flatten away, and
`ExtractedDocument.pages` carries it to `ingest.py`. Each chunk's `page` is the page the section
it belongs to opened on. Reconstructing page numbers after the fact — e.g. guessing from
character offset into the joined text — would have been strictly worse than reading the number
`pypdf` already knew, for no benefit.

> **Superseded in part by [ADR-026](ADR-026-a-chunks-page-is-its-own-page.md).** The rule
> above — a chunk's `page` is the page the section it belongs to opened on — no longer holds.
> ADR-026 replaces it with the page the chunk's own text starts on. Nothing else in this
> decision changes.

**`:Chunk` is the first *derived* label.** Every other node this codebase has written so far —
`:Document`, `:DocumentVersion`, `:Authority`, `:Entity` — is canonical: it records something an
ingest read directly off a source, and nothing about it is invented by the chunking algorithm's
own judgement calls. A `:Chunk` is different: it exists because `chunk_pages` decided where to
draw a boundary, and a better chunker landing later must be able to replace every chunk without
anyone treating the old ones as a fact that was true and is now being revised. Two properties
make that safe. First, **chunk ids are stable, not merely deterministic** — `_chunk_id` hashes
`(version_id, section_path, section_occurrence, ordinal_within_section)`, not any
database-assigned sequence and deliberately not the document-global reading-order counter. A
chunk's identity therefore depends only on where it sits in the document's *own* structure:
which section, which opening of that section, and how far into that opening. Adding a paragraph
to section 5 renumbers section 5 and nothing else. An id keyed on a document-global ordinal
would be reproducible on byte-identical input and worthless on anything else — measured against
this branch's own earlier scheme, inserting one paragraph into page 20 of `850001_2014.pdf`
orphaned 40 of the 125 ids that scheme produced when the paragraph was appended at the foot of
the page, and 74 of 125 when it was inserted mid-page; under the current key, the same two edits
orphan none. Reproducibility on identical input was never the property worth having: the case
that matters is an unrelated edit, or exactly the chunker improvement this ADR defers below.
Second, **ingest drops before it writes, inside the same transaction that writes the version's
other state.** `_write_document` calls `drop_chunks` then
`write_chunks` after `merge_version` and `link_supersession`, both under the one
`session.execute_write` the rest of the ingest already used — so a chunker change (or simply
re-running the same chunker) replaces a version's chunk set atomically rather than leaving the
previous run's chunks orphaned beside the new ones, and a failure partway through rolls back
the whole ingest exactly as a node or edge write failure already did.

**A version's chunks are exposed at `GET /documents/{slug}/chunks`.** `version_id` is optional
and defaults to the newest edition, resolved the same way `link_supersession` orders editions
(latest labelled date, then latest ingest time) — a caller who does not care which edition gets
the current one; a caller who does can pin an explicit `version_id` even while a newer edition
exists in the same graph. Results are ordered by `ordinal`, the field that makes a rebuilt
chunk set's reading order reproducible.

**Two classes of line are filtered out of heading detection: contents rows and page furniture.**
A table-of-contents row opens with a genuine-looking heading and is indistinguishable from one by
prefix alone; the dot leader running to a page number is what gives it away, so `DOT_LEADER`
rejects any candidate carrying four or more leader dots. Read as headings, those rows bound a
section path to the contents page rather than to the body — in `850001_2014.pdf`
`["ENCLOSURE 3","1"]` bound to a contents row on page 7 instead of to `1. INTRODUCTION` on
page 26 — and chunked a page of dot leaders as document text. Measured over the seven samples,
the filter removes 5 detections of 67 in `850001_2014.pdf`, 15 of 44 in `500001p.pdf`, 14 of 39
in `500001p_2020.pdf`, 17 of 94 in `500088p.pdf`, 63 of 214 in `818001m.pdf`, and none in the
two samples with no contents page. Every removed line was a contents row; no genuine heading in
the corpus carries a dot leader. Separately, `_page_furniture` refuses to read a heading out of a
line that repeats verbatim on three or more pages, because a running header or footer
(`ENCLOSURE 2` standing alone at the foot of every page of an enclosure) matches the heading
patterns exactly and would re-open its section once per page. In these seven samples that rule
fires zero times — their footers carry a `Change 1, 10/07/2019  15` prefix, so they never matched
at the line anchor in the first place — and it is kept as a guard on a failure mode the pattern
plainly admits, pinned by a test rather than by corpus evidence. Neither filter touches the
genuine-heading path: a line is still a heading if and only if it matches the same two patterns.

**Known limitation: `section_heading` still cannot tell a numbered subsection heading from a
numbered list item.** Both are a number, a dot, and text at the start of a line. After the two
filters above, `850001_2014.pdf` produces 62 section-open events, of which **47 are genuine
headings and 15 are not**. The genuine ones include the whole of Enclosure 2, whose real
structure *is* one numbered paragraph per responsible official (`1. DoD CIO.`,
`2. DIRECTOR, DISA`, `13. DoD COMPONENT HEADS.`) — reading those as subsections is correct, not a
defect. The 15 misdetections are ordinary numbered lists sitting inside a section: 3 on page 5
(the signature page's `Enclosures: 1. References / 2. Responsibilities / 3. Procedures`), 2 on
page 37, 6 on page 39 (`1. PIT systems are analogous to enclaves…`), and 4 on page 40
(`1. Ensure that interagency agreements…`). Their effect is not, as an earlier draft of this ADR
claimed, a finer grain: chunks under `ENCLOSURE 2`/`ENCLOSURE 3` have a **median length of 1646
characters against 1358 elsewhere in the same document**, so the enclosures chunk *coarser* than
the rest of it. The real effect is that a section path is opened more than once — 9 paths, 15
redundant re-opens, down from 12 and 20 before the contents-row filter — so `section_path` alone
does not locate a passage, and a handful of list items each get a small chunk of their own
instead of staying with the lead-in sentence that governs them. It is accepted for now because
distinguishing the two cases needs either layout information `pypdf`'s text extraction discards
or evidence about what granularity retrieval actually wants, which nothing before Phase 6 can
supply — and because the occurrence counter in a chunk's identity makes the ambiguity survivable
in the meantime: a duplicate path is disambiguated, not collided.

## Consequences

**Makes easy.** Phase 3 can extract an obligation against a chunk that already respects the
document's own section boundaries, instead of first having to work out where one obligation
ends and another begins. A citation returned to a reviewer carries a real page number and a
real section path, not a guess. A future chunker improvement — better sentence-boundary
detection, teaching `section_heading` to tell a heading from a numbered list item — can replace
the whole derived layer in one ingest, and because identity is keyed on document structure
rather than on how much text precedes a chunk, only the sections the improvement actually moves
lose their anchors. Everything else reconciles by equality, with nothing to fix up by hand.

**Makes hard.** Until `section_heading` can tell a heading from a numbered list item, a document
whose sections contain numbered lists will open some section paths more than once — 9 paths in
`850001_2014.pdf` — so a consumer cannot treat `section_path` as a unique locator within a
document, and a list item that should have stayed with its lead-in sentence can arrive as its own
small chunk. Anything that needs to point at one passage must carry the chunk id, not the path.

**Commits us to.** `:Chunk` is this codebase's first derived-and-rebuildable label; the pattern
`:DocumentVersion`'s `SUPERSEDES` edge started in ADR-011 — deterministic identity, drop before
write inside one transaction, safe to discard because nothing about it is a human decision — is
now the shape every future derived layer should follow, most immediately whatever phase 3
attaches to a chunk. Chunk ids being a hash of `(version_id, section_path, section_occurrence,
ordinal_within_section)` also commits this codebase to treating a chunk's *position in the
document's structure*, not its content, as its identity: two sections with identical text get
different chunk ids, and — the other side of the same coin — editing a chunk's text in place
leaves its id unchanged. A chunk id is not a fingerprint of the text it holds. What it does
promise is that an unrelated edit elsewhere in the document will not move it, which is the
promise Phase 3's anchors depend on. It also means the structural reading is load-bearing: if a
future chunker splits a section into two sections, or stops opening a spurious one, the
occurrence numbers after that point in the document shift and those ids do change. That is the
intended blast radius — the section that actually changed — rather than everything downstream.
