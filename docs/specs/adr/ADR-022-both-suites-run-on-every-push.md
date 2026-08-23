# ADR-022: Both suites run on every push, integration included

**Status:** Accepted · **Date:** 2026-08-22 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

Until now this project had no automated checks at all. `architecture.md` said so plainly, and
the [Definition of Done](../../backlog/README.md#definition-of-done) carried a `TODO` about it
from the day it was written. Every gate — 543 backend tests, ruff among them as `test_lint.py`,
and the frontend's chained eslint/tsc/vitest — depended on a person choosing to run two
commands.

Sprint 3 closed seven items that way and sprint 4 changed the most load-bearing code in the
project: a queue, a worker, and the dependency graph of the backend image. The surge was always
going to close a dozen defects; nothing would have caught the thirteenth.

The interesting question was never *whether* to have CI. It was what to do about the
integration half. 300 of the 543 backend tests carry `@pytest.mark.integration` and start real
Neo4j and Redis containers through testcontainers. They are slow, they need a Docker daemon,
and they are also the only tests that touch the database this product is built on.

## Decision

**Two jobs, on every push and every pull request, with the integration suite as its own step.**

1. **Trigger: `push` and `pull_request`, unfiltered by branch.** Restricting integration to
   `main` was considered and rejected — see below.
2. **The backend job runs `pytest` twice**: `-m "not integration"` and then `-m integration`.
   Not as a speedup. `pytest` exits **5** when a marker selects nothing, so a step selecting
   `-m integration` *fails* if the marker is renamed, the tests are deleted, or the suite is
   restructured — where a single combined `pytest` run would report a cheerful green over
   exactly that. Verified rather than assumed: `pytest -m "integration and nonexistentmarker"`
   returns 5 against this repository.
3. **`-rs` on both steps**, so skip reasons print. Two tests can only be demonstrated by a real
   model and skip loudly when it cannot be loaded; that message is worthless if the log never
   shows it.
4. **The backend job installs the full developer environment**, not `--no-dev`. Since
   [ADR-021](ADR-021-the-default-image-carries-no-model-runtime.md) the `dev` group pulls the
   `local-embeddings` extra and therefore torch. That is heavy and deliberate: ADR-021 made the
   library optional for the *image*, not for the suite, and a CI that quietly stopped
   exercising the real model would be the same silent-skip failure in a different coat.
5. **`npm ci`, not `npm install`**, and node pinned to 22 to match `frontend/Dockerfile`.
   `install` silently reconciles a lockfile that disagrees with `package.json`; `ci` fails.
6. **`tests/test_ci.py` guards the workflow's shape** — that both suites run, that integration
   is its own marker-selected step, and that the triggers are push and pull_request. A CI
   config is exactly the kind of file that gets "temporarily" trimmed under deadline pressure.

## Consequences

**Makes easy.** A defect in the database layer now fails a branch rather than waiting for a
person to remember `uv run pytest`. The Definition of Done's last gate stops being aspirational.

**Makes hard.** Every push pays for a torch install and 300 containerised tests — roughly 77
seconds of integration time measured locally, plus setup. uv and npm caching absorb some of it;
the `concurrency` block cancels superseded runs so a branch under active work does not queue
runs describing commits nobody is waiting on. If this becomes the bottleneck, the honest fix is
to make the suite faster, not to stop running half of it.

**Assumption:** GitHub-hosted `ubuntu-latest` runners provide a usable Docker daemon and enough
disk for Neo4j, Redis and torch together. This follows from testcontainers' documented support
and standard runner specifications, but **it has not been observed on a real run** — no run of
this workflow has executed at the time of writing, because the repository had no CI to compare
against. The first push is the experiment. If disk is the binding constraint, the first thing
to try is dropping the `local-embeddings` extra from the CI install and accepting two loud
skips, which is a smaller loss than dropping integration.

## Alternatives considered

**Integration on `main` and pull requests only, unit tests on every push.** The genuinely
tempting option: it keeps the inner loop fast and still gates anything that merges. Rejected
because it makes "green" mean two different things depending on where you look, and the weaker
meaning is the one a developer sees most often — on their own branch, mid-work, which is
precisely when they are deciding whether a change is safe. A check whose reassurance is
conditional on a branch name teaches people to trust it in the cases where it is wrong.

**A third job building the compose images.** The Definition of Done's last gate is "runs under
`docker compose up` from a clean checkout", and nothing here proves it. Considered and
deliberately deferred: it is worth doing, it is not what STORY-051 asked for, and adding it in
the same change would have meant shipping an unrequested job alongside an unproven workflow.
Left as a follow-up rather than smuggled in.
