# DI-2 Phase 5: Change Detection and Propagation — Implementation Plan

**Status:** Complete. Verified on 2026-08-20 with `uv run pytest` (456 passed), including the integration suite against a real `neo4j:2025.10` container.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the question the whole increment exists for — *a higher-level policy changed; which of our policies are affected, and how urgently?*

**Architecture:** Diff obligations between two `:DocumentVersion`s to produce `:Change` nodes, then propagate along `IMPLEMENTS` to reach the org obligations that depend on them. Both stages are graph queries, not model calls, which is why the answer is explainable, cheap to test, and cannot hallucinate an obligation into the result.

**Tech Stack:** FastAPI, Pydantic v2, neo4j Python driver 6.x, pytest + testcontainers.

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Change detection, triage, and review*.

**Depends on:** Phase 4 — `IMPLEMENTS` edges exist and are human-promoted.

## Global Constraints

- Python `>=3.14`; deps via `uv`. Add nothing to `pyproject.toml` — this phase is Cypher and arithmetic.
- Ruff enforced **as a test**. Integration tests use real `neo4j:2025.10`; never mock the driver.
- `:Change` is **derived** — droppable and rebuildable with the rest of the overlay.
- Triage traverses `IMPLEMENTS` only, never `IMPLEMENTS_PROPOSED`. An unreviewed inference must not reach a triage row.
- Documentation updated in the same change.

## Decisions an executor must not silently change

*Executor's note (2026-08-20):* Decision 1 below could not be implemented as written and was changed on the project owner's decision. An `obligation_id` hashes its version (ADR-013), so a clause reproduced word for word in two editions carries two different ids — verified: the same statement in the same section of two editions hashes to `ee0577cf…` and `c741ac71…`. Matching on id would report every obligation in the document as a removal plus an addition, which is the failure Decision 2 exists to prevent. The diff matches on `(section_path, normalize(statement))` instead — the version-independent part of the same identity. `obligation_id` is unchanged, so Phase 4's decisions still work. See [ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md).

**1. The diff matches on obligation id, which is content-derived.** Two obligations with the same id in both versions are unchanged. An id present only in the new version is `ADDED`; only in the old, `REMOVED`. `MODIFIED` needs care — see decision 2.

**2. `MODIFIED` is detected by section, not by id.** Phase 3's id includes the normalized statement, so *any* wording change produces a different id — which alone would report every edit as a REMOVED plus an ADDED. A pair occupying the same `section_path` in both versions, with different ids, is one `MODIFIED` change carrying both statements. Where a section holds several obligations, fall back to ADDED/REMOVED rather than guessing a pairing, and say so in the change's summary.

**3. Ranking is arithmetic, and the weights are named constants.** `modality weight × change kind × tier distance`. A magic number buried in Cypher is a ranking nobody can argue with; a named constant is one a policy analyst can challenge.

**4. A change with no `IMPLEMENTS` path produces no triage row, and that is reported.** Silence would be indistinguishable from "nothing is affected". The response states how many changes had no reviewed link, so an empty triage reads as "nothing linked yet" rather than "nothing affected".

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/changes/diff.py` | *Create* — version-to-version obligation diff |
| `backend/src/policy_grapher/changes/propagate.py` | *Create* — the triage traversal and ranking |
| `backend/src/policy_grapher/routers/triage.py` | *Create* — the triage API |
| `backend/src/policy_grapher/db.py` | *Modify* — change constraint |
| `backend/tests/test_diff.py`, `test_triage.py` | *Create* |
| `docs/specs/adr/ADR-015-*.md` | *Create* — how a change is detected and ranked |

---

### Task 1: Diff two versions into `:Change` nodes

**Files:**
- Create: `backend/src/policy_grapher/changes/diff.py`, `backend/tests/test_diff.py`
- Modify: `backend/src/policy_grapher/db.py`

**Interfaces:**
- Produces: `diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]` returning counts by kind, having written `:Change` nodes joined by `FROM_VERSION`, `TO_VERSION` and `AFFECTS`

- [x] **Step 1: Add the constraint**

```python
    (
        "CREATE CONSTRAINT change_id_unique IF NOT EXISTS "
        "FOR (c:Change) REQUIRE c.change_id IS UNIQUE"
    ),
```

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_diff.py`. Seed two versions of one document with hand-built
obligations, then assert:
- an obligation present only in the new version is one `ADDED` change
- present only in the old is one `REMOVED`
- **same `section_path`, different statement → exactly one `MODIFIED`, not an ADDED plus a REMOVED.** This is the case that matters and the one most likely to be got wrong
- a `MODIFIED` change carries both the old and the new statement, so a reviewer can see what actually changed
- an identical obligation in both versions produces **no** change
- a section holding two obligations, both reworded, produces ADDED/REMOVED rather than a guessed pairing — and the summary says why
- re-running the diff is idempotent: the same `:Change` nodes, not duplicates
- a change is joined to both versions by `FROM_VERSION` and `TO_VERSION`, and to the affected obligation by `AFFECTS`

