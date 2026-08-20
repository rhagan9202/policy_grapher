"""The five extraction stages. No database, so this stays outside the integration mark."""

import re
from datetime import date
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


def test_the_cover_page_bound_adapts_to_a_moderate_front_matter():
    """The identity bound must not be a fixed character count *below* the fallback:
    a classification banner or distribution statement that pushes a real header
    past a naively short bound (but still within `_COVER_PAGE_FALLBACK`) must not
    defeat header detection."""
    padding = "DISTRIBUTION STATEMENT A. Approved for public release. " * 20
    full = f"{padding}\nDepartment of Defense\nDIRECTIVE\nNUMBER 5143.01\n\nREFERENCES\n(a) x\n"
    assert 500 < len(padding) < 2000

    assert pdf.document_name(full) == "DoDD 5143.01"


def test_the_cover_page_bound_gives_up_past_the_fallback_rather_than_scanning_the_body():
    """Past `_COVER_PAGE_FALLBACK`, `_cover_page` stops at the fallback even when a
    references heading exists further out — `min(heading.start(),
    _COVER_PAGE_FALLBACK)`, not `heading.start()` alone. This is a real trade-off,
    not an oversight: DoD's modern layout puts REFERENCES near the *end* of the
    document (500001p.pdf's cover-to-full ratio was 96% before this bound existed),
    so bounding by the heading alone made `effective_date` a whole-document scan in
    practice, free to pick up a citation's own unlabelled date deep in the body. An
    honest `None` here — like an unread date — beats a header found by accident far
    past where a cover page plausibly ends."""
    padding = "DISTRIBUTION STATEMENT A. Approved for public release. " * 60
    full = f"{padding}\nDepartment of Defense\nDIRECTIVE\nNUMBER 5143.01\n\nREFERENCES\n(a) x\n"
    assert len(padding) > 2000

    assert pdf.document_name(full) is None


# effective_date: a cover states three kinds of date (labelled effective, labelled
# change, and an unlabelled date inside a citation of some other issuance), and only
# the first two are candidates. Real fixtures cover the first two forms and the
# "latest wins" rule directly; the third case below — an unlabelled date that is
# *later* than the labelled one — has no real fixture (DoD boilerplate happens to
# always restate an *older* date unlabelled), so it is built by hand.


def test_effective_date_reads_a_plain_effective_label():
    """500088p.pdf's cover carries exactly one date, plainly labelled."""
    cover = pdf._cover_page(pdf.text_of(SAMPLES / "500088p.pdf"))

    assert pdf.effective_date(cover) == date(2020, 11, 18)


def test_effective_date_prefers_a_change_effective_label_over_the_base_date():
    """500001p.pdf's cover carries both "Effective: September 9, 2020" and "Change 1
    Effective: July 28, 2022" — the file on disk is the Change-1-incorporated
    edition, so the later, change-labelled date must win, not the first one found."""
    cover = pdf._cover_page(pdf.text_of(SAMPLES / "500001p.pdf"))

    assert pdf.effective_date(cover) == date(2022, 7, 28)


def test_effective_date_reads_a_bare_incorporating_change_label():
    """514301p.pdf's "Incorporating Change 2, April 6, 2020" carries no word
    "Effective" at all — it must still count as labelled."""
    cover = pdf._cover_page(pdf.text_of(SAMPLES / "514301p.pdf"))

    assert pdf.effective_date(cover) == date(2020, 4, 6)


def test_effective_date_reads_a_colon_less_effective_label():
    """850001_2014.pdf's "Incorporating Change 1, Effective October 7, 2019" has no
    colon after "Effective" — the label still anchors the date."""
    cover = pdf._cover_page(pdf.text_of(SAMPLES / "850001_2014.pdf"))

    assert pdf.effective_date(cover) == date(2019, 10, 7)


def test_effective_date_ignores_an_unlabelled_date_even_when_it_is_later():
    """The case with no real fixture: a cover carrying an unlabelled date from a
    citation of some *other* issuance, later than the labelled effective date, must
    not win. Only a labelled date is ever a candidate — this is the defect the
    original "first regex hit" implementation had (500001p's cover offers an
    unlabelled "May 12, 2003" that only lost by coming after the labelled date in
    the text; this pins the rule, not the position, as what decides it)."""
    cover = (
        "Effective: September 9, 2020\n"
        'Reissues and Cancels: DoD Directive 9999.99, "Some Other Issuance," '
        "December 31, 2099\n"
    )

    assert pdf.effective_date(cover) == date(2020, 9, 9)


def test_effective_date_is_none_with_no_date_at_all():
    assert pdf.effective_date("A cover page mentioning no date at all.") is None


