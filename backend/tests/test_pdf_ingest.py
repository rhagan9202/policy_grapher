import hashlib
from datetime import date
from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_document, ingest_parsed
from policy_grapher.sources import pdf
from policy_grapher.sources.document import ExtractedDocument, ExtractionReport
from policy_grapher.sources.manifest import parse_corpus

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_ingesting_a_pdf_creates_the_document_and_its_edges(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    merged = ingest_document(
        clean_graph, database, extracted, SAMPLES / "500001p.pdf"
    )

    assert merged.slug == "dodd-5000-01"
    assert merged.nodes_created == 1 + len(extracted.references)
    assert merged.relationships_created == len(extracted.references)


def test_cited_documents_are_created_external(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted, SAMPLES / "500001p.pdf")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'dodd-5000-01'})-[:REFERENCES]->(t) "
        "RETURN count(t) AS cited, sum(CASE WHEN t:External THEN 1 ELSE 0 END) AS external",
        database_=database,
    )
    assert records[0]["cited"] == len(extracted.references)
    assert records[0]["external"] == len(extracted.references)


def test_reingesting_the_same_pdf_creates_nothing_new(clean_graph, database):
    """STORY-003's invariant, on the document path."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")
    ingest_document(clean_graph, database, extracted, SAMPLES / "500001p.pdf")

    merged = ingest_document(
        clean_graph, database, extracted, SAMPLES / "500001p.pdf"
    )

    assert (merged.slug, merged.nodes_created, merged.relationships_created) == (
        "dodd-5000-01", 0, 0,
    )


def test_the_ingested_document_is_not_external(clean_graph, database):
    """It was cited by nothing, but it is a corpus document, not a citation target."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted, SAMPLES / "500001p.pdf")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'dodd-5000-01'}) RETURN d:External AS is_external",
        database_=database,
    )
    assert records[0]["is_external"] is False


def test_two_cited_names_contesting_a_base_slug_stay_distinct(clean_graph, database):
    """Regression for the in-batch slug collision the brief missed.

    "Military Standard 882E" and "Military-Standard 882E" both normalise to the
    base slug "military-standard-882e" (ADR-005 names this exact pair as the real
    corpus's contested base). Neither exists in the database yet, so resolving
    each citation's slug independently against the database would hand both the
    same bare slug, and the second MERGE would collapse into the first node,
    discarding its name. Built by hand because no sample PDF cites this pair.
    """
    extracted = ExtractedDocument(
        name="DoDD 5000.01",
        references=("Military Standard 882E", "Military-Standard 882E"),
        self_references_skipped=0,
        report=ExtractionReport(
            format="modern",
            section_found=True,
            attributed=("Military Standard 882E", "Military-Standard 882E"),
            unattributed=(),
        ),
        # A hand-built document still has to carry text: an ingest that produces
        # no chunks is refused, because the drop-then-write order would otherwise
        # let it delete a previous ingest's chunks silently.
        pages=["1. PURPOSE\nThis directive establishes policy.\n"],
    )

    merged = ingest_document(
        clean_graph, database, extracted, SAMPLES / "500001p.pdf"
    )

    assert merged.nodes_created == 3
    assert merged.relationships_created == 2

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.slug <> $main RETURN d.slug AS slug, d.name AS name",
        {"main": merged.slug},
        database_=database,
    )
    by_name = {r["name"]: r["slug"] for r in records}
    assert by_name.keys() == {"Military Standard 882E", "Military-Standard 882E"}

    slugs = set(by_name.values())
    assert len(slugs) == 2, "the two cited documents must not share a slug"
    assert "military-standard-882e" in slugs
    suffixed = slugs - {"military-standard-882e"}
    assert len(suffixed) == 1
    assert next(iter(suffixed)).startswith("military-standard-882e-")


def test_posting_a_pdf_filename_ingests_it(client_with_auth):
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "document"
    assert body["format"] == "modern"
    assert body["document"]["slug"] == "dodd-5000-01"
    assert body["references_attributed"] > 0
    assert isinstance(body["references_unattributed"], list)


def test_the_csv_response_still_says_manifest(client_with_auth):
    response = client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = response.json()
    assert body["source"] == "manifest"
    assert body["nodes_created"] == 438
    assert body["relationships_created"] == 672


