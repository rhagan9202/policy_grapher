from pathlib import Path

import pytest

from policy_grapher.csv_source import (
    CsvSourceError,
    canonical_name,
    parse_corpus,
    resolve_csv_path,
)

REPO_DATA = Path(__file__).resolve().parents[2] / "data"
SAMPLE = "dod_policy_references_08122026.csv"


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "corpus.csv"
    path.write_text(body, encoding="utf-8")
    return path


# --- path resolution -------------------------------------------------------

def test_resolve_accepts_a_bare_filename(tmp_path):
    (tmp_path / "a.csv").write_text("x", encoding="utf-8")
    assert resolve_csv_path("a.csv", tmp_path) == (tmp_path / "a.csv").resolve()


@pytest.mark.parametrize("attempt", ["../secrets.csv", "sub/a.csv", "/etc/passwd"])
def test_resolve_rejects_anything_that_is_not_a_bare_filename(tmp_path, attempt):
    with pytest.raises(CsvSourceError):
        resolve_csv_path(attempt, tmp_path)


def test_resolve_rejects_a_missing_file(tmp_path):
    with pytest.raises(CsvSourceError):
        resolve_csv_path("nope.csv", tmp_path)


# --- canonical names -------------------------------------------------------

def test_canonical_name_strips_punctuation_and_case():
    assert canonical_name("Military-Standard 882E") == "militarystandard882e"
    assert canonical_name("Military Standard 882E") == "militarystandard882e"


def test_canonical_name_drops_parenthesised_segments():
    a = "National Security Presidential Directive (NSPD)-47/Homeland Security Presidential Directive-16"
    b = "National Security Presidential Directive-47/Homeland Security Presidential Directive-16"
    assert canonical_name(a) == canonical_name(b)


def test_canonical_name_keeps_distinct_numbers_distinct():
    a = canonical_name("Code of Federal Regulations, Title 15")
    b = canonical_name("Code of Federal Regulations, Title 5")
    assert a != b


# --- parsing ---------------------------------------------------------------

def test_parses_rows_edges_and_the_external_split(tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        'A,"[\'B\', \'C\']",Root Reference\n'
        'B,"[\'C\']",Sub-Reference\n',
    )
    parsed = parse_corpus(path)

    assert parsed.corpus_names == {"A", "B"}
    assert parsed.external_names == {"C"}
    assert set(parsed.edges) == {("A", "B"), ("A", "C"), ("B", "C")}
    assert parsed.rows[0].reference_role == "Root Reference"


def test_self_references_are_skipped_and_counted(tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        'A,"[\'A\', \'B\']",Sub-Reference\n',
    )
    parsed = parse_corpus(path)

    assert ("A", "A") not in parsed.edges
    assert set(parsed.edges) == {("A", "B")}
    assert parsed.self_references_skipped == 1


def test_names_and_references_are_whitespace_stripped(tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        '  A  ,"[\'  B  \']",  Sub-Reference  \n',
    )
    parsed = parse_corpus(path)

    assert parsed.corpus_names == {"A"}
    assert parsed.external_names == {"B"}
    assert parsed.rows[0].reference_role == "Sub-Reference"


def test_wrong_columns_are_rejected(tmp_path):
    path = write_csv(tmp_path, "Name,Refs\nA,B\n")
    with pytest.raises(CsvSourceError):
        parse_corpus(path)


def test_an_unparseable_references_cell_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "Document Name,References,Type\nA,not-a-list,Sub-Reference\n",
    )
    with pytest.raises(CsvSourceError):
        parse_corpus(path)


def test_duplicate_detection_groups_near_identical_names(tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        'A,"[\'Military Standard 882E\', \'Military-Standard 882E\']",Sub-Reference\n',
    )
    parsed = parse_corpus(path)

    assert parsed.suspected_duplicates == (
        ("Military Standard 882E", "Military-Standard 882E"),
    )


# --- the real corpus -------------------------------------------------------

def test_sample_corpus_matches_the_measured_figures():
    parsed = parse_corpus(resolve_csv_path(SAMPLE, REPO_DATA))

    assert len(parsed.rows) == 23
    assert len(parsed.corpus_names) == 23
    assert len(parsed.external_names) == 415
    assert len(parsed.corpus_names | parsed.external_names) == 438
    assert len(parsed.edges) == 672
    assert parsed.self_references_skipped == 4
    assert len(parsed.suspected_duplicates) == 2


def test_sample_corpus_self_referencing_documents_are_the_expected_four():
    parsed = parse_corpus(resolve_csv_path(SAMPLE, REPO_DATA))
    self_citing = {row.name for row in parsed.rows if row.name in row.references}
    assert self_citing == {
        "DoDD 5124.02",
        "DoDD 5143.01",
        "DoDD 5144.02",
        "DoDI 4151.19",
    }
