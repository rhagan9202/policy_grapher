# Models in the Default Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker compose up --build` bring up the whole product — model server, extraction and embeddings — and make the lean stack the flagged path.

**Architecture:** Three edits and one new file. `ollama` and `ollama-pull` lose their `profiles:` key so they join the default stack (which also makes `docker compose down` stop them). The adapter and build-arg defaults in `docker-compose.yml` flip from `null`/empty to `local`/`--extra local-embeddings`. A tracked `docker-compose.lean.yml` turns both services off *and* the adapters back. CI switches to building through that override file so its 1GB size gate keeps measuring an image whose size is still a decision.

**Tech Stack:** Docker Compose v2 · Ollama + llama3.1:8b · Python 3.14 / FastAPI / pytest · GitHub Actions

**Spec:** [`docs/superpowers/specs/2026-08-25-models-in-the-default-stack-design.md`](../specs/2026-08-25-models-in-the-default-stack-design.md)

## Global Constraints

- **Backend tests:** `cd backend && uv run pytest`. Baseline **595 passed / 5 skipped**. Ruff lints inside the suite via `tests/test_lint.py`.
- **Frontend tests:** `docker compose run --rm frontend npm test` — ESLint `--max-warnings=0`, then `tsc -b`, then Vitest. Baseline **169 passed**.
- **`Settings` defaults in `backend/src/policy_grapher/config.py` do not change.** `extractor_adapter` and `embedder_adapter` stay `"null"`. The default stack is a compose decision; a bare `uvicorn` run and every test constructing `Settings` directly must keep working with no model server.
- **The two stacks share image tags.** `EXTRAS` is a build argument and both invocations produce `policy_grapher-backend`. Every documented command carries `--build`, or a stale image serves the wrong stack.
- **ADRs are frozen.** ADR-021 is Accepted and is never edited — it is superseded by a new ADR that cites it.
- **Never lower a ratchet floor or raise a ceiling** to turn a suite green (`backend/tests/test_extraction_ratchet.py`).
- **Assert values, not types.** This project shipped a dead screen behind a green suite because a test asserted `expect.any(Number)` where `0` was the bug. Three more untestable tests were caught in the last two days. Every test here is watched failing before it is made to pass.
- **Commit style:** Conventional Commit prefixes, imperative subject.
- **Disk:** the full build produces two 16.6GB images. Check free space before Task 5 — `df -h /var/lib/docker` — and expect the default build to take tens of minutes on a cold cache.

---

## Task 1: ADR-028 — the default stack carries its models

