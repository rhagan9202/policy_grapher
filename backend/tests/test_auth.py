from policy_grapher.auth import Principal, token_digest, verify_token


def test_a_valid_token_resolves_to_its_principal():
    configured = f"alice:{token_digest('s3cret')}"
    assert verify_token("s3cret", configured) == Principal(name="alice")


def test_an_unknown_token_resolves_to_nobody():
    configured = f"alice:{token_digest('s3cret')}"
    assert verify_token("wrong", configured) is None


def test_an_empty_configuration_admits_nobody():
    """Fail closed: no configured tokens must not mean no authentication."""
    assert verify_token("anything", "") is None


def test_several_principals_can_be_configured():
    configured = f"alice:{token_digest('a')},bob:{token_digest('b')}"
    assert verify_token("b", configured) == Principal(name="bob")


def test_a_malformed_entry_is_ignored_rather_than_crashing():
    configured = f"garbage,alice:{token_digest('a')}"
    assert verify_token("a", configured) == Principal(name="alice")