- [x] **Step 3: Run to verify failure, then implement**

`change_id` is `hash(from_version_id, to_version_id, kind, obligation_id)` so re-running is
idempotent. `MODIFIED` uses the *new* obligation as its `AFFECTS` target, because that is
the one a reviewer must now act on.

- [x] **Step 4: Run tests and commit**

```bash
git add backend/src/policy_grapher/changes backend/src/policy_grapher/db.py backend/tests/test_diff.py
git commit -m "feat: diff two editions into changes a reviewer can read"
```

---

### Task 2: Propagate to the affected org policies

**Files:**
- Create: `backend/src/policy_grapher/changes/propagate.py`
- Modify: `backend/tests/test_diff.py` or create `backend/tests/test_triage.py`

**Interfaces:**
- Produces: `MODALITY_WEIGHT`, `KIND_WEIGHT`, `triage(tx, *, from_version_id, to_version_id) -> TriageResult` with ranked rows and an `unlinked_changes` count

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_triage.py` covering:
- a change to an obligation an org policy `IMPLEMENTS` produces one triage row naming the org document, the org clause, and both citations
- **a change linked only by `IMPLEMENTS_PROPOSED` produces no row** — assert this explicitly. It is the invariant Phase 4 exists to protect and the one a careless join would break
- a changed `SHALL` outranks a changed `MAY`, given everything else equal
- a `REMOVED` obligation an org policy implements still produces a row — the org policy now implements something that no longer exists, which is exactly what a reviewer needs to know
- changes with no reviewed link are counted in `unlinked_changes` rather than dropped
- an empty result reports `unlinked_changes` so "nothing linked yet" is distinguishable from "nothing affected"

- [x] **Step 2: Implement**

```python
MODALITY_WEIGHT = {"SHALL": 4.0, "MUST": 4.0, "SHOULD": 2.0, "MAY": 1.0}
KIND_WEIGHT = {"REMOVED": 3.0, "MODIFIED": 2.0, "ADDED": 1.0}
```

*Executor's note:* the third factor Decision 3 names, tier distance, is omitted rather than fixed at 1.0 — nothing in the graph records a policy tier, so including it would mean multiplying by a constant and calling it a factor.

Named because a policy analyst should be able to argue with them. A REMOVED obligation
outranks a MODIFIED one because an org policy implementing something that no longer exists
is a live compliance gap, whereas a modified one is work.

The traversal is the one from the design:

```cypher
MATCH (c:Change)-[:AFFECTS]->(higher:Obligation)
      <-[:IMPLEMENTS]-(ours:Obligation)
      <-[:MANDATES]-(v:DocumentVersion)<-[:HAS_VERSION]-(d:Document)
```

- [x] **Step 3: Run tests and commit**

```bash
git add backend/src/policy_grapher/changes/propagate.py backend/tests/test_triage.py
git commit -m "feat: propagate a change to the policies that implement it"
```

---

### Task 3: The triage API

**Files:**
- Create: `backend/src/policy_grapher/routers/triage.py`
- Modify: `backend/src/policy_grapher/main.py`, `backend/src/policy_grapher/models.py`, `backend/tests/test_triage.py`
- Create: `docs/specs/adr/ADR-015-changes-are-detected-and-ranked.md`

**Interfaces:**
- Produces: `GET /triage?from_version_id=&to_version_id=` → `TriageOut` with ranked rows and `unlinked_changes`

- [x] **Step 1: Write the failing tests**

- the route requires a principal
- an unknown version id is a 404, not an empty result — an empty result would read as "nothing affected"
- omitting `from_version_id` defaults to the version the target supersedes, and the response says which was used
- every row carries both citations, so nothing in the response is unsourced

- [x] **Step 2: Implement and wire the router**

- [x] **Step 3: Write ADR-015**

Must state: the diff matches on content-derived ids; `MODIFIED` is detected by section
because id-matching alone reports every edit as a remove-plus-add; multi-obligation sections
fall back rather than guess a pairing; ranking weights are named constants so they can be
argued with; REMOVED outranks MODIFIED and why; and triage traverses `IMPLEMENTS` only, with
unlinked changes counted rather than dropped.

- [x] **Step 4: Run everything and commit**

```bash
git add backend/src/policy_grapher backend/tests docs/specs/adr/ADR-015-changes-are-detected-and-ranked.md
git commit -m "feat: ask what a policy change affects, and get an evidenced answer"
```

---

## Done when

- A reworded obligation in the same section is one `MODIFIED`, not a remove-plus-add
- A change linked only by `IMPLEMENTS_PROPOSED` produces no triage row
- A changed `SHALL` outranks a changed `MAY`; a `REMOVED` outranks a `MODIFIED`
- Unlinked changes are counted, so an empty triage is never mistaken for "nothing affected"
- Every triage row carries both citations
- ADR-015 exists

Phase 6 (retrieval, question answering and the UI) can start.