**Files:**
- Create: `docs/specs/adr/ADR-028-the-default-stack-carries-its-models.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the decision Tasks 3–5 implement. No code.

- [ ] **Step 1: Read the template and two recent ADRs for the house voice**

Run: `cat docs/specs/adr/TEMPLATE-adr.md && sed -n '1,40p' docs/specs/adr/ADR-027-a-rebuild-repoints-decisions.md`

The voice is sober, specific, prose over bullets, and it names the cost of the decision out loud. Match it — that is most of what this task is judged on beyond correctness.

- [ ] **Step 2: Write the ADR**

Content:

- **Context.** `docker compose up --build` brings up five services and no model server. `EXTRACTOR_ADAPTER` defaults to `null`, so a rebuild writes chunks and zero obligations, and Review and Triage cannot fill no matter what the reader does. The product tells them this in the README rather than on the screen. The model server has sat behind `profiles: ["models"]` since it was added, and because a profile is only active when named, `docker compose down` does not stop it either.
- **Decision.** The default stack is the whole product. `ollama` and `ollama-pull` become ordinary services; `EXTRACTOR_ADAPTER` and `EMBEDDER_ADAPTER` default to `local`; `BACKEND_EXTRAS` defaults to `--extra local-embeddings`. A lean stack with no models is reached through `docker-compose.lean.yml`.
- **Consequences.** A fresh clone now moves roughly 13GB before the first screen renders — ollama at 8.43GB, `llama3.1:8b` at about 4.9GB — and builds two 16.6GB images. [ADR-019](../../specs/adr/ADR-019-the-first-run-is-empty.md)'s empty first run still holds: nothing is ingested. It is only expensive to arrive there. `docker compose down` now stops the model server, which is the behaviour the profile made impossible.
- **Alternatives rejected.** `COMPOSE_PROFILES=models` in `.env` would have delivered the same default in one line and fixed `down` at the same time. Rejected because `.env` is untracked and this project has twice been bitten by an `.env` predating the keys `.env.example` documents — most recently in the README addendum of 2026-08-24. Which services exist by default belongs in the tracked file. `--scale ollama=0` was rejected for the lean path because it removes containers but cannot return the adapters to `null`, leaving a stack that looks healthy and fails on every rebuild.

- [ ] **Step 3: Commit**

```bash
git add docs/specs/adr/ADR-028-the-default-stack-carries-its-models.md
git commit -m "docs: ADR-028, the default stack carries its models"
```

---

## Task 2: ADR-029 — superseding ADR-021

**Files:**
- Create: `docs/specs/adr/ADR-029-the-default-image-carries-the-model-runtime.md`
- Modify: `docs/specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md` (a pointer only)

**Interfaces:**
- Consumes: nothing.
- Produces: the decision Task 4 implements. No code.

- [ ] **Step 1: Read what is being superseded**

Run: `cat docs/specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md`

Note its measured figures — 16.6GB per backend service against 399MB — and its *Makes easy* section. This ADR gives those back for the default path.

- [ ] **Step 2: Write the ADR**

Content:

- **Context.** ADR-021 kept `sentence-transformers` out of the default image because the default configuration never loaded it: a 16.6GB pull for a library nothing used. ADR-028 makes the default configuration load it. The premise the trade rested on no longer holds.
- **Decision.** The default image carries the model runtime. `EXTRAS` defaults to `--extra local-embeddings`, so `policy_grapher-backend` and `policy_grapher-worker` are about 16.6GB on the default path. The lean path keeps ADR-021's 399MB and is what CI measures.
- **Consequences — state the loss first.** STORY-052 took these images from 16.6GB to 399MB and that reduction is deliberately given back for the default path. Every `up --build` on a cold cache now moves ~13GB before anything renders. What is gained is that Ask acquires its vector leg, so a question phrased in words the document does not use can reach the passage that answers it — which is the whole argument of [ADR-016](../../specs/adr/ADR-016-embeddings-are-a-port.md) and was unreachable by default until now.
- **Not attempted.** ADR-021 records a route to roughly 5GB through a multi-stage sync layer that leaves torch in the runtime stage. It stays unexplored; this decision gives the size back rather than optimising it.
- **Supersedes** ADR-021.

- [ ] **Step 3: Mark ADR-021 superseded with a pointer**

Add a note at the top of ADR-021 pointing at ADR-029. Do not edit its prose, its figures, or its decision — it is a dated record of what was true on 2026-08-21, and only the pointer is added.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/adr/ADR-029-the-default-image-carries-the-model-runtime.md docs/specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md
git commit -m "docs: ADR-029 supersedes ADR-021, the default image carries the model runtime"
```

---

## Task 3: STORY-078 — the model server joins the default stack

**Files:**
- Modify: `docker-compose.yml:205` and `:226` (remove `profiles: ["models"]`), and the comment block above `ollama` at roughly `:190-203`
- Test: `backend/tests/test_compose_stack.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a default service set of seven, which Task 4's override file reduces and Task 5's CI job builds against.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compose_stack.py`:

```python
"""What `docker compose up` brings up, asserted against the file rather than a habit.

ADR-028 makes the default stack the whole product. The model server sat behind
`profiles: ["models"]`, and because a profile is only active when it is named,
`docker compose down` did not stop it either — the asymmetry this closes.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())

MODEL_SERVICES = ("ollama", "ollama-pull")


def test_the_model_services_are_in_the_default_stack():
    """No profile, so `up` starts them and — the point — `down` stops them."""
    for name in MODEL_SERVICES:
        service = COMPOSE["services"][name]
        assert "profiles" not in service, (
            f"{name} carries profiles={service.get('profiles')!r}; a profiled service "
            "is not stopped by a plain `docker compose down`, which is the behaviour "
            "ADR-028 exists to fix"
        )


def test_the_default_stack_is_every_service():
    """A service added later and quietly profiled would not be caught above."""
    profiled = {
        name for name, service in COMPOSE["services"].items() if service.get("profiles")
    }
    assert profiled == set(), f"these services do not start by default: {sorted(profiled)}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -v`
