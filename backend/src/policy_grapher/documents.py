"""Document and reference Cypher.

Knows nothing about HTTP, exactly as graph.py does not. Reference lists carry
slugs, not names — see the DI-1 completion design.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import DocumentOut
from policy_grapher.slugs import base_slug, hash_suffix

DOCUMENT_FIELDS = """
OPTIONAL MATCH (d)-[:REFERENCES]->(out:Document)
WITH d, collect(DISTINCT out.slug) AS references
OPTIONAL MATCH (d)<-[:REFERENCES]-(inc:Document)
WITH d, references, collect(DISTINCT inc.slug) AS referenced_by
RETURN d.slug AS slug, d.name AS name, d.reference_role AS reference_role,
       d:External AS is_external, references, referenced_by
"""

LIST_DOCUMENTS = f"MATCH (d:Document) {DOCUMENT_FIELDS} ORDER BY slug ASC"
GET_DOCUMENT = f"MATCH (d:Document {{slug: $slug}}) {DOCUMENT_FIELDS}"


SLUG_TAKEN = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"
NAME_TAKEN = "MATCH (d:Document {name: $name}) RETURN count(d) AS total"

CREATE_DOCUMENT = """
CREATE (d:Document {slug: $slug, name: $name, reference_role: $reference_role})
"""

UPDATE_ROLE = """
MATCH (d:Document {slug: $slug})
SET d.reference_role = $reference_role
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


class NameMismatchError(ValueError):
    """The body's name does not match the addressed document."""


class ExternalDocumentError(ValueError):
    """The addressed document is external and has no reference_role."""


class SelfReferenceError(ValueError):
    """A document may not reference itself."""


def _to_document(record) -> DocumentOut:
    # Neo4j has no list sort without APOC, so order the reference lists here.
    return DocumentOut(
        slug=record["slug"],
        name=record["name"],
        reference_role=record["reference_role"],
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
    """ADR-005: the incumbent keeps its bare slug, the newcomer takes the suffix."""
    base = base_slug(name)
    if _count(driver, database, SLUG_TAKEN, {"slug": base}) == 0:
        return base
    return f"{base}-{hash_suffix(name)}"


def create_document(
    driver: Driver, database: str, name: str, reference_role: str
) -> DocumentOut:
    if _count(driver, database, NAME_TAKEN, {"name": name}) > 0:
        raise NameConflictError(name)

    slug = allocate_slug(driver, database, name)
    _write(
        driver,
        database,
        CREATE_DOCUMENT,
        {"slug": slug, "name": name, "reference_role": reference_role},
    )
    return get_document(driver, database, slug)


def update_document(
    driver: Driver, database: str, slug: str, name: str, reference_role: str
) -> DocumentOut:
    current = get_document(driver, database, slug)  # raises DocumentNotFoundError
    if current.is_external:
        raise ExternalDocumentError(slug)
    if current.name != name:
        raise NameMismatchError(name)

    _write(driver, database, UPDATE_ROLE, {"slug": slug, "reference_role": reference_role})
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
