import re

import pytest

from policy_grapher import auth, main
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


# Routes that are deliberately open. Adding to this set is a security decision and
# should be argued for in review — everything not named here must require a
# principal, and the test below enumerates the app to find out.
OPEN_ROUTES = frozenset({"/health"})

PLACEHOLDER = re.compile(r"\{[^}]+\}")


def _iter_routes(routes):
    """Every (path, methods) the app actually serves.

    Walks nested routers rather than reading `app.routes` directly: this FastAPI
    keeps included routers lazy (`_IncludedRouter`) until startup, so the top
    level yields four opaque objects and none of the fifteen real routes. Both
    the lazy wrapper's `original_router` and a plain nested `.routes` are
    followed, so the walk survives a FastAPI that changes its mind about which
    it uses.
    """
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _iter_routes(original.routes)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            yield from _iter_routes(nested)
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            yield path, frozenset(methods)


def _discovered_routes() -> list[tuple[str, str]]:
    found = set()
    for path, methods in _iter_routes(main.app.routes):
        for method in methods - {"HEAD", "OPTIONS"}:
            found.add((method.lower(), path))
    return sorted(found)


PROTECTED = [
    (method, path) for method, path in _discovered_routes() if path not in OPEN_ROUTES
]


def test_the_route_enumeration_actually_found_the_routes():
    """The guard on the guard. A walker that silently returned nothing would make
    the property test below vacuously green — no parameters, no failures, and
    every route in the application unprotected without a word from the suite."""
    discovered = _discovered_routes()
    paths = {path for _, path in discovered}

    assert len(discovered) >= 15, discovered
    assert "/health" in paths, "the walk missed a route known to exist"
    assert "/review/queue" in paths, "the walk missed the most recently added router"
    assert len(PROTECTED) == len(discovered) - 1, (
        "exactly one route is expected to be open; OPEN_ROUTES says otherwise"
    )


@pytest.mark.integration
@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_route_but_health_requires_a_principal(client_with_graph, method, path):
    """Enumerated from the application rather than listed by hand.

    The hand-maintained list this replaces had drifted: `/documents/{slug}/chunks`
    and `/documents/{slug}/versions` shipped in phase 2 and were never added to
    it, so nothing checked that either required a token. A list only covers the
    routes somebody remembered, and the one that gets forgotten is by definition
    the one nobody is thinking about.

    A body is sent on every request because FastAPI resolves dependencies before
    it validates the body: a route that rejects the caller returns 401 whatever
    the body is, and one that does not returns 422 and fails this test loudly
    rather than passing for the wrong reason.
    """
    response = client_with_graph.request(
        method, PLACEHOLDER.sub("placeholder", path), json={}
    )
    assert response.status_code == 401, (
        f"{method.upper()} {path} answered {response.status_code} to an "
        f"unauthenticated caller. Every route but {sorted(OPEN_ROUTES)} must "
        f"require a principal."
    )


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
