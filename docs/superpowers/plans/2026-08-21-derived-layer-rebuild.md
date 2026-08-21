# Derived-Layer Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the running application a way to turn an ingested edition into obligations, links and embeddings, so Triage, Review and Ask can be filled without running Python by hand.

**Architecture:** An RQ queue on Redis. A `POST` validates synchronously and enqueues; a worker process — the same backend image — runs the existing `rebuild_derived` and `embed_chunks`, reporting per-chunk progress into the job's metadata; a `GET` polls it. No existing phase-4 code is restructured: `rebuild_derived` gains one optional callback and nothing else.

**Tech Stack:** FastAPI, RQ 2.11, redis-py 8.1, Pydantic v2, neo4j Python driver 6.x, pytest + testcontainers (Neo4j and Redis).

**Spec:** [`docs/superpowers/specs/2026-08-21-derived-layer-rebuild-design.md`](../specs/2026-08-21-derived-layer-rebuild-design.md)

## Global Constraints

- Python `>=3.14`. **Celery is disqualified** — 5.6.3 declares support only to 3.13. RQ 2.11 and redis 8.1 both declare 3.14.
- Deps via `uv`. This plan adds exactly two runtime dependencies — `rq>=2.11` and `redis>=8.1` — and one dev extra, `testcontainers[redis]`. Nothing else.
- Ruff enforced **as a test** (`tests/test_lint.py`). Integration tests use real containers; never mock the driver or the Redis connection.
- The `null` extractor and `null` embedder stay the defaults, so `uv run pytest` and a fresh clone need no model server.
- Redis being unreachable must fail **only** the rebuild routes. Everything else is Neo4j and keeps working. The app must still boot.
- Every route requires a principal. `tests/test_auth.py` enumerates routes from the app; neither new route may be added to `OPEN_ROUTES`.
- Documentation updated in the same change.

## Decisions an executor must not silently change

**1. Validation happens before enqueueing.** An unknown edition, an unreadable source file, or a run already in flight are answered synchronously with 404/409/409. A dead job reporting "file not found" ten seconds later meets the letter of STORY-048's criterion and not its intent.

**2. The worker mounts `./data` and carries the backend's settings.** `rebuild_derived` re-reads the PDF from `file:///data/samples/...`, a path *inside* a container. The route's readability check runs in the backend, where the file exists. A worker without the mount fails every job on a check that already passed. This is the sharpest edge in the design.

**3. Extraction goes through `CachedExtractor` over `GraphCacheStore`.** Not as an optimisation — it is what makes a second run over an unchanged edition call the model zero times, and it closes the dead-code half of STORY-050.

**4. `rebuild_derived` is not restructured.** It gains one optional `on_progress` parameter. Its transaction shape — extraction outside, every mutation in one `execute_write` — is what makes a dying worker unable to corrupt the graph, and must not move.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/links/rebuild.py` | *Modify* — add the `on_progress` callback |
| `backend/src/policy_grapher/jobs/__init__.py` | *Create* — package marker |
| `backend/src/policy_grapher/jobs/queue.py` | *Create* — the only module that constructs a Redis connection |
| `backend/src/policy_grapher/jobs/rebuild.py` | *Create* — the job function the worker runs |
| `backend/src/policy_grapher/routers/rebuilds.py` | *Create* — both routes |
| `backend/src/policy_grapher/dependencies.py` | *Modify* — `get_queue` |
| `backend/src/policy_grapher/config.py` | *Modify* — `redis_url`, `rebuild_job_timeout_seconds` |
| `backend/src/policy_grapher/models.py` | *Modify* — `RebuildStarted`, `RebuildStatus` |
| `backend/src/policy_grapher/main.py` | *Modify* — build the queue in `lifespan`, include the router |
| `backend/tests/test_rebuild_job.py` | *Create* — queue, job function, progress |
| `backend/tests/test_rebuilds_route.py` | *Create* — route validation and status |
| `docker-compose.yml`, `.env.example` | *Modify* — `redis` and `worker` services |

---

### Task 1: `rebuild_derived` reports progress

**Files:**
- Modify: `backend/src/policy_grapher/links/rebuild.py`
- Test: `backend/tests/test_rebuild.py`

**Interfaces:**
- Produces: `rebuild_derived(driver, database, *, version_id, extractor, candidate_version_ids=None, proposer="lexical-v1", on_progress: Callable[[int, int], None] | None = None) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_rebuild.py`:

```python
@pytest.mark.integration
def test_a_rebuild_reports_progress_chunk_by_chunk(reviewed_graph, clean_graph, database):
    """A run over a real edition takes minutes with a real model, and the caller
    is watching. Progress is reported per chunk, ending at the chunk count."""
    seen: list[tuple[int, int]] = []

    rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen, "no progress was reported"
    totals = {total for _, total in seen}
    assert len(totals) == 1, f"the total changed mid-run: {totals}"
    total = totals.pop()
    assert [done for done, _ in seen] == list(range(1, total + 1))


