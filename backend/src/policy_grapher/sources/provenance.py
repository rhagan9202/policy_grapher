"""Which ingest described which document, and the :External view derived from it.

ADR-007: a document is external when no ingest has described it first-hand. The
label is kept for query ergonomics — ADR-002 chose it and `WHERE NOT d:External`
stays cheap — but it is recomputed from this one rule rather than set by each
ingest path according to its own opinion.
"""

MANIFEST = "manifest"
DOCUMENT = "document"
API = "api"
API_SOURCE_ID = "api"


def source_id(kind: str, filename: str) -> str:
    """The stable identity of an ingest source. Re-ingesting a file reuses it."""
    return f"{kind}:{filename}"


MERGE_SOURCE = """
MERGE (s:Source {id: $id})
SET s.kind = $kind, s.filename = $filename
"""

DESCRIBES = """
MATCH (s:Source {id: $id})
UNWIND $slugs AS slug
MATCH (d:Document {slug: slug})
MERGE (s)-[:DESCRIBES]->(d)
"""

# Applied to every slug an ingest touched, so a promotion and a demotion are the
# same statement rather than two passes that can disagree.
REFRESH_EXTERNAL = """
UNWIND $slugs AS slug
MATCH (d:Document {slug: slug})
FOREACH (_ IN CASE WHEN EXISTS { (:Source)-[:DESCRIBES]->(d) } THEN [1] ELSE [] END |
    REMOVE d:External)
FOREACH (_ IN CASE WHEN EXISTS { (:Source)-[:DESCRIBES]->(d) } THEN [] ELSE [1] END |
    SET d:External)
"""