def test_an_unreadable_pdf_is_a_400(client_with_auth, tmp_path, monkeypatch):
    """A PDF with no issuance header is a client error, not a 500."""
    from policy_grapher import ingest as ingest_module
    from policy_grapher.sources.document import DocumentSourceError

    def refuse(path):
        raise DocumentSourceError("no recognisable issuance header")

    monkeypatch.setattr(ingest_module.pdf, "extract_document", refuse)

    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    assert response.status_code == 400
    assert "header" in response.json()["detail"]


def test_a_document_the_manifest_only_cites_is_not_demoted_by_reingest(
    clean_graph, database, tmp_path
):
    """STORY-037, the real regression proof.

    An HTTP-level CSV reingest against the real sample corpus cannot exercise
    the defect: every one of the five sample PDFs (including DoDD 5000.01) is
    also a `Document Name` row in the sample CSV, so `MERGE_CORPUS` promotes it
    regardless of whether this fix exists. The defect only shows up for a
    document the manifest *cites* but does not list as a row of its own — a
    shape `POST /ingest` cannot produce, since it resolves filenames under
    DATA_DIR rather than a synthetic CSV. So this ingests the PDF, then a
    hand-written one-row CSV that cites DoDD 5000.01 without listing it, at the
    function level.

    Before ADR-007, `ingest_parsed`'s `REFRESH_EXTERNAL` call swept every slug
    it touched — corpus rows and external names alike — and DoDD 5000.01 landed
    in this manifest's external names, so it was marked :External even though
    the PDF had already described it first-hand.
    """
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")
    ingest_document(clean_graph, database, extracted, SAMPLES / "500001p.pdf")

    citing_csv = tmp_path / "citing.csv"
    citing_csv.write_text(
        'Document Name,References,Type\n'
        'Citing Doc,"[\'DoDD 5000.01\']",Root Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(citing_csv), citing_csv.name)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'dodd-5000-01'}) RETURN d:External AS is_external",
        database_=database,
    )
    assert records[0]["is_external"] is False


def test_a_csv_reingest_does_not_demote_a_pdf_ingested_document(client_with_auth):
    """STORY-037, smoke coverage at the HTTP level.

    Every sample PDF is also a corpus row in the sample CSV, so this does not
    discriminate the fix on its own (see the function-level regression test
    above) — it just confirms the endpoint still holds the invariant end to
    end. Before ADR-007 that demoted the PDF-ingested node to :External, hiding
    it from the default graph view."""
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = client_with_auth.get("/documents/dodd-5000-01").json()
    assert body["is_external"] is False

    graph = client_with_auth.get("/graph").json()
    assert "dodd-5000-01" in {node["id"] for node in graph["nodes"]}


def test_a_pdf_records_itself_as_the_source_of_its_document(client_with_auth, driver, database):
    from neo4j import RoutingControl

    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    records, _, _ = driver.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document {slug: 'dodd-5000-01'}) "
        "RETURN s.id AS id, s.kind AS kind",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "document:500001p.pdf"
    assert records[0]["kind"] == "document"


def test_a_cited_document_a_pdf_introduces_is_still_external(client_with_auth):
    """Only the PDF's own subject is described; what it cites is not."""
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    body = client_with_auth.get("/documents/dodd-1322-18").json()
    assert body["is_external"] is True


def _extracted(name, effective_date):
    return ExtractedDocument(
        name=name,
        references=(),
        self_references_skipped=0,
        report=ExtractionReport(
            format="modern", section_found=True, attributed=(), unattributed=()
        ),
        effective_date=effective_date,
        # Text, not because these tests care about it, but because an ingest that
        # yields no chunks is now refused outright — see
        # `test_a_pdf_with_no_extractable_text_fails_instead_of_wiping_its_chunks`.
        pages=[f"1. PURPOSE\nThe body of {name}.\n"],
    )


def test_ingesting_two_editions_through_the_ingest_path_links_supersession(
    clean_graph, database
):
    """I2: the plan's own 'a newer edition produces a SUPERSEDES edge' must be
    pinned through `ingest_document` — the actual ingest path — not only at the
    `link_supersession` unit level, which a mutated `slug` argument can dodge
    while every existing test stays green.
    """
    older = _extracted("DoDI Test Instrument", date(2020, 1, 1))
    newer = _extracted("DoDI Test Instrument", date(2024, 1, 1))

    older_merged = ingest_document(clean_graph, database, older, SAMPLES / "500001p.pdf")
    newer_merged = ingest_document(clean_graph, database, newer, SAMPLES / "500088p.pdf")
    slug = older_merged.slug
    assert newer_merged.slug == slug

    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [
        (f"{slug}@2024-01-01", f"{slug}@2020-01-01")
    ]


