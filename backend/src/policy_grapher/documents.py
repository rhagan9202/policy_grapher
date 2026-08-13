"""Document and reference Cypher.

Knows nothing about HTTP, exactly as graph.py does not. Reference lists carry
slugs, not names — see the DI-1 completion design.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import DocumentOut

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


class DocumentNotFoundError(LookupError):
    """No document with the requested slug exists."""


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
