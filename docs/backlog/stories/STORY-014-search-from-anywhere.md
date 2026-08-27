# STORY-014: A user can search for a document by name or ID from anywhere in the UI

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As someone who knows which issuance they want, I want to find it from wherever I am, so that
reaching a document does not mean navigating to the table first and remembering that its filter
exists.

## Context

An MVP definition-of-done item — "Users can search by document name or ID" — open since DI-1 and
the last one of the four that is reachable.

STORY-010 built a filter on the Documents table. It matches on `name` only, it lives on one
screen, and a user on Triage or Ask has no way to reach a document without going there first.
The bar asks for two things that filter does not do: match the **ID** as well as the name, and be
available **from anywhere**.

"ID" is the slug ([STORY-025](../backlog.md#done)) — `dodd-5000-01`, the thing that appears in
URLs and in every citation the product prints. A reader who has seen a citation has seen a slug,
and today they cannot search for it.

**The decision this needed was taken at sprint 8 planning.** A global search box in the
application header, always visible, that submits to the existing Documents table with its filter
pre-applied — rather than a new search results screen. It reuses the table, the cap-and-say-so
behaviour (STORY-070) and the row rendering already tested, and adds one control plus one
predicate. A separate results view would duplicate all of that to show the same rows.

## Acceptance criteria

- [ ] A search control is present on every screen, from the same navigation declaration
      `App.tsx` already uses so that it cannot exist on some screens and not others.
- [ ] Given a search for text matching a document's **name**, **When** it is submitted, **Then**
      the Documents table shows that document.
- [ ] Given a search for text matching a document's **slug**, **Then** the same happens — this is
      the half STORY-010's filter does not do.
- [ ] Matching is case-insensitive and matches on a substring, the way the existing filter
      behaves, so the two do not disagree about what a match is.
- [ ] Given a search matching nothing, **Then** the screen says so and says what was searched
      for, rather than rendering an empty table.
- [ ] Searching from a screen other than Documents navigates there with the term applied, and
      the term is visible in the control afterwards.
- [ ] `App.test.tsx` asserts the control is reachable from every declared route, the way it
      already asserts one navigation link per route.

## Dependencies

- STORY-010 (browse and filter the document table) — **Done.** This extends its predicate and
  adds a way in from elsewhere.
- STORY-025 (the slug) — **Done.** It is the ID being searched for.

## Open questions

- Should the search reach editions as well as documents — `dodd-5000-01@2020-09-09` is also an
  identifier a reader will have seen in a citation. The criteria above say documents only,
  because an edition is reached from its document's page in one more click and adding it means
  deciding what a mixed result list looks like. Worth revisiting once someone has wanted it.
