"""Editions of an instrument.

`:Document` is the instrument's stable identity — unique slug, unique name,
provenance-tracked. A `:DocumentVersion` is one edition of it. Identity is a
function of content, not of ingest order, for the same reason slugs are
(ADR-003): re-ingesting a file must resolve to the version it already made.
"""

from datetime import date

from neo4j import ManagedTransaction

CHECKSUM_PREFIX = 12

MERGE_VERSION = """
MATCH (d:Document {slug: $document_slug})
MERGE (v:DocumentVersion {version_id: $version_id})
ON CREATE SET v.effective_date = $effective_date,
              v.checksum       = $checksum,
              v.source_uri     = $source_uri,
              v.ingested_at    = datetime()
MERGE (d)-[:HAS_VERSION]->(v)
RETURN v.ingested_at = v.ingested_at AS existed
"""


def version_id(document_slug: str, effective_date: date | None, checksum: str) -> str:
    """A version's permanent identity.

    Dated editions are addressed by their date, which is what a reader cites.
    An undated one falls back to a checksum prefix — stable, meaningless to a
    human, and honest about the fact that we could not read a date.
    """
    discriminator = (
        effective_date.isoformat() if effective_date else checksum[:CHECKSUM_PREFIX]
    )
    return f"{document_slug}@{discriminator}"


def merge_version(
    tx: ManagedTransaction,
    *,
    document_slug: str,
    effective_date: date | None,
    checksum: str,
    source_uri: str,
) -> str:
    """Attach an edition to its instrument. Returns the resolved version id.

    Returns the id rather than a created/not-created flag because every caller
    needs the id — phase 2 chunks against it, phase 3 extracts against it. A
    boolean would force each of them to recompute it.

    Additive per ADR-007: an existing version is left exactly as it was, so a
    re-ingest cannot rewrite the date or checksum of an edition already recorded.
    """
    resolved = version_id(document_slug, effective_date, checksum)
    tx.run(
        MERGE_VERSION,
        {
            "document_slug": document_slug,
            "version_id": resolved,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "checksum": checksum,
            "source_uri": source_uri,
        },
    ).consume()
    return resolved