@pytest.mark.integration
def test_a_rebuild_without_a_progress_callback_still_works(
    reviewed_graph, clean_graph, database
):
    """The callback is optional — every existing caller passes nothing."""
    counts = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
    )

    assert counts["chunks_written"] > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_rebuild.py -k progress -v`
Expected: FAIL — `TypeError: rebuild_derived() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Implement**

In `backend/src/policy_grapher/links/rebuild.py`, add the import:

```python
from collections.abc import Callable
```

Add the parameter to `rebuild_derived`'s signature, after `proposer`:

```python
    on_progress: Callable[[int, int], None] | None = None,
```

Replace the list comprehension under the comment `# Outside the transaction on purpose — see the module docstring.` — including the `extracted = [entry for entry in extracted if entry[2]]` line that follows it — with:

```python
    # Outside the transaction on purpose — see the module docstring. A loop
    # rather than a comprehension so progress can be reported per chunk: with a
    # real model this is one call each over dozens of chunks, and a caller
    # watching a blank response for minutes cannot tell work from a hang.
    total = len(chunks)
    extracted: list[tuple[str, list[str], list]] = []
    for done, chunk in enumerate(chunks, start=1):
        found = extractor.extract(chunk.text, section_path=chunk.section_path)
        if found:
            extracted.append((chunk.chunk_id, chunk.section_path, found))
        if on_progress is not None:
            on_progress(done, total)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_rebuild.py -v`
Expected: PASS — every existing rebuild test plus the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/links/rebuild.py backend/tests/test_rebuild.py
git commit -m "feat: a rebuild can report its progress chunk by chunk"
```

---

### Task 2: The queue

**Files:**
- Create: `backend/src/policy_grapher/jobs/__init__.py`, `backend/src/policy_grapher/jobs/queue.py`, `backend/tests/test_rebuild_job.py`
- Modify: `backend/src/policy_grapher/config.py`, `backend/pyproject.toml`

**Interfaces:**
- Produces: `QUEUE_NAME = "rebuilds"`, `build_queue(settings: Settings) -> rq.Queue`

- [ ] **Step 1: Add the dependencies**

```bash
cd backend
uv add "rq>=2.11" "redis>=8.1"
uv add --dev "testcontainers[redis]"
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_rebuild_job.py`:

```python
import pytest

from policy_grapher.config import Settings
from policy_grapher.jobs.queue import QUEUE_NAME, build_queue


def test_the_queue_is_named_and_carries_a_timeout():
    """A job with no timeout that hangs holds a worker until the process dies."""
    queue = build_queue(Settings(_env_file=None))

    assert queue.name == QUEUE_NAME
    # Private on purpose: RQ 2.11 exposes the class constant `Queue.DEFAULT_TIMEOUT`
    # but no public accessor for the value a queue was constructed with, and
    # asserting the constant would test RQ rather than this code.
    assert queue._default_timeout == 1800


def test_building_the_queue_does_not_connect():
    """Redis being down must fail only the rebuild routes — the app still boots,
    so constructing the queue cannot reach out to the server."""
    queue = build_queue(
        Settings(_env_file=None, redis_url="redis://not-a-host.invalid:6379/0")
    )

    assert queue is not None
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_rebuild_job.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.jobs'`

- [ ] **Step 4: Implement**

Create `backend/src/policy_grapher/jobs/__init__.py`:

```python
"""Work that happens outside a request."""
```

Create `backend/src/policy_grapher/jobs/queue.py`:

```python
"""The rebuild queue.

The only module that constructs a Redis connection. `Redis.from_url` does not
connect eagerly, which is what lets the application boot with Redis down — every
route but the two rebuild ones talks to Neo4j and is unaffected.
"""

from redis import Redis
from rq import Queue

from policy_grapher.config import Settings

QUEUE_NAME = "rebuilds"


def build_queue(settings: Settings) -> Queue:
    """The queue rebuild jobs are enqueued on.

    `default_timeout` is not decoration: a job that hangs without one holds a
    worker until the process is killed, and with a real model a rebuild
    legitimately runs for minutes, so there is no short timeout that is safe.
    """
    return Queue(
        QUEUE_NAME,
        connection=Redis.from_url(settings.redis_url),
        default_timeout=settings.rebuild_job_timeout_seconds,
    )
```

In `backend/src/policy_grapher/config.py`, add inside `Settings`, immediately before `data_dir`:

```python
    # The rebuild queue (STORY-048). Unreachable Redis fails only the rebuild
    # routes — the connection is lazy and every other route talks to Neo4j.
    redis_url: str = "redis://localhost:6379/0"
    # Generous on purpose: a rebuild with a real model is one call per chunk over
    # dozens of chunks, so there is no short timeout that is not a false alarm.
    rebuild_job_timeout_seconds: int = 1800
```

- [ ] **Step 5: Run the tests and commit**

Run: `cd backend && uv run pytest tests/test_rebuild_job.py -v`
Expected: PASS (2 tests)

```bash
git add backend/src/policy_grapher/jobs backend/src/policy_grapher/config.py \
        backend/pyproject.toml backend/uv.lock backend/tests/test_rebuild_job.py
git commit -m "feat: a queue for work that outlives a request"
```

---

### Task 3: The job the worker runs

**Files:**
- Create: `backend/src/policy_grapher/jobs/rebuild.py`
- Modify: `backend/tests/test_rebuild_job.py`, `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `rebuild_derived(..., on_progress=...)` from Task 1
- Produces: `rebuild_edition(version_id: str, candidate_version_ids: list[str] | None = None, proposer: str = "lexical-v1") -> dict[str, int]`

- [ ] **Step 1: Add the Redis fixtures**

Add to `backend/tests/conftest.py`, after the `clean_graph` fixture:

```python
@pytest.fixture(scope="session")
def redis_container():
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:8-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def redis_connection(redis_container):
    """A real Redis, as Neo4j is real — this project does not mock its drivers."""
    from redis import Redis

    return Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_rebuild_job.py`:

```python
from pathlib import Path

from rq import Queue

from policy_grapher.ingest import ingest_file
from policy_grapher.jobs.rebuild import rebuild_edition

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def _ingest_one(driver, database):
    result = ingest_file(driver, database, "514301p.pdf", SAMPLES)
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        {"slug": result.document.slug},
        database_=database,
    )
    return records[0]["id"]


