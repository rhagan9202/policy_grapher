"""The five extraction stages. No database, so this stays outside the integration mark."""

import re
from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

MODERN = SAMPLES / "500001p.pdf"      # DoDD 5000.01
LEGACY = SAMPLES / "850001_2014.pdf"  # DoDI 8500.01


def test_text_of_reads_every_page():
    text = pdf.text_of(MODERN)

    assert "DOD DIRECTIVE 5000.01" in text
    assert "THE DEFENSE ACQUISITION SYSTEM" in text
    # 17 pages of content, not just the first
    assert len(text) > 10_000


def test_legacy_document_is_detected_by_its_lettered_entries():
    fmt, section = pdf.locate_references(pdf.text_of(LEGACY))

    assert fmt == "legacy"
    assert section is not None
    assert "(a) DoD Directive 8500.01" in section


def test_modern_document_is_detected_as_a_flat_list():
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    assert fmt == "modern"
    assert section is not None
    assert "DoD Directive 1322.18" in section


def test_the_section_is_the_enclosure_not_a_body_mention():
    """A legacy document says "References: See Enclosure 1" in its body and mentions
    "Reference (a)" dozens of times. Matching either scores zero."""
    section = pdf.locate_references(pdf.text_of(LEGACY))[1]

    assert section is not None
    assert "See Enclosure" not in section
    assert section.lstrip().startswith("(a)")


def test_a_document_with_no_references_section_reports_not_found():
    fmt, section = pdf.locate_references("A document with no references at all.")

    assert fmt == "unknown"
    assert section is None


def test_legacy_entries_split_on_their_letter_markers():
    fmt, section = pdf.locate_references(pdf.text_of(LEGACY))

    entries = pdf.split_entries(fmt, section)

    assert len(entries) > 100  # DoDI 8500.01 cites 114
    assert entries[0].startswith("DoD Directive 8500.01")
    assert not any(entry.startswith("(") for entry in entries)


def test_modern_entries_split_at_identifier_boundaries():
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    entries = pdf.split_entries(fmt, section)

    assert any(entry.startswith("DoD Directive 1322.18") for entry in entries)
    assert any(entry.startswith("Military-Standard 882E") for entry in entries)


def test_wrapped_lines_are_rejoined_into_one_entry():
    """Entries wrap mid-citation in the source PDF; a split on newlines would
    cut titles in half."""
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    entries = pdf.split_entries(fmt, section)

    wrapped = [e for e in entries if e.startswith("DoD Directive 5124.02")]
    assert wrapped, "expected the entry that wraps across two lines"
    assert "USD(P&R)" in wrapped[0]
    assert "\n" not in wrapped[0]


@pytest.mark.parametrize(
    "entry,expected",
    [
        ('DoD Directive 1322.18, “Military Training,” October 3, 2019', "DoD Directive 1322.18"),
        ('Military-Standard 882E, “DoD Standard Practice,” May 11, 2012', "Military-Standard 882E"),
        (
            'DoD Directive 5143.01, “USD(I),” November 23, 2005 (hereby cancelled)',
            "DoD Directive 5143.01",
        ),
        ("Title 10, United States Code", "Title 10, United States Code"),
        # Modern documents cite the US Code in the reversed order: "United States
        # Code, Title N" rather than "Title N, United States Code".
        ("United States Code, Title 10", "United States Code, Title 10"),
    ],
)
def test_identifier_is_the_text_before_the_quoted_title(entry, expected):
    assert pdf.identifier(entry) == expected


def test_an_entry_with_neither_identifier_nor_recognised_shape_is_unattributable():
    entry = '“Summary of the 2018 National Defense Strategy,” 2018'

    assert pdf.identifier(entry) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("DoD Directive 5000.01", "DoDD 5000.01"),
        ("DoD Instruction 8500.01", "DoDI 8500.01"),
        ("DoD Manual 8180.01", "DoDM 8180.01"),
        ("Title 10, United States Code", "United States Code, Title 10"),
        ("Public Law 116-283", "Public Law 116-283"),
        ("Military-Standard 882E", "Military-Standard 882E"),
    ],
)
def test_normalise_maps_to_the_corpus_vocabulary(name, expected):
    assert pdf.normalise(name) == expected


