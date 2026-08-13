"""Document and reference Cypher.

Knows nothing about HTTP, exactly as graph.py does not. Reference lists carry
slugs, not names — see the DI-1 completion design.
"""

from collections.abc import Iterable

from neo4j import Driver, RoutingControl

from policy_grapher.models import DocumentOut
from policy_grapher.slugs import assign_slugs, base_slug, hash_suffix

DOCUMENT_FIELDS = """
OPTIONAL MATCH (d)-[:REFERENCES]->(out:Document)
WITH d, collect(DISTINCT out.slug) AS references
OPTIONAL MATCH (d)<-[:REFERENCES]-(inc:Document)
WITH d, references, collect(DISTINCT inc.slug) AS referenced_by
RETURN d.slug AS slug, d.name AS name,
       d:External AS is_external, references, referenced_by
"""

LIST_DOCUMENTS = f"MATCH (d:Document) {DOCUMENT_FIELDS} ORDER BY slug ASC"
GET_DOCUMENT = f"MATCH (d:Document {{slug: $slug}}) {DOCUMENT_FIELDS}"


SLUG_TAKEN = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"
NAME_TAKEN = "MATCH (d:Document {name: $name}) RETURN count(d) AS total"
SLUG_FOR_NAME = "MATCH (d:Document {name: $name}) RETURN d.slug AS slug"

SLUGS_FOR_NAMES = """
UNWIND $names AS name
MATCH (d:Document {name: name})
RETURN name AS name, d.slug AS slug
"""
ALL_SLUGS = "MATCH (d:Document) RETURN d.slug AS slug"

CREATE_DOCUMENT = """
CREATE (d:Document {slug: $slug, name: $name})
"""

DELETE_DOCUMENT = "MATCH (d:Document {slug: $slug}) DETACH DELETE d"

ADD_REFERENCE = """
MATCH (source:Document {slug: $source})
MATCH (target:Document {slug: $target})
MERGE (source)-[:REFERENCES]->(target)
"""

REMOVE_REFERENCE = """
MATCH (source:Document {slug: $source})-[r:REFERENCES]->(target:Document {slug: $target})
DELETE r
"""


class DocumentNotFoundError(LookupError):
    """No document with the requested slug exists."""


class NameConflictError(ValueError):
    """A document with this name already exists."""


class SelfReferenceError(ValueError):
    """A document may not reference itself."""


def _to_document(record) -> DocumentOut:
    # Neo4j has no list sort without APOC, so order the reference lists here.
    return DocumentOut(
        slug=record["slug"],
        name=record["name"],
        is_external=record["is_external"],
        references=sorted(record["references"]),
        referenced_by=sorted(record["referenced_by"]),
    )


def _read(driver: Driver, database: str, cypher: str, params: dict | None = None):
    records, _, _ = driver.execute_query(
        cypher, params or {}, database_=database, routing_=RoutingControl.READ
    )
    return records


def list_documents(driver: Driver, database: str) -> list[DocumentOut]:
    return [_to_document(r) for r in _read(driver, database, LIST_DOCUMENTS)]


def get_document(driver: Driver, database: str, slug: str) -> DocumentOut:
    records = _read(driver, database, GET_DOCUMENT, {"slug": slug})
    if not records:
        raise DocumentNotFoundError(slug)
    return _to_document(records[0])


def _write(driver: Driver, database: str, cypher: str, params: dict):
    _, summary, _ = driver.execute_query(
        cypher, params, database_=database, routing_=RoutingControl.WRITE
    )
    return summary


def _count(driver: Driver, database: str, cypher: str, params: dict) -> int:
    return _read(driver, database, cypher, params)[0]["total"]


def allocate_slug(driver: Driver, database: str, name: str) -> str:
    """ADR-005: the incumbent keeps its bare slug, the newcomer takes the suffix.

    Callers must only pass a `name` that is not already an existing document's
    name (`create_document` enforces this with `NameConflictError` before ever
    reaching here) — ADR-005 treats a duplicate name as a different case from a
    contested slug, and this function only implements the latter. A name that
    already belongs to a stored document would be misread here as a *newcomer*
    contesting its own base slug and get needlessly suffixed; `allocate_slugs`
    below is the batch-safe version that does handle that case, for callers
    (like PDF re-ingestion) that can legitimately see the same name twice.
    """
    base = base_slug(name)
    if _count(driver, database, SLUG_TAKEN, {"slug": base}) == 0:
        return base
    return f"{base}-{hash_suffix(name)}"