@pytest.mark.integration
def test_the_job_rebuilds_an_edition_and_reports_counts(
    clean_graph, database, monkeypatch, settings_for_container
):
    """Runs the real job function in-process. The null extractor produces no
    obligations, which is the point: this proves the composition works without
    needing a model."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(job_module, "get_settings", lambda: settings_for_container)
    version_id = _ingest_one(clean_graph, database)

    counts = rebuild_edition(version_id)

    assert counts["chunks_written"] > 0
    assert counts["obligations_written"] == 0
    assert "embedded" in counts


@pytest.mark.integration
def test_the_job_records_progress_in_its_metadata(
    clean_graph, database, monkeypatch, settings_for_container, redis_connection
):
    """Progress is polled from job.meta, so it has to be written there while the
    job runs — not merely handed to a callback that discards it."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(job_module, "get_settings", lambda: settings_for_container)
    version_id = _ingest_one(clean_graph, database)

    queue = Queue("test-rebuilds", connection=redis_connection, is_async=False)
    job = queue.enqueue(rebuild_edition, version_id=version_id)

    assert job.meta["chunks_total"] > 0
    assert job.meta["chunks_done"] == job.meta["chunks_total"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_rebuild_job.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.jobs.rebuild'`

- [ ] **Step 4: Implement**

Create `backend/src/policy_grapher/jobs/rebuild.py`:

```python
"""The job a worker runs to build one edition's derived layer.

It takes primitives, not objects: RQ serialises a job's arguments through Redis,
so a driver or a Settings instance could not cross that boundary. The worker
resolves its own configuration and opens its own driver, and closes it again — a
worker process outlives any single job and would otherwise leak one per run.
"""

from neo4j import Driver
from rq import get_current_job

from policy_grapher.config import get_settings
from policy_grapher.db import create_driver
from policy_grapher.embedding import build_embedder, embed_chunks
from policy_grapher.extraction import build_extractor
from policy_grapher.extraction.cache import CachedExtractor, GraphCacheStore
from policy_grapher.links.rebuild import rebuild_derived


def _progress_reporter():
    """Write progress where a poller can read it.

    `get_current_job` returns None when the function is called directly rather
    than through a queue, which the unit tests do — so this degrades to no
    reporting instead of requiring a queue to exist.
    """
    job = get_current_job()
    if job is None:
        return None

    def report(done: int, total: int) -> None:
        job.meta["chunks_done"] = done
        job.meta["chunks_total"] = total
        job.save_meta()

    return report


def _run(driver: Driver, database: str, settings, **kwargs) -> dict[str, int]:
    # Cached on purpose (ADR-013): a second run over an unchanged edition calls
    # the model zero times, which is what makes re-extraction cheap enough to be
    # routine rather than an event.
    extractor = CachedExtractor(
        build_extractor(settings), GraphCacheStore(driver, database)
    )
    counts = rebuild_derived(
        driver,
        database,
        extractor=extractor,
        on_progress=_progress_reporter(),
        **kwargs,
    )
    counts["embedded"] = embed_chunks(
        driver,
        database,
        version_id=kwargs["version_id"],
        embedder=build_embedder(settings),
    )
    return counts


def rebuild_edition(
    version_id: str,
    candidate_version_ids: list[str] | None = None,
    proposer: str = "lexical-v1",
) -> dict[str, int]:
    """Rebuild one edition's derived layer, then embed its chunks.

    Returns the counts `rebuild_derived` reports plus `embedded`. Raises
    `MissingSourceError` if the edition or its source file is gone — the route
    checks for that before enqueueing, so reaching it here means the file
    disappeared between the check and the run, or the worker cannot see it.
    """
    settings = get_settings()
    driver = create_driver(settings)
    try:
        return _run(
            driver,
            settings.neo4j_database,
            settings,
            version_id=version_id,
            candidate_version_ids=candidate_version_ids,
            proposer=proposer,
        )
    finally:
        driver.close()
```

- [ ] **Step 5: Run the tests and commit**

Run: `cd backend && uv run pytest tests/test_rebuild_job.py -v`
Expected: PASS (4 tests)

```bash
git add backend/src/policy_grapher/jobs/rebuild.py backend/tests/test_rebuild_job.py \
        backend/tests/conftest.py
git commit -m "feat: a worker can build an edition's derived layer"
```

---

### Task 4: The routes

**Files:**
- Create: `backend/src/policy_grapher/routers/rebuilds.py`, `backend/tests/test_rebuilds_route.py`
- Modify: `backend/src/policy_grapher/models.py`, `backend/src/policy_grapher/dependencies.py`, `backend/src/policy_grapher/main.py`, `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `rebuild_edition` (Task 3), `build_queue` (Task 2)
- Produces: `POST /documents/{slug}/versions/{version_id}/rebuild -> 202 RebuildStarted`; `GET /rebuilds/{run_id} -> RebuildStatus`

- [ ] **Step 1: Point the test client's queue at the Redis container**

In `backend/tests/conftest.py`, add `redis_connection` to `client_with_graph`'s parameters:

```python
def client_with_graph(
    clean_graph, settings_for_container, database, monkeypatch, redis_connection
):
```

and immediately after the `monkeypatch.setattr(main, "get_settings", lambda: settings)` line:

```python
    # The routes enqueue against a real Redis, exactly as they will in
    # production. No worker runs here, so these tests observe precisely what a
    # caller sees between enqueue and completion.
    from rq import Queue

    from policy_grapher.jobs.queue import QUEUE_NAME

    monkeypatch.setattr(
        main,
        "build_queue",
        lambda _settings: Queue(QUEUE_NAME, connection=redis_connection),
    )
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_rebuilds_route.py`:

```python
from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_file

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def _ingest(client, filename="514301p.pdf"):
    driver = client.app.state.driver
    database = client.app.state.settings.neo4j_database
    result = ingest_file(driver, database, filename, SAMPLES)
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        {"slug": result.document.slug},
        database_=database,
    )
    return result.document.slug, records[0]["id"]


