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

    slug, nodes, relationships = ingest_document(
        clean_graph, database, extracted, "500001p.pdf"
    )

    assert slug == "dodd-5000-01"
    assert nodes == 1 + len(extracted.references)
    assert relationships == len(extracted.references)


def test_cited_documents_are_created_external(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted, "500001p.pdf")

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
    ingest_document(clean_graph, database, extracted, "500001p.pdf")

    slug, nodes, relationships = ingest_document(
        clean_graph, database, extracted, "500001p.pdf"
    )

    assert (slug, nodes, relationships) == ("dodd-5000-01", 0, 0)


def test_the_ingested_document_is_not_external(clean_graph, database):
    """It was cited by nothing, but it is a corpus document, not a citation target."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted, "500001p.pdf")

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
    )

    slug, nodes, relationships = ingest_document(
        clean_graph, database, extracted, "500001p.pdf"
    )

    assert nodes == 3
    assert relationships == 2

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.slug <> $main RETURN d.slug AS slug, d.name AS name",
        {"main": slug},
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


def test_posting_a_pdf_filename_ingests_it(client_with_graph):
    response = client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "document"
    assert body["format"] == "modern"
    assert body["document"]["slug"] == "dodd-5000-01"
    assert body["references_attributed"] > 0
    assert isinstance(body["references_unattributed"], list)


def test_the_csv_response_still_says_manifest(client_with_graph):
    response = client_with_graph.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = response.json()
    assert body["source"] == "manifest"
    assert body["nodes_created"] == 438
    assert body["relationships_created"] == 672


def test_an_unreadable_pdf_is_a_400(client_with_graph, tmp_path, monkeypatch):
    """A PDF with no issuance header is a client error, not a 500."""
    from policy_grapher import ingest as ingest_module
    from policy_grapher.sources.document import DocumentSourceError

    def refuse(path):
        raise DocumentSourceError("no recognisable issuance header")

    monkeypatch.setattr(ingest_module.pdf, "extract_document", refuse)

    response = client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

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
    ingest_document(clean_graph, database, extracted, "500001p.pdf")

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


def test_a_csv_reingest_does_not_demote_a_pdf_ingested_document(client_with_graph):
    """STORY-037, smoke coverage at the HTTP level.

    Every sample PDF is also a corpus row in the sample CSV, so this does not
    discriminate the fix on its own (see the function-level regression test
    above) — it just confirms the endpoint still holds the invariant end to
    end. Before ADR-007 that demoted the PDF-ingested node to :External, hiding
    it from the default graph view."""
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    client_with_graph.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = client_with_graph.get("/documents/dodd-5000-01").json()
    assert body["is_external"] is False

    graph = client_with_graph.get("/graph").json()
    assert "dodd-5000-01" in {node["id"] for node in graph["nodes"]}


def test_a_pdf_records_itself_as_the_source_of_its_document(client_with_graph, driver, database):
    from neo4j import RoutingControl

    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    records, _, _ = driver.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document {slug: 'dodd-5000-01'}) "
        "RETURN s.id AS id, s.kind AS kind",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "document:500001p.pdf"
    assert records[0]["kind"] == "document"


def test_a_cited_document_a_pdf_introduces_is_still_external(client_with_graph):
    """Only the PDF's own subject is described; what it cites is not."""
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    body = client_with_graph.get("/documents/dodd-1322-18").json()
    assert body["is_external"] is True
