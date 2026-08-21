# DI-2 Phase 4: Typed Links and the Review Queue — Implementation Plan

**Status:** Complete. Verified on 2026-08-20 with `uv run pytest` (419 passed), including the integration suite against a real `neo4j:2025.10` container.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link an org obligation to the higher-level obligation it implements — proposed by machine, promoted only by a human, and surviving a full rebuild of the derived layer.

**Architecture:** Two relationship types, not one with a status property: `IMPLEMENTS_PROPOSED` (derived, machine-authored) and `IMPLEMENTS` (promoted by a human). Triage traverses `IMPLEMENTS` only, so an unreviewed inference cannot read as fact *by construction*. Verdicts live in a canonical `:LinkDecision` keyed by content, so a rebuild replays them instead of discarding them.

**Tech Stack:** FastAPI, Pydantic v2, neo4j Python driver 6.x, pytest + testcontainers, the Phase 3 extraction port.

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Human decisions live in the canonical layer* and *Change detection, triage, and review*.

**Depends on:** Phase 3 — `:Obligation` nodes exist with deterministic ids anchored to chunks.

## Global Constraints

- Python `>=3.14`; deps via `uv`. Add nothing to `pyproject.toml`.
- Ruff enforced **as a test**. Integration tests use real `neo4j:2025.10`; never mock the driver.
- Relationship types are directed `SCREAMING_SNAKE_CASE` verb phrases read source → target ([ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)).
- `:LinkDecision` is **canonical**. It is never dropped by a rebuild and never derived from anything.
- `IMPLEMENTS_PROPOSED`, `IMPLEMENTS`, `APPLIES_TO`, `ENFORCED_BY` are **derived** — droppable, rebuildable.
- One reviewer is sufficient per link (confirmed by the project owner, 2026-08-20). No second approver, no segregation of duties.
- Documentation updated in the same change.

## Decisions an executor must not silently change

**1. Two edge types, never one with a `status` property.** A status property means every consumer must remember to filter, and the first one that forgets presents a machine guess as an approved fact. Two types make the mistake impossible to write: the triage query names `IMPLEMENTS` and simply cannot see a proposal.

**2. Rejections are stored, not just approvals.** A rebuild that resurrects a link someone already rejected is worse than one that forgets an approval — it silently re-adds work a human already did and dismissed.

**3. The decision key is content-derived, never a node id.** `hash(source_obligation_id, target_obligation_id)`. Both are already deterministic from Phase 3, so the key survives re-extraction. A key built from an internal node id would not.

**4. Promotion is one-way through the decision.** Nothing writes an `IMPLEMENTS` edge directly. The only path is: proposal exists → human verdicts it → replay promotes it. That keeps a single code path to audit.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/links/propose.py` | *Create* — candidate generation and rationale |
| `backend/src/policy_grapher/links/decisions.py` | *Create* — `:LinkDecision`, promotion, replay |
| `backend/src/policy_grapher/links/rebuild.py` | *Create* — drop the derived layer, re-extract, replay |
| `backend/src/policy_grapher/routers/review.py` | *Create* — the review queue API |
| `backend/src/policy_grapher/db.py` | *Modify* — decision constraint |
| `backend/tests/test_links.py`, `test_rebuild.py`, `test_review.py` | *Create* |
| `docs/specs/adr/ADR-014-*.md` | *Create* — proposals and decisions are different things |

---

### Task 1: Proposing links

**Files:**
- Create: `backend/src/policy_grapher/links/propose.py`, `backend/tests/test_links.py`

**Interfaces:**
- Consumes: `:Obligation` nodes from Phase 3; the Phase 3 extraction port pattern for the rationale call
- Produces: `propose_links(tx, *, org_version_id, candidate_version_ids, proposer) -> int`

Candidate generation is deliberately cheap here: lexical overlap plus shared designator
references, over obligations in the named higher-tier versions. Phase 6's hybrid retrieval
will improve recall; this phase needs *something* to review, and a weak proposer with a
human gate is safe in a way a strong proposer without one is not.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_links.py` covering, each as a real test with assertions:
- a proposal creates `(:Obligation)-[:IMPLEMENTS_PROPOSED]->(:Obligation)` with `confidence` and `rationale` on the edge
- proposing twice creates one edge, not two
- **a proposal never creates an `IMPLEMENTS` edge** — assert the count of `IMPLEMENTS` is zero after proposing. This is the invariant the whole phase rests on
- an obligation with no plausible counterpart yields no proposal (an empty queue is a correct outcome)
- a proposal carries the `proposer` id, so a later rebuild can tell machine-authored edges apart

