---
title: Assert and mutate the exact property a guard test protects
date: 2026-09-17
category: best-practices
module: policy_grapher.graph (focused-view render budget, backend/src/policy_grapher/graph.py)
problem_type: best_practice
component: testing_framework
related_components:
  - service_layer
  - api_layer
severity: high
applies_when:
  - A test guards an ordering, priority, or tier-selection invariant
  - Code orders a collection and then truncates it to a budget or cap
  - A test fixture sits on the boundary between two priority tiers
  - Validating a new test by mutation before trusting it
  - A plan states an explicit prohibition the implementation must obey
tags:
  - guard-tests
  - mutation-testing
  - test-assertions
  - vacuous-tests
  - ordering-invariants
  - boundary-conditions
  - truncation
  - regression-testing
---

# Assert and mutate the exact property a guard test protects

This specialises standing rule 4, **"A gate must exercise the thing it gates"** (`AGENTS.md:47`),
from ML eval gates down to unit tests. The rule already says a gate measuring a different system
means nothing about production. The same holds one level smaller: an assertion that cannot vary
with the property it claims to guard is measuring a different property, and its green tick means
nothing about that property.

## Context

The graph endpoint gained a focused mode: given one document slug, return that document and its
dependency neighbourhood — what it cites and what cites it — and nothing else
(`backend/src/policy_grapher/graph.py:89-165`). Every mode is bounded by a render cap,
`graph_render_cap: int = 300` (`backend/src/policy_grapher/config.py:26`).

The corpus-wide mode spends that cap corpus-first: all 23 in-corpus documents survive, externals
take what is left (`graph.py:232-237`). Carrying that allocation into the focused mode is the
defect. A budget that admits the neighbourhood first and then lets the rest of the corpus fill the
remainder reads as a sensible priority order and is not one: 23 documents against a cap of 300
means the second tier always fits whole. Every focused request would have returned the entire
corpus — which is exactly what the mode exists not to do.

**It was caught twice, at two stages, by two different reviewers.** A document reviewer caught it
in the written plan before any code existed, and the plan then carried the warning explicitly:

> A focused view does not re-rank that list — it replaces it: documents outside the neighbourhood
> are never admitted at any budget, because at this corpus's size they would always fit and the
> view would silently become the corpus again.
> — `docs/plans/2026-09-17-0801-feat-dependency-map-home-plan.md:244` (KTD2), echoed at `:374`

The implementation — same session, working from that document — reproduced the defect anyway, and
a code reviewer caught it a second time in the diff.

**Then the guard test written for the fix did not guard.** It asserted counts only: how many nodes
survived, not which ones. The fixture `dodi-3115-14` sits exactly on the tier boundary — two
in-corpus neighbours and six external, against a budget of three. Reverse the two tiers and you get
the same count, the same `truncated` flag, the same `total_nodes`, and the same non-null basis. The
guard passed under the regression it existed to catch.

**Mutation testing ran, three times, and missed it.** Three mutations were applied and each was
correctly caught by its intended test, which produced false assurance. They perturbed the focused
node's *position* in the ordering, the truncation-reason field's *nullability*, and the
*composition* of the neighbourhood set. None perturbed the tier ordering — the one property the
count-based test claimed to guard. A fourth mutation, reversing corpus-before-external, was run
only after review flagged the gap; it failed the new identity-based test.

## Guidance

### 1. The invariance check: evaluate the assertion under the defect before accepting it as a guard

A procedure you can run on paper in under a minute:

1. Write down the wrong implementation **W** that violates the property **P** you claim to guard.
   Here, W is swapping the two tiers at `graph.py:144`.
2. Evaluate every assertion in the test under W, with the test's real fixture and real parameters.
3. If the assertions come out the same under W as under the correct code, the test does not guard
   P. Do not argue that it "covers" P. Change the fixture so the values diverge, or change the
   assertion to read a quantity that depends on P.

For this code the failure is derivable, not a judgement call. Look at what the three reported
quantities are functions of:

```python
total_nodes = len(ordered)                                                       # graph.py:146
kept = ordered[: max(1, limit)] if limit is not None and limit > 0 else ordered  # graph.py:149
truncated = len(kept) < total_nodes                                              # graph.py:156
```

`len(kept)` is `min(limit, len(ordered))`. `total_nodes` is `len(ordered)`. `truncated` compares
the two. All three are functions of the budget and the population size alone — **none is a function
of the order of `ordered`**. So no assertion built only from `returned_nodes`, `total_nodes`, or
`truncated` can observe a permutation of the ordering, on any fixture, ever. That is not a
heuristic about weak tests; it is a property of the code, readable off the three lines above.

**The checkable rule:** *if an assertion can be written as a function of inputs that exclude the
property under test, it does not test that property.* For a truncating selector, ordering is
observable only through element identity. Assert identity.

### 2. Derive the expectation from the source of truth, size the budget from it, and prove the derivation is non-empty

The replacement test does all three (`backend/tests/test_graph.py:410-437`):

```python
corpus_neighbours, _, _ = driver.execute_query(
    "MATCH (d:Document {slug: 'dodi-3115-14'})-[:REFERENCES]-(n:Document) "
    "WHERE NOT n:External "
    "RETURN collect(DISTINCT n.slug) AS slugs",
    database_=database,
    routing_=RoutingControl.READ,
)
expected = set(corpus_neighbours[0]["slugs"])
assert expected, "fixture no longer has corpus neighbours to prioritise"

graph = build_graph(driver, database, focus="dodi-3115-14", limit=1 + len(expected))

assert {node.id for node in graph.nodes} == {"dodi-3115-14", *expected}
assert all(not node.is_external for node in graph.nodes)
assert graph.truncated is True
```

Three things are separately load-bearing:

- **The expectation is queried, not hardcoded.** A literal `== 3` decays into a lie the moment the
  sample corpus changes; a query re-derives the truth.
- **The budget is computed from the derived set** (`limit=1 + len(expected)`). This keeps the test
  *on the tier boundary* when the fixture shifts. A hardcoded `limit=3` against a fixture that grows
  a third corpus neighbour silently stops testing the boundary and starts testing something easier.
- **The derivation's own liveness is asserted.** A dynamically derived expectation can degrade to
  vacuous: if `expected` came back empty, the set equality reduces to `{focus} == {focus}` and passes
  forever while testing nothing. That one-line `assert expected, ...` is the cost of choosing
  derivation over literals, and it is not optional.

### 3. Mutation coverage is property-addressed, not counted

"We ran three mutations and all three were caught" is not a statement about coverage. A mutation
certifies exactly the property it perturbs and nothing adjacent. Mutations of position, nullability,
and set membership tell you position, nullability, and set membership are guarded; they say nothing
about tier ordering, which is a fourth, independent property.

The practice: **for each claim a test's docstring makes, name the mutation that falsifies exactly
that claim.** If you cannot name one, the claim is decoration. Write that list *before* mutating,
derived from the docstrings — not after, derived from what was convenient to break.

This refines the standing action carried across sprints 6-10, "When a new test passes on its first
run, mutate the thing it guards before believing it" (`docs/sprints/sprint-09/retrospective.md:106`;
tracked as Standing at `docs/sprints/sprint-08/retrospective.md:71`). Mutation was performed here, three times,
and the vacuous check survived all three. The gap was not *whether* to mutate but *what*: mutating
something in the neighbourhood of the code is not mutating the property. Address mutations to
properties by name.

### 4. A plan's warning owes an implementing test named for it

The plan said the thing, twice, in the section the implementer was working from, and the defect was
reproduced anyway. The lesson is not that the warning was badly written — it is as direct as prose
can be. It is that prose in a plan protects nothing at execution time. When a plan contains a
"do not do X" warning, the unit implementing it owes a test named for X that fails when X is done.
That test now exists as `test_documents_outside_the_neighbourhood_are_never_admitted`
(`test_graph.py:330-348`), and its name is the warning.