def test_normalise_is_idempotent_on_the_already_reversed_us_code_order():
    """"United States Code, Title N" is already the corpus's vocabulary (see the
    "Title 10, United States Code" case above, which normalises *to* this order) —
    normalise() must not reverse it a second time."""
    assert pdf.normalise("United States Code, Title 10") == "United States Code, Title 10"


def test_modern_header_names_the_document_on_one_line():
    assert pdf.document_name(pdf.text_of(MODERN)) == "DoDD 5000.01"


def test_legacy_header_splits_the_type_and_number_across_lines():
    """A legacy cover page reads "Department of Defense / DIRECTIVE / NUMBER 5143.01"."""
    legacy_directive = SAMPLES / "514301p.pdf"

    assert pdf.document_name(pdf.text_of(legacy_directive)) == "DoDD 5143.01"


def test_a_manual_is_named_DoDM():
    assert pdf.document_name(pdf.text_of(SAMPLES / "818001m.pdf")) == "DoDM 8180.01"


def test_text_with_no_recognisable_header_has_no_name():
    assert pdf.document_name("Some other document entirely.") is None


def test_a_wrapped_title_containing_an_opener_phrase_does_not_split_the_entry():
    """An entry's own quoted title can wrap onto a line starting with an opener
    phrase ("Department of" / "Defense ..."). A citation cannot begin while the
    previous one's title is still open, so the boundary must respect the quote."""
    fmt, section = pdf.locate_references(pdf.text_of(SAMPLES / "500088p.pdf"))

    entries = pdf.split_entries(fmt, section)

    assert not any(entry.startswith("Defense Risk, Issue, and Opportunity") for entry in entries)
    whole = [e for e in entries if "Risk, Issue, and Opportunity Management Guide" in e]
    assert len(whole) == 1
    assert whole[0].startswith("Office of the Deputy Assistant Secretary")


@pytest.mark.parametrize("filename", ["514301p.pdf", "850001_2014.pdf"])
def test_a_located_section_does_not_trail_into_the_page_footer(filename):
    """Legacy sections end at the next enclosure heading, but the page footer that
    precedes it ("DoDD 5143.01, October 24, 2014 Change 2, 04/06/2020 21 GLOSSARY")
    leaks in and corrupts the final entry."""
    section = pdf.locate_references(pdf.text_of(SAMPLES / filename))[1]

    assert section is not None
    assert not re.search(r"(?:GLOSSARY|ENCLOSURE\s+\d+)\s*$", section, re.IGNORECASE)
    assert not re.search(r"Change \d+,\s*\d{2}/\d{2}/\d{4}\s*\d*\s*$", section)


def test_a_heading_with_no_citations_beneath_it_is_not_a_references_section():
    """A table-of-contents line can match the heading pattern. A real section
    contains citations; a contents entry does not."""
    # Mentions "DoD Directive" — enough for the format marker — but carries no
    # citation: no entry yields an identifier. A real section always does.
    contents = (
        "ENCLOSURE\nREFERENCES\n"
        "1. Purpose, and how it relates to DoD Directive 5000.01 generally.\n"
        "2. Responsibilities of the offices named above.\n"
    )

    assert pdf.locate_references(contents) == ("unknown", None)


def test_the_cover_page_bound_adapts_to_a_long_front_matter():
    """The identity bound must not be a fixed character count: a long classification
    banner or distribution statement can push a real header past it."""
    padding = "DISTRIBUTION STATEMENT A. Approved for public release. " * 60
    full = f"{padding}\nDepartment of Defense\nDIRECTIVE\nNUMBER 5143.01\n\nREFERENCES\n(a) x\n"
    assert len(padding) > 2000

    assert pdf.document_name(full) == "DoDD 5143.01"
