import pytest
from pydantic import ValidationError

from policy_grapher.extraction.schema import (
    WORD_MODALITIES,
    ExtractedObligation,
    Modality,
    is_responsibilities_section,
    obligation_id,
    validate_extracted,
)


def test_a_well_formed_obligation_validates():
    o = ExtractedObligation(
        statement="The Director shall notify the Comptroller within 24 hours.",
        modality=Modality.SHALL,
        actor="The Director",
        deadline="24 hours",
        conditions=None,
        confidence=0.9,
    )
    assert o.modality is Modality.SHALL


def test_an_unknown_modality_is_rejected():
    """A closed enum: an adapter inventing a modality must fail loudly.

    The example used to be 'WILL', which ADR-025 admitted to the set once the
    corpus was counted — `will` outnumbers `shall` 458 to 93. The rule this test
    asserts did not change; only which words are in the set. 'OUGHT' stands in
    because no DoD issuance imposes a duty with it.
    """
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality="OUGHT", actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_confidence_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=1.4,
        )


def test_an_empty_statement_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="   ", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_identity_is_stable_across_runs():
    args = ("v", ["3", "3.2"], "The Director shall notify the Comptroller.")
    assert obligation_id(*args) == obligation_id(*args)


def test_identity_ignores_whitespace_and_case_in_the_statement():
    """Re-extraction must not orphan a human decision over a reflowed line."""
    a = obligation_id("v", ["3.2"], "The Director shall notify.")
    b = obligation_id("v", ["3.2"], "the  director   SHALL notify.")
    assert a == b


def test_identity_distinguishes_sections():
    a = obligation_id("v", ["3.2"], "Same words.")
    b = obligation_id("v", ["4.1"], "Same words.")
    assert a != b


def test_identity_distinguishes_versions():
    a = obligation_id("v1", ["3.2"], "Same words.")
    b = obligation_id("v2", ["3.2"], "Same words.")
    assert a != b


# --- WILL, and what makes an obligation binding (STORY-055, ADR-025) -----------


def test_will_is_a_modality_this_corpus_actually_uses():
    """`shall` 93 against `will` 458 across the seven samples, and it is
    generational rather than incidental: the 2003 edition of DoDD 5000.01 uses
    `shall` 92 times and `must` never, while its 2020 re-issue uses `shall` zero
    times and `will` 44. An extractor obeying the old enum could only report a
    minority of a modern issuance's duties."""
    assert Modality("WILL") is Modality.WILL


def test_a_will_obligation_is_binding():
    """DoD's plain-language drafting replaced the directive `shall` with `will`.
    It is a duty, not an expectation."""
    assert ExtractedObligation(
        statement="The DoD Components will report annually.",
        modality=Modality.WILL,
        actor="DoD Components",
        deadline="annually",
        conditions=None,
        confidence=0.9,
    ).is_binding


def test_shall_and_must_stay_binding():
    # The statement carries the word it is labelled with, which the schema now
    # requires — a modality is a claim about a word in the passage.
    for modality in (Modality.SHALL, Modality.MUST):
        assert ExtractedObligation(
            statement=f"The Director {modality.value.lower()} notify.",
            modality=modality,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        ).is_binding


def test_should_and_may_are_not_binding():
    """The distinction the closed enum exists to protect. A binding duty read as
    advice is the silent downgrade `schema.py` refuses to allow."""
    for modality in (Modality.SHOULD, Modality.MAY):
        assert not ExtractedObligation(
            statement=f"The Director {modality.value.lower()} consider notifying.",
            modality=modality,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        ).is_binding


def test_bindingness_is_asked_of_the_obligation_not_pattern_matched():
    """Every member has an answer, so no consumer has to keep its own list of
    which names count — the way a consumer written before WILL existed would."""
    for modality in Modality:
        obligation = ExtractedObligation(
            statement=f"The Component {modality.value.lower()} do the thing.",
            modality=modality,
            # Named rather than None because ADR-033 requires an ASSIGNED
            # obligation to name the office it is assigned to. The claim here is
            # unchanged — every member answers `is_binding` — only the fixture
            # had to become valid for all six.
            actor="Component",
            deadline=None,
            conditions=None,
            confidence=0.5,
        )
        assert isinstance(obligation.is_binding, bool)


# --- the modality word must be in the statement (sprint 7) ---------------------