Note what this is *not*: evidence that standing rule 7 ("A spec is adversarially checked before it
becomes a plan", `AGENTS.md:84`) failed. Rule 7 worked — the adversarial document review is what
caught this the first time. The gap is downstream of it: nothing requires code review to re-check
an implementation against the plan's own named prohibitions.

The same plan anticipated the *adjacent* failure and still did not prevent this one:

> **Execution note:** the existing graph tests encode corpus-first budget allocation as their
> premise. Rewrite them to assert the new allocation deliberately rather than adjusting numbers
> until they pass.
> — `docs/plans/2026-09-17-0801-feat-dependency-map-home-plan.md:377`

"Assert the new allocation deliberately" was followed in spirit — a new test was written for it —
and still produced an assertion blind to the allocation. Deliberateness is necessary and not
sufficient; the invariance check in rule 1 is what makes it sufficient.

## Why This Matters

The failure mode is silent, which is why nothing downstream would have caught it. A focused request
under the defect returns HTTP 200, a well-formed `GraphOut`, a node count comfortably under the cap,
and `truncated: false` with a null basis — the field whose null value is defined as "nothing was
dropped" (`graph.py:164`). Nothing in the response says "you asked for one document's neighbourhood
and I gave you the corpus". The renderer draws 29 nodes where 9 were asked for, and the mode's whole
justification — that a focused view is dense and legible where a corpus view is mostly empty space —
evaporates without a single error.

The tier-ordering half is worse in one respect: it stays invisible until a neighbourhood actually
exceeds the budget. On today's corpus the largest focused view is small, so the wrong tier order is
latent. It surfaces the day a heavily-cited document is focused, by dropping the in-corpus
dependencies an analyst is there to see in favour of more-frequently-cited external names — and it
surfaces as a plausible-looking graph, not as a failure.

**There is prior art for this question in the very same test file.**
`test_tie_break_keeps_the_lexicographically_smaller_slug_at_the_boundary`
(`test_graph.py:110-123`) exists because someone already worked it through for the corpus-wide mode,
and its comment says so outright:

> Reversing that ORDER BY clause to slug DESC keeps every other test in this file green, because
> every other test asserts counts or degrees far from this boundary.

The rule was already known here, written seven lines deep in one test's comment, and applied to the
corpus-wide path — and the new focused path repeated the mistake it documents. That is the argument
for stating it as a practice rather than a comment on one test.

## When to Apply

Run the invariance check whenever the code under test does any of these:

- **Orders, then truncates by a budget.** The count of survivors is `min(limit, total)` whatever the
  order is.
- **Assigns items to priority tiers** that are then flattened into one sequence.
- **Tie-breaks.** A tie-break is by definition invisible to every aggregate, since the tied items are
  interchangeable by every measure except identity.
- **Filters, deduplicates, or merges** where two different rules yield sets of the same size.
- **Sorts for presentation** where the test looks at how many rows came back.

A quicker trigger for the same set: *if you can compute the assertion's expected value from the
fixture size and the parameters, without knowing how the code ranks anything, the assertion is blind
to ranking.*

**Counts are sufficient when the defect changes cardinality**, and the same session supplies the
contrast. The outside-admission defect at `limit=300` returns 29 nodes where the correct code returns
9 — a count assertion catches it outright. The tier-reversal defect at `limit=3` returns 3 either
way. Same file, same fixture, two defects, opposite observability. The rule is not "never assert
counts"; it is "check, per property, whether the count moves". Where it moves, a count is a fine and
cheap guard. Where it does not, identity is the only guard there is.

A cheap tell that you are in the second case: the test's docstring contains *which*, *instead of*, or
*over* — "keeps X over Y", "chooses A instead of B". Those are identity claims. A count cannot make
them.

## Examples

### Before — the guard that did not guard

This shape was never committed, so the following is a reconstruction from the session rather than a
git artifact. Its shape is the point:

```python
def test_truncation_keeps_corpus_neighbours_over_external_ones(loaded):
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14", limit=3)

    assert graph.returned_nodes == 3
    assert graph.truncated is True
```

Now run the invariance check. W = swap the two tiers at `graph.py:144`:

```python
# correct  (graph.py:144)
ordered = [focused, *corpus_neighbours, *(entry[2] for entry in external_neighbours)]
# W
ordered = [focused, *(entry[2] for entry in external_neighbours), *corpus_neighbours]
```

The fixture's neighbourhood is 1 focus + 2 corpus + 6 external = 9 nodes.

| | correct | under W |
|---|---|---|
| `returned_nodes` | 3 | 3 |
| `total_nodes` | 9 | 9 |
| `truncated` | `True` | `True` |
| `truncation_basis` | non-null | non-null |
| `nodes[0].id` | `dodi-3115-14` | `dodi-3115-14` |
| **node ids** | **focus + 2 corpus neighbours** | **focus + 2 highest-degree externals** |

Every row but the last is identical. The test asserted rows one and three.

### After — the guard that guards

`backend/tests/test_graph.py:410-437`, quoted in full under Guidance rule 2. Under W the returned
ids are the two externals, both identity assertions fail, and the count assertion that survived W is
no longer what the test rests on. The tier-reversal mutation was run against it after review flagged
the gap, and failed — which is the only evidence distinguishing this test from its predecessor, since
both are green against correct code.

### The companion guard for the outside-admission half

`test_graph.py:330-348` pins the other property at a budget where the neighbourhood is not truncated
at all, deriving the expected set the same way. Note that this one *would* have worked as a count
assertion (9 vs 29) and is still written as identity. That is the right default when the two cost the
same: identity is never weaker, and the query that derives it is three lines.

### The fix it all guards

```python
corpus_neighbours.sort(key=lambda node: node.id)
external_neighbours.sort(key=lambda entry: (entry[0], entry[1]))
ordered = [focused, *corpus_neighbours, *(entry[2] for entry in external_neighbours)]
```
— `backend/src/policy_grapher/graph.py:142-144`

Nothing from outside the neighbourhood is ever a candidate: `ordered` is built only from `focused`
and the nodes the `NEIGHBOURS` traversal returned. The wider corpus is not ranked lower, it is not
present. The slice at `graph.py:149` uses `max(1, limit)` so the focused document survives any
budget, and the docstring at `graph.py:99-106` carries the reasoning forward for the next reader.

## Related

- `AGENTS.md:47` — standing rule 4, "A gate must exercise the thing it gates". The governing
  principle this document specialises to unit-test assertions.
- `AGENTS.md:84` — standing rule 7, "A spec is adversarially checked before it becomes a plan". It
  worked here; the gap this incident exposes is downstream of it, at plan-to-implementation.
- `docs/sprints/sprint-08/retrospective.md:71`, `docs/sprints/sprint-09/retrospective.md:106`,
  and `docs/sprints/sprint-10/retrospective.md:88` — the standing "mutate the thing it guards" action
  that Guidance 3 refines.
- `docs/sprints/sprint-07/retrospective.md:9` — "A check written against literals is a check against
  literals. Measure the shape." The nearest existing analogue: same family, but about hardcoded
  literals rather than about reported fields being provably insensitive to a permutation.
- `docs/specs/adr/ADR-002-external-references-and-corpus-first-graph.md` — origin of the 23 / 300 /
  438 figures and of the corpus-first allocation the buggy draft copied instead of replacing.
- `docs/specs/adr/ADR-038-the-document-table-pages-rather-than-caps.md` — the other place this repo
  reasons about caps, truncation, and what a reader can still reach.
- `docs/plans/2026-09-17-0801-feat-dependency-map-home-plan.md:244` (KTD2), `:374`, `:377` — where the
  rule was written down before the code, and did not prevent the defect.

**Merge state:** the work this documents is uncommitted on the branch named
docs/dependency-map-home-plan, across `backend/src/policy_grapher/graph.py`,
`backend/src/policy_grapher/routers/graph.py`, `backend/src/policy_grapher/ingest.py`,
`backend/src/policy_grapher/models.py`, `backend/tests/test_graph.py`, and
`backend/tests/test_ingest.py`. There is no PR. The backend suite is container-backed and was not
re-run while writing this.