@pytest.mark.integration
def test_starting_a_rebuild_returns_a_run_id(client_with_auth):
    slug, version_id = _ingest(client_with_auth)

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 202
    assert response.json()["run_id"]
    assert response.json()["version_id"] == version_id


@pytest.mark.integration
def test_an_unknown_edition_is_a_404_naming_it(client_with_auth):
    slug, _ = _ingest(client_with_auth)

    response = client_with_auth.post(f"/documents/{slug}/versions/not-an-edition/rebuild")

    assert response.status_code == 404
    assert "not-an-edition" in response.json()["detail"]


@pytest.mark.integration
def test_an_unreadable_source_is_a_409_naming_the_file(client_with_auth, tmp_path):
    """STORY-048: a 4xx from the route, not a job that dies later. A dead job
    reporting 'file not found' meets the letter of that and not its intent."""
    slug, version_id = _ingest(client_with_auth)
    missing = tmp_path / "vanished.pdf"
    client_with_auth.app.state.driver.execute_query(
        "MATCH (v:DocumentVersion {version_id: $id}) SET v.source_uri = $uri",
        {"id": version_id, "uri": f"file://{missing}"},
        database_=client_with_auth.app.state.settings.neo4j_database,
    )

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 409
    assert "vanished.pdf" in response.json()["detail"]


@pytest.mark.integration
def test_a_second_rebuild_of_the_same_edition_is_refused(client_with_auth):
    """Two runs racing over one edition would each drop and rewrite the same
    derived layer, and the second would replay decisions against a half-built one."""
    slug, version_id = _ingest(client_with_auth)
    first = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild"
    ).json()["run_id"]

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 409
    assert first in response.json()["detail"]


@pytest.mark.integration
def test_a_started_run_can_be_polled(client_with_auth):
    slug, version_id = _ingest(client_with_auth)
    run_id = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild"
    ).json()["run_id"]

    response = client_with_auth.get(f"/rebuilds/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["version_id"] == version_id
    assert body["state"] in {"queued", "started", "finished"}


@pytest.mark.integration
def test_an_unknown_run_is_a_404(client_with_auth):
    assert client_with_auth.get("/rebuilds/not-a-run").status_code == 404


@pytest.mark.integration
def test_both_routes_require_a_principal(client_with_graph):
    assert client_with_graph.post("/documents/x/versions/y/rebuild").status_code == 401
    assert client_with_graph.get("/rebuilds/anything").status_code == 401
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_rebuilds_route.py -v`
Expected: FAIL — 404 on every route; they do not exist yet.

- [ ] **Step 4: Add the models**

Append to `backend/src/policy_grapher/models.py`:

```python
class RebuildStarted(BaseModel):
    run_id: str
    version_id: str


class RebuildStatus(BaseModel):
    """What a poller sees.

    `counts` is populated only once the run finishes and `error` only if it
    failed. Both empty, with `state` still in progress, is the normal mid-run
    reading.
    """

    run_id: str
    version_id: str
    state: str
    chunks_done: int = 0
    chunks_total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
```

- [ ] **Step 5: Add the dependency**

In `backend/src/policy_grapher/dependencies.py`, add the import:

```python
from rq import Queue
```

and append:

```python
def get_queue(request: Request) -> Queue:
    """The rebuild queue `lifespan` built. Constructed once at boot; the Redis
    connection behind it is lazy, so a queue exists even when Redis is down."""
    return request.app.state.queue
```

- [ ] **Step 6: Implement the routes**

Create `backend/src/policy_grapher/routers/rebuilds.py`:

```python
"""Starting and polling a derived-layer rebuild.

Everything knowable before the work starts is checked here, in the request: an
unknown edition, a source file the backend cannot read, a run already in flight.
STORY-048 requires a missing source to be a 4xx naming the edition, and a job
that dies ten seconds later reporting the same thing would satisfy the letter of
that and not its intent.
"""

from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver, RoutingControl
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import StartedJobRegistry

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver, get_queue
from policy_grapher.jobs.rebuild import rebuild_edition
from policy_grapher.models import RebuildStarted, RebuildStatus

router = APIRouter(tags=["rebuilds"])

EDITION = """
MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion {version_id: $version_id})
RETURN v.source_uri AS source_uri
"""


def _in_flight(queue: Queue, version_id: str) -> str | None:
    """The run id already working on this edition, if any.

    Scans the queued and started registries rather than keeping a lock key: a
    lock has to be released, and a worker killed mid-run would leave one behind
    that nothing clears. The registries are the queue's own truth, and there are
    never many jobs here.
    """
    ids = list(queue.get_job_ids()) + list(StartedJobRegistry(queue=queue).get_job_ids())
    for job_id in ids:
        job = queue.fetch_job(job_id)
        if job is not None and job.kwargs.get("version_id") == version_id:
            return job_id
    return None


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="The rebuild queue is unreachable. Every other route is unaffected.",
    )


