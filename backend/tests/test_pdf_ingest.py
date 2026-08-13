from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_document
from policy_grapher.sources import pdf
from policy_grapher.sources.document import ExtractedDocument, ExtractionReport

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_ingesting_a_pdf_creates_the_document_and_its_edges(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    slug, nodes, relationships = ingest_document(clean_graph, database, extracted)

    assert slug == "dodd-5000-01"
    assert nodes == 1 + len(extracted.references)
    assert relationships == len(extracted.references)


def test_cited_documents_are_created_external(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted)

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
    ingest_document(clean_graph, database, extracted)

    slug, nodes, relationships = ingest_document(clean_graph, database, extracted)

    assert (slug, nodes, relationships) == ("dodd-5000-01", 0, 0)


def test_the_ingested_document_is_not_external(clean_graph, database):
    """It was cited by nothing, but it is a corpus document, not a citation target."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted)

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

    slug, nodes, relationships = ingest_document(clean_graph, database, extracted)

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