def test_a_statement_without_its_modality_word_is_rejected():
    """The prompt has asked for this since PROMPT_VERSION 2 and nothing enforced
    it, so it kept happening.

    Measured on the live graph 2026-08-27, after a full rebuild under that prompt:
    18 of 215 obligations were four words or fewer — "Be Responsive.", "Focus on
    Affordability.", "e. Emphasize Competition." — section headings recorded as
    duties, each labelled SHALL by a model that had no SHALL to point at.

    Sprint 6 reported these as fixed. That check compared five exact strings
    without their trailing full stops, and the same prompt change that stopped the
    model dropping sentence subjects also made it keep the closing "." — so the
    strings no longer matched and the headings were counted as gone.

    A modality is a claim about a word in the passage. If the word is not in the
    statement, the claim is not about anything.
    """
    with pytest.raises(ValidationError):
        ExtractedObligation.model_validate(
            {
                "statement": "Be Responsive.",
                "modality": "SHALL",
                "actor": None,
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            }
        )


def test_the_modality_word_is_matched_regardless_of_case():
    """Documents write "shall" and the enum records SHALL."""
    obligation = ExtractedObligation.model_validate(
        {
            "statement": "The Director shall notify the Comptroller of any breach.",
            "modality": "SHALL",
            "actor": "The Director",
            "deadline": None,
            "conditions": None,
            "confidence": 0.9,
        }
    )

    assert obligation.modality is Modality.SHALL


def test_a_modality_word_inside_another_word_does_not_count():
    """"Marshall" contains "shall" and imposes nothing. Substring matching here
    would let exactly the statements this rejects back in."""
    with pytest.raises(ValidationError):
        ExtractedObligation.model_validate(
            {
                "statement": "General Marshall commanded the Army.",
                "modality": "SHALL",
                "actor": None,
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            }
        )


def test_an_assigned_obligation_needs_no_modal_verb_in_its_statement():
    """ADR-033. DoD assigns duties by position — a role heading followed by
    lettered third-person verbs — and there is no word to quote."""
    obligation = ExtractedObligation(
        statement=(
            "The USD(R&E) executes the research and engineering responsibilities "
            "in DoDD 5137.02."
        ),
        modality=Modality.ASSIGNED,
        actor="USD(R&E)",
        deadline=None,
        conditions=None,
        confidence=0.9,
    )

    assert obligation.modality is Modality.ASSIGNED


def test_every_word_modality_still_requires_its_word():
    """The rule is restated, not exempted: if a modality names a word, the
    statement must contain it.

    Written as an exception list, this is where a word modality would quietly
    slip out of the rule — so the set is derived from the enum and this iterates
    it rather than naming the five.
    """
    for modality in WORD_MODALITIES:
        with pytest.raises(ValidationError):
            ExtractedObligation(
                statement="The Component reports annually.",  # no modal verb
                modality=modality,
                actor="Component",
                deadline=None,
                conditions=None,
                confidence=0.9,
            )


def test_an_assigned_obligation_must_name_the_office_it_is_assigned_to():
    """ADR-033's schema half of the structural guard.

    A positional duty is an assignment *to somebody*. Without an actor there is
    no position, and ASSIGNED becomes the escape hatch that puts section
    headings back in the graph as duties.
    """
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="Executes the research and engineering responsibilities.",
            modality=Modality.ASSIGNED,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        )


def test_an_assigned_duty_binds():
    """ADR-033: a responsibility assigned to a named office is not advice."""
    obligation = ExtractedObligation(
        statement="The DoD CIO monitors and evaluates the program.",
        modality=Modality.ASSIGNED,
        actor="DoD CIO",
        deadline=None,
        conditions=None,
        confidence=0.9,
    )

    assert obligation.is_binding


# --- ADR-033: the section half of the guard -----------------------------------


def test_a_responsibilities_section_is_recognised_by_its_own_title():
    """Read out of the document's own heading, not from a list of sections we
    expect to exist — which is what keeps this from being a keyword list."""
    assert is_responsibilities_section("RESPONSIBILITIES")
    assert is_responsibilities_section("Responsibilities")
    assert is_responsibilities_section("RESPONSIBILITIES AND FUNCTIONS")
    assert not is_responsibilities_section("PROCEDURES")
    assert not is_responsibilities_section("GENERAL ISSUANCE INFORMATION")
    assert not is_responsibilities_section(None)


def test_an_assigned_item_outside_a_responsibilities_section_is_refused():
    """ADR-033's adapter half. The model validates an item without knowing where
    it came from, so this is the half that needs the section."""
    item = {
        "statement": "Monitors and evaluates the program.",
        "modality": "ASSIGNED",
        "actor": "DoD CIO",
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }

    assert validate_extracted(item, section_title="RESPONSIBILITIES")
    with pytest.raises(ValueError):
        validate_extracted(item, section_title="PROCEDURES")
    with pytest.raises(ValueError):
        validate_extracted(item, section_title=None)