@router.post(
    "/documents/{slug}/versions/{version_id}/rebuild",
    response_model=RebuildStarted,
    status_code=202,
)
def start_rebuild(
    slug: str,
    version_id: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    queue: Queue = Depends(get_queue),
    principal: Principal = Depends(require_principal),
) -> RebuildStarted:
    records, _, _ = driver.execute_query(
        EDITION,
        {"slug": slug, "version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No edition {version_id!r} on document {slug!r}.",
        )

    source = Path(unquote(urlparse(records[0]["source_uri"]).path))
    if not source.is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                f"{version_id!r} was read from {source}, which is not readable now. "
                f"Re-chunking needs the original document."
            ),
        )

    try:
        existing = _in_flight(queue, version_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Rebuild {existing} is already running for {version_id!r}.",
            )
        job = queue.enqueue(rebuild_edition, version_id=version_id)
    except RedisError as exc:
        raise _unavailable() from exc

    return RebuildStarted(run_id=job.id, version_id=version_id)


@router.get("/rebuilds/{run_id}", response_model=RebuildStatus)
def read_rebuild(
    run_id: str,
    queue: Queue = Depends(get_queue),
    principal: Principal = Depends(require_principal),
) -> RebuildStatus:
    try:
        job = Job.fetch(run_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail=f"No rebuild run {run_id!r}.") from exc
    except RedisError as exc:
        raise _unavailable() from exc

    return RebuildStatus(
        run_id=job.id,
        version_id=job.kwargs.get("version_id", ""),
        state=job.get_status(),
        chunks_done=job.meta.get("chunks_done", 0),
        chunks_total=job.meta.get("chunks_total", 0),
        counts=job.result if isinstance(job.result, dict) else {},
        error=job.latest_result().exc_string if job.is_failed else None,
    )
```

In `backend/src/policy_grapher/main.py`:

```python
from policy_grapher.jobs.queue import build_queue
from policy_grapher.routers import admin, ask, documents, graph, rebuilds, review, triage
```

In `lifespan`, after `embedder = build_embedder(settings)`:

```python
    # Lazy: Redis being down must not stop the app booting, since every route
    # but the two rebuild ones talks to Neo4j.
    queue = build_queue(settings)
```

after `app.state.embedder = embedder`:

```python
    app.state.queue = queue
```

and beside the other routers:

```python
app.include_router(rebuilds.router)
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest tests/test_rebuilds_route.py tests/test_auth.py -v`
Expected: PASS. `test_auth.py` picks both routes up through its route enumeration without any edit.

- [ ] **Step 8: Run the full suite and commit**

Run: `cd backend && uv run pytest`
Expected: PASS

```bash
git add backend/src/policy_grapher backend/tests
git commit -m "feat: an edition's derived layer can be rebuilt from the app"
```

---

### Task 5: The worker and Redis run beside everything else

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `docs/specs/architecture.md`

**Interfaces:**
- Produces: `redis` and `worker` compose services

- [ ] **Step 1: Add the services**

In `docker-compose.yml`, add to the `backend` service's `environment` block, after `EMBEDDER_MODEL`:

```yaml
      REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
```

and add to the `backend` service:

```yaml
    depends_on:
      redis:
        condition: service_healthy
