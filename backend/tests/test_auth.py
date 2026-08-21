import pytest

from policy_grapher import auth
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


def test_a_non_ascii_digest_does_not_take_down_the_entries_after_it():
    """ADR-008 Decision 3: one bad line must not disable every valid token.

    `hmac.compare_digest` raises TypeError on a non-ASCII string, which aborted the
    loop before a later valid entry was reached and surfaced as a 500 on every
    protected route — authentication down, not bypassed, but down.
    """
    configured = f"bad:\u00e9,alice:{token_digest('a')}"
    assert verify_token("a", configured) == Principal(name="alice")


def test_a_digest_that_is_not_sixty_four_hex_characters_is_skipped():
    """The shape check is on configured data only, never on the presented token."""
    configured = f"truncated:abc123,alice:{token_digest('a')}"
    assert verify_token("a", configured) == Principal(name="alice")
    assert verify_token("abc123", configured) is None


def test_every_entry_is_compared_even_after_a_match(monkeypatch):
    """Exhaustive scan: verify_token must not stop comparing once it finds a match.

    If it did, response timing would reveal how many entries were configured before
    the match landed. A counting wrapper around hmac.compare_digest catches that
    regression even though it changes no return value the other tests check — the
    match here is deliberately the *first* entry, so a short-circuiting
    implementation would still pass every other test in this file.
    """
    real_compare_digest = auth.hmac.compare_digest
    calls = []

    def counting_compare_digest(a, b):
        calls.append((a, b))
        return real_compare_digest(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", counting_compare_digest)

    configured = f"alice:{token_digest('a')},bob:{token_digest('b')}"
    assert verify_token("a", configured) == Principal(name="alice")
    assert len(calls) == 2


PROTECTED = [
    ("post", "/ingest", {"filename": "x.csv"}),
    ("post", "/reset", None),
    ("post", "/query", {"cypher": "RETURN 1"}),
    ("post", "/documents", {"name": "X"}),
    ("delete", "/documents/some-slug", None),
    ("get", "/graph", None),
    ("get", "/documents", None),
    ("get", "/documents/some-slug", None),
    ("post", "/documents/some-slug/references/other-slug", None),
    ("delete", "/documents/some-slug/references/other-slug", None),
    ("get", "/review/queue", None),
    ("post", "/review/some-id/other-id", {"verdict": "approve"}),
]


@pytest.mark.integration
@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_routes_reject_an_unauthenticated_caller(
    client_with_graph, method, path, body
):
    response = getattr(client_with_graph, method)(
        path, **({"json": body} if body is not None else {})
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_health_stays_open(client_with_graph):
    """/health must not require a token — it is what the container healthcheck calls."""
    assert client_with_graph.get("/health").status_code == 200


@pytest.mark.integration
def test_a_well_formed_but_unknown_token_is_rejected(client_with_auth):
    """Every PROTECTED case above sends *no* header, so all of them stop at the
    missing-credential 401 and none reaches the `verify_token` -> None branch. Without
    this test that branch could be deleted and the suite would stay green while the
    API admitted any well-formed bearer string.
    """
    response = client_with_auth.get("/graph", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
def test_a_non_bearer_scheme_is_rejected(client_with_auth):
    response = client_with_auth.get("/graph", headers={"Authorization": "Basic abc"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
def test_a_missing_credential_challenges_for_bearer(client_with_graph):
    """ADR-008 Decision 5: the 401 says what would satisfy it."""
    response = client_with_graph.get("/graph")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
def test_a_valid_token_is_admitted(client_with_auth):
    response = client_with_auth.post("/query", json={"cypher": "RETURN 1 AS n"})
    assert response.status_code == 200
    assert response.json()["rows"] == [{"n": 1}]
