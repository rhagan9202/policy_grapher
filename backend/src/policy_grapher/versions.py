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
RETURN v.checksum AS checksum
"""


class UnknownDocumentError(Exception):
    """Raised when a version is merged against a document that does not exist.

    An instrument must be ingested before any of its editions — there is
    nothing for a version to hang off. A silently-dropped write here would
    hand the caller a plausible-looking id for a version that was never
    recorded, so this is loud instead.
    """


class VersionConflictError(Exception):
    """Raised when two different files resolve to the same version identity.

    Same effective date, different checksum: a corrected reissue ("Change 1")
    and a distinct edition look identical under a date-only identity. The
    graph cannot tell which one this is — guessing would put a wrong edition
    boundary into the record, which is exactly what an honest identity is
    supposed to prevent. The operator decides.
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

    Raises `UnknownDocumentError` if `document_slug` names no `:Document`, and
    `VersionConflictError` if this version id is already recorded under a
    different checksum than the one presented here.
    """
    resolved = version_id(document_slug, effective_date, checksum)
    record = tx.run(
        MERGE_VERSION,
        {
            "document_slug": document_slug,
            "version_id": resolved,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "checksum": checksum,
            "source_uri": source_uri,
        },
    ).single()
    if record is None:
        raise UnknownDocumentError(
            f"no :Document with slug {document_slug!r}; "
            "ingest the document before its versions"
        )
    stored_checksum = record["checksum"]
    if stored_checksum != checksum:
        raise VersionConflictError(
            f"version {resolved!r} is already recorded with checksum "
            f"{stored_checksum!r}, but this ingest presents checksum "
            f"{checksum!r} for the same effective date — two different "
            "files claim the same edition"
        )
    return resolved


REBUILD_SUPERSESSION = """
MATCH (d:Document {slug: $document_slug})-[:HAS_VERSION]->(v:DocumentVersion)
WITH v ORDER BY coalesce(v.effective_date, '') ASC, v.ingested_at ASC
WITH collect(v) AS ordered
CALL {
    WITH ordered
    UNWIND range(0, size(ordered) - 1) AS i
    WITH ordered[i] AS v
    MATCH (v)-[old:SUPERSEDES]->()
    DELETE old
}
WITH ordered
UNWIND range(1, size(ordered) - 1) AS i
WITH ordered[i] AS newer, ordered[i - 1] AS older
MERGE (newer)-[:SUPERSEDES]->(older)
RETURN count(*) AS edges
"""


def link_supersession(tx: ManagedTransaction, document_slug: str) -> int:
    """Rebuild one instrument's supersession chain from scratch.

    Rebuilt rather than appended because editions do not arrive in order. A
    2025 edition ingested after the 2026 one belongs in the middle, and an
    append-only chain would record that 2026 supersedes 2024 forever.

    This deletes and recreates SUPERSEDES edges, which is the one place ingest
    is not purely additive. It is safe because the chain is *derived* from the
    versions' own dates — no human decision lives on these edges. Do not extend
    this pattern to edges that carry a judgement.
    """
    records = tx.run(REBUILD_SUPERSESSION, {"document_slug": document_slug})
    row = records.single()
    return row["edges"] if row else 0