def test_a_word_modality_is_unaffected_by_the_section_it_was_read_from():
    """The section guard exists only because ASSIGNED names no word. A SHALL
    quotes its word wherever it is written, so nothing about it depends on the
    section — and a guard that refused one would silently lose real duties."""
    item = {
        "statement": "The Director shall notify the Comptroller.",
        "modality": "SHALL",
        "actor": "The Director",
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }

    assert validate_extracted(item, section_title="PROCEDURES")
    assert validate_extracted(item, section_title=None)


def test_be_responsive_is_refused_by_both_guards_independently():
    """The regression test of this sprint.

    "Be Responsive." is a section heading that a model labelled SHALL for a whole
    sprint, and 18 of 215 obligations in the live graph were shapes like it. The
    danger ADR-033 accepts is that it returns as ASSIGNED instead, since ASSIGNED
    names no word to check against the passage.

    It fails both guards, and each half is asserted on its own so that losing one
    guard cannot be masked by the other still holding.
    """
    heading = {
        "statement": "Be Responsive.",
        "modality": "ASSIGNED",
        "actor": None,
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }

    # Guard one, on its own: no actor, even in the right section.
    with pytest.raises(ValueError):
        validate_extracted(heading, section_title="RESPONSIBILITIES")

    # Guard two, on its own: wrong section, even once an actor is supplied.
    with pytest.raises(ValueError):
        validate_extracted(
            {**heading, "actor": "DoD"}, section_title="GENERAL ISSUANCE INFORMATION"
        )


def test_an_assigned_actor_may_not_be_the_statement_itself():
    """Found by rebuilding DoDD 5000.01 (2020) after ADR-033 landed.

    Two of 33 ASSIGNED obligations came back with `actor` set to the whole
    statement, character for character. The model could not find a role heading
    and satisfied the "ASSIGNED requires an actor" rule by copying the sentence
    into the field — which passes a non-null check while naming nobody, and so
    defeats the guard by obeying its letter.

    The rule is exact rather than a length heuristic on purpose: a real actor can
    be long ("DoD Component heads, including the Directors of the Defense
    Agencies with acquisition authority ..." is one), so anything shaped like
    "the actor must be shorter than the statement" would refuse real duties to
    catch this one.
    """
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="Reviews and advises the MDA on the DT&E plan in the TEMP.",
            modality=Modality.ASSIGNED,
            actor="Reviews and advises the MDA on the DT&E plan in the TEMP.",
            deadline=None,
            conditions=None,
            confidence=0.9,
        )


def test_a_long_but_real_actor_is_still_accepted():
    """The other side of the rule above: this actor is 150 characters and names
    real offices, and refusing it would lose the duty."""
    obligation = ExtractedObligation(
        statement="Implement the policy in this issuance for programs they oversee.",
        modality=Modality.ASSIGNED,
        actor=(
            "DoD Component heads, including the Directors of the Defense Agencies "
            "with acquisition authority but not the CJCS"
        ),
        deadline=None,
        conditions=None,
        confidence=0.9,
    )

    assert obligation.is_binding


# --- a statement is a quotation, and that is now checked ----------------------


def test_a_statement_absent_from_its_own_chunk_is_refused():
    """The prompt has required word-for-word quoting since PROMPT_VERSION 2, and
    asking was not enough — the same lesson the modality-word rule taught.

    Measured on the live graph 2026-08-28: 34 of 196 obligations, 17%, had a
    statement that does not occur in the chunk it was read from. `obligation_id`
    hashes the normalised statement, so a misquotation is an id derived from text
    the document does not contain — and a later extraction that quotes correctly
    produces a different id, orphaning every decision recorded against the first.
    """
    item = {
        "statement": "The Director shall notify the Comptroller.",
        "modality": "SHALL",
        "actor": "The Director",
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }

    assert validate_extracted(
        item, section_title=None,
        chunk_text="Preamble.\nThe Director shall notify the\nComptroller.\nMore text.",
    )
    with pytest.raises(ValueError):
        validate_extracted(
            item, section_title=None,
            chunk_text="This passage says something else entirely.",
        )


