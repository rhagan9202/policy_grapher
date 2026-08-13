# ADR-003: Documents are addressed by generated slug, not by name

**Status:** Accepted · **Date:** 2026-08-12 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

SPEC-001 made `name` the unique key and put it directly in URL paths:
`GET /documents/{name}`. Against the real corpus, that doesn't work.

Document names in `data/dod_policy_references_08122026.csv` contain characters that are
structural in URLs:

- Slashes — `National Security Presidential Directive-47/Homeland Security Presidential Directive-16`
- Commas — `United States Code, Title 44, Section 3554`
- Parentheses — `North Atlantic Treaty Organization Document AC/92(ATMCNS)D(2020)0002`

The slashes are the fatal ones: a name with `/` splits into multiple path segments, and no
amount of routing cleverness makes `GET /documents/{name}` unambiguous.

Separately, the MVP definition of done asks that users be able to search "by document name
or ID" — and no ID existed.

## Options considered

**Percent-encode the name in the path.** No schema change. But encoded slashes (`%2F`) are
rejected by default in many servers and reverse proxies, and pass through others decoded —
a deployment-dependent trap that works locally and fails elsewhere.

**Move the name to a query parameter.** `GET /documents?name=...` sidesteps path encoding
entirely and is genuinely simple. Diverges from the resource-per-path shape of the rest of
the API.

**Use Neo4j's internal element id.** No generation logic at all — but element ids are not
stable across re-ingest, so every saved URL breaks the next time the graph is rebuilt. For a
system whose reset-and-reingest cycle is a documented workflow, that's disqualifying.

**Generate a deterministic slug.** A URL-safe identifier derived from the name, stored as a
property.

## Decision

Every node gets a `slug` property, unique, generated from its name:

1. Casefold; replace each run of non-alphanumeric characters with a single hyphen; trim
   leading and trailing hyphens; truncate to 80 characters.
2. On collision, append `-` plus the first 8 hex characters of the SHA-256 of the full name.

All document-addressing endpoints take `slug`. `name` remains unique and stays a property.

The collision suffix is a **hash, not a counter**, and that choice carries the weight here:
a counter would make a slug depend on the order rows were ingested, so re-ingesting the same
corpus after a reset could hand `united-states-code-title-44` to a different document than
before. Hashing makes slugs a pure function of the name — stable across resets, across
machines, and across ingest order.

`PUT` does not rename. A body `name` that disagrees with the addressed document is a `400`;
renaming means delete and recreate. This keeps slug and name from drifting apart, at the
cost of an awkward correction path for a typo'd name.

## Consequences

What this makes easy, what it makes hard, and what it commits us to.

**Makes easy.** URLs are readable and shareable — `/documents/dodd-5000-01`. They survive a
reset-and-reingest cycle unchanged, which the auto-ingest-on-empty startup makes routine.
The MVP's "search by name or ID" now has an ID to search.

**Makes hard.** A generation rule is code that has to be identical everywhere it runs, and
it has one genuinely fiddly branch (collision) that will be under-exercised — the sample
corpus may not collide at all, so the path needs a deliberate test rather than incidental
coverage. Every API consumer now resolves name → slug before addressing a document.

**Commits us to.** Slug stability as a contract. Changing the normalization rule later
silently changes every URL and every stored reference to one. If the rule needs to change,
it needs a migration, not an edit.

**Accepted cost.** Documents can't be renamed through the API. For a demo over a fixed
corpus this is close to free; it will need revisiting when corpus management arrives, since
"fix a typo in a document name" is an obvious thing to want.
