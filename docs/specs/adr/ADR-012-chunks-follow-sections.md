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
self-describing outside the document it came from.

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

**`:Chunk` is the first *derived* label.** Every other node this codebase has written so far —
`:Document`, `:DocumentVersion`, `:Authority`, `:Entity` — is canonical: it records something an
ingest read directly off a source, and nothing about it is invented by the chunking algorithm's
own judgement calls. A `:Chunk` is different: it exists because `chunk_pages` decided where to
draw a boundary, and a better chunker landing later must be able to replace every chunk without
anyone treating the old ones as a fact that was true and is now being revised. Two properties
make that safe. First, **chunk ids are deterministic** — `_chunk_id` hashes
`(version_id, section_path, ordinal)`, not any database-assigned sequence — so a rebuild that
produces the same sections and the same ordinals reproduces the same ids, and anything a later
phase anchors to a chunk id (an extracted obligation, an approved link) survives a rebuild that
does not actually change that chunk. Second, **ingest drops before it writes, inside the same
transaction that writes the version's other state.** `_write_document` calls `drop_chunks` then
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

**Known limitation: `section_heading` treats a numbered list item as a section heading, not only
a genuine one.** The regex that recognises `"3.2.1. "` at the start of a line cannot tell a
genuine subsection heading from an ordinary numbered list entry — both are a number, a dot, and
text. `850001_2014.pdf`, a legacy-format sample, shows exactly this: 36 of its 48 distinct
section paths are numbered items nested directly under `ENCLOSURE 2` or `ENCLOSURE 3` alone —
each enclosure's own numbered list misread as a fresh subsection every time a new number opens a
line. The effect is over-segmentation — inventing section boundaries that split text which
should have stayed together — which risks the same failure this ADR exists to prevent, an
obligation separated from its conditions, reached from the opposite direction to a fixed window:
instead of a window cutting across a section, a false section boundary cuts *within* what should
have been one section. It is accepted for now because changing heading detection moves chunk
boundaries for every document and invalidates every chunk id already written; that decision
needs evidence about what granularity retrieval actually wants, which nothing before Phase 6 can
supply. The derived layer being droppable and rebuildable is precisely what makes deferring it
safe.

## Consequences

**Makes easy.** Phase 3 can extract an obligation against a chunk that already respects the
document's own section boundaries, instead of first having to work out where one obligation
ends and another begins. A citation returned to a reviewer carries a real page number and a
real section path, not a guess. A future chunker improvement — better sentence-boundary
detection, a fix to the legacy over-segmentation named above — can replace the whole derived
layer in one ingest without anyone needing to reconcile old chunks against new ones by hand.

**Makes hard.** A legacy-format issuance's enclosures — numbered lists, not subsections — chunk
at a finer, noisier grain than the rest of the document until `section_heading` is taught to
tell a heading from a numbered list entry, a fix this ADR deliberately defers (see the known
limitation above). Any consumer of chunk text before that fix lands should expect a legacy
document's enclosures specifically to arrive in more, smaller pieces than the source material's
actual structure calls for.

**Commits us to.** `:Chunk` is this codebase's first derived-and-rebuildable label; the pattern
`:DocumentVersion`'s `SUPERSEDES` edge started in ADR-011 — deterministic identity, drop before
write inside one transaction, safe to discard because nothing about it is a human decision — is
now the shape every future derived layer should follow, most immediately whatever phase 3
attaches to a chunk. Deterministic chunk ids being a hash of `(version_id, section_path,
ordinal)` also commits this codebase to treating a section's position, not its content alone,
as part of a chunk's identity: two sections with identical text at different ordinals get
different chunk ids, which is the correct behaviour for a rebuild but means a chunk id is not by
itself a fingerprint of the text it holds.