def test_the_quotation_check_survives_the_line_breaks_a_pdf_puts_in():
    """A chunk holds the document's text verbatim, newlines and all, while a
    statement is a single line. Comparing them raw would refuse every real
    obligation, so both sides are normalised the way `obligation_id` normalises."""
    assert validate_extracted(
        {
            "statement": "The USD(A&S) shall issue and maintain requirements for acquisition strategies.",
            "modality": "SHALL",
            "actor": "USD(A&S)",
            "deadline": None,
            "conditions": None,
            "confidence": 0.9,
        },
        section_title=None,
        chunk_text=(
            "2.1.  USD(A&S).\nThe USD(A&S) shall issue and maintain\n"
            "requirements   for acquisition strategies.\n"
        ),
    )


def test_without_the_passage_the_quotation_check_does_not_run():
    """Callers that hold no chunk text — replaying a fixture, validating a gold
    item — must keep working. The guard is evidence-based: absent the passage
    there is no evidence to check against, and inventing a verdict would be
    worse than declining to reach one."""
    assert validate_extracted(
        {
            "statement": "The Director shall notify the Comptroller.",
            "modality": "SHALL",
            "actor": "The Director",
            "deadline": None,
            "conditions": None,
            "confidence": 0.9,
        },
        section_title=None,
    )


def test_a_placeholder_actor_is_recorded_as_no_actor():
    """The prompt has said "never write a placeholder such as 'no actor
    specified' — use null" since PROMPT_VERSION 2, and asking was not enough for
    the third time in three sprints.

    Measured on the live graph 2026-08-28: 20 obligations carry the *string*
    "null" as their actor. A consumer reading that field gets four characters
    that look like a name, and `actor IS NOT NULL` in Cypher counts them as
    having one.
    """
    for placeholder in ("null", "None", "  N/A ", "no actor specified", "   "):
        obligation = ExtractedObligation(
            statement="The Component shall report annually.",
            modality=Modality.SHALL,
            actor=placeholder,
            deadline=None,
            conditions=None,
            confidence=0.9,
        )
        assert obligation.actor is None, placeholder


def test_a_placeholder_actor_cannot_satisfy_an_assigned_duty():
    """The two rules compose, and the order matters: the placeholder becomes None
    first, so ADR-033's requirement that an ASSIGNED obligation name its office
    sees no actor and refuses. Without the coercion, "null" would pass as a name."""
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="Monitors and evaluates the program.",
            modality=Modality.ASSIGNED,
            actor="null",
            deadline=None,
            conditions=None,
            confidence=0.9,
        )


# --- ADR-035: an actor is validated before it is canonicalised ----------------


def test_a_word_modality_actor_must_occur_in_its_statement():
    """ADR-035. The prompt says the actor is "copied from the statement", and
    measured on the live graph 2026-08-28, 14 of 123 word-modality actors were
    not there — including `"the passage"` against a statement lifted from the
    extraction prompt itself."""
    item = {
        "statement": "The Director shall notify the Comptroller.",
        "modality": "SHALL",
        "actor": "The Director",
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }
    assert validate_extracted(item, section_title=None)

    with pytest.raises(ValueError):
        validate_extracted({**item, "actor": "the passage"}, section_title=None)


def test_an_actor_is_matched_on_whole_words_not_substrings():
    """`gers` is a substring of "managers" and is not an actor. It was in the
    live graph, alongside `e systems` — both truncation artefacts."""
    item = {
        "statement": "Acquisition managers shall balance cost against capability.",
        "modality": "SHALL",
        "actor": "gers",
        "deadline": None,
        "conditions": None,
        "confidence": 0.9,
    }
    with pytest.raises(ValueError):
        validate_extracted(item, section_title=None)


def test_an_actor_ending_in_punctuation_is_still_found():
    """A naive word-boundary regex fails on a trailing bracket, which is how the
    first measurement of this rule overstated the violation rate by half:
    `The USD(AT&L)` is present verbatim and `\\b` does not match after `)`."""
    for actor in ("The USD(AT&L)", "The DoD Component(s)"):
        assert validate_extracted(
            {
                "statement": f"{actor} shall establish training requirements.",
                "modality": "SHALL",
                "actor": actor,
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            },
            section_title=None,
        )


def test_an_assigned_actor_is_exempt_because_it_comes_from_the_heading():
    """ADR-033 takes an ASSIGNED obligation's office from the role heading above
    the item, so its absence from the statement is the correct state — 31 of 31
    such obligations in the graph are correctly absent. Exempt by construction:
    the rule is about actors copied from a statement, and this one is not."""
    assert validate_extracted(
        {
            "statement": "Executes the acquisition responsibilities in DoDD 5135.02.",
            "modality": "ASSIGNED",
            "actor": "USD(A&S)",
            "deadline": None,
            "conditions": None,
            "confidence": 0.9,
        },
        section_title="RESPONSIBILITIES",
    )
