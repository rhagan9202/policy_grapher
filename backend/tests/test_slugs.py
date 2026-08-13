import hashlib

from policy_grapher.slugs import assign_slugs, base_slug, hash_suffix

MIL_A = "Military Standard 882E"
MIL_B = "Military-Standard 882E"
ASD_A = (
    "Assistant Secretary of Defense for Networks and Information Integration/"
    "DoD Chief Information Officer"
)
ASD_B = ASD_A + " Memorandum"


def test_base_slug_lowercases_and_hyphenates():
    assert base_slug("DoDD 5000.01") == "dodd-5000-01"


def test_base_slug_collapses_runs_of_punctuation_and_trims():
    assert base_slug("United States Code, Title 44, Section 3554") == (
        "united-states-code-title-44-section-3554"
    )
    assert base_slug("  ...Policy A!!!  ") == "policy-a"


def test_base_slug_handles_slashes_and_parentheses():
    assert base_slug("NATO Document AC/92(ATMCNS)D(2020)0002") == (
        "nato-document-ac-92-atmcns-d-2020-0002"
    )


def test_base_slug_truncates_to_eighty_characters_without_trailing_hyphen():
    slug = base_slug("A" * 40 + " " + "B" * 60)
    assert len(slug) <= 80
    assert not slug.endswith("-")


def test_base_slug_of_an_unsluggable_name_falls_back():
    assert base_slug("///") == "document"


def test_hash_suffix_is_first_eight_hex_of_sha256():
    expected = hashlib.sha256(MIL_A.encode("utf-8")).hexdigest()[:8]
    assert hash_suffix(MIL_A) == expected
    assert len(hash_suffix(MIL_A)) == 8


def test_uncontested_names_keep_the_bare_slug():
    assert assign_slugs(["DoDD 5000.01"]) == {"DoDD 5000.01": "dodd-5000-01"}


def test_every_contender_for_a_contested_slug_is_suffixed():
    """Not just the second arrival — otherwise slugs depend on ingest order."""
    slugs = assign_slugs([MIL_A, MIL_B])
    assert slugs[MIL_A] == f"military-standard-882e-{hash_suffix(MIL_A)}"
    assert slugs[MIL_B] == f"military-standard-882e-{hash_suffix(MIL_B)}"
    assert slugs[MIL_A] != slugs[MIL_B]


def test_assignment_is_independent_of_input_order():
    forward = assign_slugs([MIL_A, MIL_B, "DoDD 5000.01"])
    reverse = assign_slugs(["DoDD 5000.01", MIL_B, MIL_A])
    assert forward == reverse


def test_collision_caused_by_truncation_is_resolved():
    """ASD_A and ASD_B diverge at character 101, so they share a truncated base."""
    assert base_slug(ASD_A) == base_slug(ASD_B)
    slugs = assign_slugs([ASD_A, ASD_B])
    assert slugs[ASD_A] != slugs[ASD_B]
    assert len(set(slugs.values())) == 2


def test_duplicate_names_in_the_input_collapse_to_one_entry():
    assert assign_slugs([MIL_A, MIL_A]) == {MIL_A: "military-standard-882e"}


def test_slugs_are_unique_across_a_contested_and_uncontested_mix():
    names = [MIL_A, MIL_B, ASD_A, ASD_B, "DoDD 5000.01"]
    slugs = assign_slugs(names)
    assert len(set(slugs.values())) == len(names)
