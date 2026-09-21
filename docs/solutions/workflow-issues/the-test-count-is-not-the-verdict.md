---
title: The test count is not the verdict — read the exit code
date: 2026-09-21
category: workflow-issues
module: the frontend gate (frontend/package.json, `npm test`)
problem_type: workflow_issue
component: testing_framework
related_components:
  - frontend
  - development_workflow
severity: high
applies_when:
  - Reporting whether a quality gate passed
  - Reading a test runner's output through grep, a summary line, or a scraped count
  - A change adds work that runs outside a test body — an effect, a timer, a floating promise
symptoms:
  - The runner prints a full passing count and the command still fails
  - A gate is reported green and CI disagrees on the same commit
  - An Errors line appears beside a passing Tests line and is filtered out of view
root_cause: incomplete_setup
resolution_type: workflow_improvement
tags:
  - vitest
  - exit-codes
  - quality-gates
  - unhandled-rejection
  - verification
  - false-green
---

# The test count is not the verdict — read the exit code

## Context

This repo's frontend gate is one command running lint at zero warnings, a full type build, then
vitest. `AGENTS.md:13` gives it in its containerised form; run directly it is `cd frontend && npm
test`, which is the form CI uses and the form these examples show. Either way it is a single exit
code covering three tools. Checking it by eye or by `grep` on the summary is the obvious thing to
do, and for most runners it is safe — a failure moves the count.

Vitest does not always move the count. Work that throws **outside a test body** — inside a React
effect, a timer, a floating promise — is reported as an *unhandled error*, in its own section, while
every per-test tally still says passed. The command fails; the numbers do not.

This was measured on this repo rather than assumed. Restoring a real historical defect (a value read
one line outside the `try` that reports its failure, so a malformed answer threw past every branch)
and running a single test that reaches it produces exactly this:

```
EXIT CODE: 1
⎯⎯⎯⎯⎯⎯ Unhandled Errors ⎯⎯⎯⎯⎯⎯
TypeError: Cannot read properties of undefined (reading 'at')
 Test Files  1 passed (1)
      Tests  1 passed | 105 skipped (106)
     Errors  1 error
```

`Test Files` says passed. `Tests` says passed. Only `Errors` and the exit code say otherwise.

## Guidance

**Gate on the exit code. Always.** It is the only line that merges every failure mode the runner
knows about.

```bash
# The check
npm test > /tmp/gate.log 2>&1; echo "exit=$?"

# Not the check
npm test 2>&1 | grep -E "Tests  "
```

When a summary is wanted as well as the verdict, print both and let the exit code decide:

```bash
npm test > /tmp/gate.log 2>&1; code=$?
grep -E "Test Files|Tests  |Errors" /tmp/gate.log
echo "exit=$code"
```

Note `Errors` in that grep. A filter written for `Test Files|Tests` omits the one line that
contradicts them, which is how a green report gets made over a red run.

## Why This Matters

The defect class that separates the count from the verdict is not an exotic one. It is precisely the
class that escapes a component's own error handling: a throw that no `catch` in the change is
positioned to catch. Those are the failures most worth hearing about, and they are the ones the
per-test tally is least able to report.

In the session that produced this document, that gap let a **real production defect** be reported as
a green gate twice. The panel that reads a document's editions could be left loading for ever with
nothing on screen to say why, and the suite answered `403 passed`. CI caught it; the local gate had
been saying so all along, on a line that was being filtered out.

The cost is not only the missed bug. Reporting a gate green when it is red spends trust that is
expensive to rebuild, and it does so in the one place where a reader has every reason to believe the
report.

## When to Apply

- **Whenever a gate's result is being reported to someone**, by a person or an agent. The exit code
  is the claim; anything else is commentary on it.
- **Whenever a change adds work outside a test body.** Effects, subscriptions, timers, and `void
  somePromise()` all run where the per-test tally cannot see them fail. This repo's map and ingest
  screens do all of these.
- **Whenever a check is scripted.** A human running the command interactively sees the `Errors`
  section scroll past; a grep does not. The narrower the filter, the more confident and the more
  wrong the resulting report.
- **Not** only for vitest. The rule is runner-agnostic; the specific shape above is vitest's.

## Examples

### Before — a filter that could only report success

```bash
npx vitest run 2>&1 | grep -E "Test Files|Tests  "
#  Test Files  14 passed (14)
#       Tests  403 passed (403)
```

Reported as "gate green, 403 tests". The run had exited non-zero. The `Errors` line existed and sat
one row below the last line the filter kept.

### After — the verdict, with the summary as context

```bash
npm test > /tmp/gate.log 2>&1; echo "npm test exit=$?"
grep -E "Test Files|Tests  |Errors" /tmp/gate.log
#  npm test exit=0
#   Test Files  14 passed (14)
#        Tests  405 passed (405)
```

Same command, same summary, and now a line that can say no.

### The defect underneath, for shape

The historical version of `frontend/src/views/GraphExplorer.tsx` read the newest edition one line
outside the `try` that reports an editions failure:

```ts
editions = await listVersions(slug)
} catch (cause) { /* reports the failure */ }
if (cancelled) return
const newest = editions.at(-1)   // <- outside every catch
```

An answer that was not a list threw from here, past the error branch, past the empty branch, past
the render — leaving the panel on "Reading what it holds…" with no error anywhere. The current code
performs that read inside the guard (`frontend/src/views/GraphExplorer.tsx:606-612`), and a test
covers it ("reports an unreadable editions answer rather than reading for ever").

## Related

- `docs/solutions/ui-bugs/a-cleanup-only-effect-is-inverted-by-strictmode.md` — the other way this
  suite told the truth about the wrong thing. That one is a test harness that could not reproduce
  the failure; this one is a passing harness whose verdict was read off the wrong line. Both shipped
  through the same review.
- `docs/solutions/best-practices/assert-and-mutate-the-exact-property-a-guard-test-protects.md` —
  the third member of the family, about assertions that cannot fail. Together: an assertion that
  cannot fail, a harness that cannot fail, and a verdict that was not read.
- `AGENTS.md:47` — standing rule 4, "A gate must exercise the thing it gates". A gate whose result
  is read off a line that cannot express failure is not being read at all.
- `AGENTS.md:13` — the frontend gate's definition: one command running ESLint, the TypeScript build
  checks and Vitest, which is what makes its single exit code authoritative over any one summary
  line inside it.

**Merge state:** the defect this document uses as its worked example was fixed in `2b760d1`, merged
to `main` in PR #2 and reachable from `origin/main`. This document records the reporting failure
around it, which nothing in the tree otherwise captures.
