"""extract_document end to end. Still no database."""

from pathlib import Path

import pytest

from policy_grapher.sources import pdf
from policy_grapher.sources.document import DocumentSourceError

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_a_modern_issuance_yields_its_name_and_references():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert result.name == "DoDD 5000.01"
    assert "DoDD 1322.18" in result.references
    assert "Military-Standard 882E" in result.references
    assert result.report.format == "modern"
    assert result.report.section_found is True


def test_references_are_sorted_and_unique():
    result = pdf.extract_document(SAMPLES / "850001_2014.pdf")

    assert list(result.references) == sorted(set(result.references))


def test_a_self_reference_is_skipped_and_counted():
    """DoDD 5143.01 lists its own cancelled prior version as entry (a)."""
    result = pdf.extract_document(SAMPLES / "514301p.pdf")

    assert result.name == "DoDD 5143.01"
    assert "DoDD 5143.01" not in result.references
    assert result.self_references_skipped == 1


def test_a_document_that_cites_no_version_of_itself_skips_nothing():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert result.self_references_skipped == 0


def test_entries_that_cannot_be_attributed_are_reported_verbatim():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert any(
        "National Defense Strategy" in entry for entry in result.report.unattributed
    ), result.report.unattributed


def test_a_pdf_with_no_header_is_refused():
    with pytest.raises(DocumentSourceError):
        pdf.extract_document(SAMPLES / "dod_policy_references_08122026.csv")
