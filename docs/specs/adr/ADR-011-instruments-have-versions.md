# ADR-011: Instruments have versions

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

Every `:Document` in the graph today is one node holding one set of properties, but a real
DoD issuance is not one document — it is a lineage. DoDD 5000.01 was issued May 12, 2003,
reissued September 9, 2020, and amended by Change 1 on July 28, 2022; DoDI 8500.01 carries an
`Incorporating Change 1, Effective October 7, 2019` line on its own cover page. `ingest_file`
today reads whichever PDF is handed to it and merges one node keyed on the issuance's name —
re-ingesting a later edition of the same instrument does not create a second node (the name is
the same), and does not update the first one either (`MERGE_DOCUMENT` uses `SET`, so it would
silently overwrite what is there with no record that anything changed). Nothing in the graph
today can answer "which edition is this text from" or "what did this instrument say before the
2020 reissue" — both questions phase 2 (chunking) and phase 3 (extraction) need answered
before they can attach anything to a specific state of an instrument's text.

`document_name_unique` and `document_slug_unique` ([ADR-003](ADR-003-slug-identifiers.md))
are asserted on `:Document` today, which forecloses the simplest-looking fix: giving each
edition its own `:Document` node with the issuance's name would violate the uniqueness
constraint the moment a second edition tried to register the same name. Any versioning
scheme has to introduce a new node label for "edition," not multiply the existing one.

## Options considered

