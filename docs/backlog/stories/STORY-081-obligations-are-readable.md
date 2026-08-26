# STORY-081: A user can read the obligations extracted from an edition

**Epic:** — · **Status:** Done · **Estimate:** M

## User story

As a policy analyst who has just rebuilt an edition, I want to read the obligations that were
extracted from it, so that I can judge whether extraction found what the document actually
requires before I trust Review's proposals or Triage's ranking.

## Context

Obligations are the product's central noun. Extraction produces them
([ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)), Review judges
links between them ([ADR-014](../../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md)), Triage
ranks changes to them ([ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md)),
and the graph's value rests on them. No endpoint lists them and no screen shows them.

They are reachable in exactly three places today: as a count in a finished rebuild's report,
two at a time in the Review queue, and quoted inside a Triage row. `GET
/documents/{slug}/chunks` returns raw text; there is no `/obligations` beside it.

Measured 2026-08-25: a real-model rebuild of `dodd-5000-01@2020-09-09` wrote **113
obligations**. Confirming that number required `cypher-shell`. A user who has just spent hours
of CPU inference has no way to answer the first question anyone asks — *what did it find?* —
which also means extraction quality is unauditable from inside the running application. The
extraction ratchet checks *references* against a fixed corpus CSV; nothing lets a person read
the obligations themselves.

The response shape mostly exists. `ObligationCitationOut`
(`backend/src/policy_grapher/models.py:126`) already carries `obligation_id`, `statement`,
`modality`, `document`, `section_path` and `page` — assembled for Review, and the same fields a
reader needs here.

## Acceptance criteria

- [ ] `GET /documents/{slug}/versions/{version_id}/obligations` returns the obligations
      recorded for that edition, each with `obligation_id`, `statement`, `modality`,
      `section_path` and `page`.
- [ ] Given a slug or `version_id` that does not exist, **When** the route is called, **Then**
      it answers 404 — not an empty list, which would read as "built and found nothing".
- [ ] The route requires bearer auth, like every route except `/health`.
- [ ] The response is bounded and reports the true total when it truncates, following the
      cap-and-say-so idiom already used by the graph view (STORY-015) and the document table
      (STORY-070). A 204-chunk edition can produce several hundred obligations.
- [ ] A document's page lists, per edition, how many obligations it holds and offers a way to
      read them.
- [ ] Given an edition whose derived layer has never been built, **When** a user opens its
      obligations, **Then** the screen says it has not been built — distinct from an edition
      that was built and yielded none. This is the distinction STORY-067 drew for Triage, and
      it is the same trap here.
- [ ] Obligations are returned in a deterministic order that follows the document, and the
      ordering is documented in the route: by the `ordinal` of the `Chunk` each obligation is
      `ANCHORED_IN`, then by `obligation_id` to break ties within a chunk.

      *Revised at sprint 6 planning.* This first read "by `section_path`, then by position
      within the section", which is not implementable: `WRITE_OBLIGATIONS`
      (`backend/src/policy_grapher/obligations.py`) stores statement, modality, actor,
      deadline, conditions, confidence and section_path — there is no ordinal, so "position
      within the section" has nothing to sort on. Adding one is a schema change that would
      re-size this item. Chunk ordinal already exists, already follows the document, and
      needs no migration.

## Notes

Read-only. Editing or annotating an obligation is a different story and is not implied here.

Ordering is called out as a criterion because the natural Cypher return order is insertion
order, which is chunk order — close to document order but not equal to it, since one chunk can
yield several obligations and back matter is chunked separately
([ADR-012](../../specs/adr/ADR-012-chunks-follow-sections.md), STORY-063).

Sized **M** rather than L: it adds an endpoint and a screen, which crosses backend and
frontend, but it contains no unmade decision. The response shape follows
`ObligationCitationOut`, the bounding follows STORY-070, and the empty-state distinction
follows STORY-067. STORY-077 was the same shape — a new read endpoint plus the UI that consumes
it — and landed inside one sprint.

## Dependencies

- STORY-048 (the derived layer can be built from the running app) — **Done.** Without a
  rebuild there are no obligations to read.
- No blocking dependency on STORY-082; the two are independent and either can land first.

## Open questions

- Should the obligations view offer any filter — by modality, say — or is ordering by section
  enough for a first version? Ordering alone is the smaller thing and the criteria above assume
  it; a filter can be its own row if reading the list proves unwieldy.