```

Add both services as siblings of `backend`:

```yaml
  redis:
    image: redis:8-alpine
    # No published port: only the backend and the worker speak to it, and both
    # are on this network. Publishing it would put an unauthenticated data store
    # on the host for nothing.
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  worker:
    build: ./backend
    restart: on-failure
    command: ["uv", "run", "rq", "worker", "--url", "redis://redis:6379/0", "rebuilds"]
    depends_on:
      redis:
        condition: service_healthy
    environment:
      # The same configuration as the backend, deliberately: the worker opens its
      # own Neo4j driver and builds its own extractor and embedder.
      NEO4J_URI: ${NEO4J_URI}
      NEO4J_USER: ${NEO4J_USER}
      NEO4J_PASSWORD: ${NEO4J_PASSWORD}
      NEO4J_DATABASE: ${NEO4J_DATABASE}
      DATA_DIR: /data/samples
      REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
      EXTRACTOR_ADAPTER: ${EXTRACTOR_ADAPTER:-null}
      EXTRACTOR_MODEL: ${EXTRACTOR_MODEL:-qwen3:8b}
      EXTRACTOR_BASE_URL: ${EXTRACTOR_BASE_URL:-http://localhost:11434}
      EMBEDDER_ADAPTER: ${EMBEDDER_ADAPTER:-null}
      EMBEDDER_MODEL: ${EMBEDDER_MODEL:-sentence-transformers/all-MiniLM-L6-v2}
    volumes:
      # Load-bearing, not incidental: rebuild_derived re-reads the source PDF
      # from `file:///data/samples/...`, a path inside a container. The route's
      # readability check runs in the backend, where the file exists — a worker
      # without this mount fails every job on a check that already passed.
      - ./data:/data:ro,z
```

- [ ] **Step 2: Add the variable to `.env.example`**

```bash
# The rebuild queue (STORY-048). Redis is reached only from inside the compose
# network; unreachable Redis fails the two rebuild routes and nothing else.
REDIS_URL=redis://redis:6379/0
```

- [ ] **Step 3: Verify the stack starts**

```bash
docker compose config >/dev/null && echo ok
docker compose down -v && docker compose up -d --build
docker compose logs worker --tail 20
```

Expected: the worker logs `Worker rq:worker:...` and `*** Listening on rebuilds...`.

- [ ] **Step 4: Walk it end to end**

With `TOKEN=$(grep -E '^API_TOKEN=' .env | cut -d= -f2-)`:

```bash
curl -s -X POST localhost:8000/ingest -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"filename":"514301p.pdf"}'
curl -s localhost:8000/documents/dodd-5143-01/versions -H "Authorization: Bearer $TOKEN"
curl -s -X POST "localhost:8000/documents/dodd-5143-01/versions/<version_id>/rebuild" \
     -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/rebuilds/<run_id>" -H "Authorization: Bearer $TOKEN"
```

Expected: `202` with a `run_id`, then a status reaching `finished` with
`chunks_done == chunks_total` and a `counts` object. With the default `null`
extractor `obligations_written` is 0 — the composition is what is proved here,
not extraction quality.

- [ ] **Step 5: Update the architecture document**

In `docs/specs/architecture.md`:

- Add `POST /documents/{slug}/versions/{version_id}/rebuild` and
  `GET /rebuilds/{run_id}` to the backend row's endpoint list in *Components*.
- Add a `redis` row: the rebuild queue, unpublished, reached only from the compose
  network.
- Add a `worker` row: the same backend image running `rq worker`, mounting
  `./data` because a rebuild re-reads the source PDF from a container path.
- Under *Known weak points*, record that run state lives in Redis and expires,
  so run history is not durable — chosen deliberately over Postgres, per the
  design, on the grounds that audit history is a speculative requirement and a
  second source of truth is not.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example docs/specs/architecture.md
git commit -m "feat: a worker runs beside the app, and Redis carries its queue"
```

---

## Done when

- `POST /documents/{slug}/versions/{version_id}/rebuild` returns 202 with a run id, and the work happens in a worker process
- An unknown edition is 404 naming it; an unreadable source is 409 naming the file; a second run for the same edition is 409 naming the first
- `GET /rebuilds/{run_id}` reports state, per-chunk progress, and either counts or an error
- Both routes appear in `test_auth.py`'s enumeration without being added to `OPEN_ROUTES`
- A second rebuild of an unchanged edition calls the model zero times, through `CachedExtractor`
- `uv run pytest` passes with no model server, and the app boots with Redis down
- From a wiped volume: ingest a PDF, start a rebuild, poll it to `finished` — no Python, no direct Bolt

Sprint 4's remaining items — STORY-051 (CI), STORY-052 (image size), STORY-056 (containerised model server) — are independent of this plan and may be done in any order after it.
