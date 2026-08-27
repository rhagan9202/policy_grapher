"""Reading a manifest out of a spreadsheet — STORY-036.

One of the four file types the vision's definition of done names, and the only
one of the two open ones that can be started: a DOCX issuance is a real document
whose structure we would have to discover and no sample exists, whereas a
manifest is *our* format — the three columns `manifest.py` already requires — so
a fixture generated from the CSV that ships is a faithful sample.
"""

from pathlib import Path

import pytest

from policy_grapher.sources import SourceError, is_document_source, list_sources
from policy_grapher.sources.manifest import parse_corpus

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
CSV = SAMPLES / "dod_policy_references_08122026.csv"
XLSX = SAMPLES / "dod_policy_references_08122026.xlsx"


def test_the_two_manifests_describe_the_same_corpus():
    """The criterion that matters. Asserting the XLSX path *works* would pass
    against a reader that produced a different corpus; asserting the two agree is
    what makes the format a second door onto one thing rather than a second
    thing. The fixture is generated from the CSV by `scripts/make-xlsx-manifest.py`,
    so a stale fixture fails here instead of drifting quietly."""
    assert parse_corpus(XLSX) == parse_corpus(CSV)


def test_a_spreadsheet_manifest_is_not_mistaken_for_a_document():
    """`.xlsx` is a manifest: many documents and the references between them, no
    text and no edition (ADR-011). Reading it as a document would try to chunk a
    spreadsheet."""
    assert not is_document_source(XLSX)


def test_the_ingest_screen_offers_spreadsheets(tmp_path):
    """STORY-077 lists what the backend can read so a reader does not have to know
    a filename. A format ingestion accepts and the picker hides is unreachable."""
    (tmp_path / "corpus.xlsx").write_bytes(XLSX.read_bytes())

    offered = list_sources(tmp_path)

    assert [f.filename for f in offered] == ["corpus.xlsx"]
    assert offered[0].kind == "manifest"


def test_a_spreadsheet_with_the_wrong_columns_says_which_it_found(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Name", "Cites", "Kind"])
    workbook.active.append(["DoDD 5000.01", "[]", "policy"])
    bad = tmp_path / "wrong.xlsx"
    workbook.save(bad)

    with pytest.raises(SourceError) as failure:
        parse_corpus(bad)

    assert "Document Name" in str(failure.value)
    assert "Name" in str(failure.value)


def test_a_file_that_is_not_a_spreadsheet_names_the_file(tmp_path):
    """A library traceback is not an answer for someone who renamed a file."""
    pretend = tmp_path / "not-really.xlsx"
    pretend.write_text("Document Name,References,Type\n", encoding="utf-8")

    with pytest.raises(SourceError) as failure:
        parse_corpus(pretend)

    assert "not-really.xlsx" in str(failure.value)


def test_an_empty_spreadsheet_is_rejected_rather_than_read_as_an_empty_corpus(
    tmp_path,
):
    """An empty corpus and an unreadable one need different actions, and ADR-019
    makes the empty graph a legitimate state — so this must not look like one."""
    from openpyxl import Workbook

    empty = tmp_path / "empty.xlsx"
    Workbook().save(empty)

    with pytest.raises(SourceError):
        parse_corpus(empty)
