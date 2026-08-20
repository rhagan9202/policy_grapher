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
def test_a_valid_token_is_admitted(client_with_auth):
    response = client_with_auth.post("/query", json={"cypher": "RETURN 1 AS n"})
    assert response.status_code == 200
    assert response.json()["rows"] == [{"n": 1}]
