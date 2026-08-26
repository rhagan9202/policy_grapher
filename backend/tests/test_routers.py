"""The refactor must not move any route or change any status code."""

import pytest

from policy_grapher.auth import require_principal
from policy_grapher.main import app

EXPECTED_ROUTES = {
    ("/health", "GET"),
    ("/ingest", "POST"),
    ("/graph", "GET"),
}


def _flatten_routes(routes):
    """Yield leaf routes, resolving lazily-included routers.

    FastAPI >=0.141 wraps `include_router()` targets in a private
    `_IncludedRouter` that defers flattening until `effective_candidates()`
    is called, so a plain walk of `app.routes` no longer exposes the
    `.methods` of routes registered through a router. Recursing through
    `effective_candidates()` when present keeps this working there while
    staying a no-op (falls through to the route itself) on older FastAPI
    versions that flatten eagerly.
    """
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            yield from _flatten_routes(candidates())
        else:
            yield route


def registered_routes() -> set[tuple[str, str]]:
    found = set()
    for route in _flatten_routes(app.routes):
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            found.add((route.path, method))
    return found


def test_every_expected_route_is_registered():
    assert EXPECTED_ROUTES <= registered_routes()


# The single exception to "every route requires a principal": /health is what the
# compose healthcheck calls, and it discloses nothing. See ADR-008's amendment.
OPEN = {("/health", "GET")}


def test_every_route_but_health_requires_a_principal():
    """The policy itself, not a list of today's routes.

    `test_auth.py`'s PROTECTED enumerates the ten routes that exist now, so a route
    added later with the dependency forgotten would leave the suite green. This walks
    the registered routes instead, so the next route arrives already covered.
    """
    for route in _flatten_routes(app.routes):
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            # Not a FastAPI route with a dependency tree — a mount, or the OpenAPI
            # routes if ENABLE_API_DOCS turns them on.
            continue
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            if (route.path, method) in OPEN:
                continue
            assert any(
                dependency.call is require_principal
                for dependency in dependant.dependencies
            ), (route.path, method)


def test_the_openapi_routes_are_not_published_by_default():
    """`/openapi.json`, `/docs` and `/redoc` carry no dependencies of their own.

    Publishing them would falsify the claim above in the way that matters to a
    reader: an unauthenticated caller could enumerate every route. They are off
    unless ENABLE_API_DOCS opts back in.
    """
    paths = {route.path for route in _flatten_routes(app.routes)}
    assert paths.isdisjoint({"/openapi.json", "/docs", "/redoc"})


def test_no_route_is_registered_twice():
    paths = [
        (route.path, method)
        for route in _flatten_routes(app.routes)
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
    ]
    assert len(paths) == len(set(paths))


@pytest.mark.integration
def test_health_still_serves_through_the_router(client_with_graph):
    response = client_with_graph.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- STORY-086: the browser can reach what the server declares -----------------

import re
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "client.ts"

# `POST /query` is declared unreachable on purpose.
# ADR-008 superseded ADR-001 precisely to stop assuming the audience writes
# Cypher, so putting a query box in front of them argues against a decision this
# project has already taken once. STORY-045 parks it in Ideas for the same reason.
DELIBERATELY_UNREACHABLE = {"/query"}

# `/health` is covered rather than exempt: `getHealth` models it, and the compose
# healthcheck calling it is not a reason for the browser not to.
PATH_PARAMETER = re.compile(r"\{[^}]*\}")
INTERPOLATION = re.compile(r"\$\{[^}]*\}")
CLIENT_PATH = re.compile(r"""['"`](/[^'"`]*)['"`]""")


def _cut_at_suffix_interpolation(path: str) -> str:
    """Drop a trailing `${...}` that is appending a query string, not a segment.

    The client writes both shapes. `/documents/${slug}/chunks` interpolates a path
    *parameter* — it follows a slash and a real segment continues after it.
    `/review/queue${query}` and `/graph${query ? `?${query}` : ''}` interpolate a
    query string onto a complete path, and the second nests a template literal
    inside the first, which no flat quote-to-quote capture survives.

    A `${` that does not follow `/` therefore ends the path, and cutting there
    handles both without parsing TypeScript.
    """
    at = 0
    while True:
        found = path.find("${", at)
        if found == -1:
            return path
        if found > 0 and path[found - 1] == "/":
            at = found + 2
            continue
        return path[:found]


def _normalise(path: str) -> str:
    """One shape for both sides: parameters collapse, query strings drop."""
    path = _cut_at_suffix_interpolation(path)
    path = INTERPOLATION.sub("{}", path)
    path = PATH_PARAMETER.sub("{}", path)
    return path.split("?", 1)[0].rstrip("/") or "/"


def _paths_the_client_models() -> set[str]:
    source = CLIENT.read_text(encoding="utf-8")
    return {_normalise(found) for found in CLIENT_PATH.findall(source)}


def test_the_browser_can_reach_every_route_the_server_declares():
    """Sprint 5's retrospective made this its number-one change, and it was
    written into `architecture.md` as prose and never automated.

    Its Definition of Done had said "no client function in `api/client.ts` is left
    without a caller". That check passes trivially against a route the client never
    modelled at all — which is exactly the state sprint 4's rebuild routes were in,
    and `GET /documents/{slug}/chunks` before them. The claim was about *backend
    capability being reachable*; the check was about *client functions being
    called*. A capability can therefore ship complete on the server and be invisible
    to the only audience ADR-008 says this product has.

    This compares paths rather than path-and-method, deliberately and with a cost.
    `listChunks` builds its path into a local before calling `request`, so a
    method-accurate parse would have to follow assignments, and a parser that
    silently failed to resolve one would produce exactly the false green this test
    exists to prevent. A path the client has never heard of is the defect that has
    actually occurred here, twice.
    """
    declared = {
        _normalise(path)
        for path, _method in registered_routes()
    } - DELIBERATELY_UNREACHABLE

    unreachable = sorted(declared - _paths_the_client_models())

    assert not unreachable, (
        f"the browser cannot reach {len(unreachable)} route(s) the server "
        f"declares: {unreachable}. Add a client function in {CLIENT.name}, or — if "
        f"the route is deliberately not for the browser — record it in "
        f"DELIBERATELY_UNREACHABLE with the decision that parked it."
    )


def test_the_parked_route_is_still_parked_on_purpose():
    """A blanket exception list rots into a place to hide failures.

    This asserts the one entry is the one ADR-008 argued for, so adding a second
    has to be a deliberate edit to a test that says why the first is there.
    """
    assert DELIBERATELY_UNREACHABLE == {"/query"}
    assert "/query" in {_normalise(p) for p, _ in registered_routes()}
