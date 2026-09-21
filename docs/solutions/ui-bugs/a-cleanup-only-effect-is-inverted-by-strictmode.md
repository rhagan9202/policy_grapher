---
title: A cleanup-only effect is inverted by StrictMode, and the suite cannot see it
date: 2026-09-21
last_updated: 2026-09-21
category: ui-bugs
module: the ingest screen (frontend/src/views/Ingest.tsx)
problem_type: ui_bug
component: frontend
related_components:
  - testing_framework
severity: high
symptoms:
  - A successful action leaves the screen where it was, with no error and no result
  - The network shows the request succeeded — `POST /api/ingest` returned 200
  - Reproducible on every attempt in `npm run dev`, invisible to the test suite
root_cause: logic_error
resolution_type: code_fix
tags:
  - react
  - strictmode
  - useeffect
  - lifecycle
  - test-harness-fidelity
  - refs
  - silent-failure
---

# A cleanup-only effect is inverted by StrictMode, and the suite cannot see it

## Problem

A `useRef` flag tracking whether a screen is still mounted was set `false` in an effect's cleanup
and never set back in its body. Under `React.StrictMode` the flag was `false` for the life of the
screen, so the navigation it guarded was refused on every attempt — silently disabling the headline
action of the feature it was added to protect.

## Symptoms

Choosing a PDF on `/ingest` and pressing Ingest:

- The screen stayed on `/ingest`. No result block, no error, no console output.
- `POST /api/ingest` returned **200** — the write had happened. Only the navigation was refused.
- Every attempt, every document, reproducible by hand in seconds.
- The test suite was green throughout: 405 passing frontend tests, including tests that assert
  exactly this navigation.

The combination is what made it hard: the expensive half succeeded, so nothing looked broken enough
to investigate. A screen that simply does not move reads as a slow request, not a defect.

## What Didn't Work

Nothing was tried and rejected — the defect was never suspected, which is the interesting part.
It survived, in order:

- **405 passing frontend tests**, four of which drive this exact flow and assert the landing.
- **A full `ce-code-review` spine**: six local reviewer personas (correctness, testing, reliability,
  project-standards, maintainability, learnings) plus a cross-model adversarial peer with
  `independence_verified: true`. Fourteen findings were retained; this was not among them.
- **Mutation testing of the guard itself.** The guard was mutated (`if (!onThisScreen.current)
  return` removed) and the mutation was caught. That certified the guard's *logic* and said nothing
  about its *lifecycle* — the mutation and the assertion were both fine; the harness differed from
  production.

It was found in the first minute of driving the branch in a browser.

## Solution

The defect, introduced in `31988fe` (PR #2) while fixing a genuine review finding — that a pending
ingest could haul back a reader who had navigated away:

```tsx
// Wrong: the body is empty. This only registers a cleanup.
const onThisScreen = useRef(true)
useEffect(() => () => { onThisScreen.current = false }, [])
```

The fix, `07667a0` (`frontend/src/views/Ingest.tsx:58-64`):

```tsx
const onThisScreen = useRef(true)
useEffect(() => {
  onThisScreen.current = true      // <- the half that was missing
  return () => {
    onThisScreen.current = false
  }
}, [])
```

The guard it protects is unchanged, at `frontend/src/views/Ingest.tsx:124`.

## Why This Works

`React.StrictMode` (mounted at `frontend/src/main.tsx:20`) deliberately double-invokes effects in
development: it mounts the component, runs every effect, runs every cleanup, and then runs the
effects again. This is intentional — it surfaces effects that are not resilient to being re-run.

An effect written as `() => () => { flag = false }` has **no body**. The first StrictMode cycle runs
its cleanup, setting the flag `false`; the remount runs the effect again, which registers a fresh
cleanup and does nothing else. Nothing restores the flag, so it stays `false` from the first render
onward — the exact inverse of the intended meaning.

Setting the value in the body makes the effect idempotent under re-invocation, which is what
StrictMode is checking for. The initial `useRef(true)` is not enough on its own: it is the value
before the first effect cycle, and the cycle overwrites it.

Production is unaffected — StrictMode's double-invoke is development-only. That is not a mitigation.
Development is where the product is built, demonstrated, and reviewed; a feature broken only in
`npm run dev` is broken for everyone who touches it before a deploy.

## Prevention

**1. A mount-scoped flag sets its value in the body and clears it in the cleanup.** The cleanup-only
form reads as complete and is not. This generalises past liveness refs to any flag whose meaning is
"this component is currently mounted".

```tsx
useEffect(() => {
  flag.current = true
  return () => { flag.current = false }
}, [])
```

**2. Render lifecycle-sensitive screens under StrictMode in their tests.** Before this fix, not one
of the repo's 11 view test files rendered under `StrictMode`, so the whole suite was structurally
blind to this class. The regression test
(`frontend/src/views/Ingest.test.tsx:429`, "still lands on the map under StrictMode") wraps the
render:

```tsx
render(
  <StrictMode>
    <MemoryRouter initialEntries={['/ingest']}>
      <Routes>
        <Route path="/ingest" element={<Ingest />} />
        <Route path="/" element={<MapStub />} />
      </Routes>
    </MemoryRouter>
  </StrictMode>,
)
```

It fails without the fix (`Unable to find an element by: [data-testid="map"]`) and passes with it.
A screen is lifecycle-sensitive when it holds a ref across an async boundary, subscribes to
something, or starts work in an effect whose result outlives the effect.

**3. Where a flow's value is what happens *after* a request, assert on the destination.** A 200 on
the wire is not evidence the feature worked. The four pre-existing tests all asserted the landing —
they simply did it in a harness that could not reproduce the failure, which is a different problem
from asserting the wrong thing.

**4. Mutation testing does not cover this class.** Mutating the guard perturbs its logic while
leaving the harness identical, so the mutation is caught and certifies nothing about the lifecycle.
Where the defect is a difference between the test environment and the runtime, no mutation of the
code under test can reach it — only running the code in the environment it ships in.

## Related

- `docs/solutions/best-practices/assert-and-mutate-the-exact-property-a-guard-test-protects.md` —
  the sibling failure mode, and the contrast worth holding. That document is about a test asserting
  the wrong property or against an insufficient fixture; this one is about a test asserting the
  right property, correctly, in an environment that cannot fail. Its rule 1 invariance check would
  not have found this defect.
- `docs/solutions/workflow-issues/the-test-count-is-not-the-verdict.md` — the third member of the
  set, and the one that would have caught this defect's cousin rather than this defect. There the
  suite genuinely failed and said so in its exit code, while the summary line it was being read
  through still said passed. Here the suite did not fail at all. Together the three cover the ways
  a green result can mean nothing: an assertion that cannot fail, a harness that cannot fail, and a
  verdict that was never read.
- `docs/dogfood-reports/2026-09-21-docs-dependency-map-home-plan-dogfood.md` — the run that found it,
  with the matrix and the census evidence for the two guarantees checked alongside it.
- `frontend/src/main.tsx:20` — where StrictMode is mounted, and therefore why development and
  production disagree.
- `AGENTS.md:47` — standing rule 4, "A gate must exercise the thing it gates". A suite that never
  renders under the mode the app runs in is a gate exercising a different system, one level up from
  the assertion.

**Merge state:** the defect shipped in PR #2 (`31988fe`) and was merged to `main`. The fix
`07667a0` is on `main` and pushed, reachable from `origin/main`, with CI green. Direct commits to
`main` rather than a PR, so the SHAs are stable rather than rebased.