def allocate_slugs(driver: Driver, database: str, names: Iterable[str]) -> dict[str, str]:
    """Allocate slugs for a batch of names arriving together, e.g. one ingested
    document plus everything it cites.

    Two distinct problems `allocate_slug` doesn't handle on its own:

    1. **Same-batch collision.** `allocate_slug` decides bare-vs-suffixed by
       querying the database, which can't see a sibling name in this same batch
       that hasn't been written yet. "Military Standard 882E" and
       "Military-Standard 882E" both normalise to the base slug
       `military-standard-882e`; if each were resolved independently against an
       empty database, both would get the bare slug, and `MERGE (d:Document
       {slug: ...})` would silently collapse the second into the first node,
       discarding its name. Fix: track bases claimed *within this call* the same
       way the database is checked for bases claimed by earlier ingests — the
       first name (in the order given) to reach a base keeps it bare, and any
       later contender for that base, in this batch or already stored, takes
       the hash suffix. This mirrors `allocate_slug`'s own incumbent-wins rule,
       just extended to cover an incumbent that hasn't been committed yet.

    2. **Re-arrival of an already-stored name.** PDF ingestion is a MERGE, not
       a create — the same document (or one of its citations) can legitimately
       arrive again on a later ingest. `d.name` is unique (see `db.py`'s
       constraints), so if a document with this exact name already exists, this
       is not a new contender for its base slug at all — it is the incumbent
       itself, reappearing. Reusing whatever slug it already holds (bare or
       previously suffixed) keeps re-ingestion a no-op, per the additive
       promise `ingest.py` opens with; recomputing via the bare-vs-suffix rule
       would, on the document's own second appearance, hash-suffix it against
       itself and then fail the unique name constraint when MERGE tried to
       create a second node under a slug nobody has yet, but a name someone
       already has. ADR-005 treats a duplicate name as a different case from a
       contested slug for `POST /documents` (a 409, not resolved here); for a
       merge, the equivalent right answer is "reuse it," not "reject it."
    """
    assigned: dict[str, str] = {}
    claimed_bases: set[str] = set()
    for name in names:
        if name in assigned:
            continue
        records = _read(driver, database, SLUG_FOR_NAME, {"name": name})
        if records:
            assigned[name] = records[0]["slug"]
            continue
        base = base_slug(name)
        if base in claimed_bases or _count(driver, database, SLUG_TAKEN, {"slug": base}) > 0:
            assigned[name] = f"{base}-{hash_suffix(name)}"
        else:
            assigned[name] = base
            claimed_bases.add(base)
    return assigned


def reconcile_slugs(driver: Driver, database: str, names: Iterable[str]) -> dict[str, str]:
    """Allocate slugs for a whole manifest, reconciled against what is already stored.

    The manifest path assigns slugs over the *set* of names (ADR-005 decision 1:
    every contender for a contested base is suffixed, so no document's URL
    depends on row order), which `slugs.assign_slugs` does as a pure function of
    the names alone. On an empty graph — the normal path, since compose
    auto-ingests into an empty database — that is the whole answer and this
    function returns exactly what `assign_slugs` does.

    A graph that already holds documents needs the same reconciliation
    `allocate_slugs` performs on the document path, for the same reason:

    1. **A name that is already stored is the incumbent, not a new contender.**
       It keeps whatever slug it holds. Re-deriving one from the name set would
       move a document that a PDF ingest had already placed — and because
       `d.name` is unique, "moving" it means merging a *second* node under an
       already-taken name, which fails `document_name_unique` and rolls the
       whole ingest back. That failure is permanent until `POST /reset`, since
       every retry re-derives the same slug.
    2. **A genuinely new name cannot take a slug someone else holds.** Its base
       may be free within this name set yet already belong to a stored document
       (the incumbent's contender only shows up now). Suffixing the newcomer and
       leaving the incumbent alone is ADR-005 decision 2, exactly as
       `allocate_slug` resolves it for `POST /documents`.

    Reusing a stored slug increases URL stability rather than reducing it;
    ADR-005 already accepts that a reset-and-reingest may produce different slugs
    than incremental arrival did.
    """
    wanted = set(names)
    stored = {
        record["name"]: record["slug"]
        for record in _read(driver, database, SLUGS_FOR_NAMES, {"names": sorted(wanted)})
    }
    taken = {record["slug"] for record in _read(driver, database, ALL_SLUGS)}

    assigned = dict(stored)
    for name, slug in assign_slugs(wanted - stored.keys()).items():
        # `assign_slugs` only sees this name set, so a bare slug it hands out may
        # already belong to a stored document. Suffixed slugs carry the hash of
        # their own name and so can only clash with themselves; recomputing one
        # here yields the same string.
        assigned[name] = f"{base_slug(name)}-{hash_suffix(name)}" if slug in taken else slug
    return assigned


def create_document(driver: Driver, database: str, name: str) -> DocumentOut:
    if _count(driver, database, NAME_TAKEN, {"name": name}) > 0:
        raise NameConflictError(name)

    slug = allocate_slug(driver, database, name)
    _write(
        driver,
        database,
        CREATE_DOCUMENT,
        {"slug": slug, "name": name},
    )
    return get_document(driver, database, slug)


def delete_document(driver: Driver, database: str, slug: str) -> None:
    summary = _write(driver, database, DELETE_DOCUMENT, {"slug": slug})
    if summary.counters.nodes_deleted == 0:
        raise DocumentNotFoundError(slug)


def _require_document(driver: Driver, database: str, slug: str) -> None:
    if _count(driver, database, SLUG_TAKEN, {"slug": slug}) == 0:
        raise DocumentNotFoundError(slug)


def add_reference(driver: Driver, database: str, source: str, target: str) -> None:
    if source == target:
        raise SelfReferenceError(source)
    _require_document(driver, database, source)
    _require_document(driver, database, target)
    _write(driver, database, ADD_REFERENCE, {"source": source, "target": target})


def remove_reference(driver: Driver, database: str, source: str, target: str) -> None:
    _require_document(driver, database, source)
    _require_document(driver, database, target)
    # No-op when the edge is absent: the contract is the end state, not the delta.
    _write(driver, database, REMOVE_REFERENCE, {"source": source, "target": target})
