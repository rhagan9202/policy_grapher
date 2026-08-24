# ADR-026: A chunk's page is its own page

**Status:** Accepted · **Date:** 2026-08-24 · **Deciders:** Project owner
**Supersedes in part:** [ADR-012](ADR-012-chunks-follow-sections.md)

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

[ADR-012](ADR-012-chunks-follow-sections.md) chose the section's opening page for every chunk
under it, and gave a reason: reconstructing a per-chunk page after the fact meant guessing from
character offset into a string that had already been flattened across page boundaries. That
reasoning does not hold today. `sources/pdf.py`'s `pages_of` already returns the per-page list,
`chunk_pages` already receives it, and the boundary is not lost to flattening — it is discarded
one line later, inside the function itself, at `body.append(line)`, which keeps the line and
drops the page number that came with it. Nothing about the per-page information ADR-012
describes as unavailable is in fact unavailable; it arrives at the function and is thrown away.

The audit of 2026-08-24 measured what that costs. `/ask`, asked against DoDD 5000.01, cited
*SECTION 2/2.10 · p. 14* while quoting the glossary and reference list, which sit on pages
15–16. The chunk's `page` names the page the section *2.10* opened on, not the page its own
text — the glossary and reference material, well past where 2.10 itself ends — actually
appears. A reader following the citation to page 14 finds the wrong page, because the number
was never about this chunk's text in the first place.

## Options considered

**Keep the section-opening page and qualify it in the UI** — render it as "section opens near
p. 14" rather than claiming the chunk itself is there. Rejected: it makes the number honest
without making it useful. A reader still cannot turn to the page the quoted text is actually
on; the citation has been relabelled, not fixed.

**Store both the section's opening page and the chunk's own starting page.** Rejected as
unnecessary complexity. Nothing downstream — `/ask`, the chunk list, a review queue citation —
has ever asked "where did the section start"; every consumer wants "where is this text",
which is the second number alone.

**A chunk's `page` is the page its own text starts on.** Chosen.

## Decision

A chunk's `page` is the page the chunk's own text starts on, not the page the section it
belongs to opened on. `chunk_pages` already has this number in hand at the point `body.append`
discards it; the fix is to keep it instead — `body` accumulates `(page_number, line)` rather
than bare `line`, and a chunk's `page` is read off the first line of its own body.

## Consequences

**Makes easy.** A citation can be followed. `page` was never part of any identity — not
`chunk_id`, not `obligation_id` — so this decision re-keys nothing and requires no rebuild for
correctness. An edition chunked before this lands simply keeps its old, section-opening page
numbers until it is next rebuilt.

**Makes hard.** A chunk spanning a page break now reports only the page it starts on, not
both. That is a deliberate simplification, not an oversight: a chunk that already carries its
section path and its own verbatim text gives a reader two other ways to locate the passage, and
a `page` field that could hold two numbers would ask every consumer to handle a case that is
rare and does not change what the citation is for.

**Supersedes.** [ADR-012](ADR-012-chunks-follow-sections.md), in part: only its rule that a
chunk's `page` is the page the section it belongs to opened on. ADR-012's chunk-identity
decision — chunk ids keyed on `(version_id, section_path, occurrence, ordinal)` — and its
section-boundary decision — chunks follow the document's own section hierarchy, splitting only
within an oversized section — both stand, unchanged and still authoritative.