- [x] **Step 2: Run to verify failure, then implement**

`propose_links` matches org obligations against higher-tier ones, writes
`IMPLEMENTS_PROPOSED` with `confidence`, `rationale`, and `proposer`, and returns the count.
The rationale is one sentence written for a human about to make a decision — what the two
obligations have in common and why the link is plausible.

- [x] **Step 3: Run tests and commit**

```bash
git add backend/src/policy_grapher/links backend/tests/test_links.py
git commit -m "feat: propose which org obligation implements which higher one"
```

---

### Task 2: Decisions and promotion

**Files:**
- Create: `backend/src/policy_grapher/links/decisions.py`
- Modify: `backend/src/policy_grapher/db.py`, `backend/tests/test_links.py`

**Interfaces:**
- Produces: `decision_key(source_id, target_id) -> str`, `record_decision(tx, *, source_id, target_id, verdict, actor, rationale) -> None`, `replay_decisions(tx) -> tuple[int, int]` returning `(promoted, suppressed)`

*Executor's note (2026-08-20):* `replay_decisions` returns a dict of three counts, not a two-tuple. Task 3 requires a rebuild to report an approval it could no longer apply, and `(promoted, suppressed)` has no slot for it — an approval whose obligations vanished is neither. The third count is `unpromotable`.

- [x] **Step 1: Add the constraint**

```python
    (
        "CREATE CONSTRAINT link_decision_key_unique IF NOT EXISTS "
        "FOR (d:LinkDecision) REQUIRE d.key IS UNIQUE"
    ),
```

- [x] **Step 2: Write the failing tests**

Append to `backend/tests/test_links.py`:
- approving a proposal creates an `IMPLEMENTS` edge and leaves the proposal in place
- **rejecting a proposal creates no `IMPLEMENTS` edge and records the rejection** — then assert re-running `replay_decisions` still creates none
- a decision records `actor` and `at`
- re-deciding the same pair updates the verdict rather than creating a second decision
- `replay_decisions` is idempotent — running it twice yields the same graph
- `decision_key` is symmetric-free: `(a, b)` and `(b, a)` are different keys, because "A implements B" is not "B implements A"

- [x] **Step 3: Implement**

`record_decision` merges a `:LinkDecision {key}` with `verdict`, `actor`, `at`, `rationale`.
`replay_decisions` walks decisions and, for each `approve`, merges the `IMPLEMENTS` edge;
for each `reject`, ensures no such edge exists. It is the **only** writer of `IMPLEMENTS`.

- [x] **Step 4: Run tests and commit**

```bash
git add backend/src/policy_grapher/links backend/src/policy_grapher/db.py backend/tests/test_links.py
git commit -m "feat: a human verdict promotes a proposal, and survives"
```

---

### Task 3: Rebuild the derived layer without losing a decision

**Files:**
- Create: `backend/src/policy_grapher/links/rebuild.py`, `backend/tests/test_rebuild.py`

**Interfaces:**
- Produces: `rebuild_derived(driver, database, *, version_id, extractor) -> dict` reporting what was dropped, re-extracted and replayed

**This task is the one that makes "rebuildable overlay" a fact rather than an intention.**
If it is wrong, every later phase inherits a graph whose human decisions quietly evaporate.

- [x] **Step 1: Write the failing test — the whole point of the phase**

Create `backend/tests/test_rebuild.py`:

```python
@pytest.mark.integration
def test_a_rebuild_preserves_every_human_decision(clean_graph, database, ...):
    """Drop the derived layer, re-extract, replay. Approvals and rejections both survive.

    This is the test that makes the overlay safe to rebuild. If it fails, the
    derived layer is not rebuildable and phase 5 must not start.
    """
    # 1. Ingest, extract, propose.
    # 2. Approve one proposal, reject another.
    # 3. Snapshot: the set of IMPLEMENTS edges, and the set of decisions.
    # 4. rebuild_derived(...)
    # 5. Assert the IMPLEMENTS set is identical, the rejected pair is still
    #    absent, and the decisions are unchanged in count, verdict and actor.
```

Write it out in full against the real fixtures — do not leave the numbered comments as the test.

Add three more:
- a rebuild drops and recreates chunks and obligations (counts match, ids identical)
- a rebuild after an extractor change that *removes* an obligation leaves its decision recorded but unpromotable, and reports that in the return value rather than silently
- a rebuild leaves `:Document`, `:DocumentVersion`, `:Source` and `:Authority` untouched

- [x] **Step 2: Run to verify failure, then implement**

`rebuild_derived` in one transaction: `drop_obligations` → `drop_chunks` → re-chunk →
re-extract → `write_chunks` → `write_obligations` → `propose_links` → `replay_decisions`.

*Executor's note (2026-08-20):* on the project owner's decision, re-chunking and re-extraction run *before* the transaction opens; everything that mutates the graph still runs inside one `execute_write`, so the atomic swap this step is protecting is preserved. A model call per chunk inside an open write transaction would hold Neo4j locks across minutes of network I/O. The pages come from re-reading the PDF at the version's `source_uri` — stored chunk text cannot be re-chunked differently, which is the main reason to rebuild. The signature gained `candidate_version_ids` and `proposer`, which `propose_links` needs and the stated one had no way to supply.
Return a dict of counts so a caller can see what happened. Decisions are never touched.

- [x] **Step 3: Run tests and commit**

```bash
git add backend/src/policy_grapher/links/rebuild.py backend/tests/test_rebuild.py
git commit -m "feat: rebuilding the derived layer keeps every human decision"
```

---

### Task 4: The review queue API

**Files:**
- Create: `backend/src/policy_grapher/routers/review.py`, `backend/tests/test_review.py`
- Modify: `backend/src/policy_grapher/main.py`, `backend/src/policy_grapher/models.py`
- Create: `docs/specs/adr/ADR-014-proposals-and-decisions-are-different-things.md`

**Interfaces:**
- Produces: `GET /review/queue` → unreviewed proposals with both obligations, both citations, rationale and confidence; `POST /review/{source_id}/{target_id}` taking `{verdict, rationale}` and recording the decision as the authenticated principal

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_review.py` covering:
- the queue returns a proposal with **both sides' citation** — `section_path` and `page` for each — because a reviewer cannot decide without them
- an already-decided pair does not reappear in the queue
- posting a verdict records the **authenticated principal** as `actor`, not a client-supplied name
- posting an unknown verdict is a 400
- both routes require a principal (the Phase 0 property test enforces this, but assert it here too — this is the route that writes an audit record)

- [x] **Step 2: Implement, wire the router into `main.py`, and run**

The `actor` comes from `Depends(require_principal)` and nowhere else. A client-supplied
actor field would make the audit trail worthless.

- [x] **Step 3: Write ADR-014**

Must state: why two edge types rather than a status property; that rejections are stored
and why; that the decision key is content-derived so it survives re-extraction; that
`replay_decisions` is the sole writer of `IMPLEMENTS`; and that one reviewer is sufficient,
confirmed by the project owner on 2026-08-20, with the note that `:LinkDecision`'s shape
allows more than one verdict per key without migration if a control framework later
requires dual approval.

- [x] **Step 4: Run everything and commit**

```bash
git add backend/src/policy_grapher backend/tests docs/specs/adr/ADR-014-proposals-and-decisions-are-different-things.md
git commit -m "feat: a review queue a human can actually decide from"
```

---

## Done when

- Proposing never creates an `IMPLEMENTS` edge — asserted, not assumed
- Approving promotes; rejecting is remembered and stays unpromoted across replays
- **A full rebuild of the derived layer preserves every approval and every rejection**
- The queue shows both obligations with page and section citations
- `actor` comes from the authenticated principal, never from the request body
- ADR-014 exists

Phase 5 (diff and propagation) can start.