def test_checksum_reflects_file_bytes_not_filename(clean_graph, database, tmp_path):
    """I4: the checksum is the sole discriminator behind VersionConflictError and
    the version identity for undated editions, so it must track actual file
    content — not the filename, which is all a `path.name.encode()` mutation
    would leave it tracking.
    """
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    # Same filename, different bytes, different directories -> must produce
    # different checksums.
    same_name_a = dir_a / "same.pdf"
    same_name_b = dir_b / "same.pdf"
    same_name_a.write_bytes(b"first edition bytes")
    same_name_b.write_bytes(b"second edition bytes")

    # Different filenames, identical bytes -> must produce the same checksum.
    diff_name_a = dir_a / "alpha.pdf"
    diff_name_b = dir_b / "beta.pdf"
    diff_name_a.write_bytes(b"shared bytes")
    diff_name_b.write_bytes(b"shared bytes")

    def checksum_for(name, path):
        merged = ingest_document(clean_graph, database, _extracted(name, None), path)
        records, _, _ = clean_graph.execute_query(
            "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
            "RETURN v.checksum AS checksum",
            {"slug": merged.slug},
            database_=database,
        )
        return records[0]["checksum"]

    checksum_same_name_a = checksum_for("Same Name Doc A", same_name_a)
    checksum_same_name_b = checksum_for("Same Name Doc B", same_name_b)
    assert checksum_same_name_a != checksum_same_name_b
    assert checksum_same_name_a == hashlib.sha256(b"first edition bytes").hexdigest()
    assert checksum_same_name_b == hashlib.sha256(b"second edition bytes").hexdigest()

    checksum_diff_name_a = checksum_for("Diff Name Doc A", diff_name_a)
    checksum_diff_name_b = checksum_for("Diff Name Doc B", diff_name_b)
    assert checksum_diff_name_a == checksum_diff_name_b
    assert checksum_diff_name_a == hashlib.sha256(b"shared bytes").hexdigest()


def test_a_pdf_with_no_extractable_text_fails_instead_of_wiping_its_chunks(
    client_with_auth, monkeypatch
):
    """The reachable half of "a document ingests successfully with no text".

    `drop_chunks` runs before `write_chunks`, so a scanned PDF with no text
    layer, a pypdf regression, or a refactor that forgets to pass `pages` would
    delete the chunk set a previous ingest built and return 200 with a
    healthy-looking node count. Nothing downstream asserts that a document ended
    up with any text at all, so the loss is silent. A document source that
    produces no chunks must fail the whole ingest instead.
    """
    from dataclasses import replace

    from policy_grapher import ingest as ingest_module

    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    assert first.status_code == 200
    slug = first.json()["document"]["slug"]
    before = client_with_auth.get(f"/documents/{slug}/chunks").json()
    assert len(before) > 1, "positive control: the first ingest must store text"

    real = ingest_module.pdf.extract_document
    monkeypatch.setattr(
        ingest_module.pdf, "extract_document", lambda path: replace(real(path), pages=[])
    )

    second = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    assert second.status_code == 400
    assert "no text" in second.json()["detail"]
    after = client_with_auth.get(f"/documents/{slug}/chunks").json()
    assert [c["chunk_id"] for c in after] == [c["chunk_id"] for c in before]


@pytest.mark.integration
def test_ingesting_a_pdf_reports_the_edition_and_the_text_it_read(client_with_auth):
    """"0 nodes created" is what a second edition of an already-known document
    reports, and it reads as "nothing happened" while 38 chunks land."""
    body = client_with_auth.post("/ingest", json={"filename": "500001p_2020.pdf"}).json()

    assert body["source"] == "document"
    assert body["version_id"] == "dodd-5000-01@2020-09-09"
    assert body["chunks_written"] > 0


def test_a_manifest_ingest_is_unaffected_by_the_no_text_guard(client_with_auth):
    """A CSV legitimately carries names and edges, not text, and so legitimately
    produces no chunks. The guard is on the document path only."""
    response = client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    assert response.status_code == 200
    assert response.json()["source"] == "manifest"