Expected: both FAIL — `ollama carries profiles=['models']`, and the second naming both services.

- [ ] **Step 3: Remove the profile keys**

In `docker-compose.yml`, delete the line `    profiles: ["models"]` from the `ollama` service (line 205) and from the `ollama-pull` service (line 226). Change nothing else in either service — the loopback port binding, the healthcheck, the named volume and the `depends_on` all stay exactly as they are.

- [ ] **Step 4: Rewrite the comment block above `ollama`**

The block currently tells the reader to run `docker compose --profile models up -d` and explains that wanting real extraction is what costs the download. Replace it with the inverse: that the model server is part of the default stack because a stack without it cannot fill Review or Triage, what it costs (8.43GB image, ~4.9GB of weights on first run), and that `docker-compose.lean.yml` is the way to a stack without it. Cite ADR-028.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -v`
Expected: 2 passed

- [ ] **Step 6: Verify compose resolves the new default**

Run: `docker compose config --services | sort | tr '\n' ' '`
Expected: `backend frontend neo4j ollama ollama-pull redis worker` — seven services, with no profile named on the command line.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: 597 passed / 5 skipped (595 baseline plus the two new tests)

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml backend/tests/test_compose_stack.py
git commit -m "feat: the model server is part of the default stack"
```

---

## Task 4: STORY-078 — the adapters default on

**Files:**
- Modify: `docker-compose.yml` lines 36, 71, 81 (backend) and 121, 147, 157 (worker)
- Modify: `.env.example`
- Test: `backend/tests/test_compose_stack.py` (extend)

**Interfaces:**
- Consumes: the seven-service default from Task 3.
- Produces: compose-resolved defaults of `EXTRACTOR_ADAPTER=local`, `EMBEDDER_ADAPTER=local`, `EXTRAS=--extra local-embeddings`, which Task 5's override file inverts.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_compose_stack.py`:

```python
import subprocess


def _resolved(*compose_files: str) -> dict:
    """What compose actually resolves, not what the file literally says.

    Reading the YAML would test the template `${VAR:-default}` rather than the
    value a container receives, and the default is the whole subject here.
    """
    # --env-file /dev/null is load-bearing. Compose reads ./.env automatically,
    # so a developer who has set EXTRACTOR_ADAPTER there would see their own
    # value and this test would assert nothing about the default. Verified: with
    # it, GRAPH_RENDER_CAP resolves empty, proving .env was not read.
    argv = ["docker", "compose", "--env-file", "/dev/null"]
    for path in compose_files:
        argv += ["-f", path]
    argv.append("config")
    out = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT, check=True)
    return yaml.safe_load(out.stdout)


def test_the_default_stack_extracts_and_embeds_for_real():
    """ADR-028. A default stack whose adapters are `null` cannot fill Review or
    Triage, which is the state this inverts."""
    config = _resolved("docker-compose.yml")
    for name in ("backend", "worker"):
        env = config["services"][name]["environment"]
        assert env["EXTRACTOR_ADAPTER"] == "local", f"{name} would extract nothing"
        assert env["EMBEDDER_ADAPTER"] == "local", f"{name} would embed nothing"


def test_the_default_build_carries_the_embedding_extra():
    """ADR-029. `EMBEDDER_ADAPTER=local` without the extra makes the backend
    refuse to start — `require_sentence_transformers` fires in the lifespan."""
    config = _resolved("docker-compose.yml")
    for name in ("backend", "worker"):
        args = config["services"][name]["build"]["args"]
        assert args["EXTRAS"] == "--extra local-embeddings", f"{name} builds without torch"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -k "for_real or embedding_extra" -v`
Expected: FAIL — `backend would extract nothing` (the resolved value is `null`), and `backend builds without torch` (the resolved `EXTRAS` is the empty string).

