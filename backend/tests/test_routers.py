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
