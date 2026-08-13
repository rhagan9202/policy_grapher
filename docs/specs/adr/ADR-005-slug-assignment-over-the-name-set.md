# ADR-005: Slug assignment is a function of the whole name set

**Status:** Accepted · **Date:** 2026-08-13 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

**Amends [ADR-003](ADR-003-slug-identifiers.md).** ADR-003 stands: documents are addressed
by generated slug, not by name, and the collision suffix is a hash, not a counter. This ADR
corrects how that suffix gets assigned and records a consequence ADR-003 didn't anticipate.

## Context

ADR-003 states the collision rule as a per-name check: generate the base slug, and "on
collision, append `-` plus the first 8 hex characters of the SHA-256 of the full name." Read
literally, that means whichever name is processed first keeps the bare base slug and only
the *second* arrival gets suffixed.

That literal rule makes a slug depend on ingest order — the exact thing ADR-003 says hashing
was chosen to avoid: "Hashing makes slugs a pure function of the name — stable across
resets, across machines, and across ingest order." A per-name, first-come-first-served rule
is not a pure function of the name; it's a function of the name *and* the order names were
seen in. Sprint 1's implementation caught this before it shipped and fixed it in code before
writing this ADR.

This isn't a hypothetical edge case. Ingest against the real 23-row corpus contests a base
slug twice:

- `Military Standard 882E` and `Military-Standard 882E` normalise to the same
  `military-standard-882e`.
- Two Assistant Secretary of Defense names are identical for their first 101 characters and
  differ only in a trailing `" Memorandum"`; truncating the base slug to 80 characters (per
  ADR-003) cuts both down to the same 80-character prefix,
  `assistant-secretary-of-defense-for-networks-and-information-integration-dod-chie`.

Both pairs are present in every ingest of the sample corpus, so the collision path is not an
under-exercised branch — it runs every time.

Separately, STORY-006 (`POST /documents`, incremental document creation) needs a rule for
what happens when a newly created document's name collides with an existing one's base
slug. Ingest has a full name set to resolve at once; incremental creation does not — a new
document arrives alone, against a graph that already holds a slug it may now contest.
ADR-003 has no answer for this case, and it blocks STORY-006 from being implemented.

## Options considered

**Keep the per-name, first-arrival rule literally as ADR-003 states it, everywhere.**
Simplest reading of the existing text. Rejected: it is ingest-order dependent, which directly
contradicts the stability promise ADR-003 itself makes.

**Resolve every collision — ingest and incremental alike — over the whole name set,
recomputing affected slugs whenever a new contender arrives.** Fully consistent: ingest and
create would always agree. Rejected for incremental creation: a document already has a slug
that other systems may have stored (bookmarks, links, cached responses); re-slugging it out
from under a caller because an unrelated document happened to collide with it breaks the one
guarantee slugs are supposed to give — a stable URL for a document that hasn't changed.

**Ingest resolves over the whole batch; incremental creation favours the incumbent.** Ingest
sees every name at once and can suffix every contender fairly, with no ordering privilege.
Incremental creation, which only ever sees one new name against an existing graph, leaves
existing slugs untouched and suffixes only the newcomer. Chosen.

## Decision

1. **Ingest assigns slugs over the whole name set, not per name.** `assign_slugs` (in
   `backend/src/policy_grapher/slugs.py`) groups all names by base slug first; for any base
   slug with more than one contender, *every* contender gets suffixed with `-<sha8>` — not
   just the one that arrives second. No name in a contested group keeps the bare base slug.
   This makes slug assignment order-independent within a single ingest, honouring ADR-003's
   stability promise instead of contradicting it.

2. **At incremental creation (`POST /documents`), the incumbent keeps its bare slug; the
   newcomer takes the suffix.** A new document whose base slug matches an existing document's
   slug does not cause the existing document to be re-slugged. Only the newcomer is suffixed.

   The consequence, stated plainly: ingest-time and create-time assignment can
   diverge. A document created incrementally, then later included in a reset-and-reingest of
   the full corpus, can end up with a *different* slug than it held before the reset — because
   reingest resolves the same collision over the whole batch, with no incumbent to favour.
   Rebuilding the graph from the CSV is a documented, routine workflow in this system, so this
   is not a remote scenario. The trade accepted here is: URL stability for an existing
   document *right now*, against URL stability for that same document *across a future
   reset*. The project owner judged the former worth more, because a reset is a deliberate,
   visible operation and an incremental creation happening under an existing document's feet
   is not.

3. **A suffixed slug can reach 89 characters, not the 80 ADR-003 states.** `base_slug`
   truncates to `MAX_SLUG_LENGTH = 80` *before* the suffix is appended; `hash_suffix` adds
   `-` plus 8 hex characters, for 9 more. `80 + 9 = 89`. Nothing in `slugs.py` enforces an
   80-character bound on the final slug — only on the base. The Assistant Secretary of
   Defense collision above produces a real 89-character slug
   (`assistant-secretary-of-defense-for-networks-and-information-integration-dod-chie-c90f259e`)
   on every ingest. This ADR records 89, not 80, as the actual maximum.

## Consequences

What this makes easy, what it makes hard, and what it commits us to.

**Makes easy.** Ingest slugs are order-independent, so ADR-003's stability promise actually
holds for the case it was written to cover. `POST /documents` has an unambiguous rule to
implement: an existing document's slug never changes because of something created after it.

**Makes hard.** Two assignment rules for the same underlying operation (contested base slug
→ suffix) means a reader has to know which one applies — whole-batch at ingest, incumbent-
favouring at create — rather than one rule everywhere. A reset-and-reingest can silently
change the slug of a document that was created incrementally and never touched again; nothing
in the system warns the caller when that happens.

**Commits us to.** Any client that stores a slug across a reset must treat it as
provisional for documents created via `POST /documents`, not just for documents from the
original corpus. Slug length assumptions downstream (storage, logging, URL length limits)
must budget for 89 characters, not 80.

**A duplicate name is a different case from a contested slug and must not be conflated with
it.** `POST /documents` with a `name` that exactly matches an existing document's `name` is a
`409` — the document already exists, full stop; this ADR does not touch that path. A
contested *slug* with a distinct name — the cases this ADR is about — is not a conflict at
all: it succeeds, and the newcomer gets a suffixed slug per decision 2. An implementation
that rejects the second case as though it were the first would refuse legitimate documents
that happen to normalise the same way as an existing one.