- [ ] **Step 3: Flip the six defaults**

In `docker-compose.yml`, for **both** the `backend` and `worker` services:

```yaml
        EXTRAS: ${BACKEND_EXTRAS:---extra local-embeddings}
```
```yaml
      EXTRACTOR_ADAPTER: ${EXTRACTOR_ADAPTER:-local}
```
```yaml
      EMBEDDER_ADAPTER: ${EMBEDDER_ADAPTER:-local}
```

The `${VAR:-default}` form is kept deliberately: an `.env` naming any of these still wins, so an existing checkout keeps whatever it already set.

- [ ] **Step 4: Update the comments that justify the old defaults**

The lines above these settings explain why the default is `null` and why `EXTRAS` is empty. Both now argue for the opposite. Rewrite them to say the default stack carries its models (ADR-028), that the image is about 16.6GB as a result (ADR-029), and that the lean path is `docker-compose.lean.yml`.

- [ ] **Step 5: Update `.env.example`**

Change the `EXTRACTOR_ADAPTER`, `EMBEDDER_ADAPTER` and `BACKEND_EXTRAS` example values and their surrounding prose to match the new defaults. Keep documenting what `null` and an empty `EXTRAS` do — they are what the lean path uses.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -v`
Expected: 4 passed

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: 599 passed / 5 skipped

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml .env.example backend/tests/test_compose_stack.py
git commit -m "feat: the default stack extracts and embeds for real"
```

---

## Task 5: STORY-079 — the lean stack

**Files:**
- Create: `docker-compose.lean.yml`
- Test: `backend/tests/test_compose_stack.py` (extend)

**Interfaces:**
- Consumes: `_resolved(*compose_files)` from Task 4.
- Produces: the override file Task 6's CI job builds through.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_compose_stack.py`:

```python
LEAN = "docker-compose.lean.yml"


def test_the_lean_stack_runs_no_model_services():
    config = _resolved("docker-compose.yml", LEAN)
    for name in MODEL_SERVICES:
        replicas = config["services"][name].get("deploy", {}).get("replicas")
        assert replicas == 0, f"{name} would still start under the lean stack"


def test_the_lean_stack_turns_the_adapters_back():
    """The half `--scale` cannot do. A lean stack still pointing at
    EXTRACTOR_ADAPTER=local looks healthy and fails on every rebuild against a
    model server that is not there."""
    config = _resolved("docker-compose.yml", LEAN)
    for name in ("backend", "worker"):
        env = config["services"][name]["environment"]
        assert env["EXTRACTOR_ADAPTER"] == "null", f"{name} would call a model that is not running"
        assert env["EMBEDDER_ADAPTER"] == "null", f"{name} would embed against a model that is not running"


def test_the_lean_build_drops_the_embedding_extra():
    """Without this the lean stack builds a 16.6GB image and CI's size gate —
    which measures exactly this build — fails."""
    config = _resolved("docker-compose.yml", LEAN)
    for name in ("backend", "worker"):
        assert config["services"][name]["build"]["args"]["EXTRAS"] == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -k lean -v`
Expected: FAIL — `docker compose` exits non-zero because `docker-compose.lean.yml` does not exist, surfacing through `check=True` as a `CalledProcessError`.

- [ ] **Step 3: Write the override file**

Create `docker-compose.lean.yml`:

```yaml
# The stack without models, for development and for CI.
#
# ADR-028 made the full product the default. This is the flagged path back:
#
#     docker compose -f docker-compose.yml -f docker-compose.lean.yml up --build
#
# `--build` is not optional. EXTRAS is a build argument and both stacks produce
# the same image tags, so without it the previous stack's image is reused — which
# in this direction means a 16.6GB image quietly serving a stack that claims to
# carry no model runtime.
#
# The adapters are returned to `null` here, in the same file that stops the
# services. Stopping the model server while the adapters still say `local`
# produces a stack that looks healthy and fails on every rebuild, which is why
# `--scale ollama=0` was not enough on its own.
services:
  ollama:
    deploy:
      replicas: 0

  ollama-pull:
    deploy:
      replicas: 0

  backend:
    build:
      args:
        EXTRAS: ""
    environment:
      EXTRACTOR_ADAPTER: "null"
      EMBEDDER_ADAPTER: "null"

  worker:
    build:
      args:
        EXTRAS: ""
    environment:
      EXTRACTOR_ADAPTER: "null"
      EMBEDDER_ADAPTER: "null"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_compose_stack.py -v`
