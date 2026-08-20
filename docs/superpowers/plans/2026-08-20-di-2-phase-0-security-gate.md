# DI-2 Phase 0: Security Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three security holes that gate every later DI-2 phase — unrestricted Cypher, no authentication, and a publicly committed database password.

**Architecture:** `POST /query` becomes read-only, time-bounded and row-capped, reporting truncation the way `GET /graph` already does. A bearer-token dependency supplies a `Principal` to every request, behind a single verifier function so an OIDC provider can replace it later without touching call sites. The committed `.env` is replaced by a generated one.

**Tech Stack:** FastAPI, Pydantic v2, pydantic-settings, neo4j Python driver 6.x, pytest + testcontainers, React 19 + TypeScript (client types only).

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Phase 0 — the security gate*.

## Global Constraints

- Python `>=3.14`; dependencies managed by `uv`. Add nothing to `pyproject.toml` that is not used by code in this plan.
- Ruff is enforced **as a test** (`tests/test_lint.py`). A lint failure is a test failure.
- Frontend `npm test` runs `eslint . --max-warnings=0 && tsc -b && vitest run`, each gating the next.
- Integration tests run against a real `neo4j:2025.10` via testcontainers. Do not mock the driver.
- Every relationship type is directed `SCREAMING_SNAKE_CASE`, read source → target ([ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)).
- IDs are permanent. Never renumber a STORY or ADR.
- Definition of Done includes documentation updated **in the same change**, and a clean-checkout `docker compose up` working.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/config.py` | *Modify* — add query limits, API tokens, CORS origins |
| `backend/src/policy_grapher/models.py` | *Modify* — add `QueryResult` |
| `backend/src/policy_grapher/query.py` | *Modify* — read-only routing, timeout, row cap |
| `backend/src/policy_grapher/auth.py` | *Create* — `Principal`, token hashing, `require_principal` |
| `backend/src/policy_grapher/routers/graph.py` | *Modify* — return `QueryResult`, require a principal |
| `backend/src/policy_grapher/routers/admin.py` | *Modify* — require a principal on `/ingest` and `/reset` |
| `backend/src/policy_grapher/routers/documents.py` | *Modify* — require a principal on mutating routes |
| `backend/src/policy_grapher/main.py` | *Modify* — CORS from settings |
| `backend/tests/test_query.py` | *Modify* — read-only, timeout, row-cap tests |
| `backend/tests/test_auth.py` | *Create* — token verification and route protection |
| `frontend/src/api/types.ts` | *Modify* — `QueryResult` |
| `frontend/src/api/client.ts` | *Modify* — `runQuery` return type |
| `scripts/init-env.sh` | *Create* — generate `.env` with a random password |
| `docs/specs/adr/ADR-008-*.md`, `ADR-009-*.md`, `ADR-010-*.md` | *Create* — folded into the tasks that make each decision |

---

### Task 1: Constrain `POST /query`

Closes STORY-024. Supersedes [ADR-004](../../specs/adr/ADR-004-unrestricted-cypher-in-di-1.md).

**Files:**
- Modify: `backend/src/policy_grapher/config.py`
- Modify: `backend/src/policy_grapher/models.py`
- Modify: `backend/src/policy_grapher/query.py`
- Modify: `backend/src/policy_grapher/routers/graph.py`
- Modify: `backend/tests/test_query.py`
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`
- Create: `docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md`

**Interfaces:**
- Consumes: `coerce(value) -> JSONValue` (unchanged, already in `query.py`)
- Produces: `run_cypher(driver, database, cypher, *, row_cap: int, timeout_seconds: float) -> QueryResult`, and `QueryResult(rows: list[dict[str, JSONValue]], returned_rows: int, truncated: bool)`

- [ ] **Step 1: Write the failing read-only test**

Add to `backend/tests/test_query.py`:

```python
@pytest.mark.integration
def test_a_write_query_is_rejected_and_changes_nothing(client_with_graph):
    """ADR-009: /query is read-only. The invariant is the graph, not the error string."""
    before = client_with_graph.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]

    response = client_with_graph.post(
        "/query", json={"cypher": "CREATE (:Document {slug: 'x', name: 'X'})"}
    )
    assert response.status_code == 400

    after = client_with_graph.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]
    assert after == before
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && uv run pytest tests/test_query.py::test_a_write_query_is_rejected_and_changes_nothing -v`
Expected: FAIL — the response body is currently a bare list, so `["rows"]` raises `TypeError`.