def test_effective_date_is_none_when_every_date_present_is_unlabelled():
    """A date exists in the text, but none of it is anchored to a label — the
    honest answer is None, not a guess at which unlabelled date might be it."""
    cover = 'Reissues DoD Directive 1234.56, "Some Issuance," May 12, 2003\n'

    assert pdf.effective_date(cover) is None


def test_effective_date_prefers_the_calendar_latest_over_the_positionally_last_date():
    """"Latest" must mean latest by calendar value, not by text position — real DoD
    covers sometimes list change history most-recent-first. If this cover's dates
    were taken in text order (`found[-1]`) rather than by calendar comparison
    (`max(found)`), the answer would be the *earlier* date, 2019-10-07, because it
    comes last in the text. Every other fixture and synthetic cover in this suite
    happens to list its latest date last, so only this ordering distinguishes the
    two implementations."""
    cover = (
        "Incorporating Change 2, April 6, 2020\n"
        "Incorporating Change 1, October 7, 2019\n"
    )

    assert pdf.effective_date(cover) == date(2020, 4, 6)


def test_the_cover_page_bound_is_the_heading_when_it_is_smaller_than_the_fallback():
    """The other side of `_cover_page`'s `min(heading.start(), _COVER_PAGE_FALLBACK)`:
    when the heading sits *before* the fallback, the bound must be the heading, not
    a flat `full[:_COVER_PAGE_FALLBACK]` that happens to reach the same place. None
    of the five sample fixtures exercises this side — every real heading sits well
    past 2000 characters (see
    `test_the_cover_page_bound_gives_up_past_the_fallback_rather_than_scanning_the_body`)
    — so this is assembled from 850001_2014.pdf's own real text: its true legacy
    header, its real (non-matching, colon-broken) "References: See Enclosure 1"
    body mention, a real heading-shaped line drawn from its own enclosure list
    ("1. References"), and its real cancelled predecessor citation ("(a) DoD
    Directive 8500.01, ...", the exact citation the pre-existing comment on
    `_COVER_PAGE_FALLBACK` names as the risk this bound exists to prevent).

    `document_name` tries `_MODERN_HEADER` before `_LEGACY_HEADER`, so a
    modern-shaped match anywhere in the cover wins regardless of position — and
    "(a) DoD Directive 8500.01" is exactly modern-shaped. If the bound reached even
    one character past the heading here, that citation would be included and
    `_MODERN_HEADER` would misname this DoDI a DoDD.
    """
    full = (
        "Department of Defense \nINSTRUCTION \n \n \n \nNUMBER 8500.01 \nMarch 14, 2014 \n"
        "Incorporating Change 1, Effective October 7, 2019 \n \nDoD CIO \n \n"
        "SUBJECT: Cybersecurity \n \nReferences: See Enclosure 1 \n \n \n"
        "1. References\n2. Responsibilities\n\n"
        '(a) DoD Directive 8500.01, "Information Assurance (IA)," October 4, 2002 '
        "(hereby cancelled)\n"
    )
    heading = pdf._HEADING.search(full)
    assert heading is not None
    assert heading.start() < pdf._COVER_PAGE_FALLBACK, "the test must exercise the heading side"
    assert len(full) < pdf._COVER_PAGE_FALLBACK, "so a flat fallback slice would still see the citation"

    assert pdf.document_name(full) == "DoDI 8500.01"


def test_a_legacy_cover_is_not_titled_as_the_predecessor_it_cancels():
    """Pattern order must not beat text position.

    Real cover matter from DoDD 5000.01 (May 12, 2003). Its own header is the
    legacy form — "DIRECTIVE ... NUMBER 5000.01" — but reference (a) cites the
    modern-format "DoD Directive 5000.1", the very issuance it cancels. Trying
    `_MODERN_HEADER` across the whole cover before `_LEGACY_HEADER` lets that
    citation win from further down the page, titling the document as the one it
    replaced and hanging every citation edge off the wrong node.

    The heading bound does not save this: `_HEADING` wants "REFERENCES" on its
    own line, and this cover runs "References:   (a) ..." inline.
    """
    full = (
        "Department of Defense\n\nDIRECTIVE\n\nNUMBER 5000.01\nMay 12, 2003\n"
        "Incorporating Change 2, August 31, 2018\n\nUSD(A&S)\n\n"
        "SUBJECT:   The Defense Acquisition System\n\n"
        'References:   (a) DoD Directive 5000.1, "The Defense Acquisition System,"\n'
        "October 23, 2000 (hereby canceled)\n"
    )
    assert _HEADING_DOES_NOT_BITE(full)
    assert pdf.document_name(full) == "DoDD 5000.01"


def _HEADING_DOES_NOT_BITE(full: str) -> bool:
    """Guard: if this ever bites, the test stops exercising what it claims to."""
    heading = pdf._HEADING.search(full)
    return heading is None or heading.start() >= pdf._COVER_PAGE_FALLBACK