Expected: 7 passed

- [ ] **Step 5: Prove the lean stack actually comes up**

The tests above read resolved configuration. This proves the thing runs. Check disk first — the *default* build in Step 6 needs room for two 16.6GB images.

```bash
df -h /var/lib/docker | tail -1
docker compose -f docker-compose.yml -f docker-compose.lean.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.lean.yml ps --services | sort | tr '\n' ' '
curl -s -o /dev/null -w "api %{http_code}\n" localhost:8000/health
docker image inspect policy_grapher-backend --format '{{.Size}}'
```

Expected: five services (`backend frontend neo4j redis worker`), `api 200`, and a size **under** 1000000000 — that last number is CI's threshold, and this is the build CI will measure.

- [ ] **Step 6: Prove the default stack still comes up, and that `down` stops the model server**

```bash
docker compose up --build -d
docker compose ps --services | sort | tr '\n' ' '
docker compose down
docker ps --filter name=ollama --format '{{.Names}}'
```

Expected: seven services including `ollama`; and after `down`, **no output** from the last command. That empty line is the third thing this whole change was asked for — record it in the report.

- [ ] **Step 7: Watch CI's size gate reject the default image**

A threshold nobody has seen reject anything is not a gate. The default build from Step 6 is still on disk; run the gate's own arithmetic against it and against the lean image:

```bash
for image in policy_grapher-backend policy_grapher-worker; do
  bytes=$(docker image inspect "$image" --format '{{.Size}}')
  echo "$image: $((bytes / 1000000)) MB — gate says $([ "$bytes" -gt 1000000000 ] && echo REJECT || echo PASS)"
done
```

Expected: **REJECT** for both, at roughly 16600 MB. Then rebuild lean (`docker compose -f docker-compose.yml -f docker-compose.lean.yml build backend worker`) and re-run the same loop: **PASS** for both. Paste both outputs in the report — they are the evidence that Task 6's job measures something real.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.lean.yml backend/tests/test_compose_stack.py
git commit -m "feat: a lean stack with no models is one command"
```

---

## Task 6: STORY-080 — CI builds and measures the lean stack

**Files:**
- Modify: `.github/workflows/ci.yml` (the `compose` job)
- Modify: `backend/tests/test_ci.py:75-108`

**Interfaces:**
- Consumes: `docker-compose.lean.yml` from Task 5.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Read what the existing assertions actually assert**

Run: `sed -n '75,108p' backend/tests/test_ci.py`

`test_the_workflow_proves_the_stack_builds` looks for the substring `docker compose build` in the job's run commands. `test_the_compose_build_covers_every_service_that_is_built` collects every service in `docker-compose.yml` with a `build:` key — `backend`, `worker`, `frontend` — and asserts each is named somewhere in the job's commands. **Both will still pass after a careless edit**, which is the trap: the first matches a looser string, and the second only checks service names appear. Neither notices which compose files are used.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_ci.py`:

```python
def test_the_compose_job_measures_the_lean_stack(workflow):
    """ADR-028 moved the models into the default stack, so the default image is
    now ~16.6GB and the 1GB gate below would fail on every push. The gate exists
    to prove the *lean* image has not silently regrown, and that purpose survives
    the default changing — but only if the job actually builds the lean stack.
    """
    commands = " ".join(_run_commands(workflow["jobs"]["compose"]))

    assert "docker-compose.lean.yml" in commands, (
        "the compose job builds the default stack, whose images are ~16.6GB — "
        "the size gate would fail on every push"
    )
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_ci.py -k measures_the_lean_stack -v`
Expected: FAIL — "the compose job builds the default stack".

- [ ] **Step 4: Point the compose job at the lean stack**

In `.github/workflows/ci.yml`, in the `compose` job, change the three run steps to use both files:

```yaml
      - name: Build every image compose builds
        run: docker compose -f docker-compose.yml -f docker-compose.lean.yml build backend worker frontend

      - name: The compose file itself resolves
        run: docker compose -f docker-compose.yml -f docker-compose.lean.yml config --quiet
```

- [ ] **Step 5: Rename the size gate and correct its error message**

The step is called *The default image has not regrown* and its error says "ADR-021 keeps the model runtime out of the default image." Both are now false: this measures the lean image, and ADR-021 is superseded. Rename the step to name the lean stack, and change the error to cite ADR-029 and say plainly which stack was measured. Update the long comment above it too — it quotes 399MB against 16.6GB as default-versus-regression, and that framing is now backwards.

- [ ] **Step 6: Add a step asserting the default stack still resolves**

CI no longer builds the default stack, so nothing would catch a syntax error in it. Add one cheap step:

```yaml
      - name: The default stack resolves too
        run: docker compose config --quiet
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_ci.py -v`
Expected: all pass, including the two pre-existing compose-job assertions — confirm they still pass rather than assuming, since Step 4 changed the strings they read.

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: 600 passed / 5 skipped

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/ci.yml backend/tests/test_ci.py
git commit -m "ci: build and measure the lean stack, not the default one"
```

---

## Task 7: The documentation the change makes wrong

**Files:**
- Modify: `README.md` (setup and model sections)
- Modify: `docs/specs/architecture.md`
- Modify: `docs/backlog/backlog.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Find every claim the change falsifies**

```bash
grep -n "profile models\|--profile models\|8.4GB\|399MB\|not among them\|EXTRACTOR_ADAPTER" README.md docs/specs/architecture.md
```

The README's *Setting up and running* says four services come up by default and "the model server is **not** among them". Its *Running a real extraction model* and *Running a real embedding model* sections describe opt-in paths that are now the default. Its *Stopping it* section says `docker compose down` leaves `ollama` running — which Task 3 fixed.

- [ ] **Step 2: Rewrite the README's setup section**

`docker compose up --build` now brings up seven services and the whole product. Say what it costs on a cold cache — about 13GB of pulls and two 16.6GB images — because a reader who is not told will assume the command hung. The two former opt-in sections become one section on the lean stack and its single command. The *Stopping it* caveat about `ollama` surviving `down` is deleted, not reworded: it is no longer true.

- [ ] **Step 3: Update `architecture.md`**

It describes the model server as profiled and the default image as carrying no model runtime. Both are now false. It is a living document, so it describes the present; cite ADR-028 and ADR-029.

- [ ] **Step 4: Add the three stories to the backlog's Done table**

Add rows for STORY-078, STORY-079 and STORY-080 with a Sprint of `—`, matching the convention for work done outside a sprint. Update `Last reviewed` at the top of the file to the date this lands.

- [ ] **Step 5: Verify every link still resolves**

```bash
grep -oE '\]\([^)]+\.md[^)]*\)' README.md docs/specs/architecture.md | sed 's/](\(.*\))/\1/' | sed 's/#.*//' | sort -u | while read l; do [ -e "$(dirname README.md)/$l" ] || [ -e "docs/specs/$l" ] || [ -e "$l" ] || echo "MISS $l"; done
```

Expected: no `MISS` lines.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/specs/architecture.md docs/backlog/backlog.md
git commit -m "docs: one command brings up the whole product"
```

---

## Done when

- [ ] `docker compose config --services` lists seven services with no profile named.
- [ ] `docker compose up --build` starts the model server; `docker compose down` stops it, proved by an empty `docker ps --filter name=ollama`.
- [ ] `docker compose -f docker-compose.yml -f docker-compose.lean.yml up --build` serves `/health` with five services and a `policy_grapher-backend` under 1GB.
- [ ] `cd backend && uv run pytest` passes at 600 / 5 skipped.
- [ ] `docker compose run --rm frontend npm test` passes at 169.
- [ ] CI is green, and its compose job names `docker-compose.lean.yml`.
- [ ] ADR-021 carries a pointer to ADR-029 and is otherwise untouched.