- [ ] **Step 3: Add the settings**

In `backend/src/policy_grapher/config.py`, inside `Settings`, after `graph_render_cap`:

```python
    query_row_cap: int = 1000
    query_timeout_seconds: float = 10.0
```

- [ ] **Step 4: Add the response model**

In `backend/src/policy_grapher/models.py`, after `GraphOut`:

```python
class QueryResult(BaseModel):
    rows: list[dict[str, JSONValue]]
    returned_rows: int
    truncated: bool
```

`JSONValue` must move for this to work. `query.py` is about to import `QueryResult` from
`models.py`, so `models.py` importing `JSONValue` back from `query.py` is circular — move the
alias rather than trying both directions:

Cut these three lines out of `query.py` and paste them into `models.py` above `QueryResult`:

```python
type JSONScalar = str | int | float | bool
type JSONValue = JSONScalar | None | list[JSONValue] | dict[str, JSONValue]

JSON_SCALARS = (str, int, float, bool)
```

Then in `query.py` add `from policy_grapher.models import JSONValue, JSON_SCALARS, QueryResult`.
Anything else importing `JSONValue` from `policy_grapher.query` — `routers/graph.py` does —
must import it from `policy_grapher.models` instead. Dependency runs one way: models knows
nothing about query.

- [ ] **Step 5: Make `run_cypher` read-only, bounded, and capped**

Replace the module docstring and `run_cypher` in `backend/src/policy_grapher/query.py`:

```python
"""Read-only Cypher passthrough.

Read routing, a transaction timeout and a row cap, per ADR-009. Mutation moved to
authenticated routes when ADR-004's local-only assumption stopped holding.
"""
```

```python
def run_cypher(
    driver: Driver,
    database: str,
    cypher: str,
    *,
    row_cap: int,
    timeout_seconds: float,
) -> QueryResult:
    # READ routing: Neo4j rejects a write attempted in a read transaction, so the
    # enforcement is the database's, not a regex over the query text.
    result: EagerResult = driver.execute_query(
        Query(cast(LiteralString, cypher), timeout=timeout_seconds),
        database_=database,
        routing_=RoutingControl.READ,
    )
    rows = [
        {
            key: coerce(value)
            for key, value in cast(Mapping[str, Any], record).items()
        }
        for record in result.records
    ]
    truncated = len(rows) > row_cap
    # Truncation is reported, never silent — the failure mode SPEC-001 names.
    return QueryResult(
        rows=rows[:row_cap], returned_rows=min(len(rows), row_cap), truncated=truncated
    )
```

Add `from policy_grapher.models import QueryResult` to the imports.

- [ ] **Step 6: Update the router**

In `backend/src/policy_grapher/routers/graph.py`, replace the `query` handler:

```python
@router.post("/query", response_model=QueryResult)
def query(
    body: QueryRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> QueryResult:
    try:
        return run_cypher(
            driver,
            settings.neo4j_database,
            body.cypher,
            row_cap=settings.query_row_cap,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Update the imports: `from policy_grapher.models import GraphOut, QueryRequest, QueryResult`
and drop `JSONValue` from the `policy_grapher.query` import if it is now unused.

- [ ] **Step 7: Run the read-only test to verify it passes**

Run: `cd backend && uv run pytest tests/test_query.py::test_a_write_query_is_rejected_and_changes_nothing -v`
Expected: PASS

- [ ] **Step 8: Write the row-cap test**

Add to `backend/tests/test_query.py`:

```python
@pytest.mark.integration
def test_the_row_cap_truncates_and_says_so(client_with_graph, monkeypatch):
    monkeypatch.setattr(client_with_graph.app.state.settings, "query_row_cap", 3)

    response = client_with_graph.post(
        "/query", json={"cypher": "UNWIND range(1, 10) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is True
    assert len(body["rows"]) == 3


@pytest.mark.integration
def test_a_result_under_the_cap_is_not_reported_as_truncated(client_with_graph):
    response = client_with_graph.post(
        "/query", json={"cypher": "UNWIND range(1, 3) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is False
```

- [ ] **Step 9: Run the whole query suite**

Run: `cd backend && uv run pytest tests/test_query.py -v`
Expected: PASS. The existing `coerce` unit tests must still pass untouched — if any
integration test still indexes the response as a list, update it to read `["rows"]`.

- [ ] **Step 10: Update the frontend client**

In `frontend/src/api/types.ts`:

```ts
export interface QueryResult {
  rows: Record<string, unknown>[]
  returned_rows: number
  truncated: boolean
}
```

In `frontend/src/api/client.ts`:

```ts
export function runQuery(cypher: string): Promise<QueryResult> {
  return request<QueryResult>('/query', {
    method: 'POST',
    body: JSON.stringify({ cypher }),
  })
}
```

Add `QueryResult` to the `types` import at the top of `client.ts`. Update the `runQuery`
case in `frontend/src/api/client.test.ts` so its mocked response is
`{ rows: [], returned_rows: 0, truncated: false }` and it asserts on `.rows`.

- [ ] **Step 11: Run the frontend suite**

Run: `cd frontend && npm install && npm test`
Expected: PASS (eslint, then `tsc -b`, then vitest).

- [ ] **Step 12: Write ADR-009**

Create `docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md` from
`docs/specs/adr/TEMPLATE-adr.md`. It must state: the decision (read routing, transaction
timeout, deterministic row cap with truncation reported); that it supersedes ADR-004 because
ADR-004's own three conditions — local-only, disposable data, trusted Cypher-fluent audience —
stop holding once DI-2 targets a hosted deployment; and that mutation moves to authenticated
routes rather than disappearing. Add the amendment banner to ADR-004 pointing at ADR-009,
following how [ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md) amends ADR-002.

- [ ] **Step 13: Run the full backend suite and commit**

Run: `cd backend && uv run pytest`
Expected: PASS (integration tests need Docker running).

```bash
git add backend/src/policy_grapher/config.py backend/src/policy_grapher/models.py \
        backend/src/policy_grapher/query.py backend/src/policy_grapher/routers/graph.py \
        backend/tests/test_query.py frontend/src/api/types.ts frontend/src/api/client.ts \
        frontend/src/api/client.test.ts docs/specs/adr/ADR-009-query-is-read-only-and-bounded.md \
        docs/specs/adr/ADR-004-unrestricted-cypher-in-di-1.md
git commit -m "feat: STORY-024 — /query is read-only, time-bounded and row-capped"
```

---

### Task 2: Bearer-token authentication

Closes STORY-019. Supersedes [ADR-001](../../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md).

**Design decision an executor must not silently change:** tokens are opaque bearer strings,
compared by SHA-256 digest with `hmac.compare_digest`, configured as `name:digest` pairs.
Verification is isolated in `verify_token` so an OIDC/JWT verifier can replace that one function
without touching any call site. This is deliberately not OIDC yet — DI-2 needs *identity for the
`actor` field*, not a full identity provider, and choosing one now would be a guess.

**Files:**
- Create: `backend/src/policy_grapher/auth.py`
- Create: `backend/tests/test_auth.py`
- Modify: `backend/src/policy_grapher/config.py`
- Create: `docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md`

**Interfaces:**
- Consumes: `Settings` from `policy_grapher.config`, `get_app_settings` from `policy_grapher.dependencies`
- Produces: `Principal(name: str)`, `token_digest(token: str) -> str`, `verify_token(token: str, configured: str) -> Principal | None`, and the FastAPI dependency `require_principal(...) -> Principal`

- [ ] **Step 1: Write the failing unit tests**

Create `backend/tests/test_auth.py`:

```python
import pytest

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
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policy_grapher.auth'`

- [ ] **Step 3: Write the auth module**

Create `backend/src/policy_grapher/auth.py`:

```python
"""Bearer-token authentication.

Per ADR-008 the audience is no longer assumed Cypher-fluent or trusted, so every
mutating route needs a principal. Token verification is deliberately one function:
replacing it with an OIDC verifier should not touch a single call site.
"""

import hashlib
import hmac

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings


class Principal(BaseModel):
    """Who is making the request. Recorded as the actor on any decision they take."""

    name: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, configured: str) -> Principal | None:
    """Resolve a bearer token to a principal, or None.

    `configured` is `name:digest` pairs, comma-separated. Comparison is constant-time
    so a timing signal cannot enumerate valid tokens. Every entry is checked even
    after a match, for the same reason.
    """
    presented = token_digest(token)
    found: Principal | None = None
    for entry in configured.split(","):
        name, separator, digest = entry.partition(":")
        if not separator:
            continue
        if hmac.compare_digest(digest.strip(), presented) and found is None:
            found = Principal(name=name.strip())
    return found


def require_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_app_settings),
) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = verify_token(token, settings.api_tokens)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal
```

- [ ] **Step 4: Add the setting**

In `backend/src/policy_grapher/config.py`, inside `Settings`, after `query_timeout_seconds`:

```python
    # "name:sha256hex" pairs, comma-separated. Empty means nobody can authenticate.
    api_tokens: str = ""
```

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Write ADR-008 and commit**

Create `docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md` from the template. It must
state: the decision (bearer tokens, hashed at rest, constant-time comparison, one replaceable
verifier); that it supersedes ADR-001 because that ADR names LLM query construction as its own
revisit trigger and DI-2 is that work; and that choosing bearer tokens over OIDC now is a
deliberate deferral, not an oversight — DI-2 needs an `actor`, not an identity provider. Add the
amendment banner to ADR-001.

```bash
git add backend/src/policy_grapher/auth.py backend/src/policy_grapher/config.py \
        backend/tests/test_auth.py \
        docs/specs/adr/ADR-008-authenticated-non-cypher-audience.md \
        docs/specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md
git commit -m "feat: STORY-019 — bearer-token authentication and principals"
```

---

### Task 3: Protect the routes and lock down CORS

**Files:**
- Modify: `backend/src/policy_grapher/routers/admin.py`, `routers/documents.py`, `routers/graph.py`
- Modify: `backend/src/policy_grapher/main.py`, `config.py`
- Modify: `backend/tests/test_auth.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `require_principal` and `Principal` from `policy_grapher.auth` (Task 2)
- Produces: an authenticated test client fixture, `client_with_auth`, for later phases to reuse

- [ ] **Step 1: Write the failing route-protection test**

Add to `backend/tests/test_auth.py`:

```python
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
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && uv run pytest tests/test_auth.py -k unauthenticated -v`
Expected: FAIL — the routes currently return 200/400/404, never 401.

- [ ] **Step 3: Protect the routes**

In each of `routers/admin.py`, `routers/documents.py`, `routers/graph.py`, add the import:

```python
from policy_grapher.auth import Principal, require_principal
```

Then add this parameter to every handler except `health`:

```python
    principal: Principal = Depends(require_principal),
```

`GET /health` stays open — the compose healthcheck calls it and it touches no database.
`GET /graph` and `GET /documents` are also protected: the corpus itself is the asset.

- [ ] **Step 4: Add an authenticated fixture**

In `backend/tests/conftest.py`, after `client_with_graph`:

```python
TEST_TOKEN = "test-token"


@pytest.fixture
def client_with_auth(client_with_graph):
    """A client that presents a valid bearer token on every request."""
    from policy_grapher.auth import token_digest

    client_with_graph.app.state.settings.api_tokens = f"tester:{token_digest(TEST_TOKEN)}"
    client_with_graph.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
    return client_with_graph
```

- [ ] **Step 5: Write the authenticated-access test**

Add to `backend/tests/test_auth.py`:

```python
@pytest.mark.integration
def test_a_valid_token_is_admitted(client_with_auth):
    response = client_with_auth.post("/query", json={"cypher": "RETURN 1 AS n"})
    assert response.status_code == 200
    assert response.json()["rows"] == [{"n": 1}]
```

- [ ] **Step 6: Run the auth suite**

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 7: Repair the rest of the suite**

Every existing integration test that calls a now-protected route needs the authenticated
client. `tests/test_query.py` (including the tests Task 1 added) and `tests/test_di1_complete.py`
are known to need it; others will surface. Run the full suite, then change each failing test's
fixture from `client_with_graph` to `client_with_auth`:

Run: `cd backend && uv run pytest`
Expected: initially many 401 failures; after the fixture swap, PASS.

- [ ] **Step 8: Lock down CORS**

In `config.py`, inside `Settings`:

```python
    # Comma-separated origins. Empty means no cross-origin browser access.
    cors_allow_origins: str = "http://localhost:5173"
```

In `main.py`, replace the CORS middleware block:

```python
_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Read settings via `get_settings()`, which `main.py` already imports — **not**
`app.state.settings`. Middleware is registered at import time; `app.state.settings` is
populated inside `lifespan`, which runs later, so reading `app.state` here raises
`AttributeError` on import. Add above the `app.add_middleware` call:

```python
settings = get_settings()
```

- [ ] **Step 9: Pass the new settings through docker compose**

`docker-compose.yml` enumerates every environment variable explicitly rather than using
`env_file`, so a setting absent from that list never reaches the container. Without this the
stack starts with `api_tokens=""`, fails closed, and returns 401 on every route — which reads
as a broken app rather than a misconfigured one.

In `docker-compose.yml`, under `services.backend.environment`, after `AUTO_INGEST`:

```yaml
      API_TOKENS: ${API_TOKENS}
      CORS_ALLOW_ORIGINS: ${CORS_ALLOW_ORIGINS}
      QUERY_ROW_CAP: ${QUERY_ROW_CAP}
      QUERY_TIMEOUT_SECONDS: ${QUERY_TIMEOUT_SECONDS}
```

Task 1's two settings are included because compose passes an allow-list, so they are unreachable
from `.env` today too. Only `API_TOKENS` is load-bearing — its `""` default fails closed — but an
operator who cannot tune the other three from `.env` will reasonably conclude they are broken.

Add all four to the repository's `.env` as well, so the stack still runs before Task 4 replaces
that file: `API_TOKENS=` may be empty for now, `CORS_ALLOW_ORIGINS=http://localhost:5173`,
`QUERY_ROW_CAP=1000`, `QUERY_TIMEOUT_SECONDS=10.0`.

- [ ] **Step 10: Run everything and commit**

Run: `cd backend && uv run pytest` and `cd ../frontend && npm test`
Expected: PASS

```bash
git add backend/src/policy_grapher backend/tests docker-compose.yml .env
git commit -m "feat: every route but /health requires a principal; CORS is configured"
```

---

### Task 4: Secrets out of the committed `.env`

**Files:**
- Create: `scripts/init-env.sh`
- Create: `.env.example`
- Modify: `.gitignore`, `README.md`, `docker-compose.yml`
- Create: `docs/specs/adr/ADR-010-secrets-leave-the-repository.md`
- Delete from tracking: `.env`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `.env` generated locally; `API_TOKENS` populated with one principal so a fresh clone can authenticate

- [ ] **Step 1: Write the generator**

Create `scripts/init-env.sh`:

```bash
#!/usr/bin/env bash
# Generate a local .env with random secrets. Safe to re-run: refuses to overwrite.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/.env"

if [ -e "$target" ]; then
  echo "$target already exists — delete it first if you want fresh secrets." >&2
  exit 1
fi

password="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
token="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
digest="$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)"

sed -e "s|__NEO4J_PASSWORD__|$password|g" -e "s|__API_TOKENS__|dev:$digest|g" \
    "$root/.env.example" > "$target"

echo "Wrote $target"
echo "Your API token (not stored anywhere else — save it now): $token"
```

Then `chmod +x scripts/init-env.sh`.

- [ ] **Step 2: Write the template**

Create `.env.example` — the committed `.env`'s contents with the two secrets replaced by
placeholders and `NEO4J_AUTH` using the same password:

```
NEO4J_AUTH=neo4j/__NEO4J_PASSWORD__
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=__NEO4J_PASSWORD__
NEO4J_DATABASE=neo4j
DATA_DIR=/data/samples
GRAPH_RENDER_CAP=300
SAMPLE_CSV=dod_policy_references_08122026.csv
AUTO_INGEST=true
API_TOKENS=__API_TOKENS__
API_TOKEN=__API_TOKEN__
CORS_ALLOW_ORIGINS=http://localhost:5173
QUERY_ROW_CAP=1000
QUERY_TIMEOUT_SECONDS=10.0
```

`API_TOKENS` (plural) is the backend's `name:digest` allow-list; `API_TOKEN` (singular) is the
same token in plaintext, which Step 5 gives the vite dev proxy. They are not interchangeable and
both come from the one token `init-env.sh` generates.

Diff this against the repository's current `.env` before moving on and copy anything else it
sets, verbatim — Task 3 added variables after this plan was written.

- [ ] **Step 3: Stop tracking `.env`**

```bash
git rm --cached .env
printf '\n# Generated by scripts/init-env.sh — contains real secrets.\n.env\n' >> .gitignore
```

- [ ] **Step 4: Verify a clean clone works**

Run:

```bash
rm -f .env && ./scripts/init-env.sh && docker compose up --build -d
sleep 30 && curl -fsS localhost:8000/health
docker compose down
```

Expected: `{"status":"ok"}`. If the backend cannot reach Neo4j, the password did not propagate
to both `NEO4J_AUTH` and `NEO4J_PASSWORD` — they must match.

- [ ] **Step 5: Let the browser app authenticate**

Without this, `docker compose up` produces a UI where every view errors: the frontend sends no
`Authorization` header and nothing supplies one. That fails the Definition of Done's
"clean-checkout `docker compose up` working".

The token is injected **server-side by the vite dev proxy**, so it never enters browser
JavaScript. In `frontend/vite.config.ts`, the existing `/api` proxy gains a `headers` entry —
keep whatever `target` and `rewrite` the file already has:

```ts
        headers: process.env.API_TOKEN
          ? { Authorization: `Bearer ${process.env.API_TOKEN}` }
          : {},
```

In `docker-compose.yml`, under `services.frontend.environment`, add `API_TOKEN: ${API_TOKEN}`.
Add `API_TOKEN=__API_TOKEN__` to `.env.example`, and have `scripts/init-env.sh` substitute the
same plaintext token it prints (it already generates it — reuse `$token`, do not mint a second).

**This is a development affordance, not frontend authentication.** One shared token, injected by
a dev proxy, with no login, no per-user identity and no logout. It exists so a clean clone is
usable; a real login flow replaces it when multi-user lands. Put exactly that in a comment above
the `headers` line so nobody mistakes it for the real thing.

- [ ] **Step 6: Update the README**

Replace the quickstart's single `docker compose up --build` with:

```bash
./scripts/init-env.sh      # once — generates .env and prints your API token
docker compose up --build
```

Replace the README's statement that the Neo4j password is public by construction with what is
now true: secrets are generated locally, `.env` is not tracked, and every route but `/health`
requires a bearer token. Do the same for the equivalent paragraph in
[`docs/specs/architecture.md`](../../specs/architecture.md) *Known weak points* and in
[SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md) *Environment Variables*.

- [ ] **Step 7: Write ADR-010**

Create `docs/specs/adr/ADR-010-secrets-leave-the-repository.md` from the template. It must
state: the decision (`.env` generated, not committed); the cost being accepted — SPEC-001
deliberately committed `.env` so a clean clone ran with no manual step, and that property is
being traded for not shipping a public password; that the previously committed password remains
in git history and is to be treated as compromised, which is harmless only because it protected
nothing but a local development database; and that generated tokens are a deliberate stop short
of an identity provider, per ADR-008.

- [ ] **Step 8: Run everything and commit**

Run: `cd backend && uv run pytest` and `cd ../frontend && npm test`
Expected: PASS

```bash
git add scripts/init-env.sh .env.example .gitignore README.md \
        docs/specs/architecture.md docs/specs/SPEC-001-di-1-policy-grapher.md \
        docs/specs/adr/ADR-010-secrets-leave-the-repository.md
git commit -m "feat: secrets are generated locally, not committed"
```

---

## Done when

- `POST /query` cannot write, cannot run unbounded, and reports truncation
- Every route but `/health` returns 401 without a valid bearer token
- A clean clone runs via `./scripts/init-env.sh && docker compose up --build`, and the UI at
  `localhost:5173` loads the graph rather than erroring on every view
- ADR-008, ADR-009 and ADR-010 exist; ADR-001 and ADR-004 carry amendment banners
- `uv run pytest` and `npm test` both pass

Phase 1 (schema migration and versioning) can start.
