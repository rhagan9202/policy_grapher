import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.documents import (
    DocumentNotFoundError,
    NameConflictError,
    SelfReferenceError,
    add_reference,
    create_document,
    delete_document,
    get_document,
    list_documents,
    remove_reference,
)
from policy_grapher.merges import (
    MergeRefused,
    apply_merges,
    record_merge,
    record_not_duplicates,
    unresolved_duplicates,
)
from policy_grapher.models import (
    ChunkOut,
    DocumentIn,
    DocumentOut,
    DocumentVersionOut,
    DuplicateCandidate,
    MergeIn,
    ObligationOut,
    ObligationsOut,
)
from policy_grapher.obligations import primary_anchor
from policy_grapher.sources.manifest import parse_corpus

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found(slug: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No document with slug {slug!r}.")


@router.get("", response_model=list[DocumentOut])
def list_all(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DocumentOut]:
    return list_documents(driver, settings.neo4j_database)


@router.get("/{slug}", response_model=DocumentOut)
def read_one(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> DocumentOut:
    try:
        return get_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc


@router.post("", response_model=DocumentOut, status_code=201)
def create(
    body: DocumentIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> DocumentOut:
    try:
        return create_document(
            driver, settings.neo4j_database, body.name
        )
    except NameConflictError as exc:
        raise HTTPException(
            status_code=409, detail=f"A document named {body.name!r} already exists."
        ) from exc


@router.delete("/{slug}", status_code=204)
def delete(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        delete_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    return Response(status_code=204)


@router.post("/{slug}/references/{target_slug}", status_code=204)
def add_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        add_reference(driver, settings.neo4j_database, slug, target_slug)
    except SelfReferenceError as exc:
        raise HTTPException(
            status_code=400, detail="A document may not reference itself."
        ) from exc
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)


@router.delete("/{slug}/references/{target_slug}", status_code=204)
def remove_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        remove_reference(driver, settings.neo4j_database, slug, target_slug)
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)


LIST_VERSIONS = """
MATCH (d:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion)
OPTIONAL MATCH (v)-[:SUPERSEDES]->(older:DocumentVersion)
RETURN v.version_id   AS version_id,
       v.effective_date AS effective_date,
       v.checksum     AS checksum,
       v.source_uri   AS source_uri,
       older.version_id AS supersedes,
       v.build_run_id            AS build_run_id,
       v.build_state             AS build_state,
       v.build_started_at        AS build_started_at,
       v.build_changed_at        AS build_changed_at,
       v.build_extractor_adapter AS build_extractor_adapter,
       v.build_embedder_adapter  AS build_embedder_adapter,
       v.build_counts            AS build_counts,
       v.build_error             AS build_error
ORDER BY coalesce(v.effective_date, ''), v.ingested_at
"""


@router.get("/{slug}/versions", response_model=list[DocumentVersionOut])
def list_versions(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DocumentVersionOut]:
    records, _, _ = driver.execute_query(
        LIST_VERSIONS,
        {"slug": slug},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    # `build_counts` is a JSON string on the node — Neo4j stores no maps on a
    # property — so it is decoded here rather than leaking a string into a field
    # the model declares as a dict.
    editions = []
    for record in records:
        fields = dict(record)
        fields["build_counts"] = json.loads(fields.get("build_counts") or "{}")
        editions.append(DocumentVersionOut(**fields))
    return editions


LIST_CHUNKS = """
MATCH (d:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion)
WHERE $version_id IS NULL OR v.version_id = $version_id
WITH v ORDER BY coalesce(v.effective_date, '') DESC, v.ingested_at DESC
LIMIT 1
MATCH (v)-[:HAS_CHUNK]->(c:Chunk)
RETURN c.chunk_id     AS chunk_id,
       c.text         AS text,
       c.page         AS page,
       c.section_path AS section_path,
       c.ordinal      AS ordinal
ORDER BY c.ordinal
"""


@router.get("/{slug}/chunks", response_model=list[ChunkOut])
def list_chunks(
    slug: str,
    version_id: str | None = None,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[ChunkOut]:
    """A version's chunks, ordered by `ordinal`.

    `version_id` picks one edition explicitly; omitted, it resolves to the
    newest version by the same "latest labelled date, then latest ingest"
    ordering `link_supersession` uses to build the SUPERSEDES chain — see
    `versions.link_supersession`.
    """
    records, _, _ = driver.execute_query(
        LIST_CHUNKS,
        {"slug": slug, "version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    return [ChunkOut(**dict(record)) for record in records]


# --- an edition's obligations (STORY-081) --------------------------------------

# Two lookups rather than one, so "no such document" and "no such edition" are
# different answers. Collapsing them would tell a user their document is missing
# when only the edition is, which is the wrong thing to go and fix.
VERSION_EXISTS = """
MATCH (d:Document {slug: $slug})
OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: $version_id})
RETURN v IS NOT NULL AS version_exists
"""

COUNT_OBLIGATIONS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN count(o) AS total
"""

# Ordered by the anchoring chunk's `ordinal`, which already follows the document,
# then by `obligation_id` — two obligations read out of one chunk have no order
# between them, and without the tie-break the list reshuffles between requests.
# `primary_anchor` rather than a plain MATCH: an obligation can anchor to more
# than one chunk where chunking overlaps a section split, and that multiplies
# rows, showing a reader the same clause twice and inflating `returned`.
LIST_OBLIGATIONS = f"""
MATCH (:DocumentVersion {{version_id: $version_id}})-[:MANDATES]->(o:Obligation)
{primary_anchor("o", "c")}
RETURN o.obligation_id AS obligation_id,
       o.statement     AS statement,
       o.modality      AS modality,
       o.section_path  AS section_path,
       c.page          AS page
ORDER BY c.ordinal, o.obligation_id
LIMIT $limit
"""


@router.get(
    "/{slug}/versions/{version_id}/obligations", response_model=ObligationsOut
)
def list_obligations(
    slug: str,
    version_id: str,
    limit: int | None = Query(default=None, ge=0),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> ObligationsOut:
    """What extraction found in one edition.

    An edition that exists and holds nothing answers 200 with an empty list; an
    edition that does not exist answers 404. Those are different facts needing
    different actions — "extraction found nothing here" against "you are looking
    at something that was never ingested" — and a route that returned `[]` for
    both would make the screen unable to tell a user which one they have.
    """
    records, _, _ = driver.execute_query(
        VERSION_EXISTS,
        {"slug": slug, "version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    if not records:
        raise HTTPException(status_code=404, detail=f"No document {slug!r}.")
    if not records[0]["version_exists"]:
        raise HTTPException(
            status_code=404,
            detail=f"Document {slug!r} has no edition {version_id!r}.",
        )

    counted, _, _ = driver.execute_query(
        COUNT_OBLIGATIONS,
        {"version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    total = counted[0]["total"]

    effective_limit = settings.obligation_list_cap if limit is None else limit
    found, _, _ = driver.execute_query(
        LIST_OBLIGATIONS,
        {"version_id": version_id, "limit": effective_limit},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    obligations = [ObligationOut(**dict(record)) for record in found]
    return ObligationsOut(
        obligations=obligations,
        total=total,
        returned=len(obligations),
        truncated=len(obligations) < total,
    )


# --- reconciling near-duplicates (STORY-031, ADR-032) --------------------------

DUPLICATE_CONTEXT = """
UNWIND $names AS name
MATCH (d:Document {name: name})
RETURN name,
       d.slug AS slug,
       count { (d)<-[:REFERENCES]-() } AS cited_by,
       EXISTS { MATCH (d)-[:HAS_VERSION]->() } AS has_text
"""


@router.get("/duplicates", response_model=list[DuplicateCandidate])
def duplicates(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DuplicateCandidate]:
    """Flagged near-duplicate names nobody has ruled on yet.

    The flag comes from `sources/manifest.py`, re-derived from the corpus file
    rather than stored: a second detector here would let this screen and the
    ingest disagree about what is suspicious.
    """
    corpus = settings.data_dir / settings.sample_csv
    if not corpus.exists():
        return []
    flagged = parse_corpus(corpus).suspected_duplicates

    with driver.session(database=settings.neo4j_database) as session:
        pending = session.execute_read(unresolved_duplicates, flagged=flagged)

        found = []
        for group in pending:
            names = sorted(group)[:2]
            rows = {
                record["name"]: record
                for record in session.run(DUPLICATE_CONTEXT, names=names)
            }
            if len(rows) != len(names):
                continue
            has_text = [rows[n]["has_text"] for n in names]
            found.append(
                DuplicateCandidate(
                    names=names,
                    slugs=[rows[n]["slug"] for n in names],
                    cited_by=[rows[n]["cited_by"] for n in names],
                    has_text=has_text,
                    # ADR-032 takes only the case it can answer.
                    mergeable=not any(has_text),
                )
            )
    return found


@router.post("/duplicates/merge", response_model=dict[str, int])
def merge_documents(
    body: MergeIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> dict[str, int]:
    """Record that two documents are one, and apply it.

    The actor is the authenticated principal and never the request body — the
    same rule `POST /review/{source}/{target}` follows, for the same reason.
    """
    try:
        with driver.session(database=settings.neo4j_database) as session:
            session.execute_write(
                record_merge,
                survivor=body.survivor,
                merged=body.merged,
                actor=principal.name,
            )
            applied = session.execute_write(apply_merges)
    except MergeRefused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    return {"applied": applied}


@router.post("/duplicates/different", status_code=204)
def not_duplicates(
    body: MergeIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    """Record that a flagged pair is two different documents, so it stops being
    asked about. A judgement made once is not re-asked (ADR-014's reasoning)."""
    with driver.session(database=settings.neo4j_database) as session:
        session.execute_write(
            record_not_duplicates,
            first=body.survivor,
            second=body.merged,
            actor=principal.name,
        )
    return Response(status_code=204)
