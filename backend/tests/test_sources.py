"""The shared source resolver: both a manifest and a document arrive as a bare
filename under the data directory, so the resolver and its error are neutral."""

from pathlib import Path

import pytest

from policy_grapher.sources import (
    SourceError,
    is_document_source,
    resolve_source_path,
)
from policy_grapher.sources.document import DocumentSourceError
from policy_grapher.sources.manifest import CsvSourceError


def test_resolve_accepts_a_bare_filename(tmp_path):
    (tmp_path / "a.csv").write_text("x", encoding="utf-8")
    assert resolve_source_path("a.csv", tmp_path) == (tmp_path / "a.csv").resolve()


@pytest.mark.parametrize("attempt", ["../secrets.csv", "sub/a.csv", "/etc/passwd"])
def test_resolve_rejects_anything_that_is_not_a_bare_filename(tmp_path, attempt):
    with pytest.raises(SourceError):
        resolve_source_path(attempt, tmp_path)


def test_resolve_rejects_a_missing_file(tmp_path):
    with pytest.raises(SourceError):
        resolve_source_path("nope.csv", tmp_path)



@pytest.mark.parametrize(
    "filename,is_document",
    [("a.pdf", True), ("A.PDF", True), ("corpus.csv", False), ("sheet.xlsx", False)],
)
def test_a_pdf_is_a_document_source_and_a_manifest_is_not(filename, is_document):
    assert is_document_source(Path(filename)) is is_document


@pytest.mark.parametrize("error", [CsvSourceError, DocumentSourceError])
def test_both_branches_errors_are_catchable_as_one(error):
    """The route catches SourceError alone; neither branch may escape it."""
    with pytest.raises(SourceError):
        raise error("boom")