**A property list on `:Document`.** Store `versions: [{date, checksum}, ...]` directly on the
document node. No new label, no new relationship. Rejected: a property list cannot carry its
own relationships (an edition's own `ISSUED_BY` authority, its own chunks in phase 2), Neo4j
property values are scalars or arrays of scalars — not nested maps — so this does not even
fit the property model without serialising to JSON strings, and querying "the third edition
of this instrument" would mean deserialising every document's version list rather than a
graph traversal.

**Reuse `:Document` for editions, distinguished by a suffixed slug.** Give each edition its
own `:Document` node (`dodd-5000-01-2020`, `dodd-5000-01-2003`) and link them with a new
`PRECEDES`/`FOLLOWS` edge. Keeps one label. Rejected: it breaks `document_name_unique` (see
Context) unless the *name* is also made edition-specific, which corrupts what `name` means
everywhere else in the graph — `REFERENCES` edges, the manifest ingest path, and every
existing route all treat a document's name as the instrument's name, not one edition's. It
also means `:Document` stops being a stable thing to hang a reference at: a citation to "DoDD
5000.01" would have to pick an edition, which the citing text itself usually does not specify.

**A new `:DocumentVersion` label, one per edition, off a `:Document` that stays the
instrument.** Chosen.

## Decision

`:Document` is the instrument's identity and does not change or migrate: it is still the node
a `REFERENCES` edge points at, still keyed by `document_slug_unique` and
`document_name_unique`, and existing citations, provenance, and reference edges keep meaning
exactly what they meant before this ADR. What changes is that a `:Document` may now have zero,
one, or many `:DocumentVersion` nodes hanging off it via `HAS_VERSION`, one per edition
actually ingested.

**Version identity is content-derived, for [ADR-003](ADR-003-slug-identifiers.md)'s reason.**
A version's id (`document_slug@discriminator`) must be a pure function of what was ingested,
not of ingest order, so that re-ingesting the same PDF resolves to the same version instead of
creating a duplicate — the DI-1 idempotency invariant, extended. The discriminator is the
edition's effective date when the cover page states one, and a checksum prefix when it does
not (`versions.version_id`).

**`effective_date` is optional, and absence is recorded rather than guessed.**
`sources/pdf.effective_date` reads the cover page for a date in either form DoD issuances use
(`April 1, 2026` or `1 April 2026`) and returns `None` when it finds nothing that parses. It
does not fall back to file mtime or ingest time — either would put a date into the graph that
the source document never stated, and a fabricated date is worse than an honest `null`,
because a reader has no way to tell the two apart once it is stored. `None` is a correct and
common answer, not an extraction failure to be tuned away; every one of the five sample PDFs
happens to yield a date, but the extractor makes no assumption that a future one will.

**The manifest path creates no versions.** A CSV row is a citation — a name and a list of
things it references — and states no text, no date, no checksum. Inventing a version for it
would assert an edition the manifest never described. `ingest_parsed` calls neither
`merge_version` nor `link_supersession`; only `ingest_document`, the single-PDF path, does.

**`SUPERSEDES` is derived, and ingest rebuilds it rather than appending to it.**
`link_supersession` deletes and recreates one instrument's whole `SUPERSEDES` chain on every
ingest of that instrument, ordered by `effective_date` (undated versions sort first — see
below). This is the one place in the codebase ingest is not purely additive
([ADR-006](ADR-006-relational-facts-live-on-typed-edges.md) established typed edges for
relational facts generally; this is the first one whose *shape*, not just its existence, can
change after the fact). Rebuilding is safe here specifically because editions do not arrive in
publication order — a 2024 edition ingested after a 2026 one belongs in the middle of the
chain, not appended after it — and because the chain is entirely *derived* from the versions'
own dates: nothing about it reflects a human judgement that a later ingest could contradict.
**This must not be taken as a general licence to rebuild edges.** An edge that carries a
human decision (which this codebase has none of yet, but will) must stay additive; deleting
and recreating it on every ingest would silently discard whatever decision it recorded.

**A same-date, different-checksum ingest raises rather than absorbing.** Addressing a version
by date alone keeps its id citable (`dodd-5000-01@2026-04-01` is what a reader would actually
write down), but it means two genuinely different files can compute the same id: a corrected
reissue that keeps its nominal date, and — in principle — an unrelated distinct edition that
happens to share one. `merge_version` compares the checksum already stored under that id
against the one just computed, and raises `VersionConflictError` on a mismatch rather than
`ON CREATE SET`-ing over it or silently keeping the first one. The graph cannot tell a better
scan of the same edition from a genuinely distinct reissue that reused a date — guessing
either way puts a wrong edition boundary into the record, so the operator decides.

**An unknown document slug raises `UnknownDocumentError`.** `merge_version` requires an
existing `:Document` to `MATCH` against; if the slug names nothing, it raises rather than
returning a plausible-looking version id for a version that was never written. A silently
accepted write here would hand phase 2 or phase 3 an id to chunk or extract against that no
`HAS_VERSION` edge actually connects to anything.

**Known limitation: undated editions sort as oldest.** `link_supersession`'s ordering is
`coalesce(v.effective_date, '') ASC, v.ingested_at ASC` — an undated version's discriminator
sorts before any ISO date string. For an instrument that mixes dated and undated editions,
there is no honest ordering to fall back to: ingest order is not publication order, and this
codebase has no other signal to order by. This gets the common shape right — an undated scan
of an old issuance, superseded by a dated current one — but it is a real limitation, not an
implementation detail, and is recorded here rather than left implicit in the `coalesce`.

## Consequences

**Makes easy.** Phase 2 (chunking) and phase 3 (extraction) have a stable node to attach
against — a chunk or an extracted obligation can point at `dodd-5000-01@2020-09-09`
specifically, distinct from whatever the 2003 edition said, without either phase needing to
invent its own notion of "which text." `GET /documents/{slug}/versions` gives a caller the
whole chain, oldest first, with each entry's `supersedes` link, in one call.

**Makes hard.** An instrument mixing dated and undated editions — an old scanned PDF with no
readable cover date, ingested alongside a modern dated reissue — gets a chain whose ordering
this ADR admits is not fully trustworthy (see the undated-editions limitation above). Fixing
that properly needs a second, independent ordering signal (e.g. an operator-supplied
publication date at ingest time), which is out of scope here.

**Commits us to.** `SUPERSEDES` being rebuildable, not additive, is now a precedent this
codebase has one instance of. Any future edge with the same "fully derived, no human
judgement" property may reasonably follow the same pattern; anything else must not. `:Authority`
and `:Entity` (also introduced in this phase, `versions.merge_authority` /
`versions.merge_entity`) are additive like everything else — `ON CREATE SET` only — and are
not exercised by ingest yet; a future task that calls `attach_authority` from `extract_document`
needs to decide, separately, whether `ISSUED_BY` is derived-and-rebuildable or
human-authored-and-additive before it writes that call.
