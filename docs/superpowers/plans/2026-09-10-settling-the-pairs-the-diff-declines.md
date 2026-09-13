# Settling the Pairs the Diff Declines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Same-document pairing becomes a first-class, human-settleable question with its own canonical decision node, its own queue, and its own screen; `IMPLEMENTS` becomes cross-document only.

**Architecture:** The diff's wording pass records its outcomes as `PAIRING_CANDIDATE` edges written by `diff_versions` (planning stays pure); a new canonical `:PairingDecision` node is threaded into the diff before the section rule; a new `/pairings` API runs the diff itself and lets a reviewer settle or undo any pair of the two editions; a startup migration converts the legacy same-document `:LinkDecision` and deletes the stranded edges.

**Tech Stack:** FastAPI + Neo4j (Cypher) backend, pytest (+testcontainers for integration), React + Vitest frontend.

**Spec:** `docs/superpowers/specs/2026-09-09-pairing-is-not-implementing-design.md` (rev. 7 — the plan argues from it; conflicts resolve against the spec).

> **Read as written-then, not as true-now.** This is the historical record of how the work was
> sequenced. Its interface sketches, expected counts and per-task assertions were written before the
> code existed and several were wrong when measured — five stale-count defects and one known-false
> biconditional (the `documents_with_obligations` line below: holding obligations in two documents is
> *necessary* for a proposal, not sufficient, since `score_pair` must still clear `MIN_CONFIDENCE`).
> Anyone re-running a command here should expect different numbers. The spec, now at rev. 8 and
> amended from the shipped code, is the document that is kept true.

## Global Constraints

- **Pass-3 pairing structure is identical before and after every change**: `scored`, `_best_elsewhere`, and the greedy loop stay restricted to `confidence >= PAIRING_CONFIDENCE` (0.75, `diff.py:100`). Recording candidates must not change which pairs are made or declined, at which confidences. A mutation test guards this (Task 3).
- **`outcome` is the first rule that fired, in code order**: `auto_paired` | `partner_taken` | `contested` | `below_threshold`. `partner_taken`'s predicate is a strict subset of `contested`'s — the labels record precedence, not disjoint conditions.
- **`:PairingDecision` direction is older→newer** with properties `old_obligation_id` / `new_obligation_id` / `verdict` / `actor` / `rationale` / `at` / `key`; `key = sha256(f"{old_id}|{new_id}")[:32]` (directional).
- **The corpus ordering rule** for two editions is the tuple `(coalesce(effective_date, ''), ingested_at, version_id)` — the `version_id` tie-breaker is this feature's addition, applied wherever the rule is applied.
- **`replay_decisions` stays the only writer of `IMPLEMENTS`** (`decisions.py:8`). Nothing in this plan writes that edge type.
- **`IMPLEMENTS` becomes cross-document only**: `propose_links` skips same-document pairs, `record_decision` refuses them, the migration retires the legacy ones.
- **Sub-threshold recording is bounded and post-loop**: a candidate scored in `[MIN_CONFIDENCE, PAIRING_CONFIDENCE)` is kept iff at least one endpoint finished the greedy loop unpaired AND it is that endpoint's best sub-threshold candidate or within `PAIRING_MARGIN` (0.05) of that best. `distinct`-settled pairs are excluded from recording and from "best".
- **Every new test is mutation-checked** before it is believed (sprint DoD, `docs/sprints/sprint-12/plan.md:96`): after it passes, deliberately break the code it guards and confirm it fails. Each task's steps name the mutation.
- **`--collect-only` is NOT evidence a test runs.** Collection never executes a fixture body, so a
  broken fixture collects cleanly and errors only when the test runs. Task 10 hit this: all nine of
  its tests errored in the shared fixture while the briefed collection check passed throughout. Where
  a step uses `--collect-only` as the in-sandbox check, treat it as proof the module imports and the
  test names exist — nothing more. Run the tests for real against the pinned database.
- **Fixture statements must contain their modality word.** `ExtractedObligation` rejects a modality
  the statement does not use, and three briefs (Tasks 4, 9, 10) shipped fixtures that fail this at
  seed time. Derive the modality from the statement, or match them by hand, before assuming a red run
  means the code is wrong.
- **Environment caveat:** integration tests (`@pytest.mark.integration`) need Docker/testcontainers, which this sandbox cannot reach (the `docker` binary is invisible from the Flatpak namespace). For integration tests: write them TDD-style, verify they **collect** (`--collect-only`) and that their unit-level logic is mutation-checked where possible; the full integration suite is a merge gate run where Docker exists. Run unit tests with `cd backend && .venv/bin/pytest tests/<file> -k "not integration" -q` (or the named test). Lint with `cd backend && .venv/bin/ruff check <files>`.
- **Commit style** follows the repo: `feat:`/`fix:`/`docs:` prefix, lower-case summary written as a sentence about behaviour (see `git log --oneline`). Commit after each green step-cycle.
- **Comment style**: comments state constraints the code cannot show, in the repo's discursive voice; never "why my change is correct" narration.

## File Structure

**Created:**
- `backend/src/policy_grapher/links/pairing.py` — the `:PairingDecision` canonical path: verdicts, key, record/read/settled/stranded queries, `PAIRING_SCHEMA` for the repoint refactor.
- `backend/src/policy_grapher/migrate.py` — the startup migration (convert / retire / delete), idempotent, import-callable.
- `backend/src/policy_grapher/routers/pairings.py` — `GET /pairings/queue`, `POST /pairings/{old}/{new}`.
- `backend/tests/test_pairing.py` — links/pairing.py unit + integration tests.
- `backend/tests/test_pairings.py` — pairings router integration tests.
- `backend/tests/test_migrate.py` — migration integration tests.
- `frontend/src/views/Pairings.tsx` (+ `Pairings.test.tsx`) — the pairing screen.

**Modified:**
- `backend/src/policy_grapher/changes/diff.py` — candidates accumulator, outcome labels, bound, decisions threading, `WRITE_CANDIDATES`/`DROP_CANDIDATES`, `PlanResult`.
- `backend/src/policy_grapher/links/propose.py` — `_facts` split, `score_pairing`, document-scoped `READ_OBLIGATIONS`, same-document skip.
- `backend/src/policy_grapher/links/decisions.py` — `DecisionSchema` parameterisation of repoint, cross-document guard in `record_decision`.
- `backend/src/policy_grapher/links/rebuild.py` — repoint both schemas, `pairing_decisions_stranded` count.
- `backend/src/policy_grapher/db.py` — `pairing_decision_key_unique` constraint.
- `backend/src/policy_grapher/models.py` — pairing models, `ReviewQueueOut` field rename, `TriageCitationOut.version_id`.
- `backend/src/policy_grapher/routers/review.py` — `WHY_EMPTY` replacement, 400 on same-document verdict.
- `backend/src/policy_grapher/routers/triage.py` — thread `version_id`.
- `backend/src/policy_grapher/changes/propagate.py` — `TRIAGE` RETURN + `TriageRow` + constructor gain version ids.
- `backend/src/policy_grapher/export.py` — `pairing_decisions` category.
- `backend/src/policy_grapher/main.py` — register pairings router; run migration at startup.
- `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/routes.tsx` — pairing types/functions/route; renamed review field; `version_id`.
- `frontend/src/views/Review.tsx` (+ test) — empty-state copy for the new definition.
- `frontend/src/views/Reset.tsx` (+ test if pinned) — export copy names `pairing_decisions`.
- `frontend/src/views/DocumentDetail.tsx` (+ test) — build fieldset offers other documents' editions.
- `frontend/src/views/Triage.tsx` (+ test) — the citation renders the edition each clause is from.
- `backend/tests/test_diff.py`, `backend/tests/test_links.py`, `backend/tests/test_review.py`,
  `backend/tests/test_rebuild.py`, `backend/tests/test_triage.py`, `backend/tests/test_export.py` —
  new cases and call-site updates for the changed signatures and payloads.
- `frontend/src/api/client.test.ts`, `frontend/src/App.test.tsx` — the pairing client block and the
  `/pairings` route row.

## Interface Contract (binding for every task)

```python
# links/pairing.py
class PairingVerdict(StrEnum):
    PAIRED = "paired"
    DISTINCT = "distinct"

def pairing_key(old_id: str, new_id: str) -> str            # sha256(f"{old_id}|{new_id}")[:32]

def record_pairing(tx, *, old_id: str, new_id: str, verdict: str,
                   actor: str, rationale: str) -> None       # MERGE on key; ValueError on unknown verdict

def read_pairings(tx, *, from_version_id: str, to_version_id: str) -> dict[tuple[str, str], str]
    # {(old_obligation_id, new_obligation_id): verdict} — only decisions whose two obligations are
    # MANDATES-ed by the two named editions (either role); keys as stored (canonical older→newer).

def read_settled(tx, *, from_version_id: str, to_version_id: str) -> list[dict]
    # [{"old_id", "new_id", "verdict", "actor"}] same scoping.

def count_stranded_pairings(tx) -> int                       # either obligation no longer exists

PAIRING_SCHEMA: DecisionSchema                               # label="PairingDecision",
    # source_prop="old_obligation_id", target_prop="new_obligation_id", key_of=pairing_key

# links/decisions.py (refactor)
@dataclass(frozen=True)
class DecisionSchema:
    label: str
    source_prop: str
    target_prop: str
    key_of: Callable[[str, str], str]

LINK_SCHEMA: DecisionSchema                                  # current behaviour, the default

def repoint_decisions(tx, *, before, after, schema: DecisionSchema = LINK_SCHEMA) -> int

# changes/diff.py
@dataclass(frozen=True)
class PlanResult:
    changes: list[dict]
    candidates: list[dict]          # {"old_id","new_id","confidence","rationale","outcome"}
    pairings_unapplied: int

def _plan_changes(old, new, decisions: dict[tuple[str, str], str] | None = None) -> PlanResult
def _pair_by_wording(unmatched_old, unmatched_new, paired_old, paired_new,
                     changes, candidates, distinct: set[frozenset[str]]) -> None
def drop_candidates(tx, *, from_version_id: str, to_version_id: str) -> int   # relationships_deleted
def diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]
    # keys: ADDED, REMOVED, MODIFIED, pairings_unapplied

# links/propose.py
def score_pairing(after_statement: str, before_statement: str) -> Candidate | None
    # same measure and floor as score_pair; pairing-worded rationale, no implements advisory
def propose_links(...)                                        # unchanged signature; skips same-document pairs

# models.py additions
class PairingCandidateOut(BaseModel):  old: ObligationCitationOut; new: ObligationCitationOut
                                       confidence: float; rationale: str; outcome: str
                                       taken_by: list[str]    # 0-2 obligation ids
class PairingSettledOut(BaseModel):    old_id: str; new_id: str; verdict: str; actor: str
class PairingQueueOut(BaseModel):      items: list[PairingCandidateOut]; settled: list[PairingSettledOut]
                                       pairings_unapplied: int; pending: int
class PairingVerdictIn(BaseModel):     verdict: str; rationale: str = ""
# ReviewQueueOut: documents_comparable → documents_with_obligations (count of distinct documents
# holding ≥1 obligation in any edition; proposals possible iff ≥ 2)
# TriageCitationOut gains version_id: str
# TriageOut gains pairings_unapplied: int — spec §3 requires the count in BOTH GET responses, so
# routers/triage.py captures diff_versions' return instead of discarding it (triage.py:96)

# routers/pairings.py
GET  /pairings/queue?from_version_id&to_version_id&limit    → PairingQueueOut
     # 400 unless (from, to) is older→newer by the corpus rule incl. version_id tie-breaker;
     # runs diff_versions, then reads candidates + settled + pairings_unapplied
POST /pairings/{old_obligation_id}/{new_obligation_id}      → PairingSettledOut
     # body PairingVerdictIn; 404 unless both obligations exist and are MANDATES-ed by two
     # editions of one document (route orders the pair itself); 409 when verdict is paired and
     # either obligation already carries a live paired verdict with a different partner whose
     # other end is MANDATES-ed by the SAME other edition

# migrate.py
def migrate_pairing_decisions(driver, database: str) -> dict[str, int]
    # {"converted","retired_same_edition","retired_conflicting","implements_deleted","proposals_deleted"}
    # called from main.py startup after schema setup; idempotent
```

Edge shape: `(:Obligation {old side})-[:PAIRING_CANDIDATE {confidence, rationale, outcome}]->(:Obligation {new side})`, written from-side→to-side by `diff_versions`; `DROP_CANDIDATES` matches the edge **undirected** between the two editions' obligations.

---
### Task 1: :PairingDecision foundation

**Files:**
- Create: `backend/src/policy_grapher/links/pairing.py`
- Create: `backend/tests/test_pairing.py`
- Modify: `backend/src/policy_grapher/db.py:53-64` (insert one constraint tuple entry immediately after `link_decision_key_unique`, before `change_id_unique`)
- Test: `backend/tests/test_pairing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (first task). Models `record_pairing` and the module docstring on `links/decisions.py` (`record_decision`, `decision_key`, `UNPROMOTABLE`).
- Produces, in `policy_grapher.links.pairing` (all per the Interface Contract):
  - `class PairingVerdict(StrEnum)` — `PAIRED = "paired"`, `DISTINCT = "distinct"`
  - `pairing_key(old_id: str, new_id: str) -> str` — `sha256(f"{old_id}|{new_id}")[:32]`, directional
  - `record_pairing(tx, *, old_id: str, new_id: str, verdict: str, actor: str, rationale: str) -> None` — MERGE on key; `ValueError` on unknown verdict
  - `read_pairings(tx, *, from_version_id: str, to_version_id: str) -> dict[tuple[str, str], str]`
  - `read_settled(tx, *, from_version_id: str, to_version_id: str) -> list[dict]` — `[{"old_id", "new_id", "verdict", "actor"}]`
  - `count_stranded_pairings(tx) -> int`
  - Cypher constants `RECORD`, `READ`, `SETTLED`, `STRANDED` (the two reads share a `_SCOPE` fragment so they cannot disagree about scope)
- Produces in `db.py`: the `pairing_decision_key_unique` constraint on `(:PairingDecision).key`, applied by the existing `apply_schema`.
- **`PAIRING_SCHEMA` is deliberately NOT defined in this task.** The contract places it in `pairing.py`, but its type `DecisionSchema` does not exist until Task 7's refactor of `links/decisions.py`, and a placeholder or deferred import is forbidden. Task 7 adds `PAIRING_SCHEMA` to `pairing.py` when it introduces `DecisionSchema`. No task before Task 7 may import it.

**Steps:**

- [ ] Write the failing unit tests. Create `backend/tests/test_pairing.py`:

```python
"""The canonical `:PairingDecision` path: key, verdicts, edition-scoped reads."""

import pytest

from policy_grapher.links.pairing import (
    pairing_key,
    record_pairing,
)

# --- the key and the verdict vocabulary (no graph needed) ---------------------


def test_the_pairing_key_is_directional():
    """The properties say which end is old. A symmetric key would let a
    mis-ordered write replace a well-ordered verdict it does not match."""
    assert pairing_key("a", "b") != pairing_key("b", "a")


def test_the_pairing_key_is_stable():
    assert pairing_key("a", "b") == pairing_key("a", "b")


def test_an_unknown_verdict_is_refused_before_anything_is_written():
    """The vocabulary is closed for `decisions.Verdict`'s reason: the diff
    branches on the value, and one it does not know would be silently
    ignored — a settled pair the diff keeps re-asking about. Validation
    precedes the write, so `tx` is never touched and no graph is needed."""
    with pytest.raises(ValueError, match="verdict"):
        record_pairing(
            None, old_id="a", new_id="b", verdict="maybe", actor="x", rationale=""
        )
```

(The key is *not* required to differ from `decisions.decision_key` for the same ids — both are `sha256(f"{a}|{b}")[:32]` by contract, and the two node labels never share a constraint — so no such test is written.)

- [ ] Run it and confirm the failure is the missing module, not a typo:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py -q
```

Expected: collection error, exit non-zero —

```
E   ModuleNotFoundError: No module named 'policy_grapher.links.pairing'
ERROR tests/test_pairing.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

- [ ] Write the implementation. Create `backend/src/policy_grapher/links/pairing.py` in full:

```python
"""Human verdicts on same-document pairings, and the edition-scoped reads.

`:PairingDecision` is **canonical**, exactly as `:LinkDecision` is: a verdict is
a thing a person did, and no rebuild may discard it (ADR-014). It answers the
other question, in the other vocabulary — not "does our clause discharge that
duty?" but "is the newer clause the reworded older one?" — which is why the
properties are `old_obligation_id`/`new_obligation_id` and never
`source`/`target`: those names belong to the implements question.

Nothing here writes `IMPLEMENTS`, `IMPLEMENTS_PROPOSED`, or `PAIRING_CANDIDATE`.
A pairing verdict takes effect inside the diff, which reads it through
`read_pairings`; the candidate edges are the diff's own derived record, written
and dropped in `changes/diff.py`.

Direction is older→newer, but that is not a property this module can promise:
`record_pairing` stores whatever ids it is given, and the key is a directional
hash of them. The one route that records verdicts orders the pair itself before
calling in — the obligation ids determine their editions, and the editions
order — so the promise is pinned at the route, not here.
"""

import hashlib
from enum import StrEnum

from neo4j import ManagedTransaction


class PairingVerdict(StrEnum):
    """Closed on purpose, for `decisions.Verdict`'s reason: the diff branches on
    this value when applying verdicts, so one it does not recognise would be
    silently ignored — a settled pair the diff keeps re-asking about."""

    PAIRED = "paired"
    DISTINCT = "distinct"


RECORD = """
MERGE (d:PairingDecision {key: $key})
SET d.old_obligation_id = $old_id,
    d.new_obligation_id = $new_id,
    d.verdict           = $verdict,
    d.actor             = $actor,
    d.rationale         = $rationale,
    d.at                = datetime()
"""

# Scoped through :MANDATES to the two named editions, one obligation in each.
# The scope is the point: an obligation serves every diff its edition is in — a
# middle edition belongs to two pairs — so "any decision touching these
# obligations" would leak a neighbouring pair's verdict into this diff. The
# final inequality keeps out a decision recorded inside a single edition, which
# answers neither pair's question. Both reads below share this fragment so they
# can never disagree about which decisions belong to a pair of editions.
_SCOPE = """
MATCH (d:PairingDecision)
MATCH (old_v:DocumentVersion)-[:MANDATES]->
      (:Obligation {obligation_id: d.old_obligation_id})
MATCH (new_v:DocumentVersion)-[:MANDATES]->
      (:Obligation {obligation_id: d.new_obligation_id})
WHERE old_v.version_id IN [$from_version_id, $to_version_id]
  AND new_v.version_id IN [$from_version_id, $to_version_id]
  AND old_v.version_id <> new_v.version_id
"""

READ = _SCOPE + """
RETURN d.old_obligation_id AS old_id,
       d.new_obligation_id AS new_id,
       d.verdict           AS verdict
"""

# The same decisions with the actor kept: the queue lists settled pairs so a
# reviewer can reach one again to undo it, and who settled it is part of what
# they are undoing.
SETTLED = _SCOPE + """
RETURN d.old_obligation_id AS old_id,
       d.new_obligation_id AS new_id,
       d.verdict           AS verdict,
       d.actor             AS actor
"""

# A verdict whose obligation a re-extraction no longer produces. The decision
# stays — it is a fact a human established — but the diff cannot apply it, and
# a rebuild reporting only what it applied would look complete while a human
# decision had quietly stopped being represented. The true analogue of
# `decisions.UNPROMOTABLE`, counted beside it in the rebuild.
STRANDED = """
MATCH (d:PairingDecision)
WHERE NOT EXISTS { MATCH (:Obligation {obligation_id: d.old_obligation_id}) }
   OR NOT EXISTS { MATCH (:Obligation {obligation_id: d.new_obligation_id}) }
RETURN count(d) AS stranded
"""


def pairing_key(old_id: str, new_id: str) -> str:
    """Identity for a verdict on one ordered pair of clauses.

    Content-derived from two obligation ids, which are themselves
    content-derived, so the key survives a re-extraction that reproduces the
    same obligations. Directional, as `decisions.decision_key` is: the
    properties say which end is old, and a symmetric key would let a
    mis-ordered write replace a well-ordered verdict it does not match.
    """
    return hashlib.sha256(f"{old_id}|{new_id}".encode()).hexdigest()[:32]


def record_pairing(
    tx: ManagedTransaction,
    *,
    old_id: str,
    new_id: str,
    verdict: str,
    actor: str,
    rationale: str,
) -> None:
    """Record one human pairing verdict, replacing any earlier verdict on the
    same ordered pair.

    Replacing rather than appending, for `record_decision`'s reason: a reviewer
    who changes their mind must leave one current verdict, not two records for
    the diff to choose between. The MERGE is on `key`, and
    `pairing_decision_key_unique` (db.py) holds that to one node rather than a
    race to a second.
    """
    if verdict not in set(PairingVerdict):
        raise ValueError(
            f"unknown verdict {verdict!r}; expected one of "
            f"{[v.value for v in PairingVerdict]}"
        )
    tx.run(
        RECORD,
        {
            "key": pairing_key(old_id, new_id),
            "old_id": old_id,
            "new_id": new_id,
            "verdict": verdict,
            "actor": actor,
            "rationale": rationale,
        },
    ).consume()


def read_pairings(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[tuple[str, str], str]:
    """The verdicts between two editions, as `{(old_id, new_id): verdict}`.

    Keys are as stored — canonical older→newer — whichever order the editions
    were named in, because Triage accepts arbitrary direction; a caller applying
    verdicts must look a pair up under both orientations.
    """
    return {
        (record["old_id"], record["new_id"]): record["verdict"]
        for record in tx.run(
            READ,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    }


def read_settled(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> list[dict]:
    """The same decisions with their actors, for the queue's settled list."""
    return [
        {
            "old_id": record["old_id"],
            "new_id": record["new_id"],
            "verdict": record["verdict"],
            "actor": record["actor"],
        }
        for record in tx.run(
            SETTLED,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    ]


def count_stranded_pairings(tx: ManagedTransaction) -> int:
    """Decisions the graph can no longer express: either obligation is gone."""
    return tx.run(STRANDED).single()["stranded"]
```

- [ ] Run the unit tests:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py -q
```

Expected: `...` then `[100%]`, exit 0 — three passes. (`addopts` already carries `-q`, so the doubled flag prints the dot line without a count line.)

- [ ] **THE MUTATION CHECK (key direction).** In `pairing.py`, replace `pairing_key`'s return with the symmetric form:

```python
    return hashlib.sha256("|".join(sorted((old_id, new_id))).encode()).hexdigest()[:32]
```

Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py::test_the_pairing_key_is_directional -q`. Expected failure:

```
FAILED tests/test_pairing.py::test_the_pairing_key_is_directional - AssertionError: assert '0eab8a0a3380abf4c7d1fb0b43b66aaf' != '0eab8a0a3380abf4c7d1fb0b43b66aaf'
```

(both calls hash the same sorted pair). Revert the line to `return hashlib.sha256(f"{old_id}|{new_id}".encode()).hexdigest()[:32]` and re-run: passes.

- [ ] **THE MUTATION CHECK (verdict guard).** In `record_pairing`, delete the whole `if verdict not in set(PairingVerdict): raise ValueError(...)` block. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py::test_an_unknown_verdict_is_refused_before_anything_is_written -q`. Expected failure:

```
FAILED tests/test_pairing.py::test_an_unknown_verdict_is_refused_before_anything_is_written - AttributeError: 'NoneType' object has no attribute 'run'
```

— the mutant falls through to `tx.run` on the `None` transaction, which `pytest.raises(ValueError)` rightly does not swallow. Restore the guard and re-run: passes.

- [ ] Add the constraint. In `backend/src/policy_grapher/db.py`, immediately after the `link_decision_key_unique` entry (line 60, before `change_id_unique`), insert:

```python
    # :PairingDecision is the same kind of thing for the other question — a
    # same-document pairing verdict, canonical for the same ADR-014 reason.
    # Uniqueness on the directional key is what lets a re-verdict update in
    # place, and the repoint path's collision screening assumes it.
    (
        "CREATE CONSTRAINT pairing_decision_key_unique IF NOT EXISTS "
        "FOR (d:PairingDecision) REQUIRE d.key IS UNIQUE"
    ),
```

`apply_schema` already loops over `CONSTRAINTS`, and the test `driver` fixture calls it, so nothing else changes. Its guard is the integration test `test_the_pairing_decision_key_constraint_exists` written next.

- [ ] Write the integration tests. Append to `backend/tests/test_pairing.py`, and extend the module's import block to its full form:

```python
from policy_grapher.links.pairing import (
    count_stranded_pairings,
    pairing_key,
    read_pairings,
    read_settled,
    record_pairing,
)
```

with `import pytest` joined by `from neo4j import RoutingControl` at the top. Then append:

```python
# --- recording and reading against a real graph -------------------------------


def _seed_edition(driver, database, *, version_id, obligation_ids):
    """An edition MANDATES-ing obligations under caller-chosen ids.

    Seeded directly rather than through chunking and extraction: these tests
    are about the `:MANDATES` topology the reads scope through, and the ids are
    the fixture's vocabulary — deriving them from statements would only obscure
    which obligation each assertion names.
    """
    driver.execute_query(
        "MERGE (d:Document {slug: 'doc', name: 'DOC'}) "
        "MERGE (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'}) "
        "WITH v UNWIND $ids AS id "
        "MERGE (o:Obligation {obligation_id: id}) "
        "MERGE (v)-[:MANDATES]->(o)",
        {"vid": version_id, "ids": obligation_ids},
        database_=database,
    )


def _record(driver, database, *, old, new, verdict, actor="alice", rationale="r"):
    with driver.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=old,
            new_id=new,
            verdict=verdict,
            actor=actor,
            rationale=rationale,
        )


def _read(driver, database, *, from_version_id, to_version_id):
    with driver.session(database=database) as session:
        return session.execute_read(
            read_pairings,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
        )


@pytest.mark.integration
def test_a_recorded_pairing_is_read_back_under_either_edition_order(
    clean_graph, database
):
    """Triage accepts arbitrary direction, so the read must accept the editions
    in either role — while the returned keys stay as stored, older→newer."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["old-clause"]
    )
    _seed_edition(
        clean_graph, database, version_id="e2022", obligation_ids=["new-clause"]
    )
    _record(clean_graph, database, old="old-clause", new="new-clause", verdict="paired")

    forward = _read(clean_graph, database, from_version_id="e2018", to_version_id="e2022")
    backward = _read(clean_graph, database, from_version_id="e2022", to_version_id="e2018")

    assert forward == {("old-clause", "new-clause"): "paired"}
    assert backward == forward


@pytest.mark.integration
def test_re_recording_the_same_pair_replaces_the_verdict_in_place(
    clean_graph, database
):
    """One current verdict per ordered pair, never two contradictory records
    for the diff to choose between. No seeding: `record_pairing` binds no
    editions — admissibility is the route's business — so the replace is
    observable on the bare node."""
    _record(clean_graph, database, old="a", new="b", verdict="paired")
    _record(clean_graph, database, old="a", new="b", verdict="distinct", actor="bob")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:PairingDecision) RETURN count(d) AS total, "
        "collect(d.verdict) AS verdicts, collect(d.actor) AS actors",
        database_=database,
    )
    assert records[0]["total"] == 1
    assert records[0]["verdicts"] == ["distinct"]
    assert records[0]["actors"] == ["bob"]


@pytest.mark.integration
def test_a_neighbouring_pairs_verdict_does_not_leak_into_this_read(
    clean_graph, database
):
    """A middle edition belongs to two pairs, so scoping by "touches either
    edition" would leak the adjacent diff's verdicts into this one. Both
    obligations must sit in the two named editions, one in each — which also
    keeps out a decision recorded inside a single edition."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["a1", "a2"]
    )
    _seed_edition(clean_graph, database, version_id="e2020", obligation_ids=["b1"])
    _seed_edition(clean_graph, database, version_id="e2022", obligation_ids=["c1"])
    _record(clean_graph, database, old="a1", new="b1", verdict="paired")
    _record(clean_graph, database, old="b1", new="c1", verdict="distinct")
    # Recordable at this layer (only the route checks membership), so the read
    # has to be the thing that keeps it out of both adjacent pairs' diffs.
    _record(clean_graph, database, old="a1", new="a2", verdict="distinct")

    first = _read(clean_graph, database, from_version_id="e2018", to_version_id="e2020")
    second = _read(clean_graph, database, from_version_id="e2020", to_version_id="e2022")

    assert first == {("a1", "b1"): "paired"}
    assert second == {("b1", "c1"): "distinct"}


@pytest.mark.integration
def test_settled_pairs_carry_their_actor_and_respect_the_same_scope(
    clean_graph, database
):
    """The queue lists settled pairs so a reviewer can reach one to undo it;
    who settled it is part of what they are undoing."""
    _seed_edition(clean_graph, database, version_id="e2018", obligation_ids=["a1"])
    _seed_edition(clean_graph, database, version_id="e2020", obligation_ids=["b1"])
    _seed_edition(clean_graph, database, version_id="e2022", obligation_ids=["c1"])
    _record(clean_graph, database, old="a1", new="b1", verdict="paired", actor="alice")
    _record(clean_graph, database, old="b1", new="c1", verdict="distinct", actor="bob")

    with clean_graph.session(database=database) as session:
        settled = session.execute_read(
            read_settled, from_version_id="e2018", to_version_id="e2020"
        )

    assert settled == [
        {"old_id": "a1", "new_id": "b1", "verdict": "paired", "actor": "alice"}
    ]


@pytest.mark.integration
def test_a_pairing_whose_obligation_is_gone_is_counted_stranded(
    clean_graph, database
):
    """After a re-extraction the decision is still a fact a human established,
    but the graph cannot express it, and a rebuild must say so rather than
    report only what it applied."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["old-clause"]
    )
    _seed_edition(
        clean_graph, database, version_id="e2022", obligation_ids=["new-clause"]
    )
    _record(clean_graph, database, old="old-clause", new="new-clause", verdict="paired")

    with clean_graph.session(database=database) as session:
        before = session.execute_read(count_stranded_pairings)
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: 'new-clause'}) DETACH DELETE o",
        database_=database,
    )
    with clean_graph.session(database=database) as session:
        after = session.execute_read(count_stranded_pairings)

    assert before == 0
    assert after == 1


@pytest.mark.integration
def test_the_pairing_decision_key_constraint_exists(driver, database):
    """`record_pairing`'s MERGE holds one node per key only while the key is
    unique; without the constraint a concurrent writer can slip a second node
    under the same key, and the repoint path's collision screening assumes
    there is exactly one."""
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert "pairing_decision_key_unique" in set(records[0]["names"])
```

- [ ] Run the collection check (this sandbox has no Docker; the merge gate runs the integration suite where Docker exists):

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py --collect-only -q
```

Expected: `tests/test_pairing.py: 9` and no collection errors (3 unit + 6 integration). Then re-run the unit slice green: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py -k "not integration" -q` — three dots, exit 0.

- [ ] **THE MUTATION CHECK (integration, executed at the merge gate).** These seven mutations are the record of what each integration test guards; each is applied, run with `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairing.py -q` where Docker exists, confirmed failing as stated, and reverted:
  1. In `_SCOPE`, delete the line `AND new_v.version_id IN [$from_version_id, $to_version_id]` → `test_a_neighbouring_pairs_verdict_does_not_leak_into_this_read` fails: `first` gains `("b1", "c1")`, the adjacent pair's verdict.
  2. In `_SCOPE`, delete the line `AND old_v.version_id <> new_v.version_id` → the same test fails: `first` gains `("a1", "a2")`, the same-edition decision.
  3. In `RECORD`, change `MERGE (d:PairingDecision {key: $key})` to `CREATE (d:PairingDecision {key: $key})` → `test_re_recording_the_same_pair_replaces_the_verdict_in_place` fails: the second `_record` violates `pairing_decision_key_unique` (`ConstraintError`), which is the constraint and the replace guarding each other.
  4. In `STRANDED`, change `OR` to `AND` → `test_a_pairing_whose_obligation_is_gone_is_counted_stranded` fails at `assert after == 1` (got 0).
  5. In `db.py`, delete the `pairing_decision_key_unique` entry → `test_the_pairing_decision_key_constraint_exists` fails at the membership assert.
  6. In `_SCOPE`, replace the two `IN [$from_version_id, $to_version_id]` predicates with the fixed-role pair —

     ```
     WHERE old_v.version_id = $from_version_id
       AND new_v.version_id = $to_version_id
       AND old_v.version_id <> new_v.version_id
     ```

     → `test_a_recorded_pairing_is_read_back_under_either_edition_order` fails at `assert backward == forward`: `backward` comes back `{}`, because naming the editions the other way round now demands the stored `old` obligation sit in `$from_version_id`, which is the *newer* edition. (The leak test still passes under this mutant — both its reads name the editions older-first — which is why the either-order test is the one that has to exist.)
  7. In `SETTLED`, delete the line `d.actor AS actor` (and the comma ending the line above it) → `test_settled_pairs_carry_their_actor_and_respect_the_same_scope` fails inside `read_settled` with `KeyError: 'actor'`, the neo4j `Record` refusing a column the query no longer returns. That the actor is carried at all is the point: the queue lists a settled pair so a reviewer can reach it to undo it, and who settled it is part of what they are undoing.

- [ ] Lint:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/pairing.py src/policy_grapher/db.py tests/test_pairing.py
```

Expected: `All checks passed!`

- [ ] Commit:

```
git add backend/src/policy_grapher/links/pairing.py backend/src/policy_grapher/db.py backend/tests/test_pairing.py
git commit -m "feat: a same-document pairing verdict gets its own canonical node and edition-scoped reads"
```

---

### Task 2: score_pairing

**Files:**
- Modify: `backend/src/policy_grapher/links/propose.py:1-10` (module docstring gains one paragraph) and `backend/src/policy_grapher/links/propose.py:51-91` (`score_pair` + `_rationale` replaced by `_score` + `_facts` + `score_pair` + `score_pairing`; `_rationale`'s only caller is `score_pair`, verified by grep, so it disappears)
- Modify: `backend/tests/test_links.py:15-20` (import block) and after `test_confidence_never_exceeds_one` (`backend/tests/test_links.py:94-99`) — extend the pure-scoring section, do not restructure anything else
- Test: `backend/tests/test_links.py`

**Interfaces:**
- Consumes: nothing from Task 1 (this task is independent of it).
- Produces:
  - `score_pairing(after_statement: str, before_statement: str) -> Candidate | None` in `policy_grapher.links.propose` — same measure and `MIN_CONFIDENCE` floor as `score_pair` (one shared `_score`, so they cannot drift), pairing-worded rationale ending `" The question is whether the newer clause is the older one reworded."`, no implements advisory. Task 3's `_pair_by_wording` calls this in place of `score_pair`.
  - `score_pair` — signature unchanged, rationale byte-identical to before this task, pinned by test.
  - Private helpers `_score(a_statement, b_statement) -> tuple[float, set[str], set[str], float] | None` and `_facts(shared_words, shared_designators, overlap) -> str` (module-internal; no later task imports them).

**Steps:**

- [ ] Write the pin test for the existing wording. In `backend/tests/test_links.py`, after `test_confidence_never_exceeds_one`, add:

```python
def test_the_proposal_rationale_wording_is_pinned_verbatim():
    """This sentence is stored on every `IMPLEMENTS_PROPOSED` edge and shown in
    the review queue; the pairing split rewrites the *pairing* sentence, not
    this one. Byte-for-byte on purpose — a looser test would pass a paraphrase
    that still changes what live proposals say."""
    result = score_pair(
        "The Director shall assess cybersecurity risk in accordance with DoDI 5000.88.",
        "Components must comply with DoDI 5000.88 when assessing cybersecurity risk.",
    )
    assert result is not None
    assert result.rationale == (
        "Both cite DoDI 5000.88; they share 60% of the shorter clause's "
        "distinctive wording (cybersecurity, dodi, risk). Confirm the org "
        "clause actually discharges the higher duty before approving."
    )
```

- [ ] Run it:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py::test_the_proposal_rationale_wording_is_pinned_verbatim -q
```

Expected: one dot, exit 0 — it **passes immediately**, because it characterizes current behaviour. A first-time pass is believed only after its mutation check, which is next.

- [ ] **THE MUTATION CHECK (pinned wording).** In `propose.py`'s `_rationale`, change `before approving.` to `before you approve.`. Re-run the command above. Expected failure: `AssertionError` with a string diff ending

```
  + ty before you approve.
  ?           ++++      ^
```

Revert the wording to `before approving.` and re-run: passes.

- [ ] Write the failing tests for `score_pairing`. In `backend/tests/test_links.py`, extend the propose import to:

```python
from policy_grapher.links.propose import (
    content_words,
    designators,
    propose_links,
    score_pair,
    score_pairing,
)
```

and append after the pin test:

```python
def test_score_pairing_and_score_pair_agree_on_the_measure():
    """One measurement serves both reviewers. The shorter clause here is wholly
    contained in the longer, which only the min() denominator scores at 1.0 —
    so this pins the denominator as well as the agreement."""
    after = (
        "The Program Manager shall document the cybersecurity strategy for "
        "each acquisition program."
    )
    before = "The Program Manager must document the cybersecurity strategy."

    paired = score_pairing(after, before)
    proposed = score_pair(after, before)

    assert paired is not None and proposed is not None
    assert paired.confidence == proposed.confidence
    assert paired.confidence == 1.0


def test_score_pairing_keeps_the_proposers_floor():
    """Both statements carry content words but share none, which lands on the
    `MIN_CONFIDENCE` floor rather than the empty-statement branch. Below the
    floor there is nothing a rationale could honestly say the clauses share."""
    assert (
        score_pairing(
            "The Program Manager must document the cybersecurity strategy.",
            "Travel vouchers may be submitted electronically.",
        )
        is None
    )


def test_the_pairing_rationale_asks_the_pairing_question():
    """The reviewer on the pairing screen decides whether one clause is the
    other reworded — not whether anything discharges anything. The implements
    advisory would tell them to verify a relationship nobody is claiming."""
    result = score_pairing(
        "The Director shall assess cybersecurity risk in accordance with DoDI 5000.88.",
        "Components must comply with DoDI 5000.88 when assessing cybersecurity risk.",
    )
    assert result is not None
    assert "DoDI 5000.88" in result.rationale
    assert "cybersecurity" in result.rationale
    assert "reworded" in result.rationale
    assert "discharges" not in result.rationale
    assert "approving" not in result.rationale
```

- [ ] Run the file's unit slice and confirm the failure is the missing function:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration" -q
```

Expected: collection error, exit non-zero —

```
E   ImportError: cannot import name 'score_pairing' from 'policy_grapher.links.propose' (/home/rhagan/policy_grapher/backend/src/policy_grapher/links/propose.py)
ERROR tests/test_links.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

- [ ] Write the implementation. In `backend/src/policy_grapher/links/propose.py`, first extend the module docstring — after the sentence ending ``nothing in this module can write `IMPLEMENTS`).`` and before the closing `"""`, add:

```python
Two questions share the one measure. `score_pair` words its rationale for the
implements reviewer and `score_pairing` for the pairing reviewer — same overlap,
same floor, different closing sentence, because a rationale is advice to a
specific person about a specific question.
```

Then replace the whole of `score_pair` and `_rationale` (lines 51-91) with:

```python
def _score(
    a_statement: str, b_statement: str
) -> tuple[float, set[str], set[str], float] | None:
    """The measurement both scorers share: (confidence, shared words, shared
    designators, overlap), or None when a statement has no content words or the
    confidence is under `MIN_CONFIDENCE`. Symmetric, so argument order carries
    no meaning here — each caller's signature says which end is which.

    Overlap is measured against the *shorter* statement's vocabulary rather
    than the union: a short clause wholly contained in a long one is the normal
    shape for both questions, and a Jaccard denominator would score exactly
    that case as unrelated.
    """
    a_words = content_words(a_statement)
    b_words = content_words(b_statement)
    if not a_words or not b_words:
        return None

    shared_words = a_words & b_words
    overlap = len(shared_words) / min(len(a_words), len(b_words))
    shared_designators = designators(a_statement) & designators(b_statement)

    confidence = min(1.0, overlap + DESIGNATOR_WEIGHT * len(shared_designators))
    if confidence < MIN_CONFIDENCE:
        return None
    return confidence, shared_words, shared_designators, overlap


def _facts(shared_words: set[str], shared_designators: set[str], overlap: float) -> str:
    """What was actually matched, for a human about to decide — never a claim
    that the pair is correct, which is the reviewer's call. Each scorer appends
    its own closing sentence naming its reviewer's question."""
    terms = ", ".join(sorted(shared_words)[:6]) or "no distinctive terms"
    cites = (
        f"Both cite {', '.join(sorted(shared_designators))}; "
        if shared_designators
        else ""
    )
    return (
        f"{cites}they share {overlap:.0%} of the shorter clause's distinctive "
        f"wording ({terms})."
    )


def score_pair(org_statement: str, higher_statement: str) -> Candidate | None:
    """How plausibly the org clause implements the higher one, or None if not.

    The closing sentence is byte-for-byte what it was before `_facts` was split
    out, and a test pins it: this string is persisted on every proposal, so a
    rewording here silently rewrites what live review queues say.
    """
    scored = _score(org_statement, higher_statement)
    if scored is None:
        return None
    confidence, shared_words, shared_designators, overlap = scored
    return Candidate(
        confidence=confidence,
        rationale=(
            _facts(shared_words, shared_designators, overlap)
            + " Confirm the org clause actually discharges the higher duty "
            "before approving."
        ),
    )


def score_pairing(after_statement: str, before_statement: str) -> Candidate | None:
    """How plausibly the newer clause is the older one reworded, or None if not.

    The same measure and floor as `score_pair` — one `_score`, so the two
    cannot drift — with a different sentence, because the reviewer's question
    is different. An implements advisory here would tell a pairing reviewer to
    verify a relationship nobody is claiming.
    """
    scored = _score(after_statement, before_statement)
    if scored is None:
        return None
    confidence, shared_words, shared_designators, overlap = scored
    return Candidate(
        confidence=confidence,
        rationale=(
            _facts(shared_words, shared_designators, overlap)
            + " The question is whether the newer clause is the older one "
            "reworded."
        ),
    )
```

- [ ] Run the whole unit slice:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration" -q
```

Expected: fifteen dots, `[100%]`, exit 0 — the 11 pre-existing unit tests (including the pin, which proves the refactor preserved the string byte-for-byte) plus the 4 new ones.

- [ ] **THE MUTATION CHECK (denominator).** In `_score`, change `min(len(a_words), len(b_words))` to `max(len(a_words), len(b_words))`. Run the unit-slice command above. Expected failure:

```
FAILED tests/test_links.py::test_score_pairing_and_score_pair_agree_on_the_measure - assert 0.8333333333333334 == 1.0
```

Note what this proves and what it deliberately does not lean on: the pin test's two vocabularies happen to be the same size ("components" is a stopword), so the pin *survives* this mutant — the agree test's exact `== 1.0` on an asymmetric pair is the assertion that kills it, which is why it is written that way. Revert `max` to `min` and re-run: fifteen dots.

- [ ] **THE MUTATION CHECK (the shared floor).** In `_score`, delete the two lines that apply the floor:

```python
    if confidence < MIN_CONFIDENCE:
        return None
```

Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py::test_score_pairing_keeps_the_proposers_floor -q`. Expected failure:

```
FAILED tests/test_links.py::test_score_pairing_keeps_the_proposers_floor - assert Candidate(confidence=0.0, rationale="they share 0% of the shorter clause's distinctive wording (no distinctive terms). The question is whether the newer clause is the older one reworded.") is None
 +  where Candidate(confidence=0.0, rationale="they share 0% of the shorter clause's distinctive wording (no distinctive terms). The question is whether the newer clause is the older one reworded.") = score_pairing('The Program Manager must document the cybersecurity strategy.', 'Travel vouchers may be submitted electronically.')
```

— the mutant reaches the pairing reviewer with a candidate at confidence 0.0 whose own rationale admits the two clauses share "no distinctive terms", which is the queue-flooding failure `MIN_CONFIDENCE` exists to prevent. It fails on the floor branch rather than the empty-statement branch, since both statements do have content words. Restore the two lines and re-run the unit slice: fifteen dots.

- [ ] **THE MUTATION CHECK (advisory-free wording).** In `score_pairing`, replace its closing-sentence concatenation with `score_pair`'s advisory:

```python
            + " Confirm the org clause actually discharges the higher duty "
            "before approving."
```

Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py::test_the_pairing_rationale_asks_the_pairing_question -q`. Expected failure: `AssertionError` at `assert "reworded" in result.rationale`, with the rationale shown carrying the implements advisory. Revert to `+ " The question is whether the newer clause is the older one " "reworded."` and re-run the unit slice: fifteen dots.

- [ ] Lint:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/propose.py tests/test_links.py
```

Expected: `All checks passed!`

- [ ] Commit:

```
git add backend/src/policy_grapher/links/propose.py backend/tests/test_links.py
git commit -m "feat: pairing scores get their own rationale and the proposal wording is pinned"
```
### Task 3: The wording pass labels every outcome (pure planning)

**Files:**
- Modify: `backend/src/policy_grapher/changes/diff.py` (imports, lines 21–26; new `PlanResult` after the constants at lines 97–105; `_pair_by_wording`, lines 108–183; `_plan_changes`, lines 186–276; the `_plan_changes` call in `diff_versions`, line 308)
- Test: `backend/tests/test_diff.py` (import block, lines 3–17; the six `_plan_changes` call sites at lines 374, 387, 400, 411, 441, 458; new unit tests appended after line 461)

**Interfaces:**
- Consumes (Task 2): `score_pairing(after_statement: str, before_statement: str) -> Candidate | None` from `policy_grapher.links.propose` — same measure and floor as `score_pair`, pairing-worded rationale. Also the pre-existing `MIN_CONFIDENCE = 0.30` (`propose.py:31`) and `Candidate` (`propose.py:35-38`).
- Produces:
  - `PlanResult` (frozen dataclass): `changes: list[dict]`, `candidates: list[dict]`, `pairings_unapplied: int`. Candidate dict shape, relied on verbatim by Task 4's `WRITE_CANDIDATES` and Task 10's queue: `{"old_id", "new_id", "confidence", "rationale", "outcome"}` with `outcome` ∈ `auto_paired | partner_taken | contested | below_threshold`.
  - `_plan_changes(old: dict[str, dict], new: dict[str, dict], decisions: dict[tuple[str, str], str] | None = None) -> PlanResult`. **`decisions` is accepted and ignored entirely in this task** — it exists so the signature is final from the start; Task 5 wires it (verdict application, `pairings_unapplied` counting, deriving `distinct`). Until then `pairings_unapplied` is always `0`.
  - `_pair_by_wording(unmatched_old, unmatched_new, paired_old, paired_new, changes, candidates, distinct: set[frozenset[str]]) -> None`. `distinct` is honoured now — a distinct pair is skipped before scoring, so it reaches neither `scored`, nor the sub-threshold accumulator, nor the bound's per-endpoint best — but every caller passes `set()` until Task 5, and Task 5 owns the tests that exercise a non-empty `distinct`.
  - `_score_table(monkeypatch, table)` in `backend/tests/test_diff.py` — the one scorer stub this file gets. Its table is keyed `(before_statement, after_statement)`, the old→new reading order the fixtures are written in. Task 5 appends its unit tests to this same module and **reuses this helper** rather than defining a second stub: two stubs in one file keying their tables in opposite orders is precisely how a later test copied from the wrong neighbour scores `None` and passes vacuously — the failure `test_a_pair_below_the_floor_is_not_recorded_even_when_the_scorer_returns_it` exists to make impossible.
  - The module attribute `policy_grapher.changes.diff.score_pairing` (the import is hoisted to module level) — the monkeypatch seam these unit tests and Task 5's use. Safe to hoist: `links/__init__.py` imports nothing, and `propose.py` imports nothing from `changes`, so `rebuild → changes.diff → links.propose` is a chain, not a cycle.
  - Global constraint honoured and mutation-guarded here: `scored`, `_best_elsewhere`, and the greedy loop stay restricted to `>= PAIRING_CONFIDENCE`; recording changes nothing about which pairs are made or declined, at which confidences.

**Steps:**

- [ ] Write the failing unit tests. Append to `backend/tests/test_diff.py` (after `test_an_exact_tie_falls_back_too`, line 461), and add one import to the top of the file — extend the existing `from policy_grapher.extraction.schema import ExtractedObligation, Modality` block with a new line `from policy_grapher.links.propose import Candidate` (placed after the `policy_grapher.extraction.schema` import, before `from policy_grapher.obligations import write_obligations`):

```python
# --- §2: every wording-pass outcome is recorded --------------------------------


def _score_table(monkeypatch, table: dict[tuple[str, str], float]) -> None:
    """Replace the diff's scorer with a lookup table.

    `table` maps (before_statement, after_statement) to a confidence — the
    old→new reading order the fixtures are written in. Anything absent scores
    None, exactly as `score_pairing` does for a pair sharing no content words.
    The table may hold values below MIN_CONFIDENCE on purpose: the real scorer
    never returns those, and the vacuity test needs a scorer that does.
    """

    def fake_score_pairing(after_statement: str, before_statement: str):
        confidence = table.get((before_statement, after_statement))
        if confidence is None:
            return None
        return Candidate(confidence=confidence, rationale="stub rationale")

    monkeypatch.setattr(
        "policy_grapher.changes.diff.score_pairing", fake_score_pairing
    )


def _outcomes(plan) -> dict[tuple[str, str], str]:
    return {(c["old_id"], c["new_id"]): c["outcome"] for c in plan.candidates}


def test_the_greedy_loop_labels_all_three_outcomes_in_one_run(monkeypatch):
    """The chain the spec's containment argument is built on: the 0.80 pair
    loses its partner to the 0.90 pair (partner_taken), and the 0.76 tail is
    within the margin of the 0.80 rival (contested). The outcome is the first
    rule that fired, in code order — not four disjoint predicates."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old beta", "new alpha"): 0.80,
            ("old beta", "new beta"): 0.76,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    plan = _plan_changes(old, new)

    assert len(plan.candidates) == 3
    assert _outcomes(plan) == {
        ("o1", "n1"): "auto_paired",
        ("o2", "n1"): "partner_taken",
        ("o2", "n2"): "contested",
    }
    assert [c["obligation_id"] for c in plan.changes if c["kind"] == MODIFIED] == [
        "n1"
    ]
    assert plan.pairings_unapplied == 0


def test_a_contested_label_needs_no_taken_partner(monkeypatch):
    """The partner-free fork: 0.80 and 0.78 share one clause, the margin
    declines both, and nothing was accepted — so `contested` cannot be an
    artifact of a taken partner. The paired sets must come out untouched."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.80,
            ("old alpha", "new beta"): 0.78,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"), _entry("n2", ["C"], "new beta"))

    plan = _plan_changes(old, new)

    assert _outcomes(plan) == {
        ("o1", "n1"): "contested",
        ("o1", "n2"): "contested",
    }
    assert MODIFIED not in [c["kind"] for c in plan.changes]


def test_a_pair_whose_both_sides_were_taken_is_partner_taken(monkeypatch):
    """Both endpoints can be consumed — the decline fires when *either* is —
    so up to two auto_paired winners exist for one declined pair. The queue
    names each side's taker (Task 10); this pins the state it reads from."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.95,
            ("old beta", "new beta"): 0.91,
            ("old alpha", "new beta"): 0.85,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    assert outcomes[("o2", "n2")] == "auto_paired"
    assert outcomes[("o1", "n2")] == "partner_taken"


def test_recording_a_sub_threshold_rival_does_not_change_the_pairing(monkeypatch):
    """The invariant the whole feature hangs on: a 0.74 rival is recorded, and
    the 0.78 pair still auto-pairs. `_best_elsewhere` has no confidence filter
    of its own, so widening `scored` down to MIN_CONFIDENCE would flip this
    pair to contested — that mutant is what this test exists to kill."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.78,
            ("old alpha", "new beta"): 0.74,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"), _entry("n2", ["C"], "new beta"))

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    assert outcomes[("o1", "n2")] == "below_threshold"
    assert MODIFIED in [c["kind"] for c in plan.changes]


def test_a_sub_threshold_candidate_survives_only_through_an_unpaired_endpoint(
    monkeypatch,
):
    """The bound, and its timing. o1–n2's 0.60 has both endpoints consumed by
    the loop, so it is dropped; o1–n3's 0.60 is kept only because n3 finished
    unpaired and it is n3's best; o2–n3's 0.50 is not within PAIRING_MARGIN of
    that best. Judged before the loop, every endpoint is still unpaired and
    all three would survive — which is the mutant."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old beta", "new beta"): 0.85,
            ("old alpha", "new beta"): 0.60,
            ("old alpha", "new gamma"): 0.60,
            ("old beta", "new gamma"): 0.50,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(
        _entry("n1", ["C"], "new alpha"),
        _entry("n2", ["D"], "new beta"),
        _entry("n3", ["E"], "new gamma"),
    )

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    below = {pair for pair, outcome in outcomes.items() if outcome == "below_threshold"}
    assert below == {("o1", "n3")}


def test_a_pair_below_the_floor_is_not_recorded_even_when_the_scorer_returns_it(
    monkeypatch,
):
    """score_pairing already returns None under MIN_CONFIDENCE, so a fixture
    that leans on it proves nothing — the spec's vacuity warning. The stub is
    the deliberately lowered floor: it returns 0.20, and the diff's own guard
    must refuse to record it."""
    _score_table(monkeypatch, {("old alpha", "new alpha"): 0.20})
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"))

    plan = _plan_changes(old, new)

    assert plan.candidates == []
```

- [ ] Run the new tests and confirm they fail for the right reason: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"` — expected: `6 failed, 10 passed, 12 deselected`, every failure being `AttributeError: <module 'policy_grapher.changes.diff' ...> has no attribute 'score_pairing'` (the monkeypatch seam does not exist yet).

- [ ] Write the implementation in `backend/src/policy_grapher/changes/diff.py`. Four edits. First, the imports (lines 21–26 become):

```python
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import normalize
from policy_grapher.links.propose import MIN_CONFIDENCE, score_pairing
```

  Second, insert `PlanResult` immediately after the `PAIRING_MARGIN` block (after line 105):

```python
@dataclass(frozen=True)
class PlanResult:
    """What one planning run decided, in full: the changes to write, every
    wording-pass candidate labelled with the first rule that fired for it, and
    how many reviewer verdicts the plan could not apply."""

    changes: list[dict]
    candidates: list[dict]
    pairings_unapplied: int
```

  Third, replace `_pair_by_wording` (lines 108–183) in full:

```python
def _pair_by_wording(
    unmatched_old: dict[str, dict],
    unmatched_new: dict[str, dict],
    paired_old: set[str],
    paired_new: set[str],
    changes: list[dict],
    candidates: list[dict],
    distinct: set[frozenset[str]],
) -> None:
    """Pair what section-based matching left over — ADR-031.

    Greedy over the best-scoring pairs rather than optimal: an assignment problem
    would be a better answer to a question nobody is asking, since a document that
    reworded dozens of clauses into each other's sections is one no pairing rule
    should be confident about anyway.

    Every outcome lands in `candidates` labelled with the first rule that fired,
    in code order: `auto_paired`, `partner_taken`, `contested`, `below_threshold`.
    `partner_taken`'s predicate is a strict subset of `contested`'s — the
    consuming pair scores at least as high and shares an endpoint, so the margin
    rule would decline the same pair — so the labels record precedence, not
    disjoint conditions.

    `distinct` holds pairs a reviewer has ruled out. They are skipped before
    scoring, which keeps them out of `scored`, out of the sub-threshold
    accumulator, and out of the bound's notion of an endpoint's best: a score
    the reviewer rejected must not shadow the endpoint's next-best live
    candidate.
    """
    scored: list[tuple[float, str, dict, dict]] = []
    sub_threshold: list[dict] = []
    for before in unmatched_old.values():
        if before["id"] in paired_old:
            continue
        for after in unmatched_new.values():
            if after["id"] in paired_new:
                continue
            if frozenset((before["id"], after["id"])) in distinct:
                continue
            candidate = score_pairing(after["statement"], before["statement"])
            if candidate is None:
                continue
            if candidate.confidence >= PAIRING_CONFIDENCE:
                scored.append(
                    (candidate.confidence, candidate.rationale, before, after)
                )
            elif candidate.confidence >= MIN_CONFIDENCE:
                # The floor is this module's own, not inherited: the scorer
                # returns None below MIN_CONFIDENCE today, but recording is
                # bounded here so a retuned scorer cannot silently widen it.
                sub_threshold.append(
                    {
                        "old_id": before["id"],
                        "new_id": after["id"],
                        "confidence": candidate.confidence,
                        "rationale": candidate.rationale,
                        "outcome": "below_threshold",
                    }
                )

    scored.sort(key=lambda row: row[0], reverse=True)

    # The best score each obligation could have achieved with a *different*
    # partner. A pair that only just beats its own runner-up is not a pairing this
    # measure can distinguish, and choosing anyway would be choosing whichever the
    # dictionary happened to yield first. Scans only `scored`, so everything here
    # is >= PAIRING_CONFIDENCE — widening that would change which pairs are made,
    # not merely which are recorded.
    def _best_elsewhere(obligation_id: str, partner_id: str) -> float:
        return max(
            (
                confidence
                for confidence, _r, before, after in scored
                if obligation_id in (before["id"], after["id"])
                and partner_id not in (before["id"], after["id"])
            ),
            default=0.0,
        )

    for confidence, rationale, before, after in scored:
        if before["id"] in paired_old or after["id"] in paired_new:
            # An endpoint went to a higher-scoring pair earlier in this loop.
            # Checked before the margin, and the order is load-bearing: the
            # consuming pair also satisfies the margin predicate, and this is
            # the actionable label — an auto_paired winner exists to point at.
            candidates.append(
                {
                    "old_id": before["id"],
                    "new_id": after["id"],
                    "confidence": confidence,
                    "rationale": rationale,
                    "outcome": "partner_taken",
                }
            )
            continue
        contested = max(
            _best_elsewhere(before["id"], after["id"]),
            _best_elsewhere(after["id"], before["id"]),
        )
        if confidence - contested < PAIRING_MARGIN:
            # Two candidates within a hair of each other: both stay ADDED/REMOVED
            # and the summary says why, which is ADR-015's answer kept.
            candidates.append(
                {
                    "old_id": before["id"],
                    "new_id": after["id"],
                    "confidence": confidence,
                    "rationale": rationale,
                    "outcome": "contested",
                }
            )
            continue

        paired_old.add(before["id"])
        paired_new.add(after["id"])
        candidates.append(
            {
                "old_id": before["id"],
                "new_id": after["id"],
                "confidence": confidence,
                "rationale": rationale,
                "outcome": "auto_paired",
            }
        )
        changes.append(
            {
                "kind": MODIFIED,
                "obligation_id": after["id"],
                "section_path": after["section_path"],
                "statement": after["statement"],
                "previous_statement": before["statement"],
                "modality": after["modality"],
                "summary": (
                    f"The obligation moved from section "
                    f"{'/'.join(before['section_path'])} to "
                    f"{'/'.join(after['section_path'])} and was reworded — "
                    f"{rationale}"
                ),
            }
        )

    # The scoring loop is a cross product, so recording everything under the bar
    # would write thousands of edges per edition pair and bury the one candidate
    # worth a look under its own long tail. A sub-threshold record is kept iff at
    # least one of its endpoints finished the greedy loop unpaired AND it is that
    # endpoint's best sub-threshold candidate or within PAIRING_MARGIN of that
    # best. Judged after the loop, deliberately: before it, every endpoint is
    # still unpaired and this filter would keep the lot.
    best_sub: dict[str, float] = {}
    for record in sub_threshold:
        for endpoint in (record["old_id"], record["new_id"]):
            best_sub[endpoint] = max(
                best_sub.get(endpoint, 0.0), record["confidence"]
            )

    for record in sub_threshold:
        if (
            record["old_id"] not in paired_old
            and best_sub[record["old_id"]] - record["confidence"] < PAIRING_MARGIN
        ) or (
            record["new_id"] not in paired_new
            and best_sub[record["new_id"]] - record["confidence"] < PAIRING_MARGIN
        ):
            candidates.append(record)
```

  Fourth, replace `_plan_changes` (lines 186–276) in full — the section rule, the `_ambiguous` closure, and the ADDED/REMOVED passes are byte-identical to today; what changes is the signature, the `candidates` accumulator, the `_pair_by_wording` call, and the return:

```python
def _plan_changes(
    old: dict[str, dict],
    new: dict[str, dict],
    decisions: dict[tuple[str, str], str] | None = None,
) -> PlanResult:
    """Work out the changes without touching the graph, so the rule is testable
    on its own and readable in one place.

    `decisions` maps (old_obligation_id, new_obligation_id) to a reviewer's
    verdict, threaded down by `diff_versions` rather than fetched here. The
    parameter is part of the planning signature from the start; the rules that
    read it land with the pairing-decision passes, and until then it is
    accepted and unread — passing None is always safe.
    """
    unmatched_old = {k: v for k, v in old.items() if k not in new}
    unmatched_new = {k: v for k, v in new.items() if k not in old}

    by_section_old = defaultdict(list)
    by_section_new = defaultdict(list)
    for entry in unmatched_old.values():
        by_section_old[tuple(entry["section_path"])].append(entry)
    for entry in unmatched_new.values():
        by_section_new[tuple(entry["section_path"])].append(entry)

    changes: list[dict] = []
    candidates: list[dict] = []
    paired_old: set[str] = set()
    paired_new: set[str] = set()

    for section, news in by_section_new.items():
        olds = by_section_old.get(section, [])
        if len(olds) == 1 and len(news) == 1:
            before, after = olds[0], news[0]
            paired_old.add(before["id"])
            paired_new.add(after["id"])
            changes.append(
                {
                    "kind": MODIFIED,
                    # The new obligation: it is the one a reviewer must now act on.
                    "obligation_id": after["id"],
                    "section_path": after["section_path"],
                    "statement": after["statement"],
                    "previous_statement": before["statement"],
                    "modality": after["modality"],
                    "summary": (
                        f"The obligation in section {'/'.join(section)} was reworded."
                    ),
                }
            )

    # ADR-031. What section-based pairing could not reach gets a second pass on
    # wording. Structure first, always: a section holding one unmatched clause
    # each side has been edited, and no measurement improves on a certainty.
    #
    # The measure is `links/propose.py`'s, unchanged — shared content words
    # weighted by shared designators, scored against the shorter statement. It
    # keeps every row explainable by a path a person can walk, which is what
    # ADR-015 actually required; "no text similarity" was the mechanism, not the
    # constraint.
    _pair_by_wording(
        unmatched_old,
        unmatched_new,
        paired_old,
        paired_new,
        changes,
        candidates,
        distinct=set(),
    )

    def _ambiguous(section: tuple[str, ...]) -> str | None:
        if len(by_section_old.get(section, [])) + len(by_section_new.get(section, [])) > 1:
            return AMBIGUOUS_SECTION.format(section="/".join(section))
        return None

    for entry in unmatched_old.values():
        if entry["id"] in paired_old:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": REMOVED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _ambiguous(section)
                or f"The obligation in section {'/'.join(section)} is gone.",
            }
        )

    for entry in unmatched_new.values():
        if entry["id"] in paired_new:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": ADDED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _ambiguous(section)
                or f"A new obligation appears in section {'/'.join(section)}.",
            }
        )

    return PlanResult(changes=changes, candidates=candidates, pairings_unapplied=0)
```

  And in `diff_versions`, replace the single line `changes = _plan_changes(old, new)` (line 308) with:

```python
    plan = _plan_changes(old, new)
    changes = plan.changes
```

  Nothing else in `diff_versions` changes in this task — the counts dict stays `KINDS`-only until Task 4, so the integration tests' counts assertions are untouched here.

- [ ] Update the six existing unit-test call sites in `backend/tests/test_diff.py` — `_plan_changes` now returns a `PlanResult`, and these tests read the changes:

```python
# line 374 (test_a_clause_that_moved_section_is_a_modification_not_a_replacement):
    changes = _plan_changes(old, new).changes
# line 387 (test_a_pairing_found_by_wording_carries_its_evidence):
    summary = _plan_changes(old, new).changes[0]["summary"]
# line 400 (test_two_unrelated_clauses_are_not_paired):
    changes = _plan_changes(old, new).changes
# line 411 (test_section_pairing_still_wins_where_it_applies):
    changes = _plan_changes(old, new).changes
# line 441 (test_a_near_tie_falls_back_rather_than_picking_the_higher_score):
    changes = _plan_changes(old, new).changes
# line 458 (test_an_exact_tie_falls_back_too):
    changes = _plan_changes(old, new).changes
```

  These six keep running the *real* scorer, which after this task is `score_pairing` — so they double as end-to-end coverage that Task 2's function scores the ADR-031 fixtures exactly as `score_pair` did.

- [ ] Run and confirm green: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"` — expected: `16 passed, 12 deselected`. (No trailing `-q` on this run, nor on the red run above it, nor on the mutation checks below: `backend/pyproject.toml` already sets `addopts = "-q"`, and a second `-q` drops the count line these steps read, leaving only the progress dots.)

- [ ] THE MUTATION CHECK (chain — label precedence): in the greedy loop, move the `if before["id"] in paired_old or after["id"] in paired_new:` block (with its append and `continue`) *below* the `if confidence - contested < PAIRING_MARGIN:` block. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_the_greedy_loop_labels_all_three_outcomes_in_one_run` — expected `1 failed`: the (o2, n1) pair is relabelled `contested` (its 0.90 consumer makes `_best_elsewhere` return 0.90, and the margin fires first). Revert the reorder and re-run: `1 passed`.

- [ ] THE MUTATION CHECK (partner-free fork — capture exists at the margin exit): delete the `candidates.append({... "outcome": "contested"})` call at the margin decline (keep the `continue`). Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_contested_label_needs_no_taken_partner` — expected `1 failed`: `_outcomes(plan)` is `{}` where two `contested` records are asserted. Revert and re-run: `1 passed`.

- [ ] THE MUTATION CHECK (both-sides-taken — capture exists at the partner-taken exit): delete the `candidates.append({... "outcome": "partner_taken"})` call (keep the `continue`). Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_pair_whose_both_sides_were_taken_is_partner_taken` — expected `1 failed` with `KeyError: ('o1', 'n2')`. Revert and re-run: `1 passed`.

- [ ] THE MUTATION CHECK (recording must not change pairing — the widened-`scored` mutant, the plan's Global Constraint): change the scoring-filter arm `if candidate.confidence >= PAIRING_CONFIDENCE:` to `if candidate.confidence >= MIN_CONFIDENCE:`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_recording_a_sub_threshold_rival_does_not_change_the_pairing` — expected `1 failed`: the 0.74 rival enters `scored`, `_best_elsewhere` returns 0.74, `0.78 - 0.74 < PAIRING_MARGIN`, and the 0.78 pair is `contested` where `auto_paired` is asserted. Revert and re-run: `1 passed`.

- [ ] THE MUTATION CHECK (bound timing — post-loop, not pre-loop): in the post-loop keep rule, delete both paired-set conditions — i.e. change the condition to `if (best_sub[record["old_id"]] - record["confidence"] < PAIRING_MARGIN) or (best_sub[record["new_id"]] - record["confidence"] < PAIRING_MARGIN):` — which is what evaluating the bound before the loop would compute, every endpoint still unpaired. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_sub_threshold_candidate_survives_only_through_an_unpaired_endpoint` — expected `1 failed`: `below` is `{("o1", "n2"), ("o1", "n3"), ("o2", "n3")}` where `{("o1", "n3")}` is asserted. Revert and re-run: `1 passed`.

- [ ] THE MUTATION CHECK (the diff's own floor — kills the vacuity): change the capture arm `elif candidate.confidence >= MIN_CONFIDENCE:` to `else:`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_pair_below_the_floor_is_not_recorded_even_when_the_scorer_returns_it` — expected `1 failed`: the 0.20 pair is captured, survives the bound through its unpaired endpoints, and `plan.candidates` holds one record where `[]` is asserted. Revert and re-run: `1 passed`.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/changes/diff.py tests/test_diff.py` — expected: no findings.

- [ ] Commit:

```
git add backend/src/policy_grapher/changes/diff.py backend/tests/test_diff.py
git commit -m "feat: the wording pass records every pairing outcome it makes or declines"
```

---

### Task 4: diff_versions writes and drops the record

**Files:**
- Modify: `backend/src/policy_grapher/changes/diff.py` (insert `WRITE_CANDIDATES` and `DROP_CANDIDATES` after the `WRITE_CHANGES` statement, currently ending at line 72; insert `drop_candidates` beside `drop_changes`, currently at lines 279–287; rewrite `diff_versions`, currently at lines 290–327 — line numbers pre-Task-3, so drifted by roughly the size of `PlanResult` and the candidate appends)
- Test: `backend/tests/test_diff.py` (import block, lines 5–13; the six full-dict counts assertions at lines 126, 145, 161, 177, 257, 313; new integration tests appended at the end of the file)

**Interfaces:**
- Consumes (Task 3): `PlanResult` and `_plan_changes(old, new, decisions=None) -> PlanResult`; the candidate dict shape `{"old_id", "new_id", "confidence", "rationale", "outcome"}`.
- Produces:
  - `WRITE_CANDIDATES` / `DROP_CANDIDATES` Cypher constants in `changes/diff.py`. The edge shape later tasks read: `(:Obligation {old side})-[:PAIRING_CANDIDATE {confidence, rationale, outcome}]->(:Obligation {new side})`, written from-side→to-side by `diff_versions` (request order — chronology is pinned at Task 10's route, nowhere below it).
  - `drop_candidates(tx, *, from_version_id: str, to_version_id: str) -> int` — returns `relationships_deleted` (`drop_changes` returns `nodes_deleted`, `diff.py:286-287`; a candidate is an edge between two obligations that stay standing, so `nodes_deleted` here would always be 0).
  - `diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]` with keys `ADDED`, `REMOVED`, `MODIFIED`, `pairings_unapplied` — the last taken from `PlanResult.pairings_unapplied` (always 0 until Task 5 wires decisions). Task 10's queue route calls `diff_versions` and reads this key.
  - **No router change in this task**: the Triage GET already discards `diff_versions`' return value (`routers/triage.py:96-98`), so it picks up candidate writing and dropping without being touched. The key stays unread until Task 5's Cycle 4 ("the Triage GET reports what it could not apply"), which stops discarding that return and puts `pairings_unapplied` on `TriageOut`; the pairing queue surfaces the same key at Task 10.

**Steps:**

- [ ] Write the failing integration tests. In `backend/tests/test_diff.py`, extend the `policy_grapher.changes.diff` import at the top of the file to include `drop_candidates`:

```python
from policy_grapher.changes.diff import (
    ADDED,
    MODIFIED,
    REMOVED,
    _plan_changes,
    content_key,
    diff_versions,
    drop_candidates,
    drop_changes,
)
```

  and append at the end of the file:

```python
# --- §2: the diff writes and drops its candidate record ------------------------


def _candidate_edges(driver, database, *, a: str, b: str) -> int:
    """Candidate edges between two editions' obligations, either orientation.

    Undirected on purpose: a reversed Triage run writes its edges the other
    way, and a directed count would hide exactly the orphans the drop must
    reach.
    """
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $a})-[:MANDATES]->(:Obligation)"
        "-[r:PAIRING_CANDIDATE]-"
        "(:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $b}) "
        "RETURN count(r) AS total",
        {"a": a, "b": b},
        database_=database,
    )
    return records[0]["total"]


@pytest.mark.integration
def test_rediffing_the_same_pair_leaves_no_stale_candidate(clean_graph, database):
    """Both endpoints survive here — only the plan changed — so nothing deletes
    the edge as a side effect (the rebuild path's drop_obligations cannot save
    us, and drop_changes structurally cannot: a PAIRING_CANDIDATE hangs off no
    :Change node). Only the pair's own drop can remove it."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.SHALL)],
    )
    _diff(clean_graph, database)
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1

    # A re-extraction of v2 now also finds the old clause verbatim, so pass 1
    # matches it and the wording pass has nothing left to pair. The auto_paired
    # edge the first run wrote answers a question the diff no longer asks.
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    counts = _diff(clean_graph, database)

    assert counts["MODIFIED"] == 0
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 0


@pytest.mark.integration
def test_rediffing_one_pair_leaves_the_adjacent_pairs_candidates_intact(
    clean_graph, database
):
    """A middle edition's obligations belong to two pairs. A drop scoped to
    "any candidate edge touching either edition" would delete the neighbouring
    diff's record with this pair's — which is why DROP_CANDIDATES anchors both
    ends through :MANDATES."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.SHALL)],
    )
    # v3 carries v2's clause verbatim but renumbered again, so the v2→v3 diff
    # pairs it by wording at confidence 1.0.
    _seed(
        clean_graph,
        database,
        version_id="v3",
        entries=[("5.1", RENUMBERED_NEW, Modality.SHALL)],
    )
    _diff(clean_graph, database, old="v1", new="v2")
    _diff(clean_graph, database, old="v2", new="v3")
    assert _candidate_edges(clean_graph, database, a="v2", b="v3") == 1

    _diff(clean_graph, database, old="v1", new="v2")

    assert _candidate_edges(clean_graph, database, a="v2", b="v3") == 1
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1


@pytest.mark.integration
def test_a_reversed_runs_edges_are_cleaned_by_the_next_chronological_run(
    clean_graph, database
):
    """Triage accepts arbitrary direction, so a reversed GET writes its edges
    the other way round. The undirected drop lets the chronological run reach
    them; a directional match would leave them orphaned forever while deleting
    only the well-oriented ones."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.SHALL)],
    )
    _diff(clean_graph, database, old="v2", new="v1")
    _diff(clean_graph, database, old="v1", new="v2")

    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v1'})-[:MANDATES]->(:Obligation)"
        "-[r:PAIRING_CANDIDATE]->"
        "(:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: 'v2'}) "
        "RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_drop_candidates_counts_relationships_not_nodes(clean_graph, database):
    """A candidate is an edge between two obligations that stay standing.
    nodes_deleted here would always be 0 — compare drop_changes, whose unit is
    the :Change node — and a caller reading it would believe the drop did
    nothing."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.SHALL)],
    )
    _diff(clean_graph, database)

    with clean_graph.session(database=database) as session:
        dropped = session.execute_write(
            drop_candidates, from_version_id="v1", to_version_id="v2"
        )

    assert dropped == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN count(o) AS obligations", database_=database
    )
    assert records[0]["obligations"] == 2
```

- [ ] Run collection and confirm it fails for the right reason: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py --collect-only -q` — expected: collection error, `ImportError while importing test module ... cannot import name 'drop_candidates' from 'policy_grapher.changes.diff'`. (These tests are `@pytest.mark.integration`; this sandbox has no Docker, so collection is the observable red state and the merge gate runs them for real where Docker exists.)

- [ ] Write the implementation in `backend/src/policy_grapher/changes/diff.py`. Insert the two statements directly after `WRITE_CHANGES`:

```python
# The candidate edge is written from-side→to-side, whatever the caller passed:
# neither this statement nor `diff_versions` knows chronology — they carry
# request order, and older→newer is pinned at the pairing route, the one place
# built on these edges. No version anchors here: obligation ids are unique, and
# the pairs being written were read from the two named editions in this same
# transaction.
WRITE_CANDIDATES = """
UNWIND $candidates AS candidate
MATCH (old:Obligation {obligation_id: candidate.old_id})
MATCH (new:Obligation {obligation_id: candidate.new_id})
MERGE (old)-[r:PAIRING_CANDIDATE]->(new)
SET r.confidence = candidate.confidence,
    r.rationale  = candidate.rationale,
    r.outcome    = candidate.outcome
"""

# Undirected on the candidate edge, deliberately: a Triage GET run with the pair
# reversed writes its edges the other way, and a directional drop would delete
# only the well-oriented ones while leaving those orphaned forever. Anchored
# through :MANDATES on *both* ends, because a middle edition's obligations
# belong to two pairs — "any edge touching either edition" would delete the
# neighbouring diff's candidates. DROP_PAIR's scoping cannot transfer: it scopes
# through the :Change node's FROM_VERSION/TO_VERSION, which a bare relationship
# does not carry.
DROP_CANDIDATES = """
MATCH (:DocumentVersion {version_id: $from_version_id})-[:MANDATES]->(:Obligation)
      -[r:PAIRING_CANDIDATE]-
      (:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $to_version_id})
DELETE r
"""
```

  Insert `drop_candidates` directly after `drop_changes`:

```python
def drop_candidates(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> int:
    """Remove one edition pair's candidate edges, from either orientation.

    `drop_changes` cannot reach these: it DETACH-deletes `:Change` nodes, and a
    relationship between two `:Obligation` nodes hangs off no `:Change`. On the
    rebuild path the edges happen to die with `drop_obligations`' DETACH DELETE
    — by accident, from a different statement — and not at all on the re-diff
    path, which is the one this exists for. The count is
    `relationships_deleted`: nothing here deletes a node.
    """
    summary = tx.run(
        DROP_CANDIDATES,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()
    return summary.counters.relationships_deleted
```

  Replace `diff_versions` in full:

```python
def diff_versions(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[str, int]:
    """Diff two editions and write the result. Returns counts by kind, plus
    `pairings_unapplied` — reviewer verdicts the plan could not apply.

    Drops this pair's existing changes and candidates first rather than merging
    over them: a re-extraction can make either stop existing, and a record left
    behind shows a reviewer a change — or a pairing question — that is no
    longer real. Ids are deterministic, so what *does* still exist comes back
    identical.
    """
    old = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": from_version_id}))
    new = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": to_version_id}))

    tx.run(
        DROP_PAIR,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()
    drop_candidates(
        tx, from_version_id=from_version_id, to_version_id=to_version_id
    )

    plan = _plan_changes(old, new)
    changes = plan.changes
    for change in changes:
        change["change_id"] = change_id(
            from_version_id, to_version_id, change["kind"], change["obligation_id"]
        )

    if changes:
        tx.run(
            WRITE_CHANGES,
            {
                "from_version_id": from_version_id,
                "to_version_id": to_version_id,
                "changes": changes,
            },
        ).consume()

    if plan.candidates:
        tx.run(WRITE_CANDIDATES, {"candidates": plan.candidates}).consume()

    counts = dict.fromkeys(KINDS, 0)
    for change in changes:
        counts[change["kind"]] += 1
    counts["pairings_unapplied"] = plan.pairings_unapplied
    return counts
```

- [ ] Update the six whole-dict counts assertions in `backend/tests/test_diff.py` — `diff_versions`' return gains a key, and these compare the full dict:

```python
# line 126 (test_an_obligation_only_in_the_new_edition_is_added):
    assert counts == {"ADDED": 1, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
# line 145 (test_an_obligation_only_in_the_old_edition_is_removed):
    assert counts == {"ADDED": 0, "REMOVED": 1, "MODIFIED": 0, "pairings_unapplied": 0}
# line 161 (test_an_identical_obligation_produces_no_change):
    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
# line 177 (test_a_reworded_obligation_in_the_same_section_is_one_modified):
    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1, "pairings_unapplied": 0}
# line 257 (test_a_section_with_two_reworded_obligations_falls_back_and_says_so):
    assert counts == {"ADDED": 2, "REMOVED": 2, "MODIFIED": 0, "pairings_unapplied": 0}
# line 313 (test_a_rerun_after_a_change_disappears_removes_the_stale_change):
    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
```

- [ ] Run collection and the unit subset: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py --collect-only` — expected: the node ids listed one per line, the four new ones among them, ending `32 tests collected` (the file's 22 pre-plan tests, Task 3's 6, these 4). Then `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"` — expected: `16 passed, 16 deselected` (nothing unit-level regressed; the merge gate runs the 16 integration tests where Docker exists). Neither command takes a trailing `-q`: `addopts = "-q"` already supplies one, and doubling it collapses the collection listing to `tests/test_diff.py: 32` and drops the count line entirely.

- [ ] THE MUTATION CHECK (the drop is called at all): delete the `drop_candidates(...)` call from `diff_versions`. Command, in the merge-gate environment with Docker (this sandbox cannot run integration tests, so this check executes there; here, verify the mutant still collects with `--collect-only`): `cd backend && .venv/bin/pytest tests/test_diff.py::test_rediffing_the_same_pair_leaves_no_stale_candidate` — expected `1 failed`: the stale `auto_paired` edge from the first run survives the re-diff, so the final count is 1 where 0 is asserted. Revert the deletion.

- [ ] THE MUTATION CHECK (both `:MANDATES` anchors are load-bearing): replace `DROP_CANDIDATES` with the either-edition reading —

```python
DROP_CANDIDATES = """
MATCH (v:DocumentVersion)-[:MANDATES]->(:Obligation)-[r:PAIRING_CANDIDATE]-()
WHERE v.version_id IN [$from_version_id, $to_version_id]
DELETE r
"""
```

  Command (merge-gate environment): `cd backend && .venv/bin/pytest tests/test_diff.py::test_rediffing_one_pair_leaves_the_adjacent_pairs_candidates_intact` — expected `1 failed`: re-diffing v1–v2 deletes the v2–v3 edge through v2's shared obligation, so the adjacent count is 0 where 1 is asserted. Revert to the two-anchor statement.

- [ ] THE MUTATION CHECK (the drop is undirected — the task-named mutant): make the candidate match directional, `-[r:PAIRING_CANDIDATE]-` → `-[r:PAIRING_CANDIDATE]->` in `DROP_CANDIDATES`. Command (merge-gate environment): `cd backend && .venv/bin/pytest tests/test_diff.py::test_a_reversed_runs_edges_are_cleaned_by_the_next_chronological_run` — expected `1 failed`: the chronological run's drop only matches v1→v2 edges, the reversed run's v2→v1 edge survives beside the new one, and the undirected count is 2 where 1 is asserted. Revert.

- [ ] THE MUTATION CHECK (the count's unit): change `drop_candidates`' return to `summary.counters.nodes_deleted`. Command (merge-gate environment): `cd backend && .venv/bin/pytest tests/test_diff.py::test_drop_candidates_counts_relationships_not_nodes` — expected `1 failed`: `dropped` is 0 where 1 is asserted. Revert.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/changes/diff.py tests/test_diff.py` — expected: no findings.

- [ ] Commit:

```
git add backend/src/policy_grapher/changes/diff.py backend/tests/test_diff.py
git commit -m "feat: the diff writes pairing candidates and drops them with the pair"
```
### Task 5: Decisions are threaded in

**Files:**
- Modify: `backend/src/policy_grapher/changes/diff.py` — `_plan_changes` (baseline `diff.py:186-276`, as reshaped by Tasks 3–4 into the `PlanResult` shape) and `diff_versions` (baseline `diff.py:290-327`).
- Modify (cycle 4 only): `backend/src/policy_grapher/models.py` (`TriageOut`, models.py:283-302), `backend/src/policy_grapher/routers/triage.py` (`_work`, triage.py:95-111, and the `TriageOut(...)` construction, triage.py:116-148), `frontend/src/api/types.ts` (`TriageOut`, types.ts:193-213).
- Test: `backend/tests/test_diff.py` — a new section appended after Task 3's "§2: every wording-pass outcome is recorded" section, **reusing Task 3's `_score_table` helper** rather than defining a second stub. `backend/tests/test_triage.py` — exactly one integration test appended (cycle 4). `frontend/src/views/Triage.test.tsx` — the `triage: TriageOut` fixture at Triage.test.tsx:56-87 (cycle 4).

**Interfaces:**
- Consumes: from Task 1 — `PairingVerdict` (StrEnum, `PAIRED = "paired"`, `DISTINCT = "distinct"`), `record_pairing(tx, *, old_id: str, new_id: str, verdict: str, actor: str, rationale: str) -> None`, `read_pairings(tx, *, from_version_id: str, to_version_id: str) -> dict[tuple[str, str], str]` (keys as stored, canonical older→newer, scoped through `:MANDATES` to the two named editions), all in `policy_grapher.links.pairing`. From Task 2 — `score_pairing(after_statement: str, before_statement: str) -> Candidate | None`, which Task 3 hoisted to `policy_grapher.changes.diff` module scope; the tests monkeypatch `policy_grapher.changes.diff.score_pairing`. From Task 3 — `PlanResult(changes, candidates, pairings_unapplied)`; `_pair_by_wording(unmatched_old, unmatched_new, paired_old, paired_new, changes, candidates, distinct: set[frozenset[str]]) -> None`, which already skips `distinct` pairs before scoring, so they reach neither `scored`, nor the sub-threshold accumulator, nor the bound's per-endpoint "best"; the outcome labels `auto_paired` / `partner_taken` / `contested` / `below_threshold`; candidate records `{"old_id","new_id","confidence","rationale","outcome"}`; and the test helper `_score_table(monkeypatch, table)`, whose table is keyed `(before_statement, after_statement)` — the old→new reading order every fixture in that file is written in. From Task 4 — `drop_candidates(tx, *, from_version_id: str, to_version_id: str) -> int` and `WRITE_CANDIDATES` (whose only parameter is `$candidates`).
- Produces: `_plan_changes(old, new, decisions: dict[tuple[str, str], str] | None = None) -> PlanResult` with `paired` applied between pass 1 and the `by_section` grouping, `distinct` honoured by pass 2 and pass 3, and `pairings_unapplied` counting pass-1 pre-emptions; `diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]` returning `ADDED`/`REMOVED`/`MODIFIED`/`pairings_unapplied` with the count real, reading decisions itself via `read_pairings` — the pairings queue route (later task) calls `diff_versions` and gets verdict application and the unapplied count for free. `TriageOut.pairings_unapplied: int` on the Triage GET (spec §3 requires the count in *both* GET responses), mirrored as `TriageOut.pairings_unapplied: number` in `frontend/src/api/types.ts`. The fixed paired-verdict summary sentence is `"A reviewer paired these clauses: they are one obligation, reworded between these two editions."` — amended during Task 5's review, because the original wording asserted a chronology this layer explicitly does not have (it carries request order, and a reversed Triage request is supported).

#### Cycle 1 — a `paired` verdict is applied between pass 1 and the grouping

- [ ] Write the failing tests. Append to `backend/tests/test_diff.py`:

```python
# --- decisions threaded into the plan (spec §3) --------------------------------
#
# No second scorer stub here: every test below drives Task 3's `_score_table`,
# defined earlier in this file. Task 3 hoisted `score_pairing` into
# `changes.diff`'s own namespace, so `changes.diff.score_pairing` is the only
# seam that rebinds anything — patching `links.propose` would leave the real
# scorer running behind an inert stub. `_score_table`'s keys are
# (before_statement, after_statement), old→new, which is the order every table
# in this section is written in.


def test_a_paired_decision_beats_the_section_rule(monkeypatch):
    """The fixture rev. 4 could not pass. The decision's old clause sits alone
    in a section with a *different* new clause — exactly what pass 2 pairs
    unconditionally — and the human's pairing must still win. Pass 2 reads only
    the by_section grouping, so the verdict has to be applied before that
    grouping is built; anything later lets a structural heuristic consume a
    human verdict's obligation and shelve the verdict."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(
        _entry("n1", ["7.1"], "The Director shall inform the Comptroller in writing."),
        _entry("n2", ["3.2"], "Records shall be destroyed on schedule."),
    )

    result = _plan_changes(old, new, {("o1", "n1"): "paired"})

    modified = [c for c in result.changes if c["kind"] == MODIFIED]
    assert [(c["obligation_id"], c["previous_statement"]) for c in modified] == [
        ("n1", "The Director shall notify the Comptroller.")
    ]
    assert modified[0]["summary"] == (
        "A reviewer paired these clauses: they are one obligation, "
        "reworded between these two editions."
    )
    assert sorted(c["kind"] for c in result.changes) == [ADDED, MODIFIED]
    added = [c for c in result.changes if c["kind"] == ADDED]
    assert added[0]["obligation_id"] == "n2"


def test_a_paired_decision_pairs_what_nothing_scored_across_sections(monkeypatch):
    """A complete rewording sharing no content words is never scored at all —
    the silent exclusion the problem section names as the case a human most
    obviously beats the measure. The verdict must pair it anyway, across
    differing section paths, at no confidence whatsoever."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["SECTION 4"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("o1", "n1"): "paired"})

    assert [c["kind"] for c in result.changes] == [MODIFIED]
    assert result.changes[0]["obligation_id"] == "n1"
    assert result.changes[0]["previous_statement"] == "The Director shall notify the Comptroller."
    assert result.pairings_unapplied == 0


def test_a_decision_keyed_in_the_other_orientation_still_applies(monkeypatch):
    """The record's canonical direction is older→newer, but this layer binds
    whatever from/to the caller passed — a reversed Triage run flips which side
    each id falls on — so a verdict must apply however the ids fall out."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["SECTION 4"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("n1", "o1"): "paired"})

    assert [c["kind"] for c in result.changes] == [MODIFIED]
    assert result.changes[0]["obligation_id"] == "n1"
    assert result.pairings_unapplied == 0


def test_a_paired_decision_pass_1_preempted_is_counted_not_dropped(monkeypatch):
    """Pass 1 is the one thing that may pre-empt a verdict: an identical clause
    persisting in both editions is a fact, not a pairing judgement. The verdict
    is counted, never dropped or rewritten."""
    _score_table(monkeypatch, {})
    persisting = "The Director shall notify the Comptroller."
    old = _keyed(_entry("o1", ["3.2"], persisting))
    new = _keyed(
        _entry("n1", ["3.2"], persisting),
        _entry("n2", ["SECTION 4"], "Records shall be destroyed on schedule."),
    )

    decisions = {("o1", "n2"): "paired"}
    result = _plan_changes(old, new, decisions)

    assert result.pairings_unapplied == 1
    assert [c["kind"] for c in result.changes] == [ADDED]
    assert result.changes[0]["obligation_id"] == "n2"
    assert decisions == {("o1", "n2"): "paired"}
```

- [ ] Run them and confirm they fail for the right reason:
  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_paired_decision_beats_the_section_rule tests/test_diff.py::test_a_paired_decision_pairs_what_nothing_scored_across_sections tests/test_diff.py::test_a_decision_keyed_in_the_other_orientation_still_applies tests/test_diff.py::test_a_paired_decision_pass_1_preempted_is_counted_not_dropped`
  (No trailing `-q` here, nor on any step in this task that reads a count line or a `--collect-only` node-id listing: `backend/pyproject.toml` already sets `addopts = "-q"`, and a second `-q` drops the count line and the failure summary, leaving only progress dots. The steps that read the terse `tests/<file>: N` form keep the doubled flag, because doubling is what produces that form.)
  Expected: `4 failed`. `_plan_changes` already takes `decisions` (Task 3) and still ignores it, so the failures are the behaviour, not the signature: `test_a_paired_decision_beats_the_section_rule` — the section rule pairs `o1`→`n2`, so `modified` reads `[('n2', 'The Director shall notify the Comptroller.')]`; `test_a_paired_decision_pairs_what_nothing_scored_across_sections` and `test_a_decision_keyed_in_the_other_orientation_still_applies` — `['REMOVED', 'ADDED'] != ['MODIFIED']`; `test_a_paired_decision_pass_1_preempted_is_counted_not_dropped` — `assert 0 == 1` on `pairings_unapplied`.
- [ ] Write the minimal implementation. Replace `_plan_changes` in `backend/src/policy_grapher/changes/diff.py` wholesale (the survivor loops, `_ambiguous`, and the `_pair_by_wording` call keep the Task 3 shape unchanged; `distinct` stays empty this cycle — a `distinct` verdict is deliberately still ignored, that is the next cycle's failing test):

```python
def _plan_changes(
    old: dict[str, dict],
    new: dict[str, dict],
    decisions: dict[tuple[str, str], str] | None = None,
) -> PlanResult:
    """Work out the changes without touching the graph, so the rule is testable
    on its own and readable in one place.

    `decisions` is `{(old_obligation_id, new_obligation_id): verdict}` exactly
    as `links.pairing.read_pairings` returns it — a plain dict for the same
    reason `old` and `new` are plain dicts: no `tx` in here.
    """
    from policy_grapher.links.pairing import PairingVerdict

    unmatched_old = {k: v for k, v in old.items() if k not in new}
    unmatched_new = {k: v for k, v in new.items() if k not in old}

    changes: list[dict] = []
    candidates: list[dict] = []
    distinct: set[frozenset[str]] = set()
    pairings_unapplied = 0

    # A reviewer's verdicts, applied while the only structure that exists is
    # the two unmatched sets. Pass 2 pairs unconditionally and reads only the
    # by_section grouping built below, so a `paired` verdict applied any later
    # can be outranked by a structural heuristic — the inversion the design
    # forbids. Consuming means *deleting* from the unmatched dicts, not
    # marking: pass 2 never reads the paired sets, and a settled clause must
    # not count toward a section's ambiguity tally either. Only pass 1 may
    # pre-empt a verdict — an identical clause persisting in both editions is
    # a fact, not a pairing judgement — and that pre-emption is counted, never
    # silent. The keys arrive in the record's canonical older→newer
    # orientation, but this layer binds whatever from/to the caller passed (a
    # reversed Triage run flips the sides), so both orientations are tried.
    # Two live `paired` verdicts sharing an endpoint are refused at the POST
    # and retired by the migration, so the second-pop case below can only be
    # pass 1's.
    by_id_old = {entry["id"]: key for key, entry in unmatched_old.items()}
    by_id_new = {entry["id"]: key for key, entry in unmatched_new.items()}
    for (first, second), verdict in (decisions or {}).items():
        if verdict == PairingVerdict.DISTINCT:
            continue
        forward = (by_id_old.get(first), by_id_new.get(second))
        backward = (by_id_old.get(second), by_id_new.get(first))
        if forward[0] in unmatched_old and forward[1] in unmatched_new:
            old_key, new_key = forward
        elif backward[0] in unmatched_old and backward[1] in unmatched_new:
            old_key, new_key = backward
        else:
            pairings_unapplied += 1
            continue
        before = unmatched_old.pop(old_key)
        after = unmatched_new.pop(new_key)
        changes.append(
            {
                "kind": MODIFIED,
                "obligation_id": after["id"],
                "section_path": after["section_path"],
                "statement": after["statement"],
                "previous_statement": before["statement"],
                "modality": after["modality"],
                "summary": (
                    "A reviewer paired these clauses: the newer statement is "
                    "the older one reworded."
                ),
            }
        )

    by_section_old = defaultdict(list)
    by_section_new = defaultdict(list)
    for entry in unmatched_old.values():
        by_section_old[tuple(entry["section_path"])].append(entry)
    for entry in unmatched_new.values():
        by_section_new[tuple(entry["section_path"])].append(entry)

    paired_old: set[str] = set()
    paired_new: set[str] = set()

    for section, news in by_section_new.items():
        olds = by_section_old.get(section, [])
        if len(olds) == 1 and len(news) == 1:
            before, after = olds[0], news[0]
            paired_old.add(before["id"])
            paired_new.add(after["id"])
            changes.append(
                {
                    "kind": MODIFIED,
                    # The new obligation: it is the one a reviewer must now act on.
                    "obligation_id": after["id"],
                    "section_path": after["section_path"],
                    "statement": after["statement"],
                    "previous_statement": before["statement"],
                    "modality": after["modality"],
                    "summary": (
                        f"The obligation in section {'/'.join(section)} was reworded."
                    ),
                }
            )

    # ADR-031. What section-based pairing could not reach gets a second pass on
    # wording. Structure first, always: a section holding one unmatched clause
    # each side has been edited, and no measurement improves on a certainty.
    #
    # The measure is `links/propose.py`'s, unchanged — shared content words
    # weighted by shared designators, scored against the shorter statement. It
    # keeps every row explainable by a path a person can walk, which is what
    # ADR-015 actually required; "no text similarity" was the mechanism, not the
    # constraint.
    _pair_by_wording(
        unmatched_old, unmatched_new, paired_old, paired_new, changes, candidates, distinct
    )

    def _ambiguous(section: tuple[str, ...]) -> str | None:
        if len(by_section_old.get(section, [])) + len(by_section_new.get(section, [])) > 1:
            return AMBIGUOUS_SECTION.format(section="/".join(section))
        return None

    for entry in unmatched_old.values():
        if entry["id"] in paired_old:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": REMOVED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _ambiguous(section)
                or f"The obligation in section {'/'.join(section)} is gone.",
            }
        )

    for entry in unmatched_new.values():
        if entry["id"] in paired_new:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": ADDED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _ambiguous(section)
                or f"A new obligation appears in section {'/'.join(section)}.",
            }
        )

    return PlanResult(
        changes=changes, candidates=candidates, pairings_unapplied=pairings_unapplied
    )
```

- [ ] Run the four tests again (same command). Expected: `4 passed`.
- [ ] Run the file's whole unit slice for regressions: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"`. Expected: `20 passed, 16 deselected` (the 16 standing after Task 4, plus these four).
- [ ] THE MUTATION CHECK (application order): in `_plan_changes`, move the entire decision loop (from `by_id_old = ...` through the `changes.append` closing the loop) to just below the `by_section_new` construction. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_paired_decision_beats_the_section_rule`. Expected: `1 failed` — the `modified == [("n1", ...)]` assertion sees two `MODIFIED` rows, the section rule's `n2` beside the decision's `n1`, because the grouping was built while `o1` was still unmatched. Revert the move.
- [ ] THE MUTATION CHECK (orientation): delete the `elif backward[0] in unmatched_old and backward[1] in unmatched_new:` branch (fold to `else`). Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_decision_keyed_in_the_other_orientation_still_applies`. Expected: `1 failed` — `['REMOVED', 'ADDED'] != ['MODIFIED']`, the reversed key fell into the unapplied arm. Revert.
- [ ] THE MUTATION CHECK (the count): replace `pairings_unapplied += 1` with `pass`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_paired_decision_pass_1_preempted_is_counted_not_dropped`. Expected: `1 failed` — `assert 0 == 1`. Revert.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/changes/diff.py tests/test_diff.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/changes/diff.py backend/tests/test_diff.py && git commit -m "feat: a paired verdict outranks the section rule and applies in either orientation"`.

#### Cycle 2 — `distinct` suppresses pass 2 and pass 3, and shadows nothing

- [ ] Write the failing tests. Append to `backend/tests/test_diff.py`:

```python
def test_a_distinct_decision_suppresses_the_section_rule(monkeypatch):
    """Alone in a section, the two clauses are exactly what pass 2 re-pairs on
    structure — the verdict must stop it, or `distinct` is only honoured where
    the wording pass happens to be the decliner."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["3.2"], "The Director shall notify the Auditor."))

    control = _plan_changes(old, new)
    assert [c["kind"] for c in control.changes] == [MODIFIED]

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]


def test_a_distinct_decision_suppresses_a_wording_pairing(monkeypatch):
    """The other decliner. The pair scores well above PAIRING_CONFIDENCE, so
    without the verdict it auto-pairs — and a settled pair must not come back
    as a candidate either: the :PairingDecision is the record, and a candidate
    edge would re-ask a settled question."""
    old_statement = "The Director shall notify the Comptroller."
    new_statement = "The Director must notify the Comptroller promptly."
    _score_table(monkeypatch, {(old_statement, new_statement): 0.9})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], old_statement))
    new = _keyed(_entry("n1", ["SECTION 4"], new_statement))

    control = _plan_changes(old, new)
    assert [c["kind"] for c in control.changes] == [MODIFIED]
    assert [c["outcome"] for c in control.candidates] == ["auto_paired"]

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]
    assert result.candidates == []


def test_a_distinct_sub_threshold_pair_neither_records_nor_shadows(monkeypatch):
    """The reviewer said *not this one*, so its score must not shadow the
    endpoint's next-best live candidate in the bound. o1's settled 0.60 would
    otherwise be o1's best and 0.50 falls outside PAIRING_MARGIN of it; n2
    cannot rescue the record either, because n2's own best is 0.58."""
    o1_statement = "The Director shall notify the Comptroller."
    o2_statement = "Components shall report annually to the Secretary."
    n1_statement = "The Director shall inform the Comptroller."
    n2_statement = "Reports go to the Secretary each year."
    _score_table(
        monkeypatch,
        {
            (o1_statement, n1_statement): 0.60,
            (o1_statement, n2_statement): 0.50,
            (o2_statement, n2_statement): 0.58,
        },
    )
    old = _keyed(
        _entry("o1", ["1.1"], o1_statement),
        _entry("o2", ["2.2"], o2_statement),
    )
    new = _keyed(
        _entry("n1", ["8.1"], n1_statement),
        _entry("n2", ["9.9"], n2_statement),
    )

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert MODIFIED not in [c["kind"] for c in result.changes]
    recorded = {(c["old_id"], c["new_id"]): c for c in result.candidates}
    assert ("o1", "n1") not in recorded
    assert recorded[("o1", "n2")]["outcome"] == "below_threshold"
    assert recorded[("o2", "n2")]["outcome"] == "below_threshold"
    assert len(recorded) == 2
```

- [ ] Run them: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_distinct_decision_suppresses_the_section_rule tests/test_diff.py::test_a_distinct_decision_suppresses_a_wording_pairing tests/test_diff.py::test_a_distinct_sub_threshold_pair_neither_records_nor_shadows`
  Expected: `3 failed` — the first two on their final `sorted(...) == [ADDED, REMOVED]` assertion (a `MODIFIED` is still produced, because `distinct` verdicts are skipped by cycle 1's `continue`), the third on `assert ("o1", "n1") not in recorded` (the settled pair was recorded as `below_threshold`).
- [ ] Write the minimal implementation — two edits to `_plan_changes` in `backend/src/policy_grapher/changes/diff.py`. First, the `distinct` branch of the decision loop stops discarding and builds the set (replace the two lines `if verdict == PairingVerdict.DISTINCT:` / `continue`):

```python
        if verdict == PairingVerdict.DISTINCT:
            # Orientation-free by construction — a frozenset of the two ids —
            # so the reversed-run problem the paired arm handles above cannot
            # arise here. `_pair_by_wording` drops these from `scored`, from
            # the sub-threshold recording, and from the bound's "best": the
            # reviewer said *not this one*, so its score must not shadow the
            # endpoint's next-best live candidate.
            distinct.add(frozenset((first, second)))
            continue
```

  Second, pass 2 honours the set (insert directly after `before, after = olds[0], news[0]`):

```python
            if frozenset((before["id"], after["id"])) in distinct:
                # The reviewer said these are not the same clause. This rule
                # pairs on structure alone and would re-pair them; a human
                # verdict outranks it, so the pair falls through to
                # ADDED/REMOVED like any other decline.
                continue
```

  The full pass-2 loop now reads:

```python
    for section, news in by_section_new.items():
        olds = by_section_old.get(section, [])
        if len(olds) == 1 and len(news) == 1:
            before, after = olds[0], news[0]
            if frozenset((before["id"], after["id"])) in distinct:
                # The reviewer said these are not the same clause. This rule
                # pairs on structure alone and would re-pair them; a human
                # verdict outranks it, so the pair falls through to
                # ADDED/REMOVED like any other decline.
                continue
            paired_old.add(before["id"])
            paired_new.add(after["id"])
            changes.append(
                {
                    "kind": MODIFIED,
                    # The new obligation: it is the one a reviewer must now act on.
                    "obligation_id": after["id"],
                    "section_path": after["section_path"],
                    "statement": after["statement"],
                    "previous_statement": before["statement"],
                    "modality": after["modality"],
                    "summary": (
                        f"The obligation in section {'/'.join(section)} was reworded."
                    ),
                }
            )
```

- [ ] Run the three tests again (same command). Expected: `3 passed`.
- [ ] Run the file's whole unit slice: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"`. Expected: `23 passed, 16 deselected` (the 20 standing after cycle 1, plus these three).
- [ ] THE MUTATION CHECK (pass 2): delete the `if frozenset((before["id"], after["id"])) in distinct: continue` guard from the section loop. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_distinct_decision_suppresses_the_section_rule`. Expected: `1 failed` — `['MODIFIED'] != ['ADDED', 'REMOVED']`. Revert.
- [ ] THE MUTATION CHECK (pass 3 wiring): at the `_pair_by_wording` call site, pass `set()` in place of `distinct`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_distinct_decision_suppresses_a_wording_pairing`. Expected: `1 failed` — the 0.9 pair auto-pairs and `sorted(...) == [ADDED, REMOVED]` fails. Revert.
- [ ] THE MUTATION CHECK (the bound's "best"): move Task 3's `distinct` guard out of `_pair_by_wording`'s scoring loop and down to the keep filter, which is the shape the bound's wording exists to forbid. Two edits: delete the two lines

```python
            if frozenset((before["id"], after["id"])) in distinct:
                continue
```

  from the cross-product loop, and wrap the post-loop keep rule's append so the exclusion happens only there — `candidates.append(record)` becomes

```python
            if frozenset((record["old_id"], record["new_id"])) not in distinct:
                candidates.append(record)
```

  Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py::test_a_distinct_sub_threshold_pair_neither_records_nor_shadows`. Expected: `1 failed` with `KeyError: ('o1', 'n2')`. The settled 0.60 now enters `sub_threshold` and sets `best_sub["o1"] = 0.60`, so o1's live 0.50 sits 0.10 outside `PAIRING_MARGIN` of it and n2's own best of 0.58 cannot rescue it either — the record is dropped, and the test's *third* assertion (`recorded[("o1", "n2")]`) is the one that raises. The `("o1", "n1") not in recorded` assertion above it still passes, because the append is still screened. Revert both edits.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/changes/diff.py tests/test_diff.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/changes/diff.py backend/tests/test_diff.py && git commit -m "feat: a distinct verdict suppresses the section rule and the wording pass alike"`.

#### Cycle 3 — `diff_versions` reads the decisions itself

- [ ] Write the failing integration test. Append to `backend/tests/test_diff.py`:

```python
@pytest.mark.integration
def test_diff_versions_applies_a_recorded_pairing_decision(clean_graph, database):
    """No wiring by the caller: `diff_versions` reads the decisions itself,
    scoped through :MANDATES to the two named editions, so a verdict recorded
    through /pairings takes effect on the very next diff — Triage's or the
    queue's alike. The two statements share no content words, so nothing here
    is scored: only the decision can produce the MODIFIED."""
    from policy_grapher.extraction.schema import obligation_id
    from policy_grapher.links.pairing import record_pairing

    old_statement = "The Director shall notify the Comptroller of any breach."
    new_statement = "Records shall be destroyed at the end of their retention period."
    _seed(
        clean_graph, database, version_id="v1",
        entries=[("3.2", old_statement, Modality.SHALL)],
    )
    _seed(
        clean_graph, database, version_id="v2",
        entries=[("9.9", new_statement, Modality.SHALL)],
    )
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=obligation_id("v1", ["3.2"], old_statement),
            new_id=obligation_id("v2", ["9.9"], new_statement),
            verdict="paired",
            actor="tester",
            rationale="a complete rewording the measure cannot see",
        )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1, "pairings_unapplied": 0}
    change = _changes(clean_graph, database)[0]
    assert change["previous_statement"] == old_statement
    assert change["statement"] == new_statement
    assert "reviewer paired" in change["summary"]
```

- [ ] Verify it collects (this sandbox has no Docker; the merge gate runs it): `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py --collect-only`. Expected: the node ids listed one per line with `tests/test_diff.py::test_diff_versions_applies_a_recorded_pairing_decision` among them, zero collection errors, ending `40 tests collected` (the 32 standing after Task 4, plus cycle 1's four and cycle 2's three, plus this one). At the gate, pre-implementation, this test fails with `{'ADDED': 1, 'REMOVED': 1, 'MODIFIED': 0, 'pairings_unapplied': 0} != {...'MODIFIED': 1...}` — the decision is on disk and nothing reads it.
- [ ] Write the implementation. Replace `diff_versions` in `backend/src/policy_grapher/changes/diff.py` wholesale (the Task 5 delta is the `read_pairings` import and call, the third argument to `_plan_changes`, and the now-real `pairings_unapplied`; the drop/write of candidates keeps Task 4's shape):

```python
def diff_versions(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[str, int]:
    """Diff two editions and write the result. Returns counts by kind, plus
    `pairings_unapplied` — `paired` verdicts pass 1 pre-empted on this run.

    Drops this pair's existing changes and candidates first rather than
    merging over them: a re-extraction can make either stop existing, and a
    stale record shows a reviewer something that is no longer real. Ids are
    deterministic, so what *does* still exist comes back identical.

    The reviewer's pairing decisions are read here and threaded down — scoped
    through :MANDATES to the two named editions, so a middle edition's verdict
    cannot leak into a neighbouring pair's diff, and a verdict recorded on the
    pairing screen applies on the very next diff with no wiring by any caller.
    Imported inside the function so `changes` never imports `links.pairing` at
    module level.
    """
    from policy_grapher.links.pairing import read_pairings

    old = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": from_version_id}))
    new = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": to_version_id}))

    tx.run(
        DROP_PAIR,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()
    drop_candidates(
        tx, from_version_id=from_version_id, to_version_id=to_version_id
    )

    decisions = read_pairings(
        tx, from_version_id=from_version_id, to_version_id=to_version_id
    )
    result = _plan_changes(old, new, decisions)
    for change in result.changes:
        change["change_id"] = change_id(
            from_version_id, to_version_id, change["kind"], change["obligation_id"]
        )

    if result.changes:
        tx.run(
            WRITE_CHANGES,
            {
                "from_version_id": from_version_id,
                "to_version_id": to_version_id,
                "changes": result.changes,
            },
        ).consume()
    if result.candidates:
        tx.run(WRITE_CANDIDATES, {"candidates": result.candidates}).consume()

    counts = dict.fromkeys(KINDS, 0)
    for change in result.changes:
        counts[change["kind"]] += 1
    counts["pairings_unapplied"] = result.pairings_unapplied
    return counts
```

- [ ] Verify collection again (same `--collect-only` command, same `40 tests collected`) and re-run the unit slice: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_diff.py -k "not integration"`. Expected: `23 passed, 17 deselected` — the deselected count rises by one because this cycle's addition is integration-marked.
- [ ] THE MUTATION CHECK (deferred to the merge gate, named now): in `diff_versions`, pass `None` in place of `decisions` to `_plan_changes`. At the gate, `tests/test_diff.py::test_diff_versions_applies_a_recorded_pairing_decision` fails — counts read `ADDED: 1, REMOVED: 1, MODIFIED: 0`. The unit-level wiring beneath it is already mutation-checked in cycles 1–2; this check runs where Docker exists. Revert.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/changes/diff.py tests/test_diff.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/changes/diff.py backend/tests/test_diff.py && git commit -m "feat: the diff reads recorded pairing verdicts and reports the ones pass 1 pre-empted"`.

#### Cycle 4 — the Triage GET reports what it could not apply

Spec §3 puts `pairings_unapplied` on *both* GET responses that run the diff. Triage already runs it and discards the return (`routers/triage.py:96-98`), which was harmless while the key was always `0` and stops being harmless the moment cycle 1 makes it real. Exactly one integration test is added to `backend/tests/test_triage.py` here, and the frontend type is renamed in the same cycle as the model, because `frontend/src/views/Triage.test.tsx` declares a `TriageOut`-typed fixture and `npm test` runs `tsc -b` — a model that gains a required field without its mirror leaves the frontend gate red for every task after this one.

- [ ] Write the failing test. Append to `backend/tests/test_triage.py`:

```python
@pytest.mark.integration
def test_the_triage_get_reports_a_verdict_it_could_not_apply(client_with_auth):
    """The false-all-clear guard, extended to the reviewer's own verdicts.

    A `paired` verdict naming a clause pass 1 matches identically in both
    editions cannot be applied: the clause never reaches the unmatched sets, so
    there is nothing left for the verdict to pair. The diff counts that
    pre-emption, and the route has to carry the count out — discarding it leaves
    a reviewer reading a Triage table that silently ignored a decision they
    made, which is the defect `unlinked_changes` exists to prevent one layer
    down. And the verdict itself must survive: a count is a report, not a
    retraction.
    """
    from policy_grapher.links.pairing import record_pairing

    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    persisting = "Components shall retain records for seven years."
    old_ids = _seed_version(
        driver, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", HIGHER_OLD, Modality.SHALL),
                 ("9.9", persisting, Modality.SHALL)],
    )
    new_ids = _seed_version(
        driver, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", HIGHER_NEW, Modality.SHALL),
                 ("9.9", persisting, Modality.SHALL)],
    )
    # 9.9 is word-for-word identical across the two editions, so `content_key`
    # matches it in pass 1 and the verdict below has nothing left to bind.
    with driver.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=old_ids[persisting],
            new_id=new_ids[HIGHER_NEW],
            verdict="paired",
            actor="tester",
            rationale="the retention clause became the annual one",
        )

    body = client_with_auth.get(
        "/triage",
        params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"},
    ).json()

    assert body["pairings_unapplied"] == 1
    # The 3.2 rewording is still found by the section rule, so the run did the
    # ordinary work as well as reporting the verdict it could not apply.
    assert body["total_changes"] == 1
    records, _, _ = driver.execute_query(
        "MATCH (p:PairingDecision) RETURN p.verdict AS verdict", database_=database
    )
    assert [r["verdict"] for r in records] == ["paired"], (
        "an unapplied verdict is reported, never retracted"
    )
```

- [ ] Verify it collects (Docker-gated, like every test in this file's integration set): `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q`. Expected: `tests/test_triage.py: 24` (one more than the 23 the file has held since before this plan), zero collection errors. At the merge gate, pre-implementation, it fails with `KeyError: 'pairings_unapplied'` — the route's response model has no such field.
- [ ] Write the implementation. Four edits, in one cycle because the last two are the two halves of one mirror. First, in `backend/src/policy_grapher/models.py`, replace `TriageOut` (models.py:283-302):

```python
class TriageOut(BaseModel):
    """`from_version_id` is echoed back because it may have been defaulted: a
    caller who omitted it needs to know which earlier edition the answer is about.

    `unlinked_changes` is what keeps an empty `rows` honest. Without it, "nothing
    you own is affected" and "nothing has been reviewed yet, so this cannot see
    anything" are the same response, and one of them is a false all-clear.

    `pairings_unapplied` extends that discipline to the reviewer's own verdicts.
    This GET runs the diff, and the diff applies the recorded pairing decisions;
    a `paired` verdict naming a clause pass 1 has already matched as persisting
    unchanged has nothing left to bind. Reporting the number is the difference
    between a reviewer being told their decision did not land and a table that
    quietly proceeded as though it had. The verdict is untouched on disk — only
    unapplied on this pair, on this run.
    """

    from_version_id: str
    to_version_id: str
    rows: list[TriageRowOut]
    total_changes: int
    unlinked_changes: int
    pairings_unapplied: int
    # An empty `rows` has three causes, and they are not the same finding:
    # nothing is linked (unlinked_changes), nothing changed (total_changes), or
    # nothing was ever extracted. Only these two can tell the third from the
    # second, and the default `null` extractor makes the third the common case.
    from_obligations: int
    to_obligations: int
```

  Second, in `backend/src/policy_grapher/routers/triage.py`, replace `_work` and the session block (triage.py:95-114):

```python
    def _work(tx):
        # The diff's return was discarded here while everything in it could be
        # had another way — the triage below counts the changes itself.
        # `pairings_unapplied` cannot: it is a reviewer's verdict this run could
        # not apply, known only to the plan that failed to apply it and gone the
        # moment this value is dropped. Spec §3 puts it on both GETs that run
        # the diff.
        counts = diff_versions(
            tx, from_version_id=resolved_from, to_version_id=to_version_id
        )
        result = run_triage(
            tx, from_version_id=resolved_from, to_version_id=to_version_id
        )
        # Read inside the same transaction as the diff and the triage, so the
        # count reflects the same graph state those two just read — not a
        # separate read that could race a concurrent rebuild.
        from_obligations = tx.run(
            COUNT_OBLIGATIONS, {"version_id": resolved_from}
        ).single()["obligations"]
        to_obligations = tx.run(
            COUNT_OBLIGATIONS, {"version_id": to_version_id}
        ).single()["obligations"]
        return (
            result,
            from_obligations,
            to_obligations,
            counts["pairings_unapplied"],
        )

    with driver.session(database=database) as session:
        result, from_obligations, to_obligations, pairings_unapplied = (
            session.execute_write(_work)
        )
```

  and add one line to the `TriageOut(...)` construction, directly after `unlinked_changes=result.unlinked_changes,` (triage.py:120):

```python
        pairings_unapplied=pairings_unapplied,
```

  Third, in `frontend/src/api/types.ts`, insert the mirror into `TriageOut` directly after `unlinked_changes: number` (types.ts:204):

```tsx
  /**
   * `paired` verdicts the diff behind this request could not apply, because
   * pass 1 had already matched one of the two clauses as persisting unchanged.
   * Required, not optional: the pairing queue carries the same count and the
   * screen reads it, and a field that may be absent is a field a screen can
   * forget. Not a retraction — the decision is still recorded — but it has to
   * be shown, for the reason `unlinked_changes` has to be.
   */
  pairings_unapplied: number
```

  Fourth, in `frontend/src/views/Triage.test.tsx`, add the field to the `triage: TriageOut` fixture, directly after `unlinked_changes: 2,` (Triage.test.tsx:60):

```tsx
  pairings_unapplied: 0,
```

  That fixture is the only `TriageOut`-typed literal in the frontend, and without this line `tsc -b` fails with `src/views/Triage.test.tsx(56,7): error TS2741: Property 'pairings_unapplied' is missing in type '{ ... }' but required in type 'TriageOut'`.

- [ ] Verify collection again: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q`. Expected: `tests/test_triage.py: 24`, zero errors. Then run the backend's unit slice for this file, which the change must not disturb: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py -k "not integration"`. Expected: `4 passed, 20 deselected` (the file's four pure weight-table tests; everything else here needs Docker, and the deselected count is one higher than before this cycle).
- [ ] Verify the type change where it was made: `cd /home/rhagan/policy_grapher/frontend && npm test -- src/views/Triage.test.tsx`. Expected: eslint and `tsc -b` print nothing, then vitest reports `Test Files  1 passed (1)` and `Tests  15 passed (15)` — the fixture gained a field, not a test.
- [ ] THE MUTATION CHECK (the route carries the count — deferred to the merge gate, named now): in `routers/triage.py`, discard the diff's return again (`diff_versions(tx, from_version_id=resolved_from, to_version_id=to_version_id)` with no assignment, `_work` returning its original three values, the session unpack back to three names) and hardcode `pairings_unapplied=0` in the `TriageOut(...)` construction. At the gate, `tests/test_triage.py::test_the_triage_get_reports_a_verdict_it_could_not_apply` fails `assert 0 == 1`; the model still validates and every other Triage test still passes, which is why this test had to exist. In this sandbox, confirm the mutant still collects with `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q` (`tests/test_triage.py: 24`). Revert.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/models.py src/policy_grapher/routers/triage.py tests/test_triage.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/models.py backend/src/policy_grapher/routers/triage.py backend/tests/test_triage.py frontend/src/api/types.ts frontend/src/views/Triage.test.tsx && git commit -m "feat: the triage response says how many pairing verdicts the diff could not apply"`.

---

### Task 6: propose_links skips one document, and the empty-queue truth changes with it

**Files:**
- Modify: `backend/src/policy_grapher/links/propose.py` (`READ_OBLIGATIONS`, propose.py:94-98; `propose_links`, propose.py:111-151, replaced wholesale — its two `READ_OBLIGATIONS` calls at 123-124 keep their shape and their rows gain a field), `backend/src/policy_grapher/routers/review.py` (the `WHY_EMPTY` comment and query, review.py:89-100; the handler's constructor line, review.py:157), `backend/src/policy_grapher/models.py` (`ReviewQueueOut`, models.py:221-244), `frontend/src/api/types.ts` (`ReviewQueue`, types.ts:152-162), `frontend/src/views/Review.tsx` (the second empty-state branch, Review.tsx:158-165).
- Test: `backend/tests/test_links.py` (append after line 693), `backend/tests/test_review.py` (the STORY-090 section, test_review.py:250-314, including deleting the unused `COMPARABLE` constant), `frontend/src/views/Review.test.tsx` (the `q` helper and its comment at 19-28, the "why the queue is empty" describe at 314-346, the stubs at 329 and 368).

**Interfaces:**
- Consumes: nothing from Tasks 1–5 — `score_pair` and the proposal path are untouched by them (`score_pairing` is additive to `propose.py` and unused here).
- Produces: `READ_OBLIGATIONS` rows now `{id, statement, document_slug}`; `propose_links` (signature unchanged) writes no proposal between obligations sharing a `:Document`; `ReviewQueueOut.documents_with_obligations: int` (distinct documents holding ≥ 1 obligation in any edition; proposals possible iff ≥ 2), mirrored as `ReviewQueue.documents_with_obligations` in `types.ts` — `documents_comparable` no longer exists on either side. Later frontend tasks (`DocumentDetail` fieldset) rely on the skip being live so cross-document candidates are the only productive ones.

#### Cycle 1 — a pair inside one document is never proposed

- [ ] Write the failing integration tests. Append to `backend/tests/test_links.py`:

```python
# --- IMPLEMENTS is cross-document only (pairing design §1) ---------------------


def _seed_second_edition(driver, database, *, of, version_id, statements):
    """A second edition of a document `_seed_version` already created.

    `_seed_version` keys one document per version id, so the same-document
    shape — two editions under one :Document — has to be built here.
    """
    driver.execute_query(
        "MATCH (d:Document {slug: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": of, "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    obligations = [
        ExtractedObligation(
            statement=s,
            modality=Modality.MUST,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        )
        for s in statements
    ]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=obligations,
        )


@pytest.mark.integration
def test_a_pair_inside_one_document_is_never_proposed(clean_graph, database):
    """Two editions of one instrument are the pairing question, not the
    implements one — an edition does not discharge its predecessor. These two
    statements produce a proposal across two documents elsewhere in this file,
    so a written count of zero here can only be the document skip."""
    _seed_version(clean_graph, database, version_id="org", statements=[ORG])
    _seed_second_edition(
        clean_graph, database, of="org", version_id="org@2024", statements=[HIGHER]
    )

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org@2024"],
            proposer="lexical-v1",
        )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS_PROPOSED]->() RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_the_cross_document_pair_is_still_proposed_beside_a_skipped_one(
    clean_graph, database
):
    """The skip must not be a clause too wide. The same statement is offered
    from a sibling edition and from another document; exactly the
    cross-document pair survives."""
    _seed_version(clean_graph, database, version_id="org", statements=[ORG])
    _seed_second_edition(
        clean_graph, database, of="org", version_id="org@2024", statements=[HIGHER]
    )
    _seed_version(clean_graph, database, version_id="higher", statements=[HIGHER])

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org@2024", "higher"],
            proposer="lexical-v1",
        )

    assert written == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Obligation)-[:IMPLEMENTS_PROPOSED]->(t:Obligation)"
        "<-[:MANDATES]-(v:DocumentVersion) RETURN v.version_id AS version",
        database_=database,
    )
    assert [r["version"] for r in records] == ["higher"]
```

- [ ] Verify they collect (no Docker here; the merge gate runs them): `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py --collect-only -q`. Expected: `tests/test_links.py: 37` (the file's 31 pre-plan tests, Task 2's four, and these two), zero collection errors. At the gate, pre-implementation, `test_a_pair_inside_one_document_is_never_proposed` fails `assert 1 == 0` (the single ORG→HIGHER pair is still proposed) and `test_the_cross_document_pair_is_still_proposed_beside_a_skipped_one` fails `assert 2 == 1`.
- [ ] Write the implementation in `backend/src/policy_grapher/links/propose.py`. Replace `READ_OBLIGATIONS` (propose.py:94-98):

```python
READ_OBLIGATIONS = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)-[:MANDATES]->(o:Obligation)
WHERE v.version_id IN $version_ids
RETURN o.obligation_id AS id,
       o.statement     AS statement,
       d.slug          AS document_slug
"""
```

  and replace `propose_links` (propose.py:111-151) wholesale:

```python
def propose_links(
    tx: ManagedTransaction,
    *,
    org_version_id: str,
    candidate_version_ids: list[str],
    proposer: str,
) -> int:
    """Propose which obligation of `org_version_id` implements which of the
    candidates. Returns how many proposals were written.

    Writes `IMPLEMENTS_PROPOSED` and nothing else. `IMPLEMENTS` has exactly one
    writer — `decisions.replay_decisions` — and this is deliberately not it.
    Pairs whose obligations share a document are not proposed at all: between
    two editions of one instrument the question is pairing, not implementation,
    and the diff asks it.
    """
    ours = list(tx.run(READ_OBLIGATIONS, {"version_ids": [org_version_id]}))
    theirs = list(tx.run(READ_OBLIGATIONS, {"version_ids": candidate_version_ids}))
    if not ours or not theirs:
        return 0

    proposals = []
    for org in ours:
        for higher in theirs:
            # A version named as its own candidate would otherwise link every
            # clause to itself at confidence 1.0 and swamp the queue.
            if org["id"] == higher["id"]:
                continue
            # Two editions of one instrument are the pairing question — is the
            # newer clause the older one reworded? — and that question has its
            # own decision node and its own queue. An IMPLEMENTS between them
            # asserts that a document discharges its own predecessor, which is
            # the claim the sprint-12 walkthrough found scored at the top of
            # Triage.
            if org["document_slug"] == higher["document_slug"]:
                continue
            candidate = score_pair(org["statement"], higher["statement"])
            if candidate is None:
                continue
            proposals.append(
                {
                    "source": org["id"],
                    "target": higher["id"],
                    "confidence": candidate.confidence,
                    "rationale": candidate.rationale,
                    "proposer": proposer,
                }
            )

    if proposals:
        tx.run(WRITE_PROPOSALS, {"proposals": proposals}).consume()
    return len(proposals)
```

- [ ] Verify collection again: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py --collect-only -q`. Expected: `tests/test_links.py: 37`, unchanged, zero errors. The pure tests in the file still run here: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration"` — expected: `15 passed, 22 deselected` (the file's 11 pre-plan unit tests plus Task 2's four; both additions above are integration-marked, so the passing count is unchanged and only the deselected count moves).
- [ ] THE MUTATION CHECK (deferred to the merge gate, named now): remove the `if org["document_slug"] == higher["document_slug"]: continue` comparison. At the gate, `test_a_pair_inside_one_document_is_never_proposed` fails `assert 1 == 0` and `test_the_cross_document_pair_is_still_proposed_beside_a_skipped_one` fails `assert 2 == 1`. Revert.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/propose.py tests/test_links.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/links/propose.py backend/tests/test_links.py && git commit -m "feat: propose_links no longer proposes pairs inside one document"`.

#### Cycle 2 — `WHY_EMPTY` counts documents with obligations, not comparable ones

- [ ] Write the failing tests. In `backend/tests/test_review.py`, delete the `COMPARABLE` constant (test_review.py:252-257 — defined, never used, and it encodes the retired definition) and replace the **three** tests of the STORY-090 section (the section comment at 250 through `test_the_queue_reports_a_document_whose_editions_can_be_compared` at 314) with the four below. Three sufficed for `documents_comparable`; the new count needs a fourth, because one document with two obligation-holding editions and two documents with one edition each are the two configurations the retired definition confused, and no single fixture separates them. The file goes from 15 collected to 16.

```python
# --- why the queue is empty (STORY-090, redefined by the pairing design) -------


@pytest.mark.integration
def test_the_queue_says_no_edition_holds_obligations(client_with_auth):
    """An empty queue has three causes and says which. This is the first:
    nothing has been extracted anywhere, so no proposal could exist."""
    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 0
    assert body["documents_with_obligations"] == 0


@pytest.mark.integration
def test_the_queue_says_only_one_document_holds_obligations(client_with_auth):
    """The second: obligations exist, but in one document only. A proposal now
    runs between two documents — `propose_links` skips same-document pairs —
    so this configuration cannot fill the queue and the count must say so."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(driver, database, version_id="only@2020", name="Only", statement=ORG)

    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 1
    assert body["documents_with_obligations"] == 1


@pytest.mark.integration
def test_a_document_with_two_obligation_holding_editions_still_counts_once(
    client_with_auth,
):
    """The retired `documents_comparable` called exactly this shape comparable
    and reported the all-clear on it. It is now the configuration that can no
    longer yield a proposal, so it must read as one document — anything else is
    the false all-clear STORY-090 added this count to prevent."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    # One document, two editions, each mandating something. `_seed_version`
    # keys a document per version, so this is built here.
    driver.execute_query(
        "MERGE (d:Document {slug: 'two-editions', name: 'Two Editions'}) "
        "MERGE (d)-[:HAS_VERSION]->(a:DocumentVersion {version_id: 'te@2018', "
        "  checksum: 'a', source_uri: 'file:///a.pdf'}) "
        "MERGE (d)-[:HAS_VERSION]->(b:DocumentVersion {version_id: 'te@2020', "
        "  checksum: 'b', source_uri: 'file:///b.pdf'}) "
        "MERGE (a)-[:MANDATES]->(:Obligation {obligation_id: 'o-a', "
        "  statement: $higher, modality: 'MUST', section_path: ['1']}) "
        "MERGE (b)-[:MANDATES]->(:Obligation {obligation_id: 'o-b', "
        "  statement: $org, modality: 'MUST', section_path: ['1']})",
        {"higher": HIGHER, "org": ORG},
        database_=database,
    )

    body = client_with_auth.get("/review/queue").json()

    assert body["editions_with_obligations"] == 2
    assert body["documents_with_obligations"] == 1


@pytest.mark.integration
def test_the_queue_reports_two_documents_that_could_be_linked(client_with_auth):
    """The third: two documents each hold an obligation somewhere, so an empty
    queue really does mean the work has been done rather than that it could
    not start. One edition each — under the retired definition this read 0."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(
        driver, database, version_id="higher", name="DoDI 5000.88", statement=HIGHER
    )
    _seed_version(driver, database, version_id="org", name="ORG 1.0", statement=ORG)

    body = client_with_auth.get("/review/queue").json()

    assert body["editions_with_obligations"] == 2
    assert body["documents_with_obligations"] == 2
```

- [ ] Verify they collect: `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_review.py --collect-only -q`. Expected: `tests/test_review.py: 16` (one more than the file's 15, three tests having been replaced by four), zero errors. At the gate, pre-implementation, all four fail with `KeyError: 'documents_with_obligations'`.
- [ ] Write the implementation. In `backend/src/policy_grapher/routers/review.py`, replace the comment and query at review.py:89-100:

```python
# An edition counts only if it actually mandates something. What separates
# "caught up" from "nothing could be here yet" is no longer editions of one
# document — `propose_links` skips same-document pairs, so two editions of one
# instrument can never yield a proposal again — but documents: a proposal is
# possible iff at least two distinct documents hold an obligation in any
# edition.
WHY_EMPTY = """
OPTIONAL MATCH (v:DocumentVersion)-[:MANDATES]->(:Obligation)
WITH count(DISTINCT v) AS editions_with_obligations
OPTIONAL MATCH (d:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(:Obligation)
RETURN editions_with_obligations,
       count(DISTINCT d) AS documents_with_obligations
"""
```

  In the same file, the handler's return (review.py:154-159) becomes:

```python
    return ReviewQueueOut(
        items=items,
        editions_with_obligations=why[0]["editions_with_obligations"],
        documents_with_obligations=why[0]["documents_with_obligations"],
        pending=counted[0]["pending"],
    )
```

  In `backend/src/policy_grapher/models.py`, replace `ReviewQueueOut` (models.py:221-244):

```python
class ReviewQueueOut(BaseModel):
    """The queue, and enough to say why it is empty when it is — STORY-090.

    "Nothing is waiting for review" is true of three different situations and
    tells a reader only one of them: that they are caught up. It is equally
    true when nothing has been extracted anywhere, and when obligations exist
    in only one document — a proposal runs between two documents now that
    same-document pairs belong to the diff, so nothing could be proposed yet.
    `documents_with_obligations` counts distinct documents holding at least
    one obligation in any edition; a proposal is possible iff it is 2 or more.
    Its predecessor, `documents_comparable`, counted documents with two
    obligation-holding editions — exactly the configuration that can no longer
    yield a proposal, so the old count had become the false all-clear
    STORY-090 added it to prevent.

    Counted here rather than derived on the screen so that two views cannot
    drift into answering the same question differently, which is the failure
    mode STORY-067 left open on Triage and this repeats.
    """

    items: list[ReviewItemOut]
    editions_with_obligations: int
    documents_with_obligations: int
    # Undecided proposals in the graph, not rows in `items`. The queue is capped,
    # so the two differ whenever there is real work: the screen read "Proposal 1
    # of 50" over 119 waiting, and went on reading it after every verdict because
    # deciding one refilled the page from the remainder. This is the number that
    # falls as the backlog is worked through.
    pending: int
```

- [ ] Verify collection again (same command, same `tests/test_review.py: 16`) and confirm nothing else in the backend references the old name: `cd /home/rhagan/policy_grapher/backend && grep -rn documents_comparable src tests` — expected: no matches (exit status 1, which is what `grep` returns when it finds nothing).
- [ ] THE MUTATION CHECK (deferred to the merge gate, named now): put the old computation back under the new name — replace `WHY_EMPTY`'s last two lines with the retired `WITH ... count(DISTINCT ev) AS per_document / count(DISTINCT CASE WHEN per_document > 1 THEN d END) AS documents_with_obligations` shape. At the gate, `test_the_queue_reports_two_documents_that_could_be_linked` fails `assert 0 == 2` and `test_the_queue_says_only_one_document_holds_obligations` fails `assert 0 == 1`; `test_a_document_with_two_obligation_holding_editions_still_counts_once` alone cannot tell the two queries apart (both read 1 there), which is why the two-documents fixture exists. Revert.
- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/routers/review.py src/policy_grapher/models.py tests/test_review.py`. Expected: `All checks passed!`.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add backend/src/policy_grapher/routers/review.py backend/src/policy_grapher/models.py backend/tests/test_review.py && git commit -m "feat: the review queue counts documents holding obligations instead of comparable ones"`.

#### Cycle 3 — the Review empty state sends the reader to a second document

- [ ] Write the failing test. In `frontend/src/views/Review.test.tsx`, replace the `q` helper and its comment (Review.test.tsx:19-28):

```tsx
// STORY-090 changed `GET /review/queue` from a bare list to a payload carrying
// the counts that say *why* a queue is empty. `q` keeps the fixtures reading as
// lists; the two counts default to "both sides exist" — two documents holding
// obligations — which is what every test about the queue's contents assumes.
const q = (
  items: unknown[],
  editions_with_obligations = 2,
  documents_with_obligations = 2,
  pending = items.length,
) => ({ items, editions_with_obligations, documents_with_obligations, pending })
```

  In the "why the queue is empty" describe (Review.test.tsx:314-346), replace the middle test and its stub (the first and third tests keep their bodies; the third's stub `q([], 4, 2)` already reads correctly under the new semantics):

```tsx
  it('says a proposal needs a second document when only one holds obligations', async () => {
    // The old advice — build a second edition of a document that already has
    // one — became exactly the action that can no longer produce a proposal:
    // same-document pairs belong to the diff now. The screen must send the
    // reader to a second *document*.
    getReviewQueue.mockResolvedValue(q([], 1, 1))

    render(<Review />)

    expect(
      await screen.findByText(/only one document holds any/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/build a second edition/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/nothing is waiting/i)).not.toBeInTheDocument()
  })
```

  And update the walkthrough stub at Review.test.tsx:368 from `q([item, { ...item }], 2, 1, 119)` to `q([item, { ...item }], 2, 2, 119)`.
- [ ] Run the frontend suite (the real script — eslint, tsc, vitest in one): `cd /home/rhagan/policy_grapher/frontend && npm test`. Expected: eslint and `tsc -b` clean (`getReviewQueue` is a bare `vi.fn()`, so the renamed fixture is not type-checked against `ReviewQueue`), then `Test Files  1 failed | 11 passed (12)` and `Tests  1 failed | 231 passed (232)` — the one failure being `Review, why the queue is empty > says a proposal needs a second document when only one holds obligations` with `Unable to find an element with the text: /only one document holds any/i`. `Review.tsx` still branches on `queue.documents_comparable === 0`, the stub no longer carries that field, `undefined === 0` is false, and the screen falls through to "Nothing is waiting for review" — the exact false all-clear the spec describes. The other two tests in that describe still pass, which is the point: only the middle case can tell the two definitions apart.
- [ ] Write the implementation. In `frontend/src/api/types.ts`, replace the `ReviewQueue` interface (types.ts:152-162):

```tsx
/** The queue plus why it is empty when it is — STORY-090. */
export interface ReviewQueue {
  items: ReviewItem[]
  editions_with_obligations: number
  /** Distinct documents holding at least one obligation in any edition. A
   *  proposal runs between two documents now that same-document pairs belong
   *  to the diff, so the queue can only fill once this reaches 2. The old
   *  `documents_comparable` counted documents with two obligation-holding
   *  editions — exactly the configuration that can no longer yield a
   *  proposal, so keeping it would keep the false all-clear it existed to
   *  prevent. */
  documents_with_obligations: number
  /** Undecided proposals in the graph, not rows in `items`. The queue is capped
   *  server-side, so the screen read "Proposal 1 of 50" over 119 waiting — and
   *  kept reading it after every verdict, because deciding one refilled the page
   *  from the remainder. This is the number that falls as the backlog clears. */
  pending: number
}
```

  In `frontend/src/views/Review.tsx`, replace the second empty-state branch (Review.tsx:158-165, the `) : queue.documents_comparable === 0 ? (` arm through the `) : (` that opens the final one):

```tsx
        ) : queue.documents_with_obligations < 2 ? (
          <p>
            <strong>The queue cannot be filled yet.</strong> Obligations exist, but
            only one document holds any — and a proposal links a clause in one
            document to a clause in another, so it needs both sides. Ingest a
            second document and build an edition of it; comparing this
            document's own editions is the pairing screen's question.
          </p>
        ) : (
```

- [ ] Run the suite again: `cd /home/rhagan/policy_grapher/frontend && npm test`. Expected: eslint clean, `tsc -b` clean (the rename happened on both sides of the mirror at once — renaming only one side compiles against the stale declaration and fails at runtime as `undefined`, which is why the field is renamed here and not in a separate step), then `Test Files  12 passed (12)` and `Tests  232 passed (232)` — the same totals as before this cycle, one test having been replaced rather than added.
- [ ] THE MUTATION CHECK: in `Review.tsx`, change `queue.documents_with_obligations < 2` to `queue.documents_with_obligations === 0` — the old predicate under the new name. Run `cd /home/rhagan/policy_grapher/frontend && npm test`. Expected: `Tests  1 failed | 231 passed (232)`, the failure being `says a proposal needs a second document when only one holds obligations` — with the stub's count of 1 the screen renders "Nothing is waiting for review." and the `findByText(/only one document holds any/i)` query finds nothing. Revert.
- [ ] Commit: `cd /home/rhagan/policy_grapher && git add frontend/src/api/types.ts frontend/src/views/Review.tsx frontend/src/views/Review.test.tsx && git commit -m "feat: the review empty state sends the reader to a second document, not a second edition"`.
### Task 7: The repoint refactor

**Files:**
- Modify: `backend/src/policy_grapher/links/decisions.py` (imports at 13–19; the three repoint queries at 104–126; `repoint_decisions` at 142–222 and `decision_key` at 225–236, which moves above it so `LINK_SCHEMA` can name it)
- Modify: `backend/src/policy_grapher/links/pairing.py` (created by Task 1; append one import and `PAIRING_SCHEMA`)
- Modify: `backend/src/policy_grapher/links/rebuild.py` (imports at 38–43; `_write_rebuild`'s repoint/replay/counts block at 160–173)
- Test: `backend/tests/test_links.py` (append two tests; one top-level import), `backend/tests/test_rebuild.py` (append one test; one top-level import)

**Interfaces:**
- Consumes (Task 1, `links/pairing.py`): `pairing_key(old_id: str, new_id: str) -> str`; `record_pairing(tx, *, old_id: str, new_id: str, verdict: str, actor: str, rationale: str) -> None`; `count_stranded_pairings(tx) -> int`; and the `pairing_decision_key_unique` constraint in `db.py` (added with `links/pairing.py`, Interface Contract §4).
- Produces: `DecisionSchema` (frozen dataclass: `label: str`, `source_prop: str`, `target_prop: str`, `key_of: Callable[[str, str], str]`) and `LINK_SCHEMA: DecisionSchema` in `links/decisions.py`; `repoint_decisions(tx, *, before: dict[str, str], after: dict[str, str], schema: DecisionSchema = LINK_SCHEMA) -> int`; `PAIRING_SCHEMA: DecisionSchema` in `links/pairing.py`; rebuild report keys `pairing_decisions_repointed` and `pairing_decisions_stranded` beside the existing counts.

Per spec §5 this is a refactor, not a reuse: `repoint_decisions` is bound to `:LinkDecision` at `decisions.py:106/115/124`, hardcodes `source_obligation_id`/`target_obligation_id`, and calls `decision_key` directly at `decisions.py:190`; its collision rule exists to protect `link_decision_key_unique`. Parameterising label, property names and key function is what lets the same machinery repair `:PairingDecision`. **The regression gate is the existing repoint tests in `backend/tests/test_links.py` (`test_a_decision_survives_its_obligations_being_re_keyed` through `test_two_repoints_that_would_collide_with_each_other_do_not_abort_the_batch`, lines 466–631): they must pass UNCHANGED, because under the default `LINK_SCHEMA` the refactored function must reproduce the unparameterised behaviour exactly.** Do not edit them.

- [ ] Write the two failing tests. Append to `backend/tests/test_links.py`, and add one import to the top-level block (between the `links.decisions` and `links.propose` imports, so a missing `PAIRING_SCHEMA` fails the whole file's collection — a red signal this sandbox can actually see):

```python
from policy_grapher.links.pairing import (
    PAIRING_SCHEMA,
    pairing_key,
    record_pairing,
)
```

  and at the end of the file:

```python
# --- the repoint refactor serves the pairing vocabulary too (spec §5) ---------


@pytest.mark.integration
def test_a_pairing_decision_survives_its_obligations_being_re_keyed(
    clean_graph, database
):
    """`repoint_decisions` is parameterised by `DecisionSchema` so the pairing
    vocabulary rides the same ADR-027 repair path as `:LinkDecision`. Under
    `PAIRING_SCHEMA` it must read, re-key and rewrite `:PairingDecision` nodes —
    a label or property name hardcoded anywhere in the path would silently
    repoint nothing and strand the verdict."""
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id="old-old-id",
            new_id="old-new-id",
            verdict="paired",
            actor="reviewer",
            rationale="the reworded duty",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={
                "old-old-id": "the director shall report",
                "old-new-id": "the director reports",
            },
            after={
                "the director shall report": "new-old-id",
                "the director reports": "new-new-id",
            },
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.key AS key, p.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old"] == "new-old-id"
    assert records[0]["new"] == "new-new-id"
    assert records[0]["key"] == pairing_key("new-old-id", "new-new-id")
    # The verdict is what must survive. Re-pointing that dropped it would be
    # worse than not re-pointing at all.
    assert records[0]["verdict"] == "paired"


@pytest.mark.integration
def test_two_pairing_repoints_that_would_collide_do_not_abort_the_batch(
    clean_graph, database
):
    """`pairing_decision_key_unique` constrains `:PairingDecision.key` exactly as
    `link_decision_key_unique` constrains `:LinkDecision.key`, so the STORY-074
    hazard transfers whole: two moves in one batch computing the same new key
    cannot both be written, and screening each proposed key only against the
    pre-batch set would let `APPLY_REPOINT` violate the constraint and roll the
    caller's whole transaction back. Same resolution as a collision against a
    pre-existing decision: the first move lands, the loser is left unrepaired
    for `count_stranded_pairings`.
    """
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing, old_id="old-a", new_id="target",
            verdict="paired", actor="reviewer", rationale="first",
        )
        session.execute_write(
            record_pairing, old_id="old-b", new_id="target",
            verdict="distinct", actor="reviewer", rationale="second",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-x", "statement two": "new-x"},
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 1, "one move lands; the colliding one is left unrepaired"

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, p.key AS key",
        database_=database,
    )
    assert len(records) == 2, "both human verdicts still exist"
    moved = [r for r in records if r["key"] == pairing_key("new-x", "target")]
    assert len(moved) == 1
    stranded = [r for r in records if r["key"] != pairing_key("new-x", "target")]
    assert stranded[0]["old"] in {"old-a", "old-b"}
    assert stranded[0]["key"] == pairing_key(stranded[0]["old"], "target")
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration" -q`. Expected exact failure: collection errors with `ImportError: cannot import name 'PAIRING_SCHEMA' from 'policy_grapher.links.pairing'` (exit code 2) — the top-level import fails before any test runs. `--collect-only -q` fails the same way.

- [ ] Write the minimal implementation. Three edits to `backend/src/policy_grapher/links/decisions.py`. First, the import block (lines 13–19) becomes:

```python
import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import normalize
```

  Second, replace the three queries at lines 104–126 (`READ_DECISIONS_FOR`, `APPLY_REPOINT`, `EXISTING_KEYS`) with the schema dataclass and the `.format` templates:

```python
@dataclass(frozen=True)
class DecisionSchema:
    """One canonical decision shape, as the repair path needs to see it.

    Two decision types answer two different questions — `:LinkDecision` whether
    a clause discharges a higher duty, `:PairingDecision` whether a newer
    clause is the older one reworded — but a re-key strands both identically,
    so `repoint_decisions` is written against this shape rather than against
    either label. `key_of` is the directional content hash whose uniqueness
    constraint the collision screen in `repoint_decisions` exists to protect.
    """

    label: str
    source_prop: str
    target_prop: str
    key_of: Callable[[str, str], str]


# .format templates, not query parameters: Cypher cannot parameterise a label or
# a property name. The interpolated values come only from the two schemas this
# repository defines — LINK_SCHEMA below and PAIRING_SCHEMA in links/pairing.py
# — so no user input ever reaches a format field. Cypher's own map braces are
# doubled so str.format leaves them alone.
READ_DECISIONS_FOR = """
UNWIND $ids AS id
MATCH (d:{label})
WHERE d.{source_prop} = id OR d.{target_prop} = id
RETURN DISTINCT d.key AS key,
       d.{source_prop} AS source_id,
       d.{target_prop} AS target_id
"""

APPLY_REPOINT = """
UNWIND $moves AS m
MATCH (d:{label} {{key: m.old_key}})
SET d.{source_prop} = m.source_id,
    d.{target_prop} = m.target_id,
    d.key = m.new_key
RETURN count(d) AS repointed
"""

EXISTING_KEYS = """
UNWIND $keys AS key
MATCH (d:{label} {{key: key}})
RETURN collect(d.key) AS present
"""
```

  Third, replace the region from `def repoint_decisions` through the end of `decision_key` (lines 142–236; `read_obligation_statements` at 129–139 stays where it is, untouched). `decision_key` moves above `repoint_decisions` — `LINK_SCHEMA` names it, and a function default is evaluated at import time — its docstring unchanged:

```python
def decision_key(source_id: str, target_id: str) -> str:
    """Identity for a verdict on one directed pair.

    Content-derived from two obligation ids, which are themselves content-derived
    (extraction.schema.obligation_id) — so the key survives a re-extraction that
    reproduces the same obligations. A key built from an internal node id would
    not: the node is dropped and recreated on every rebuild.

    Directional. "A implements B" is not "B implements A", and a symmetric key
    would let a verdict on one direction silently decide the other.
    """
    return hashlib.sha256(f"{source_id}|{target_id}".encode()).hexdigest()[:32]


# The default, and the refactor's regression gate: under this schema
# `repoint_decisions` reproduces the pre-parameterisation behaviour exactly,
# which is what lets every existing repoint test pass unchanged.
LINK_SCHEMA = DecisionSchema(
    label="LinkDecision",
    source_prop="source_obligation_id",
    target_prop="target_obligation_id",
    key_of=decision_key,
)


def repoint_decisions(
    tx: ManagedTransaction,
    *,
    before: dict[str, str],
    after: dict[str, str],
    schema: DecisionSchema = LINK_SCHEMA,
) -> int:
    """Carry recorded verdicts across a change of obligation identity (ADR-027).

    `before` maps each old obligation id to its normalized statement; `after`
    maps each normalized statement to the id the rebuild has just written for
    it. A statement that did not move produces the same id on both sides and is
    skipped.

    `schema` names which canonical decision shape is being repaired. Both
    vocabularies strand identically under a re-key, so the machinery is shared;
    the default is `LINK_SCHEMA`, under which this behaves exactly as the
    unparameterised version did.

    **A statement two obligations share maps neither of them.** `obligation_id`
    hashes `version_id | section_path | statement`, so one sentence appearing in
    two sections is two distinct nodes with two distinct ids. The statement is
    only a handle on an obligation while it names exactly one, and mapping
    through an ambiguous one would move a human's verdict onto whichever of the
    two the rebuild happened to record — an obligation nobody judged. Ambiguous
    statements are dropped here and fall through to `unpromotable`, which is the
    honest outcome. The caller owes the same guarantee for `after`, whose dict
    keys collapse duplicates silently.

    A decision whose new key already belongs to another decision — one that
    existed before this batch, or one this batch has already accepted — is left
    exactly as it was. Merging two human verdicts into one is the single
    outcome this must not have, and the screen protects whichever uniqueness
    constraint holds the schema's label (`link_decision_key_unique`,
    `pairing_decision_key_unique`): a colliding write would violate it and roll
    the caller's whole transaction back. An unrepaired approval is still
    counted by `replay_decisions` as `unpromotable`, an unrepaired pairing by
    `count_stranded_pairings`. (A stranded *rejection* is counted nowhere; see
    ADR-027's consequences.)
    """
    fields = {
        "label": schema.label,
        "source_prop": schema.source_prop,
        "target_prop": schema.target_prop,
    }
    ambiguous = {
        statement for statement, count in Counter(before.values()).items() if count > 1
    }
    moved = {
        old_id: after[statement]
        for old_id, statement in before.items()
        if statement not in ambiguous
        and statement in after
        and after[statement] != old_id
    }
    if not moved:
        return 0

    decisions = list(
        tx.run(READ_DECISIONS_FOR.format(**fields), {"ids": list(moved)})
    )
    if not decisions:
        return 0

    proposed = []
    for record in decisions:
        source_id = moved.get(record["source_id"], record["source_id"])
        target_id = moved.get(record["target_id"], record["target_id"])
        new_key = schema.key_of(source_id, target_id)
        if new_key == record["key"]:
            continue
        proposed.append(
            {
                "old_key": record["key"],
                "new_key": new_key,
                "source_id": source_id,
                "target_id": target_id,
            }
        )
    if not proposed:
        return 0

    taken = set(
        tx.run(
            EXISTING_KEYS.format(**fields),
            {"keys": [m["new_key"] for m in proposed]},
        ).single()["present"]
    )
    # `taken` grows as moves are accepted, not only from the pre-batch read: two
    # moves within one batch can compute the same new key, and screening each
    # against the pre-batch set alone lets both through — `APPLY_REPOINT` then
    # violates the schema's key constraint and rolls the whole rebuild back
    # (STORY-074). A collision inside the batch resolves the way one against a
    # pre-existing decision does: the first move lands, the loser is unrepaired.
    moves = []
    for move in proposed:
        if move["new_key"] in taken:
            continue
        moves.append(move)
        taken.add(move["new_key"])
    if not moves:
        return 0

    return tx.run(
        APPLY_REPOINT.format(**fields), {"moves": moves}
    ).single()["repointed"]
```

  Then append to `backend/src/policy_grapher/links/pairing.py`: add `from policy_grapher.links.decisions import DecisionSchema` to its import block (after the `neo4j` import; `decisions.py` imports nothing from this module, so there is no cycle), and at the end of the file:

```python
# The pairing half of the repoint refactor (spec §5). Defined here rather than
# in links/decisions.py so that module never has to know pairing exists: the
# shared shape lives with the machinery, and each vocabulary names its own
# instance beside its own key function.
PAIRING_SCHEMA = DecisionSchema(
    label="PairingDecision",
    source_prop="old_obligation_id",
    target_prop="new_obligation_id",
    key_of=pairing_key,
)
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration"` — no trailing `-q` on this one: `backend/pyproject.toml` already sets `addopts = "-q"`, and a second `-q` suppresses the very count line this step reads. Expected: `15 passed, 24 deselected` (the 11 pre-plan unit tests plus Task 2's four; the unit slice also proves the module imports cleanly through the refactor). Then `.venv/bin/pytest tests/test_links.py --collect-only -q` — here the doubled `-q` is deliberate, because it is what produces the terse one-line form — expected `tests/test_links.py: 39` (two more than the 37 standing after Tasks 2 and 6: 31 pre-plan + Task 2's 4 unit + Task 6 Cycle 1's 2 integration + these 2). The integration tests — including the untouched regression-gate repoint tests — run at the merge gate where Docker exists.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/decisions.py src/policy_grapher/links/pairing.py tests/test_links.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK (two, one per new test). Mutation 1: in `repoint_decisions`, hardcode the label back — change `READ_DECISIONS_FOR.format(**fields)` to `READ_DECISIONS_FOR.format(label="LinkDecision", source_prop=schema.source_prop, target_prop=schema.target_prop)`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py::test_a_pairing_decision_survives_its_obligations_being_re_keyed -q` (merge gate / any Docker host; in this sandbox verify `--collect-only -q` still collects and rely on the gate). Expected failure: `assert repointed == 1` fails with `0` — the read finds no `:PairingDecision`, while every existing `:LinkDecision` repoint test still passes, which is exactly why this test had to exist. Revert. Mutation 2: delete the line `taken.add(move["new_key"])`. Run `.venv/bin/pytest tests/test_links.py::test_two_pairing_repoints_that_would_collide_do_not_abort_the_batch -q` (same caveat). Expected failure: either `assert repointed == 1` fails with `2`, or the write violates `pairing_decision_key_unique` and the transaction errors — the STORY-074 rollback this screen prevents. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/links/decisions.py backend/src/policy_grapher/links/pairing.py backend/tests/test_links.py && git commit -m "feat: the repoint path serves both canonical decision shapes"`

- [ ] Write the failing rebuild test. In `backend/tests/test_rebuild.py`, add to the top-level import block (after the `links.decisions` import):

```python
from policy_grapher.links.pairing import record_pairing
```

  and append at the end of the file:

```python
@pytest.mark.integration
def test_a_rebuild_counts_the_pairing_side_of_the_repair(
    reviewed_graph, clean_graph, database, monkeypatch
):
    """The rebuild repairs and reports both canonical shapes. A `:PairingDecision`
    whose obligation the rekey moved is repointed from the same before/after
    statement maps as the `:LinkDecision`s, and one whose obligations no longer
    exist at all is `pairing_decisions_stranded` — the analogue of
    `unpromotable`, counted beside the replay, and a different event from the
    diff-side `pairings_unapplied` (spec §3, §5).

    The repair path reads no document structure — only ids and statements — so
    the fixture borrows the approved pair's real ids for the decision that must
    ride the rekey. Membership semantics are the routes' business, not this
    machinery's.
    """
    org = reviewed_graph["org"]
    approved = reviewed_graph["approved"]

    with clean_graph.session(database=database) as session:
        # Rides the rekey: its old side is a real obligation of the edition
        # about to be rebuilt, so the statement-keyed maps must carry it.
        session.execute_write(
            record_pairing,
            old_id=approved[0], new_id=approved[1],
            verdict="paired", actor="carol", rationale="reworded",
        )
        # Already stranded: neither obligation has ever existed, so no map can
        # repair it and the count must say so.
        session.execute_write(
            record_pairing,
            old_id="never-extracted-a", new_id="never-extracted-b",
            verdict="paired", actor="carol", rationale="stranded",
        )

    original_section_heading = chunking.section_heading

    def rekeyed_section_heading(line: str) -> str | None:
        heading = original_section_heading(line)
        return f"{heading}-REKEYED" if heading is not None else None

    monkeypatch.setattr(chunking, "section_heading", rekeyed_section_heading)

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=org,
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    assert report["pairing_decisions_repointed"] == 1
    assert report["pairing_decisions_stranded"] == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision {actor: 'carol', rationale: 'reworded'}) "
        "RETURN p.old_obligation_id AS old, p.new_obligation_id AS new",
        database_=database,
    )
    assert records[0]["old"] != approved[0], "the pairing decision was not repointed"
    assert records[0]["new"] == approved[1], "the untouched edition must not move"
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_rebuild.py --collect-only -q`. Expected: `tests/test_rebuild.py: 23` (one more than before). The merge gate, where Docker exists, would fail this test right now with `KeyError: 'pairing_decisions_repointed'` — `_write_rebuild` returns no such key.

- [ ] Write the minimal implementation. In `backend/src/policy_grapher/links/rebuild.py`, add to the imports (between the `links.decisions` and `links.propose` blocks at lines 38–43):

```python
from policy_grapher.links.pairing import PAIRING_SCHEMA, count_stranded_pairings
```

  and replace the tail of `_write_rebuild` (from `repointed = repoint_decisions(...)` at line 161 through the `return` at line 173) with:

```python
    repointed = repoint_decisions(tx, before=before, after=after)
    # The same before/after maps serve both canonical shapes: a re-key strands
    # a pairing verdict exactly as it strands a link verdict, and the statement
    # is the same handle for both (ADR-027, spec §5).
    pairings_repointed = repoint_decisions(
        tx, before=before, after=after, schema=PAIRING_SCHEMA
    )

    replayed = replay_decisions(tx)
    # The rebuild-side loss for the pairing vocabulary — the analogue of
    # `unpromotable`, counted beside the replay for the same reason: a rebuild
    # reporting only its happy counts would look complete in exactly the case
    # where a human verdict had quietly stopped being representable. The
    # diff-side count, `pairings_unapplied`, is a different event with a
    # different cause and lives with the diff (spec §3).
    pairings_stranded = count_stranded_pairings(tx)
    return {
        "changes_dropped": changes_dropped,
        "chunks_dropped": chunks_dropped,
        "obligations_dropped": obligations_dropped,
        "chunks_written": chunks_written,
        "obligations_written": obligations_written,
        "proposed": proposed,
        "decisions_repointed": repointed,
        "pairing_decisions_repointed": pairings_repointed,
        "pairing_decisions_stranded": pairings_stranded,
        **replayed,
    }
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_rebuild.py --collect-only -q`. Expected: `tests/test_rebuild.py: 23`, no import errors. The merge gate runs the full file where Docker exists; the pre-existing rebuild tests assert their counts by key, so the two additive keys change none of them.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/rebuild.py tests/test_rebuild.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK. Mutation: in `_write_rebuild`, delete the second `repoint_decisions` call and the `count_stranded_pairings` call, hardcoding `"pairing_decisions_repointed": 0` and `"pairing_decisions_stranded": 0` in the returned dict. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_rebuild.py::test_a_rebuild_counts_the_pairing_side_of_the_repair -q` (merge gate / Docker host; in this sandbox verify `--collect-only -q` still collects). Expected failure: `assert report["pairing_decisions_repointed"] == 1` fails with `0`, and were the first assert removed, the stranded assert and the `records[0]["old"] != approved[0]` assert would fail too — the counts are wired to real work, not to key presence. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/links/rebuild.py backend/tests/test_rebuild.py && git commit -m "feat: a rebuild repoints pairing decisions and counts the stranded ones"`

---

### Task 8: record_decision refuses one document

**Files:**
- Modify: `backend/src/policy_grapher/links/decisions.py` (add the `SAME_DOCUMENT` query directly after `RECORD_DECISION`, currently lines 31–39; extend `record_decision`, the function after `repoint_decisions` following Task 7's reorder)
- Modify: `backend/src/policy_grapher/routers/review.py` (`decide()`'s write tail, lines 204–216)
- Test: `backend/tests/test_links.py` (append three tests and one helper), `backend/tests/test_review.py` (append one test and one helper; extend the `extraction.schema` import at line 7)

**Interfaces:**
- Consumes: Task 7's reordered `links/decisions.py` (no signatures; this task edits the same file after it). Nothing from `links/pairing.py`.
- Produces: `record_decision(tx, *, source_id, target_id, verdict, actor, rationale) -> None` now raises `ValueError` when both obligations exist and resolve through `HAS_VERSION`/`MANDATES` to one `:Document` (pairs that do not BOTH resolve are allowed — existing tests record decisions with fake ids and must pass unchanged); `POST /review/{source_id}/{target_id}` answers 400 for that refusal. Task 9's test fixtures rely on this guard existing (their legacy `:LinkDecision` fixtures must be written raw, and say so).

Per spec §8, third bullet: `PROMOTE` (`decisions.py:43–49`) has no document predicate, so §1's skip makes `IMPLEMENTS` cross-document only for *new* proposals, transitively via the 404 at `review.py:195–202` — but enforcement belongs at `record_decision` too, because that function is the audit path and the promote match is label-wide.

- [ ] Write the three failing tests. Append to `backend/tests/test_links.py` (top-level imports already cover everything these need):

```python
# --- IMPLEMENTS is cross-document only, enforced at the recorder (spec §8) ----


def _seed_two_editions(driver, database):
    """One document, two editions, one obligation each — the configuration whose
    IMPLEMENTS question `record_decision` must refuse. Returns the two
    obligation ids, older edition first."""
    ids = []
    for version_id, statement in (("doc@2018", ORG), ("doc@2022", HIGHER)):
        driver.execute_query(
            "MERGE (d:Document {slug: 'doc', name: 'DOC'}) "
            "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
            "checksum: $vid, source_uri: 'file:///x.pdf'})",
            {"vid": version_id},
            database_=database,
        )
        chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
        with driver.session(database=database) as session:
            session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=Modality.MUST,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                ],
            )
        ids.append(obligation_id(version_id, chunk.section_path, statement))
    return tuple(ids)


@pytest.mark.integration
def test_a_same_document_pair_is_refused_by_record_decision(clean_graph, database):
    """`IMPLEMENTS` is cross-document only (spec §8). Between two editions of one
    document the question is pairing, and a verdict recorded here would be
    matched by `PROMOTE` — which has no document predicate — on every review
    POST and every rebuild."""
    older, newer = _seed_two_editions(clean_graph, database)

    with pytest.raises(ValueError, match="pairing"):
        _decide(clean_graph, database, source=newer, target=older, verdict="approve")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_a_decision_on_ids_the_graph_cannot_resolve_still_records(
    clean_graph, database
):
    """The repoint tests above record verdicts on ids that resolve to nothing,
    and ADR-027's whole repair path depends on that staying possible: a decision
    stranded by a re-extraction is still a fact a human established, and must
    remain recordable and re-recordable. Only a pair that BOTH resolves and
    resolves to one document is refused."""
    _decide(clean_graph, database, source="gone-a", target="gone-b", verdict="approve")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.verdict AS verdict", database_=database
    )
    assert [r["verdict"] for r in records] == ["approve"]


@pytest.mark.integration
def test_a_cross_document_decision_still_records(clean_graph, database):
    """The guard is about one document, not about resolvable obligations."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 1
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py --collect-only -q`. Expected: `tests/test_links.py: 42` (three more than the 39 standing after Task 7) — collection succeeds; the red signal is Docker-gated. At the merge gate, right now, `test_a_same_document_pair_is_refused_by_record_decision` fails with `Failed: DID NOT RAISE <class 'ValueError'>` (the other two pass already — they pin the behaviour the guard must not break, and exist for this task's second mutation).

- [ ] Write the minimal implementation. In `backend/src/policy_grapher/links/decisions.py`, insert directly after the `RECORD_DECISION` statement:

```python
# Membership, read in the transaction the verdict would land in. Two obligations
# `:MANDATES`-ed by editions of one `:Document` are the pairing question wearing
# the wrong vocabulary — an edition does not discharge its predecessor — and
# `IMPLEMENTS` is cross-document only (spec §8). A pair that does not BOTH
# resolve is allowed through: `:LinkDecision` outlives its obligations by design
# (`repoint_decisions` repairs them, `unpromotable` counts them), and refusing
# an unresolvable id here would make a stranded verdict unrecordable.
SAME_DOCUMENT = """
MATCH (source:Obligation {obligation_id: $source_id})
MATCH (target:Obligation {obligation_id: $target_id})
MATCH (doc:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(source)
MATCH (doc)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(target)
RETURN doc.slug AS slug
LIMIT 1
"""
```

  and replace `record_decision` in full with:

```python
def record_decision(
    tx: ManagedTransaction,
    *,
    source_id: str,
    target_id: str,
    verdict: str,
    actor: str,
    rationale: str,
) -> None:
    """Record one human verdict, replacing any earlier verdict on the same pair.

    Replacing rather than appending: a reviewer who changes their mind must leave
    one current verdict, not two contradictory records for a replay to choose
    between. The history that a control framework might want is not kept here —
    see ADR-014 on what `:LinkDecision`'s shape leaves open.

    A pair inside one document is refused. `PROMOTE` has no document predicate,
    so a same-document approval recorded here would resurrect a same-document
    `IMPLEMENTS` on every replay; the question between two editions of one
    instrument is pairing, and it has its own canonical node (spec §4, §8).
    """
    if verdict not in set(Verdict):
        raise ValueError(
            f"unknown verdict {verdict!r}; expected one of {[v.value for v in Verdict]}"
        )
    same_document = tx.run(
        SAME_DOCUMENT, {"source_id": source_id, "target_id": target_id}
    ).single()
    if same_document is not None:
        raise ValueError(
            f"{source_id!r} and {target_id!r} are both mandated by editions of "
            f"{same_document['slug']!r}. Within one document the question is "
            "pairing, not implementation — that verdict belongs on a "
            ":PairingDecision, not here."
        )
    tx.run(
        RECORD_DECISION,
        {
            "key": decision_key(source_id, target_id),
            "source_id": source_id,
            "target_id": target_id,
            "verdict": verdict,
            "actor": actor,
            "rationale": rationale,
        },
    ).consume()
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py -k "not integration"` — no trailing `-q`, for the reason Task 7 gives: `addopts = "-q"` is already on, and doubling it hides the count line. Expected `15 passed, 27 deselected` (imports and unit behaviour intact; this task's three additions are all integration, so the unit slice is unchanged from Task 7). Then `.venv/bin/pytest tests/test_links.py --collect-only -q`, expected `tests/test_links.py: 42`. The merge gate runs the integration set where Docker exists; every pre-existing decision test uses either two documents or unresolvable ids (`test_export.py`'s decision fixture uses `"a"`/`"b"`, likewise unresolvable), so all pass unchanged.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/links/decisions.py tests/test_links.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK (two directions, because a guard can fail open or fire wide). Mutation 1: delete the `if same_document is not None: raise ValueError(...)` block. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_links.py::test_a_same_document_pair_is_refused_by_record_decision -q` (merge gate / Docker host; in this sandbox verify `--collect-only -q` still collects). Expected failure: `Failed: DID NOT RAISE <class 'ValueError'>`. Revert. Mutation 2: widen the query — in `SAME_DOCUMENT`, change the fourth line to `MATCH (doc2:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(target)` so any two resolvable obligations match. Run `.venv/bin/pytest tests/test_links.py::test_a_cross_document_decision_still_records -q` (same caveat). Expected failure: `ValueError` raised where a cross-document decision must record. Revert. Mutation 3: invert the guard — change `if same_document is not None:` to `if same_document is None:`, leaving the raise's body (including `same_document['slug']`) unchanged. Run `.venv/bin/pytest tests/test_links.py::test_a_decision_on_ids_the_graph_cannot_resolve_still_records -q` (same caveat). Expected failure: `"gone-a"`/`"gone-b"` resolve to no `Obligation`, so `same_document` is `None` and the inverted guard now fires on the one pair that must record — the f-string's `same_document['slug']` evaluates against `None` before the `ValueError` can even be built, so the test errors with `TypeError: 'NoneType' object is not subscriptable` instead of the decision being recorded. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/links/decisions.py backend/tests/test_links.py && git commit -m "feat: record_decision refuses a pair inside one document"`

- [ ] Write the failing router test. In `backend/tests/test_review.py`, change line 7 to:

```python
from policy_grapher.extraction.schema import ExtractedObligation, Modality, obligation_id
```

  and append at the end of the file:

```python
def _seed_edition_of(driver, database, *, slug, version_id, statement):
    """One edition of a named document — unlike `_seed_version`, which mints a
    document per version and so can never build the same-document shape."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": slug, "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages(
        ["CHAPTER 2\n2.4. DUTIES.\nBody text.\n"], version_id=version_id
    )[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[
                ExtractedObligation(
                    statement=statement,
                    modality=Modality.MUST,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
            ],
        )
    return obligation_id(version_id, chunk.section_path, statement)


@pytest.mark.integration
def test_a_same_document_verdict_is_a_400(client_with_auth):
    """`IMPLEMENTS` is cross-document only. `propose_links` no longer creates a
    same-document proposal and the startup migration deletes the legacy ones,
    but the graph this route meets is whatever it is — the guard in
    `record_decision` is the enforcement, and the route must translate its
    refusal into a 400 rather than 500 on it."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    older = _seed_edition_of(
        driver, database, slug="doc", version_id="doc@2018", statement=ORG
    )
    newer = _seed_edition_of(
        driver, database, slug="doc", version_id="doc@2022", statement=HIGHER
    )
    # Raw on purpose: this edge can only exist as an inheritance from before
    # the split, which is exactly the state the guard exists to meet.
    driver.execute_query(
        "MATCH (a:Obligation {obligation_id: $a}), (b:Obligation {obligation_id: $b}) "
        "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
        "proposer: 'lexical-v1'}]->(b)",
        {"a": newer, "b": older},
        database_=database,
    )

    response = client_with_auth.post(
        f"/review/{newer}/{older}", json={"verdict": "approve", "rationale": "r"}
    )

    assert response.status_code == 400
    assert "pairing" in response.json()["detail"]
    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0, "a refused verdict must leave no audit record"
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_review.py --collect-only -q`. Expected: `tests/test_review.py: 17` (one more than the 16 standing after Task 6 Cycle 2, which replaced the three STORY-090 tests with four). At the merge gate, right now, this test fails with the guard's `ValueError` propagating out of the route — `TestClient` re-raises server exceptions, so the failure is the raw `ValueError`, not a status assertion.

- [ ] Write the minimal implementation. In `backend/src/policy_grapher/routers/review.py`, replace the tail of `decide()` (from `def _write(tx):` at line 204 through the final `return` at line 216) with:

```python
    def _write(tx):
        record_decision(
            tx,
            source_id=source_id,
            target_id=target_id,
            verdict=body.verdict,
            actor=principal.name,
            rationale=body.rationale,
        )
        return replay_decisions(tx)

    try:
        with driver.session(database=settings.neo4j_database) as session:
            return session.execute_write(_write)
    except ValueError as exc:
        # record_decision's same-document refusal (spec §8): the pair is a
        # pairing question, and the verdict belongs on the pairings route. The
        # unknown-verdict ValueError cannot arrive here — it is screened above
        # before the transaction opens.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_review.py --collect-only -q`. Expected: `tests/test_review.py: 17`, no import errors. The merge gate runs the file where Docker exists; the pre-existing decide tests all post cross-document pairs and pass unchanged.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/routers/review.py tests/test_review.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK. Mutation: remove the `try`/`except ValueError` wrapper, restoring the bare `with driver.session(...)` block. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_review.py::test_a_same_document_verdict_is_a_400 -q` (merge gate / Docker host; in this sandbox verify `--collect-only -q` still collects). Expected failure: the POST raises `ValueError` through the `TestClient` instead of returning 400 — the test errors before its first assertion. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/routers/review.py backend/tests/test_review.py && git commit -m "feat: a same-document verdict is a 400 at the review route"`

---

### Task 9: The migration

**Files:**
- Create: `backend/src/policy_grapher/migrate.py`
- Modify: `backend/src/policy_grapher/main.py` (import block at 14–23; `lifespan` at 64, directly after `apply_schema`)
- Test: `backend/tests/test_migrate.py` (create)

**Interfaces:**
- Consumes (Task 1, `links/pairing.py`): `pairing_key(old_id: str, new_id: str) -> str`; `PairingVerdict` (`PAIRED = "paired"`, `DISTINCT = "distinct"`); `record_pairing(tx, *, old_id, new_id, verdict, actor, rationale) -> None` (in tests, as the replace-observable); the `pairing_decision_key_unique` constraint in `db.py`. Consumes Task 8's `record_decision` guard as a fact the fixtures must respect (legacy nodes are written raw, with a comment saying why). Repo functions: `replay_decisions(tx)`, `decision_key(source_id, target_id)` from `links/decisions.py`.
- Produces: `migrate_pairing_decisions(driver, database: str) -> dict[str, int]` returning `{"converted", "retired_same_edition", "retired_conflicting", "implements_deleted", "proposals_deleted"}` — **amended during execution to seven keys**, adding `retired_unknown_verdict` (controller ruling: a corrupt verdict retires and counts rather than raising, because this runs at every boot and raising makes one bad node unstartable for everyone) and `decisions_missing_documents` (a census, not a repair: decisions whose obligations outlived their document cannot be classified as same- or cross-document, so they are counted and left alone). `converted` counts pairing decisions MINTED, not originals retired. The `:RetiredLinkDecision` label carries all original properties plus `retired_reason` ∈ `{'converted', 'same_edition', 'conflicting_pairing', 'unknown_verdict', 'pairing_exists'}`, the last added with the fix for a Critical: a conversion whose key is already held by a live `:PairingDecision` retires instead of overwriting a verdict it did not make; the startup call in `main.py` after `apply_schema`, counts logged.

Per the spec's Migration section: the vehicle is startup, because a deliverable without one is a deletion nothing schedules. The migration finds `:LinkDecision` nodes whose BOTH obligations exist and resolve to one `:Document`, classifies (same edition → retire; convertible `approve`s sharing an endpoint within one edition pair → retire ALL involved; the rest → convert re-oriented older→newer by `(coalesce(effective_date, ''), ingested_at, version_id)`), deletes each retired/converted decision's promoted same-document `IMPLEMENTS` edge in the same transaction, then deletes ALL same-document `IMPLEMENTS_PROPOSED` edges. Idempotent: a second run returns zeros.

- [ ] Write the failing tests. Create `backend/tests/test_migrate.py`. One docstring below names `test_a_newer_first_post_is_recorded_older_to_newer`, which arrives with the pairings router in Task 10 (`backend/tests/test_pairings.py`) — a deliberate forward reference: the §6 POST's own older→newer ordering is pinned there, and this file must not be read as pinning it. Nothing here imports anything the router adds; the reference is prose in a docstring.

```python
"""The startup migration: the legacy same-document :LinkDecision is converted,
retired, or both — and the edges it left behind go with it (spec, Migration).

Every fixture here that writes a :LinkDecision or an IMPLEMENTS_PROPOSED edge
between two editions of one document writes it raw, and that is the point of
this file: `record_decision` now refuses the pair and `propose_links` now skips
it, so the state these tests build can only exist as an inheritance from before
the split — which is exactly what a migration is for.
"""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.decisions import decision_key, replay_decisions
from policy_grapher.links.pairing import pairing_key, record_pairing
from policy_grapher.migrate import migrate_pairing_decisions
from policy_grapher.obligations import write_obligations

OLD_WORDING = "The Director shall notify the Comptroller of any breach."
NEW_WORDING = (
    "The Director shall notify the Comptroller and the Secretary of any breach."
)
SECOND_OLD = "Components must file the annual cybersecurity report."
SECOND_NEW = "Components must file the annual cybersecurity report electronically."

ZEROS = {
    "converted": 0,
    "retired_same_edition": 0,
    "retired_conflicting": 0,
    "implements_deleted": 0,
    "proposals_deleted": 0,
}


def _seed_edition(
    driver, database, *, version_id, effective_date, statements, slug="doc", name="DOC"
):
    """One edition of one document, one obligation per statement, all in one
    section. Returns the obligation ids in statement order. `effective_date`
    pins the corpus ordering rule explicitly — the re-orientation tests must
    not be allowed to pass by accident of version_id lexicography."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $name}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf', effective_date: $eff})",
        {"slug": slug, "name": name, "vid": version_id, "eff": effective_date},
        database_=database,
    )
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[
                ExtractedObligation(
                    statement=s,
                    modality=Modality.SHALL,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
                for s in statements
            ],
        )
    return [obligation_id(version_id, chunk.section_path, s) for s in statements]


def _legacy_decision(driver, database, *, source_id, target_id, verdict="approve"):
    """A :LinkDecision written raw, shaped exactly as RECORD_DECISION wrote it.

    Raw on purpose: `record_decision` now refuses a same-document pair, so the
    legacy state this migration exists for cannot be produced through the
    recorder any more. That refusal is the point; this helper is the
    archaeology."""
    driver.execute_query(
        "MERGE (d:LinkDecision {key: $key}) "
        "SET d.source_obligation_id = $source_id, "
        "    d.target_obligation_id = $target_id, "
        "    d.verdict = $verdict, "
        "    d.actor = 'walkthrough', "
        "    d.rationale = 'recorded before the split', "
        "    d.at = datetime()",
        {
            "key": decision_key(source_id, target_id),
            "source_id": source_id,
            "target_id": target_id,
            "verdict": verdict,
        },
        database_=database,
    )


def _replay(driver, database):
    with driver.session(database=database) as session:
        return session.execute_write(replay_decisions)


@pytest.mark.integration
def test_a_newer_to_older_approval_converts_re_oriented(clean_graph, database):
    """The walkthrough decision ran newer→older — its same-document proposal
    promoted that way. The diff's lookup is orientation-normalized, so a mutant
    migration that skips the swap passes any diff assertion; the observable
    that actually moves is the key. A mis-oriented node carries a key no
    pairings POST ever computes, so a reviewer re-verdicting the pair would
    MERGE a second decision beside it instead of replacing it. One pair, one
    node, one key.

    `record_pairing` is what the §6 POST calls and computes the same key, so
    driving it directly is the same observable; the POST's own ordering is
    pinned by `test_a_newer_first_post_is_recorded_older_to_newer`."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.verdict AS verdict, p.key AS key, "
        "p.actor AS actor, p.rationale AS rationale, p.at AS at",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old"] == older_id
    assert records[0]["new"] == newer_id
    assert records[0]["verdict"] == "paired"
    assert records[0]["key"] == pairing_key(older_id, newer_id)
    assert records[0]["actor"] == "walkthrough"
    assert records[0]["rationale"] == "recorded before the split"
    assert records[0]["at"] is not None

    # The replace observable: a re-verdict through the real write path must
    # land on the migrated node, not sit beside it.
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=older_id,
            new_id=newer_id,
            verdict="distinct",
            actor="tester",
            rationale="on reflection, a different duty",
        )
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total, "
        "collect(p.verdict) AS verdicts",
        database_=database,
    )
    assert records[0]["total"] == 1, "re-verdicting must replace, not accumulate"
    assert records[0]["verdicts"] == ["distinct"]


@pytest.mark.integration
def test_replay_recreates_no_same_document_implements_after_migration(
    clean_graph, database
):
    """`PROMOTE` has no document predicate, so a same-document approval left
    under the live label resurrects its edge on every review POST and every
    rebuild — into Ask's undirected traversal, which no shipped guard reaches.
    The migration must take the decision out of `PROMOTE`'s match by
    retirement, not delete around it."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)
    # The legacy promotion, through the one real writer of IMPLEMENTS.
    replayed = _replay(clean_graph, database)
    assert replayed["promoted"] == 1

    counts = migrate_pairing_decisions(clean_graph, database)
    assert counts["implements_deleted"] == 1

    after = _replay(clean_graph, database)

    assert after["promoted"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_shared_endpoint_approvals_retire_together(clean_graph, database):
    """Two convertible approvals sharing an endpoint within one edition pair
    would convert into exactly the two-live-`paired`-verdicts state the
    pairings POST's 409 exists to refuse — minted by a writer that route does
    not guard. Neither converts: a migration choosing the winner would be the
    design deciding what only a person may."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    newer_a, newer_b = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING, SECOND_NEW],
    )
    _legacy_decision(clean_graph, database, source_id=newer_a, target_id=older_id)
    _legacy_decision(clean_graph, database, source_id=newer_b, target_id=older_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 0
    assert counts["retired_conflicting"] == 2
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict ORDER BY d.key",
        database_=database,
    )
    assert [r["reason"] for r in records] == [
        "conflicting_pairing",
        "conflicting_pairing",
    ]
    assert [r["verdict"] for r in records] == ["approve", "approve"]
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_a_same_edition_approval_is_retired_with_its_edge_gone(clean_graph, database):
    """Reachable today — the rebuild API validates candidates by existence
    only, so a version can be named as its own candidate — and answering
    neither vocabulary's question: two clauses of one edition have no older or
    newer side to orient. Retired, never converted, every property intact
    (ADR-014 honoured in letter and spirit), the promoted edge deleted in the
    same transaction — and still gone after a replay, because the spec's
    Testing bullet asks for converted and same-edition finds alike to be taken
    out of `PROMOTE`'s match rather than deleted around."""
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    _legacy_decision(clean_graph, database, source_id=first, target_id=second)
    replayed = _replay(clean_graph, database)
    assert replayed["promoted"] == 1

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["retired_same_edition"] == 1
    assert counts["converted"] == 0
    assert counts["implements_deleted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict, d.actor AS actor, d.key AS key, "
        "d.source_obligation_id AS source, d.target_obligation_id AS target",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["reason"] == "same_edition"
    assert records[0]["verdict"] == "approve"
    assert records[0]["actor"] == "walkthrough"
    assert records[0]["key"] == decision_key(first, second)
    assert (records[0]["source"], records[0]["target"]) == (first, second)
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0

    # Deleting the edge is not enough. A node left under :LinkDecision with
    # verdict 'approve' is matched by PROMOTE on the next replay and the edge
    # comes straight back, so the retirement has to be observable through the
    # replay, not only through the edge count immediately after the migration.
    after = _replay(clean_graph, database)
    assert after["promoted"] == 0, (
        "a retired same-edition approval must be out of PROMOTE's match, not "
        "merely stripped of its edge"
    )
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_same_document_proposals_are_deleted_and_cross_document_ones_kept(
    clean_graph, database
):
    """The review queue matches proposals with no document predicate, and the
    recorder's guard makes a same-document proposal undecidable — left in
    place it sits in the queue forever, inflating `pending`, unclearable by
    any verdict. Derived, so deleted. Scoped through one :Document: a
    cross-document proposal is live inventory and must survive."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    (other_id,) = _seed_edition(
        clean_graph, database, slug="other", name="OTHER",
        version_id="other@2020-01-01", effective_date="2020-01-01",
        statements=[SECOND_OLD],
    )
    # Raw for the same reason _legacy_decision is: propose_links now skips the
    # same-document pair. The cross-document edge is raw only for determinism,
    # carrying the same properties WRITE_PROPOSALS writes.
    for target in (older_id, other_id):
        clean_graph.execute_query(
            "MATCH (a:Obligation {obligation_id: $a}) "
            "MATCH (b:Obligation {obligation_id: $b}) "
            "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
            "proposer: 'lexical-v1'}]->(b)",
            {"a": newer_id, "b": target},
            database_=database,
        )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["proposals_deleted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    assert [(r["source"], r["target"]) for r in records] == [(newer_id, other_id)]


@pytest.mark.integration
def test_a_second_run_returns_all_zeros(clean_graph, database):
    """Idempotence is the vehicle's safety property: this runs on every boot.
    Everything the first run converts or retires stops matching the queries
    that found it, so the second run must report zeros across the board — a
    non-zero here means some node is still wearing the live label."""
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=first)
    _legacy_decision(clean_graph, database, source_id=first, target_id=second)
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $a}) "
        "MATCH (b:Obligation {obligation_id: $b}) "
        "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
        "proposer: 'lexical-v1'}]->(b)",
        {"a": newer_id, "b": first},
        database_=database,
    )

    initial = migrate_pairing_decisions(clean_graph, database)
    assert initial["converted"] == 1
    assert initial["retired_same_edition"] == 1
    assert initial["proposals_deleted"] == 1

    again = migrate_pairing_decisions(clean_graph, database)

    assert again == ZEROS
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_migrate.py --collect-only -q`. Expected exact failure: collection errors with `ModuleNotFoundError: No module named 'policy_grapher.migrate'` (exit code 2) — a red signal this sandbox can see.

- [ ] Write the minimal implementation. Create `backend/src/policy_grapher/migrate.py`:

```python
"""Convert the legacy same-document :LinkDecision into the pairing vocabulary.

Before the split, a pair of clauses inside one document could be proposed,
verdicted, and promoted as `IMPLEMENTS` — the pairing question wearing the
cross-document vocabulary. The design retires that state: `propose_links` skips
the pair, `record_decision` refuses it, and this module converts what the old
path already recorded (spec, Migration). A same-document `IMPLEMENTS` question
was only ever the pairing question in disguise — an edition does not discharge
its predecessor — so the migration recovers the judgement the reviewer actually
made rather than rewriting it.

Run at application startup, after `db.apply_schema`: the conversion MERGEs on
`:PairingDecision.key` and needs `pairing_decision_key_unique` in place first.
Idempotent by construction — everything a run converts or retires stops
matching the queries that found it, so a second run returns zeros. Import-
callable so the tests can drive it directly.

ADR-014 is the constraint the shape answers to: no rebuild — and no schema
change — may discard a decision. Nothing here deletes a `:LinkDecision`. A
decision leaves the live label by *retirement*, relabelled
`:RetiredLinkDecision` with every property intact plus a `retired_reason`,
because a same-document decision left under `:LinkDecision` with
`verdict: 'approve'` is matched by `PROMOTE` — which has no document predicate
— on every review POST and every rebuild, resurrecting its edge indefinitely
into Ask's undirected traversal, which no shipped guard reaches.
"""

from collections import Counter

from neo4j import Driver, ManagedTransaction

from policy_grapher.links.pairing import PairingVerdict, pairing_key

# Decisions whose obligations BOTH still exist and resolve through one
# :Document. A decision only one side of which resolves is not this migration's
# business — it is `unpromotable`/`rejections_stranded`, and retiring it here
# would destroy the repair `repoint_decisions` may yet make.
#
# The ordering columns come back as strings on purpose: `toString` of a Neo4j
# datetime is ISO-8601, which sorts lexically as it sorts temporally, and
# `coalesce` to '' keeps an unset date or ingest timestamp comparable instead
# of None-poisoning the Python sort. `effective_date` is already stored as an
# ISO string (versions.py), so `toString` is identity there.
SAME_DOCUMENT_DECISIONS = """
MATCH (d:LinkDecision)
MATCH (source:Obligation {obligation_id: d.source_obligation_id})
MATCH (target:Obligation {obligation_id: d.target_obligation_id})
MATCH (doc:Document)-[:HAS_VERSION]->(sv:DocumentVersion)-[:MANDATES]->(source)
MATCH (doc)-[:HAS_VERSION]->(tv:DocumentVersion)-[:MANDATES]->(target)
RETURN d.key AS key,
       d.verdict AS verdict,
       d.source_obligation_id AS source_id,
       d.target_obligation_id AS target_id,
       sv.version_id AS source_version,
       coalesce(toString(sv.effective_date), '') AS source_effective,
       coalesce(toString(sv.ingested_at), '') AS source_ingested,
       tv.version_id AS target_version,
       coalesce(toString(tv.effective_date), '') AS target_effective,
       coalesce(toString(tv.ingested_at), '') AS target_ingested
"""

# Retirement: the label moves, the node stays. REMOVE :LinkDecision is the
# entire idempotency mechanism — a retired node stops matching the read above —
# and it is what takes the decision out of PROMOTE's match. The promoted edge
# goes in the same statement, because SUPPRESS deletes only for `reject` and
# nothing else would ever take an approved same-document IMPLEMENTS away.
RETIRE = """
UNWIND $keys AS key
MATCH (d:LinkDecision {key: key})
SET d:RetiredLinkDecision, d.retired_reason = $reason
REMOVE d:LinkDecision
WITH d
OPTIONAL MATCH (:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(DISTINCT d) AS retired
"""

# Conversion carries the judgement, not the shape: the verdict is re-mapped by
# the caller, actor/rationale/at copied verbatim, and the pair re-oriented
# before the key is computed — `key` is a directional hash, so a mis-oriented
# node carries one no pairings POST ever computes, and a re-verdict would MERGE
# a second decision beside it instead of replacing it. MERGE, not CREATE, for
# the same reason `record_pairing` MERGEs: one pair, one node, one key — which
# also collapses the degenerate find of the same pair verdicted in both
# directions onto a single node, last row winning.
CONVERT = """
UNWIND $conversions AS c
MATCH (d:LinkDecision {key: c.old_key})
MERGE (p:PairingDecision {key: c.new_key})
SET p.old_obligation_id = c.old_id,
    p.new_obligation_id = c.new_id,
    p.verdict           = c.verdict,
    p.actor             = d.actor,
    p.rationale         = d.rationale,
    p.at                = d.at
SET d:RetiredLinkDecision, d.retired_reason = 'converted'
REMOVE d:LinkDecision
WITH d
OPTIONAL MATCH (:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(DISTINCT d) AS converted
"""

# Derived, undecidable after the recorder's guard, and matched by the review
# queue with no document predicate: left "to lapse on the next rebuild" these
# would sit in the queue forever with `pending` inflated and no verdict able to
# clear them. Scoped through one :Document — a cross-document proposal is live
# inventory and must survive.
DELETE_SAME_DOCUMENT_PROPOSALS = """
MATCH (a:Obligation)-[r:IMPLEMENTS_PROPOSED]->(b:Obligation)
MATCH (doc:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(a)
MATCH (doc)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(b)
DELETE r
"""

# `record_decision` closed the verdict vocabulary long before this module
# existed, so an unknown verdict here is corruption and a KeyError is the
# right noise.
_VERDICT = {
    "approve": PairingVerdict.PAIRED.value,
    "reject": PairingVerdict.DISTINCT.value,
}


def _migrate(tx: ManagedTransaction) -> dict[str, int]:
    rows = list(tx.run(SAME_DOCUMENT_DECISIONS))

    same_edition: list[str] = []
    convertible: list[dict] = []
    for row in rows:
        if row["source_version"] == row["target_version"]:
            # Answers neither vocabulary's question and cannot be oriented:
            # two clauses of one edition have no older or newer side.
            same_edition.append(row["key"])
            continue
        source_order = (
            row["source_effective"],
            row["source_ingested"],
            row["source_version"],
        )
        target_order = (
            row["target_effective"],
            row["target_ingested"],
            row["target_version"],
        )
        # The corpus ordering rule — (coalesce(effective_date, ''),
        # ingested_at, version_id) — including the version_id tie-breaker this
        # feature adds: two undated editions ingested in one instant otherwise
        # tie, and neither orientation could be called older. The one live
        # decision this migration was written for ran newer→older (its
        # same-document proposal promoted that way), and canonical
        # :PairingDecision runs older→newer, so the pair is re-oriented, not
        # copied; both orientations occur in the wild and both are handled.
        if source_order < target_order:
            old_id, new_id = row["source_id"], row["target_id"]
            editions = (row["source_version"], row["target_version"])
        else:
            old_id, new_id = row["target_id"], row["source_id"]
            editions = (row["target_version"], row["source_version"])
        convertible.append(
            {
                "old_key": row["key"],
                "new_key": pairing_key(old_id, new_id),
                "old_id": old_id,
                "new_id": new_id,
                "verdict": _VERDICT[row["verdict"]],
                "editions": editions,
            }
        )

    # Two convertible approvals sharing an endpoint within one edition pair
    # would convert into exactly the two-live-`paired`-verdicts state the
    # pairings POST's 409 exists to refuse — minted by a writer that route
    # does not guard. Neither converts; the reviewer re-records the one they
    # mean through the route, which enforces the conflict rule. Scoped per
    # edition pair on purpose: a middle edition's clause paired into both
    # adjacent pairs is legitimate and passes. `distinct` verdicts never
    # conflict — the 409 refuses only a second live `paired`.
    paired_endpoints: Counter = Counter()
    for candidate in convertible:
        if candidate["verdict"] != PairingVerdict.PAIRED.value:
            continue
        paired_endpoints[(candidate["editions"], candidate["old_id"])] += 1
        paired_endpoints[(candidate["editions"], candidate["new_id"])] += 1
    conflicting_keys = {
        candidate["old_key"]
        for candidate in convertible
        if candidate["verdict"] == PairingVerdict.PAIRED.value
        and (
            paired_endpoints[(candidate["editions"], candidate["old_id"])] > 1
            or paired_endpoints[(candidate["editions"], candidate["new_id"])] > 1
        )
    }
    conversions = [
        {
            "old_key": candidate["old_key"],
            "new_key": candidate["new_key"],
            "old_id": candidate["old_id"],
            "new_id": candidate["new_id"],
            "verdict": candidate["verdict"],
        }
        for candidate in convertible
        if candidate["old_key"] not in conflicting_keys
    ]

    implements_deleted = 0
    retired_same_edition = 0
    if same_edition:
        result = tx.run(RETIRE, {"keys": same_edition, "reason": "same_edition"})
        retired_same_edition = result.single()["retired"]
        implements_deleted += result.consume().counters.relationships_deleted

    retired_conflicting = 0
    if conflicting_keys:
        result = tx.run(
            RETIRE,
            {"keys": sorted(conflicting_keys), "reason": "conflicting_pairing"},
        )
        retired_conflicting = result.single()["retired"]
        implements_deleted += result.consume().counters.relationships_deleted

    converted = 0
    if conversions:
        result = tx.run(CONVERT, {"conversions": conversions})
        converted = result.single()["converted"]
        implements_deleted += result.consume().counters.relationships_deleted

    proposals_deleted = (
        tx.run(DELETE_SAME_DOCUMENT_PROPOSALS)
        .consume()
        .counters.relationships_deleted
    )

    return {
        "converted": converted,
        "retired_same_edition": retired_same_edition,
        "retired_conflicting": retired_conflicting,
        "implements_deleted": implements_deleted,
        "proposals_deleted": proposals_deleted,
    }


def migrate_pairing_decisions(driver: Driver, database: str) -> dict[str, int]:
    """Convert, retire and clean up in one transaction; return the five counts.

    One transaction on purpose: a conversion that landed without its
    retirement would leave a decision `PROMOTE` still matches, and the next
    replay would resurrect the very edge the conversion just deleted. Keys:

    - `converted` — same-document decisions re-recorded as `:PairingDecision`,
      re-oriented older→newer by the corpus rule.
    - `retired_same_edition` — decisions between two clauses of one edition.
    - `retired_conflicting` — approvals sharing an endpoint within one edition
      pair; the reviewer re-records the survivor through the pairings route.
    - `implements_deleted` — promoted same-document edges removed with their
      decisions.
    - `proposals_deleted` — same-document `IMPLEMENTS_PROPOSED` edges removed.

    A second run returns zeros: nothing a run converts or retires still
    matches the queries that found it.
    """
    with driver.session(database=database) as session:
        return session.execute_write(_migrate)
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_migrate.py --collect-only -q`. Expected: `tests/test_migrate.py: 6`, no errors. The merge gate runs the file where Docker exists.

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/migrate.py tests/test_migrate.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK (one per behaviour, each named for the test that kills it; commands run at the merge gate / any Docker host — in this sandbox verify `--collect-only -q` still collects after each mutation and each revert). Mutation 1, kills `test_a_newer_to_older_approval_converts_re_oriented`: skip the swap — replace the `if source_order < target_order:` branch pair with unconditional `old_id, new_id = row["source_id"], row["target_id"]` and `editions = (row["source_version"], row["target_version"])`. Run `.venv/bin/pytest tests/test_migrate.py::test_a_newer_to_older_approval_converts_re_oriented -q`. Expected failure: `records[0]["old"] == older_id` fails (the newer id landed in `old`), and the replace assertion fails with `total == 2` — `record_pairing` MERGEs beside the mis-keyed node, the exact defect the spec's Testing bullet pins. Revert. Mutation 2, kills `test_replay_recreates_no_same_document_implements_after_migration`: leave the live label — delete `REMOVE d:LinkDecision` from `CONVERT`. Run `.venv/bin/pytest tests/test_migrate.py::test_replay_recreates_no_same_document_implements_after_migration -q`. Expected failure: `after["promoted"] == 0` fails with `1` — `PROMOTE` still matches the converted decision and resurrects the edge. Revert. Mutation 3, kills `test_shared_endpoint_approvals_retire_together`: convert the conflicts — replace the `conflicting_keys` set comprehension with `conflicting_keys = set()`. Run `.venv/bin/pytest tests/test_migrate.py::test_shared_endpoint_approvals_retire_together -q`. Expected failure: `counts["converted"] == 0` fails with `2` (converting either — let alone both — is the mutant). Revert. Mutation 4, kills `test_a_same_edition_approval_is_retired_with_its_edge_gone`: drop the same-edition branch — delete the `if row["source_version"] == row["target_version"]:` block so the decision falls into `convertible`. Run `.venv/bin/pytest tests/test_migrate.py::test_a_same_edition_approval_is_retired_with_its_edge_gone -q`. Expected failure: `counts["retired_same_edition"] == 1` fails with `0` and a `:PairingDecision` exists. Revert. Mutation 5, kills `test_same_document_proposals_are_deleted_and_cross_document_ones_kept`: unscope the delete — in `DELETE_SAME_DOCUMENT_PROPOSALS`, delete the line `MATCH (doc)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(b)`. Run `.venv/bin/pytest tests/test_migrate.py::test_same_document_proposals_are_deleted_and_cross_document_ones_kept -q`. Expected failure: the survivor assertion fails — the cross-document proposal was deleted too, and `proposals_deleted` is `2`. Revert. Mutation 6, kills `test_a_second_run_returns_all_zeros` and the replay assertion in `test_a_same_edition_approval_is_retired_with_its_edge_gone`: leave the live label in `RETIRE` — delete its `REMOVE d:LinkDecision` line (a different statement from mutation 2's). Run `.venv/bin/pytest "tests/test_migrate.py::test_a_second_run_returns_all_zeros" "tests/test_migrate.py::test_a_same_edition_approval_is_retired_with_its_edge_gone" -q`. Expected failure: two failures — `again == ZEROS` fails, the second run reporting `retired_same_edition == 1` again because the retired node still matches the read; and `after["promoted"] == 0` fails with `1`, because the same-edition approval is still in `PROMOTE`'s match and the replay puts the deleted `IMPLEMENTS` edge straight back. That second failure is why the edge count alone was not enough: a mutant that strips the edge but leaves the node live passes every assertion above it. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/migrate.py backend/tests/test_migrate.py && git commit -m "feat: legacy same-document decisions convert to pairing verdicts or retire"`

- [ ] Write the failing startup test. First extend `backend/tests/test_migrate.py`'s top-level imports so its head reads exactly:

```python
import pytest
from fastapi.testclient import TestClient

from policy_grapher import main
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.decisions import decision_key, replay_decisions
from policy_grapher.links.pairing import pairing_key, record_pairing
from policy_grapher.migrate import migrate_pairing_decisions
from policy_grapher.obligations import write_obligations
```

  `fastapi.testclient` joins `pytest` in the third-party block with no blank line between them — a blank line there splits one section in two and is itself an `I001` — and `from policy_grapher import main` heads the first-party block, because `policy_grapher` sorts before `policy_grapher.chunking`. Ruff does confirm this: `I001` is in the enabled set here (`.venv/bin/ruff check src tests` passes on a tree whose import blocks are all sorted), so `.venv/bin/ruff check tests/test_migrate.py` reports `I001 Import block is un-sorted or un-formatted` on any other placement. It only classifies `policy_grapher.links.pairing` and `policy_grapher.migrate` as first-party once those files exist on disk, which they do by this step — Task 1 created the first and this task's previous cycle created the second. Then append:

```python
@pytest.mark.integration
def test_startup_runs_the_migration(client_with_graph):
    """The vehicle. A migration nobody schedules is a deletion that never
    happens; this one rides every boot, after apply_schema, because the
    conversion MERGEs against pairing_decision_key_unique. Idempotence (proved
    above) is what makes running it on every boot safe."""
    driver = client_with_graph.app.state.driver
    database = client_with_graph.app.state.settings.neo4j_database

    (older_id,) = _seed_edition(
        driver, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        driver, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(driver, database, source_id=newer_id, target_id=older_id)

    # A second lifespan against the same settings: the fixture's client booted
    # before the legacy decision existed, so a fresh boot must find and
    # convert it. The inner client's driver is its own and closes with it;
    # `driver` above belongs to the fixture's lifespan and stays open.
    with TestClient(main.app):
        pass

    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS live", database_=database
    )
    assert records[0]["live"] == 0
    records, _, _ = driver.execute_query(
        "MATCH (p:PairingDecision) RETURN p.verdict AS verdict", database_=database
    )
    assert [r["verdict"] for r in records] == ["paired"]
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_migrate.py --collect-only -q`. Expected: `tests/test_migrate.py: 7`. At the merge gate, right now, this test fails at `assert records[0]["live"] == 0` with `1` — nothing in `lifespan` calls the migration yet.

- [ ] Write the minimal implementation. In `backend/src/policy_grapher/main.py`, add to the import block (between `jobs.queue` and `models`):

```python
from policy_grapher.migrate import migrate_pairing_decisions
```

  and in `lifespan`, directly after `apply_schema(driver, settings.neo4j_database)`:

```python
    # After apply_schema on purpose: the migration MERGEs on
    # :PairingDecision.key and needs pairing_decision_key_unique in place
    # before its first write. Idempotent, so every boot runs it; only a boot
    # that finds legacy same-document decisions or proposals does any work.
    migrated = migrate_pairing_decisions(driver, settings.neo4j_database)
    logger.info("Pairing decision migration: %s", migrated)
```

- [ ] Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_migrate.py --collect-only -q` — expected `tests/test_migrate.py: 7` — and `.venv/bin/pytest tests/test_startup.py --collect-only -q`, expected `tests/test_startup.py: 10` (this task adds none there), to confirm the existing startup suite still collects against the changed `lifespan`. The merge gate runs both where Docker exists (every `client_with_graph`-based test in the suite now exercises the migration call on boot, which is itself a regression check that it tolerates an empty graph).

- [ ] Lint: `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/main.py tests/test_migrate.py`. Expected: `All checks passed!`

- [ ] THE MUTATION CHECK. Mutation: delete the `migrated = migrate_pairing_decisions(...)` call and its log line from `lifespan`. Run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_migrate.py::test_startup_runs_the_migration -q` (merge gate / Docker host; in this sandbox verify `--collect-only -q` still collects). Expected failure: `assert records[0]["live"] == 0` fails with `1` — the boot no longer converts, so the wiring, not just the function, is what this test guards. Revert.

- [ ] Commit: `git add backend/src/policy_grapher/main.py backend/tests/test_migrate.py && git commit -m "feat: every boot converts what the pairing split left behind"`
### Task 10: The pairings API

**Files:**
- Create: `backend/src/policy_grapher/routers/pairings.py`
- Create: `backend/tests/test_pairings.py`
- Modify: `backend/src/policy_grapher/models.py` (insert between `VerdictIn` and `TriageCitationOut`, lines 257–260 at plan time — anchor by content, earlier tasks shift line numbers)
- Modify: `backend/src/policy_grapher/main.py` (the routers import at 14–22, the `include_router` block at 121–127)
- Modify: `frontend/src/api/types.ts` (insert after `export type Verdict = 'approve' | 'reject'`, line 172, beside the review analogues)
- Modify: `frontend/src/api/client.ts` (the type import block at lines 1–19; new functions after `recordVerdict`, lines 218–228)
- Modify: `frontend/src/api/client.test.ts` (the import list at lines 2–18; a new `describe` appended after the `rebuild` block, which ends at line 300)

The client half belongs to this task rather than to the pairing screen's, and the reason is a test that runs in this sandbox: `backend/tests/test_routers.py::test_the_browser_can_reach_every_route_the_server_declares` carries no `integration` marker and asserts that every path the app registers is modelled by a string literal in `frontend/src/api/client.ts`. Registering the router without `getPairingQueue`/`recordPairing` therefore turns a green unit test red and leaves it red for every task in between. The route and the two functions that reach it ship together, in one commit.

**Interfaces:**
- Consumes (from the `links/pairing.py` task, per the Interface Contract): `PairingVerdict` (StrEnum: `PAIRED = "paired"`, `DISTINCT = "distinct"`); `pairing_key(old_id: str, new_id: str) -> str`; `record_pairing(tx, *, old_id: str, new_id: str, verdict: str, actor: str, rationale: str) -> None`; `read_settled(tx, *, from_version_id: str, to_version_id: str) -> list[dict]` returning `[{"old_id", "new_id", "verdict", "actor"}]`.
- Consumes (from the diff tasks): `diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]` with keys `ADDED`/`REMOVED`/`MODIFIED`/`pairings_unapplied`; `(:Obligation)-[:PAIRING_CANDIDATE {confidence, rationale, outcome}]->(:Obligation)` edges written from-side→to-side by `diff_versions`, with settled pairs never re-recorded; `drop_candidates(tx, *, from_version_id, to_version_id) -> int`, which `diff_versions` calls and which clears candidate edges only between the two editions it is given; the `pairing_decision_key_unique` constraint from the `db.py` task.
- Consumes (existing repo): `primary_anchor(obligation_var, chunk_var)` (`obligations.py:106`), `require_principal`/`Principal` (`auth.py`), `get_driver`/`get_app_settings` (`dependencies.py`), `ObligationCitationOut` (`models.py:190`).
- Consumes (existing frontend): `ObligationCitation` (`types.ts:136-150`), `request<T>` and `ApiError` (`client.ts`), the `mockJson` helper at the top of `client.test.ts`.
- Produces (later frontend tasks rely on these): `PairingCandidateOut`, `PairingSettledOut`, `PairingQueueOut`, `PairingVerdictIn` in `models.py`; `GET /pairings/queue?from_version_id&to_version_id&limit → PairingQueueOut`; `POST /pairings/{old_obligation_id}/{new_obligation_id} → PairingSettledOut`; the router registered in `main.py`; in `frontend/src/api/types.ts` the types `PairingVerdict`, `PairingCandidate`, `PairingSettled`, `PairingQueue`; in `frontend/src/api/client.ts` the functions `getPairingQueue(fromVersionId: string, toVersionId: string, limit?: number): Promise<PairingQueue>` and `recordPairing(oldId: string, newId: string, verdict: PairingVerdict, rationale?: string): Promise<PairingSettled>` — the pairing screen's task consumes all six.

- [ ] **Write the failing integration tests.** Create `backend/tests/test_pairings.py` in full:

```python
"""The pairing queue and the verdicts that settle it.

Everything here goes through the API, because the API is the claim under test:
the queue runs the diff itself — `diff_versions`' only other caller is the
Triage GET, so a queue that merely read candidate edges would be empty for any
edition pair nobody had opened in Triage — and the POST needs no recorded
candidate edge, because gating on one would make the recorder outrank the
person for exactly the declines the design exists to reach.

The seeded editions carry no `effective_date` and no `ingested_at`, on
purpose: the corpus ordering rule then falls all the way through to the
`version_id` tie-breaker this feature adds, so these tests exercise it rather
than passing over it.
"""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.links.pairing import pairing_key
from policy_grapher.obligations import write_obligations

# The pair test_diff.py proves the wording pass auto-pairs: distinctive shared
# vocabulary well over PAIRING_CONFIDENCE, seeded across two different sections
# so the section rule cannot reach it first and pass 3 must.
REWORDED_OLD = (
    "All of the DoD Components shall acquire systems, subsystems, equipment, "
    "supplies, and services in accordance with the statutory requirements for "
    "competition."
)
REWORDED_NEW = (
    "The DoD Components will acquire systems, subsystems, equipment, supplies, "
    "product support, sustainment, and services in accordance with the "
    "statutory requirements for competition."
)

# No content words at all — every word is a stopword or under three letters —
# so `score_pair` returns None before scoring (propose.py:61-62). This is the
# silent exclusion class from the problem section, and the case a human most
# obviously beats the measure: a complete rewording sharing no content words.
BLANK_OLD = "They shall not do so."
BLANK_NEW = "It must all be this."
RIVAL = "They must not do it."

# The taker fixtures, scored by the real measure rather than a stub, because the
# join under test is Cypher and only the API reaches it. Under
# `links/propose.py`'s scorer these give test_diff.py's both-sides-taken shape at
# the confidences this corpus's own measure produces:
#   STRATEGY_OLD ~ STRATEGY_NEW  1.00 (identical content words)
#   FUNDS_OLD    ~ MERGED_NEW    0.91 (ten of eleven)
#   STRATEGY_OLD ~ MERGED_NEW    0.80 (eight of ten) — declined, both ends taken
#   FUNDS_OLD    ~ STRATEGY_NEW  unscored (no shared content word at all)
#   MERGED_NEW   ~ FUNDS_LATER   0.91 — a second edition pair's winner
# MERGED_NEW is deliberately the merge of the other two: it is the clause that
# belongs to two diffs at once, which is the whole difficulty `taken_by` has.
STRATEGY_OLD = (
    "Program managers shall prepare a cybersecurity strategy for the milestone "
    "decision on each acquisition category systems program."
)
STRATEGY_NEW = (
    "For each acquisition category systems program, the program managers will "
    "prepare a cybersecurity strategy before the milestone decision."
)
FUNDS_OLD = (
    "Contracting officers shall obligate funds by competitive procurement of "
    "sustainment services above the dollar thresholds."
)
MERGED_NEW = (
    "Contracting officers and program managers will obligate funds by "
    "competitive procurement of sustainment support above the dollar "
    "thresholds, and will prepare a cybersecurity strategy for the acquisition "
    "category systems program."
)
FUNDS_LATER = (
    "Contracting officers must obligate funds by competitive procurement of "
    "sustainment above the dollar thresholds annually."
)


def _seed(driver, database, *, doc_slug, version_id, entries):
    """`entries` is (section, statement) pairs; returns {statement: obligation_id}.

    Editions are created bare — no effective_date, no ingested_at — so ordering
    rests on the version_id tie-breaker; choose ids that sort chronologically.
    """
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"slug": doc_slug, "vid": version_id},
        database_=database,
    )
    ids = {}
    with driver.session(database=database) as session:
        for section, statement in entries:
            chunk = chunk_pages(
                [f"{section}. TITLE.\nBody text.\n"], version_id=version_id
            )[-1]
            session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=Modality.SHALL,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                ],
            )
            records, _, _ = driver.execute_query(
                "MATCH (:DocumentVersion {version_id: $vid})-[:MANDATES]->"
                "(o:Obligation {statement: $statement}) "
                "RETURN o.obligation_id AS id",
                {"vid": version_id, "statement": statement},
                database_=database,
            )
            ids[statement] = records[0]["id"]
    return ids


@pytest.mark.integration
def test_the_queue_returns_candidates_for_a_pair_never_opened_in_triage(
    client_with_auth,
):
    """The route runs the diff itself. Candidate edges are written from inside
    `diff_versions`, whose only other caller is the Triage GET — a queue that
    merely read them would be empty until someone happened to load that screen,
    and a verdict would take effect only the next time they did."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    )
    assert response.status_code == 200

    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["old"]["obligation_id"] == old_ids[REWORDED_OLD]
    assert item["new"]["obligation_id"] == new_ids[REWORDED_NEW]
    assert item["old"]["version_id"] == "pol@2018"
    assert item["new"]["version_id"] == "pol@2020"
    assert item["old"]["section_path"] == ["3.2"]
    assert item["new"]["section_path"] == ["4.1"]
    assert item["outcome"] == "auto_paired"
    assert item["confidence"] >= 0.75
    assert item["taken_by"] == []
    assert body["settled"] == []
    assert body["pending"] == 1
    assert body["pairings_unapplied"] == 0


@pytest.mark.integration
def test_a_taker_from_a_third_edition_does_not_appear_in_taken_by(client_with_auth):
    """`taken_by` names the winners of *this* diff, and only the `:MANDATES`
    scope can say which those are.

    One obligation serves every diff its edition is in, so `MERGED_NEW` ends up
    carrying two `auto_paired` edges: one to `FUNDS_OLD` in `pol@2018`, one to
    `FUNDS_LATER` in `pol@2022`. Only the first answers the question the screen
    is asking — what consumed this end of the pair in front of you — and
    direction cannot separate them, because `MERGED_NEW` is the new side of one
    edge and the old side of the other. Hence the undirected taker joins scoped
    to the request's own editions.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", STRATEGY_OLD), ("3.3", FUNDS_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", STRATEGY_NEW), ("4.2", MERGED_NEW)],
    )
    later_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2022",
        entries=[("5.1", FUNDS_LATER)],
    )

    # The later pair is diffed first, so its winner's edge is in the graph with
    # every opportunity to leak into the earlier pair's answer. It survives that
    # second run: `drop_candidates` clears only the edges between the two
    # editions it is given.
    later = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2020", "to_version_id": "pol@2022"},
    )
    assert later.status_code == 200
    assert [item["outcome"] for item in later.json()["items"]] == ["auto_paired"]

    body = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    ).json()

    declined = [
        item
        for item in body["items"]
        if item["old"]["obligation_id"] == old_ids[STRATEGY_OLD]
        and item["new"]["obligation_id"] == new_ids[MERGED_NEW]
    ]
    assert len(declined) == 1
    assert declined[0]["outcome"] == "partner_taken"
    # Old side's taker first, new side's second — the order the route builds the
    # list in. `STRATEGY_NEW` took the old end, `FUNDS_OLD` took the new one.
    assert declined[0]["taken_by"] == [
        new_ids[STRATEGY_NEW],
        old_ids[FUNDS_OLD],
    ]
    assert later_ids[FUNDS_LATER] not in declined[0]["taken_by"]


@pytest.mark.integration
def test_a_reversed_pair_is_a_400_not_a_reversed_diff(client_with_auth):
    """Nothing beneath this route carries chronology — `diff_versions` binds
    whatever from/to it is given — so a reversed pair would quietly write
    reversed candidate edges and serve a reviewer a queue whose question is
    upside down. These editions are undated and carry no ingested_at, so the
    refusal here is the version_id tie-breaker doing its work."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2020", "to_version_id": "pol@2018"},
    )

    assert response.status_code == 400
    assert "older" in response.json()["detail"]


@pytest.mark.integration
def test_a_verdict_needs_no_recorded_candidate(client_with_auth):
    """Admissibility is membership, not a recorded edge. These two statements
    have no content words, so `score_pair` never scores them at all — no
    candidate edge exists or ever will — and this pair is exactly the one a
    human most obviously beats the measure on."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired", "rationale": "a complete rewording"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_id"] == old_ids[BLANK_OLD]
    assert body["new_id"] == new_ids[BLANK_NEW]
    assert body["verdict"] == "paired"
    assert body["actor"] == "tester"


@pytest.mark.integration
def test_a_cross_document_pair_is_a_404(client_with_auth):
    """The pairing question is same-document by definition — is the newer
    clause the older one reworded? Two documents ask the other question, under
    the other vocabulary, on the Review screen."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    a_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    b_ids = _seed(
        driver, database, doc_slug="other", version_id="other@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{a_ids[BLANK_OLD]}/{b_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_a_newer_first_post_is_recorded_older_to_newer(client_with_auth):
    """Direction is older→newer and only the route can enforce it — the
    obligation ids determine the editions, the editions order. `key` is a
    directional hash, so a mis-oriented record would never be replaced by a
    later verdict on the same pair, only MERGE-d beside it."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{new_ids[BLANK_NEW]}/{old_ids[BLANK_OLD]}",
        json={"verdict": "paired"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_id"] == old_ids[BLANK_OLD]
    assert body["new_id"] == new_ids[BLANK_NEW]

    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision) "
        "RETURN d.old_obligation_id AS old_id, d.new_obligation_id AS new_id, "
        "d.key AS key",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old_id"] == old_ids[BLANK_OLD]
    assert records[0]["new_id"] == new_ids[BLANK_NEW]
    assert records[0]["key"] == pairing_key(
        old_ids[BLANK_OLD], new_ids[BLANK_NEW]
    )


@pytest.mark.integration
def test_a_second_paired_verdict_on_one_clause_in_one_pair_is_a_409(
    client_with_auth,
):
    """The diff is one-to-one within an edition pair, so two live paired
    verdicts on one clause is a state whose loser would be chosen by dict
    iteration order. Refused at the source, with the remedy named: the detail
    says which pairing to mark distinct first."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW), ("5.1", RIVAL)],
    )

    first = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    assert first.status_code == 200

    second = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[RIVAL]}",
        json={"verdict": "paired"},
    )

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "distinct" in detail
    assert new_ids[BLANK_NEW] in detail


@pytest.mark.integration
def test_a_middle_edition_pairs_into_both_adjacent_pairs(client_with_auth):
    """The scope on the 409 is what makes this legal. B's clause pairs to its
    A-predecessor and to its C-successor — the very case the MANDATES-scoped
    read exists to keep separate — and an unscoped conflict rule would refuse
    the second verdict and prescribe destroying the first."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    a_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    b_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )
    c_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2022",
        entries=[("5.1", RIVAL)],
    )

    a_to_b = client_with_auth.post(
        f"/pairings/{a_ids[BLANK_OLD]}/{b_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    b_to_c = client_with_auth.post(
        f"/pairings/{b_ids[BLANK_NEW]}/{c_ids[RIVAL]}",
        json={"verdict": "paired"},
    )

    assert a_to_b.status_code == 200
    assert b_to_c.status_code == 200


@pytest.mark.integration
def test_a_distinct_pair_stays_reachable_after_a_rediff(client_with_auth):
    """Reversal needs no candidate edge. A distinct-settled pair is excluded
    from recording, so after the next diff no edge re-asks the question — but
    the queue still returns it, marked settled, and a paired POST on it
    succeeds, because admissibility never depended on the edge."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    settled = client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "distinct", "rationale": "different duties"},
    )
    assert settled.status_code == 200

    body = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    ).json()

    assert body["settled"] == [
        {
            "old_id": old_ids[REWORDED_OLD],
            "new_id": new_ids[REWORDED_NEW],
            "verdict": "distinct",
            "actor": "tester",
        }
    ]
    assert body["items"] == []
    assert body["pending"] == 0

    reversed_verdict = client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "paired"},
    )
    assert reversed_verdict.status_code == 200
    assert reversed_verdict.json()["verdict"] == "paired"
```

- [ ] **Run the collection check** — integration tests cannot run in this sandbox (no Docker); the merge gate runs them where Docker exists:

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairings.py --collect-only -q`

  Expected: `tests/test_pairings.py: 9` and no collection errors. (`-q` twice is deliberate: `pyproject.toml` already sets `addopts = "-q"`, and the second one is what collapses the node list to that one line.) This is the failing state TDD requires: at the merge gate every test would fail with a 404 (`Not Found` — no `/pairings` routes exist yet), and the queue tests with `KeyError`/assertion failures on the missing body.

- [ ] **Add the four models to `models.py`.** Insert this block between the end of `VerdictIn` (`rationale: str = ""`) and `class TriageCitationOut` — beside their review analogues, which is where the spec places them:

```python
class PairingCandidateOut(BaseModel):
    """One pair of clauses the wording pass ruled on, and how it ruled.

    Both sides are full citations for `ObligationCitationOut`'s reason: the
    question is whether the newer clause is the older one reworded, and a
    reviewer cannot answer without reading both in place. `outcome` is the
    first rule that fired in the diff, in code order — `auto_paired`,
    `partner_taken`, `contested`, `below_threshold` — a precedence chain, not
    four disjoint conditions: every partner-taken pair also satisfies the
    margin predicate. `taken_by` names the auto-paired winners' other ends,
    zero to two of them, because a pair is declined when *either* endpoint was
    already consumed and the screen must say by what.
    """

    old: ObligationCitationOut
    new: ObligationCitationOut
    confidence: float
    rationale: str
    outcome: str
    taken_by: list[str]


class PairingSettledOut(BaseModel):
    """A pair a person has already ruled on, kept reachable so the verdict can
    be undone. Ids alone, deliberately: this list exists to mark rows settled
    and route a reversal, not to be read — the citations live on the
    candidates."""

    old_id: str
    new_id: str
    verdict: str
    actor: str


class PairingQueueOut(BaseModel):
    """The pairing queue: what the diff decided, what a person settled, and
    what it could not apply.

    `pending` is undecided candidates in the graph, not rows in `items` — the
    review queue's own pattern, for its reason: the page is capped, and the
    number that falls as the backlog is worked through is the graph count.
    `pairings_unapplied` counts `paired` verdicts the diff could not apply
    because pass 1 matched the clause identically in both editions — counted,
    never dropped, so a shelved human verdict is at least visible.
    """

    items: list[PairingCandidateOut]
    settled: list[PairingSettledOut]
    pairings_unapplied: int
    pending: int


class PairingVerdictIn(BaseModel):
    """A reviewer's pairing verdict.

    Carries no `actor`, for `VerdictIn`'s reason: the actor is the
    authenticated principal and nothing else, and a client-supplied one would
    make the audit trail worthless.
    """

    verdict: str
    rationale: str = ""
```

- [ ] **Create `backend/src/policy_grapher/routers/pairings.py`** in full:

```python
"""Settling the pairs the diff declines — and undoing the ones it guessed.

Two routes. The GET runs the diff itself, exactly as Triage does:
`diff_versions`' only other caller is the Triage GET handler, so a queue that
merely read candidate edges would be empty for any edition pair nobody had
opened in Triage, and a verdict would take effect only the next time someone
loaded that screen. It inherits the same "a GET writes derived nodes" trade
Triage already flags and accepts (routers/triage.py, ADR-015).

The GET also pins direction, because nothing beneath it does — `diff_versions`
binds whatever from/to it is given, and `:Change`'s `FROM_VERSION`/`TO_VERSION`
carry request order, not chronology. A reversed pair here would quietly write
reversed candidate edges and serve a reviewer a queue whose question is upside
down, so it is a 400 instead. Triage keeps its arbitrary-direction behaviour;
its reversed runs' edges are cleaned by the undirected drop inside the diff.

The POST needs no recorded candidate edge. Admissibility is membership — both
obligations exist and are `:MANDATES`-ed by two editions of one document —
which deliberately departs from the review queue's proposal-gated rule
(routers/review.py): the pairing question exists for every pair of clauses in
the two editions, and gating on a candidate would make the recorder outrank
the person for exactly the declines this screen exists to reach — the silent
`score_pair` exclusions and the sub-threshold pairs the recording bound drops.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.changes.diff import diff_versions
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.links.pairing import (
    PairingVerdict,
    read_settled,
    record_pairing,
)
from policy_grapher.models import (
    ObligationCitationOut,
    PairingCandidateOut,
    PairingQueueOut,
    PairingSettledOut,
    PairingVerdictIn,
)
from policy_grapher.obligations import primary_anchor

router = APIRouter(prefix="/pairings", tags=["pairings"])

VERSION_EXISTS = """
MATCH (v:DocumentVersion {version_id: $version_id}) RETURN count(v) AS total
"""

# The corpus ordering rule as a tuple this route can compare in Python:
# effective date, then ingest time, then version id. The version_id tie-breaker
# is this feature's addition — two undated editions ingested in one instant
# otherwise tie, and neither orientation of the pair would pass the 400 below.
# Strings throughout: effective_date is stored as an ISO string
# (versions.merge_version), toString on the ingest datetime yields the ISO form
# which orders lexically, and coalescing absent values to '' keeps a
# fixture-built edition comparable at all.
ORDERING = """
UNWIND [$from_version_id, $to_version_id] AS wanted
MATCH (v:DocumentVersion {version_id: wanted})
RETURN v.version_id                          AS version_id,
       coalesce(v.effective_date, '')        AS effective_date,
       coalesce(toString(v.ingested_at), '') AS ingested_at
"""

# One citation per side; see `obligations.primary_anchor` for why the anchor is
# not matched directly. The candidate edge is matched *directed* here, unlike
# the diff's drop: this route has already refused any pair that is not
# older→newer, and `diff_versions` has just dropped and rewritten this pair's
# edges from-side→to-side inside the same transaction, so every surviving edge
# runs with the request. The taker joins are undirected and `:MANDATES`-scoped
# to the request's other edition, because one obligation serves every diff its
# edition is in — a middle edition belongs to two pairs, and direction alone
# cannot separate two diffs run from the same older edition. The greedy loop is
# one-to-one within an edition pair, so each side has at most one taker.
# Substituted rather than formatted: the query contains Cypher braces.
_CANDIDATES_TEMPLATE = """
MATCH (from_version:DocumentVersion {version_id: $from_version_id})
MATCH (to_version:DocumentVersion {version_id: $to_version_id})
MATCH (from_version)-[:MANDATES]->(old:Obligation)
      -[r:PAIRING_CANDIDATE]->
      (new:Obligation)<-[:MANDATES]-(to_version)
--OLD-ANCHOR--
--NEW-ANCHOR--
MATCH (old_doc:Document)-[:HAS_VERSION]->(from_version)
MATCH (new_doc:Document)-[:HAS_VERSION]->(to_version)
OPTIONAL MATCH (old)-[:PAIRING_CANDIDATE {outcome: 'auto_paired'}]-(old_taker:Obligation)
WHERE old_taker <> new
  AND EXISTS { MATCH (to_version)-[:MANDATES]->(old_taker) }
OPTIONAL MATCH (new)-[:PAIRING_CANDIDATE {outcome: 'auto_paired'}]-(new_taker:Obligation)
WHERE new_taker <> old
  AND EXISTS { MATCH (from_version)-[:MANDATES]->(new_taker) }
RETURN old.obligation_id       AS old_id,
       old.statement           AS old_statement,
       old.modality            AS old_modality,
       old_doc.name            AS old_document,
       from_version.version_id AS old_version_id,
       old_chunk.section_path  AS old_section_path,
       old_chunk.page          AS old_page,
       new.obligation_id       AS new_id,
       new.statement           AS new_statement,
       new.modality            AS new_modality,
       new_doc.name            AS new_document,
       to_version.version_id   AS new_version_id,
       new_chunk.section_path  AS new_section_path,
       new_chunk.page          AS new_page,
       r.confidence            AS confidence,
       r.rationale             AS rationale,
       r.outcome               AS outcome,
       old_taker.obligation_id AS old_taken_by,
       new_taker.obligation_id AS new_taken_by
ORDER BY r.confidence DESC, old_id, new_id
LIMIT $limit
"""

CANDIDATES = (
    _CANDIDATES_TEMPLATE
    .replace("--OLD-ANCHOR--", primary_anchor("old", "old_chunk"))
    .replace("--NEW-ANCHOR--", primary_anchor("new", "new_chunk"))
)

# The page's own match, counted without the LIMIT — the review queue's PENDING
# reason: the page is capped, and the number a reviewer needs is the backlog.
# No anti-join here, unlike review's, because none is needed: the diff never
# re-records a settled pair as a candidate — the `:PairingDecision` is the
# record — so every candidate edge between these two editions is an open
# question by construction.
PENDING = """
MATCH (:DocumentVersion {version_id: $from_version_id})-[:MANDATES]->(:Obligation)
      -[r:PAIRING_CANDIDATE]->
      (:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $to_version_id})
RETURN count(r) AS pending
"""

# Which document and edition hold an obligation, plus the edition's ordering
# tuple. An obligation belongs to exactly one edition — its id hashes the
# version_id (extraction/schema.py) — which is what lets the POST order the
# pair from nothing but the two path parameters.
RESOLVE_EDITION = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)
      -[:MANDATES]->(:Obligation {obligation_id: $obligation_id})
RETURN d.slug                                AS document_slug,
       v.version_id                          AS version_id,
       coalesce(v.effective_date, '')        AS effective_date,
       coalesce(toString(v.ingested_at), '') AS ingested_at
"""

# A live paired verdict naming $obligation_id with a *different* partner whose
# other end is `:MANDATES`-ed by the same other edition. Both roles are
# checked, because canonical direction puts a middle edition's clause on the
# old side of one decision and the new side of another. The `:MANDATES` scope
# is the whole point: an unscoped match would refuse B→C because A→B exists,
# and prescribe destroying a verdict from a different diff.
CONFLICTING = """
MATCH (d:PairingDecision {verdict: 'paired'})
WHERE (d.old_obligation_id = $obligation_id
       AND d.new_obligation_id <> $partner_id
       AND EXISTS {
           MATCH (:DocumentVersion {version_id: $other_version_id})
                 -[:MANDATES]->(:Obligation {obligation_id: d.new_obligation_id})
       })
   OR (d.new_obligation_id = $obligation_id
       AND d.old_obligation_id <> $partner_id
       AND EXISTS {
           MATCH (:DocumentVersion {version_id: $other_version_id})
                 -[:MANDATES]->(:Obligation {obligation_id: d.old_obligation_id})
       })
RETURN d.old_obligation_id AS old_id, d.new_obligation_id AS new_id
LIMIT 1
"""


def _require_version(driver: Driver, database: str, version_id: str) -> None:
    records, _, _ = driver.execute_query(
        VERSION_EXISTS,
        {"version_id": version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if records[0]["total"] == 0:
        raise HTTPException(
            status_code=404, detail=f"No edition with version_id {version_id!r}."
        )


@router.get("/queue", response_model=PairingQueueOut)
def queue(
    from_version_id: str = Query(...),
    to_version_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> PairingQueueOut:
    """What the diff decided between two editions, and what a person settled.

    An unknown edition is a 404 for Triage's reason: an empty queue reads as
    "nothing to settle", which a mistyped version id must not be able to say.
    A pair that is not older→newer by the corpus ordering is a 400, because
    everything below this point binds request order and calls it from/to.
    """
    database = settings.neo4j_database
    _require_version(driver, database, from_version_id)
    _require_version(driver, database, to_version_id)

    records, _, _ = driver.execute_query(
        ORDERING,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    ordering = {
        record["version_id"]: (
            record["effective_date"],
            record["ingested_at"],
            record["version_id"],
        )
        for record in records
    }
    if not ordering[from_version_id] < ordering[to_version_id]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{from_version_id!r} does not precede {to_version_id!r} by the "
                "corpus ordering (effective date, then ingest time, then version "
                "id). The queue's question is one-directional — is the newer "
                "clause the older one reworded? — so a reversed pair would be "
                "answered upside down and its candidate edges written backwards. "
                "Swap from and to."
            ),
        )

    def _work(tx):
        counts = diff_versions(
            tx, from_version_id=from_version_id, to_version_id=to_version_id
        )
        candidates = [
            dict(record)
            for record in tx.run(
                CANDIDATES,
                {
                    "from_version_id": from_version_id,
                    "to_version_id": to_version_id,
                    "limit": limit,
                },
            )
        ]
        settled = read_settled(
            tx, from_version_id=from_version_id, to_version_id=to_version_id
        )
        pending = tx.run(
            PENDING,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        ).single()["pending"]
        return counts, candidates, settled, pending

    with driver.session(database=database) as session:
        counts, candidates, settled, pending = session.execute_write(_work)

    return PairingQueueOut(
        items=[
            PairingCandidateOut(
                old=ObligationCitationOut(
                    obligation_id=record["old_id"],
                    statement=record["old_statement"],
                    modality=record["old_modality"],
                    document=record["old_document"],
                    version_id=record["old_version_id"],
                    section_path=record["old_section_path"],
                    page=record["old_page"],
                ),
                new=ObligationCitationOut(
                    obligation_id=record["new_id"],
                    statement=record["new_statement"],
                    modality=record["new_modality"],
                    document=record["new_document"],
                    version_id=record["new_version_id"],
                    section_path=record["new_section_path"],
                    page=record["new_page"],
                ),
                confidence=record["confidence"],
                rationale=record["rationale"],
                outcome=record["outcome"],
                taken_by=[
                    taker
                    for taker in (record["old_taken_by"], record["new_taken_by"])
                    if taker is not None
                ],
            )
            for record in candidates
        ],
        settled=[
            PairingSettledOut(
                old_id=entry["old_id"],
                new_id=entry["new_id"],
                verdict=entry["verdict"],
                actor=entry["actor"],
            )
            for entry in settled
        ],
        pairings_unapplied=counts["pairings_unapplied"],
        pending=pending,
    )


@router.post(
    "/{old_obligation_id}/{new_obligation_id}", response_model=PairingSettledOut
)
def settle(
    old_obligation_id: str,
    new_obligation_id: str,
    body: PairingVerdictIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> PairingSettledOut:
    """Record a pairing verdict. `actor` is `principal.name`; the body has no
    say in it.

    The route orders the pair older→newer itself before keying, whatever order
    the path gave it — the obligation ids determine the editions, the editions
    order by the corpus rule. The key is a directional hash, so a mis-oriented
    record could never be replaced by a later verdict on the same pair, only
    MERGE-d beside it.

    One conflict is refused rather than recorded, inside the same transaction
    that would record it: a paired verdict naming a clause that already carries
    a live paired verdict with a different partner *in the same other edition*
    is a 409 naming the pairing to mark distinct first. The scope matters — a
    middle edition's clause legitimately pairs into both adjacent pairs.
    """
    database = settings.neo4j_database
    if body.verdict not in set(PairingVerdict):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown verdict {body.verdict!r}; expected one of "
                f"{[v.value for v in PairingVerdict]}."
            ),
        )

    editions = {}
    for obligation_id in (old_obligation_id, new_obligation_id):
        records, _, _ = driver.execute_query(
            RESOLVE_EDITION,
            {"obligation_id": obligation_id},
            database_=database,
            routing_=RoutingControl.READ,
        )
        if not records:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No obligation {obligation_id!r} held by any edition. A "
                    "pairing verdict is recorded against two clauses that exist."
                ),
            )
        editions[obligation_id] = records[0]

    first = editions[old_obligation_id]
    second = editions[new_obligation_id]
    if first["document_slug"] != second["document_slug"]:
        raise HTTPException(
            status_code=404,
            detail=(
                "A pairing runs between two editions of one document; these "
                f"obligations belong to {first['document_slug']!r} and "
                f"{second['document_slug']!r}. Whether one document's clause "
                "discharges another's is Review's question, not this one."
            ),
        )
    if first["version_id"] == second["version_id"]:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Both obligations belong to edition {first['version_id']!r}; "
                "a pairing runs between two editions of one document."
            ),
        )

    def _key(row) -> tuple[str, str, str]:
        return (row["effective_date"], row["ingested_at"], row["version_id"])

    old_id, new_id = old_obligation_id, new_obligation_id
    if _key(second) < _key(first):
        old_id, new_id = new_obligation_id, old_obligation_id
    old_edition = editions[old_id]["version_id"]
    new_edition = editions[new_id]["version_id"]

    def _write(tx):
        # The conflict check runs in the transaction that records, not as a
        # separate read: the 409 is the sole guard against the two-live-paired
        # state the diff cannot arbitrate, so it must not lose a race to a
        # concurrent verdict.
        if body.verdict == PairingVerdict.PAIRED:
            for obligation_id, partner_id, other_version_id in (
                (old_id, new_id, new_edition),
                (new_id, old_id, old_edition),
            ):
                conflict = tx.run(
                    CONFLICTING,
                    {
                        "obligation_id": obligation_id,
                        "partner_id": partner_id,
                        "other_version_id": other_version_id,
                    },
                ).single()
                if conflict is not None:
                    return dict(conflict)
        record_pairing(
            tx,
            old_id=old_id,
            new_id=new_id,
            verdict=body.verdict,
            actor=principal.name,
            rationale=body.rationale,
        )
        return None

    with driver.session(database=database) as session:
        conflict = session.execute_write(_write)

    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A live paired verdict already links {conflict['old_id']} → "
                f"{conflict['new_id']} within this edition pair, and the diff "
                "is one-to-one: two live paired verdicts on one clause would "
                "leave the loser chosen by iteration order. Mark that pairing "
                "distinct first, then re-record this one."
            ),
        )

    return PairingSettledOut(
        old_id=old_id, new_id=new_id, verdict=body.verdict, actor=principal.name
    )
```

- [ ] **Register the router in `main.py`.** Two edits. The import block at lines 14–22 becomes:

```python
from policy_grapher.routers import (
    admin,
    ask,
    documents,
    graph,
    pairings,
    rebuilds,
    review,
    triage,
)
```

  and the `include_router` block at lines 121–127 becomes:

```python
app.include_router(admin.router)
app.include_router(ask.router)
app.include_router(documents.router)
app.include_router(graph.router)
app.include_router(pairings.router)
app.include_router(rebuilds.router)
app.include_router(review.router)
app.include_router(triage.router)
```

- [ ] **Watch the route-reachability test go red — it runs here.** Registering the router puts two paths in the app that the browser cannot yet reach, and `tests/test_routers.py` says so without needing Docker:

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_routers.py`

  Expected: `1 failed, 6 passed, 1 error`. The failure is `test_the_browser_can_reach_every_route_the_server_declares` with `AssertionError: the browser cannot reach 2 route(s) the server declares: ['/pairings/queue', '/pairings/{}/{}']. Add a client function in client.ts, or — if the route is deliberately not for the browser — record it in DELIBERATELY_UNREACHABLE with the decision that parked it.` The single error is `test_health_still_serves_through_the_router`, the environmental one this sandbox always has (`DockerException`). This is a real red, not a tolerated one: the client cycle below closes it before the task commits.

- [ ] **Re-run the collection check and lint:**

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairings.py --collect-only -q`

  Expected: `tests/test_pairings.py: 9`, no errors — which now also proves the router module imports cleanly, since collection imports the app through `conftest.py`. Then:

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/models.py src/policy_grapher/routers/pairings.py src/policy_grapher/main.py tests/test_pairings.py`

  Expected: `All checks passed!`. The merge gate (where Docker exists) runs `.venv/bin/pytest tests/test_pairings.py` — no extra `-q`, or the count line is suppressed — and must report `9 passed`.

- [ ] **THE MUTATION CHECK** — nine mutations, one per test in the file, each applied alone and reverted before the next. Verified at the merge gate by `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairings.py` (no extra `-q`: `addopts` already supplies one and a second suppresses the count line). In this sandbox run `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_pairings.py --collect-only -q` after each, expecting `tests/test_pairings.py: 9`, to confirm the mutation did not simply stop the file collecting.
  1. In `queue`, drop the `version_id` tie-breaker — build the ordering tuples as `(record["effective_date"], record["ingested_at"])`. Expected: `3 failed, 6 passed`. `test_the_queue_returns_candidates_for_a_pair_never_opened_in_triage` fails with a 400 on the *well-oriented* request — every edition here is undated and carries no ingest time, so without the tie-breaker both orientations tie and neither passes — and the other two tests that GET the queue (`test_a_taker_from_a_third_edition_does_not_appear_in_taken_by` on its first request, `test_a_distinct_pair_stays_reachable_after_a_rediff` on `body["settled"]`, which raises `KeyError: 'settled'` against the 400's `{"detail": …}` body) go with it. Revert.
  2. In `queue`, delete the `if not ordering[from_version_id] < ordering[to_version_id]: raise HTTPException(status_code=400, …)` block entirely. Expected: `1 failed, 8 passed` — `test_a_reversed_pair_is_a_400_not_a_reversed_diff` gets 200 and a queue of candidate edges written backwards. Revert.
  3. In `settle`, gate the verdict on a recorded candidate — the review queue's proposal rule transplanted onto a route that deliberately refuses it. Immediately above `def _write(tx):` insert:

     ```python
         joined, _, _ = driver.execute_query(
             "MATCH (:Obligation {obligation_id: $old_id})-[:PAIRING_CANDIDATE]-"
             "(:Obligation {obligation_id: $new_id}) RETURN count(*) AS total",
             {"old_id": old_id, "new_id": new_id},
             database_=database,
             routing_=RoutingControl.READ,
         )
         if joined[0]["total"] == 0:
             raise HTTPException(status_code=404, detail="No candidate for this pair.")
     ```

     Expected: `5 failed, 4 passed`. `test_a_verdict_needs_no_recorded_candidate` is the named one — its two statements have no content words at all, so no candidate edge exists or ever will, and the POST that must be a 200 becomes a 404. The other four POST tests fail with it (`test_a_newer_first_post_is_recorded_older_to_newer`, `test_a_second_paired_verdict_on_one_clause_in_one_pair_is_a_409` on its first POST, `test_a_middle_edition_pairs_into_both_adjacent_pairs`, `test_a_distinct_pair_stays_reachable_after_a_rediff` on its settling POST), which is the claim restated: not one verdict in this file is admitted by an edge the recorder wrote. Revert.
  4. In `settle`, delete the `if first["document_slug"] != second["document_slug"]: raise HTTPException(status_code=404, …)` block. Expected: `1 failed, 8 passed` — `test_a_cross_document_pair_is_a_404` gets 200, because the two editions differ and nothing else refuses the pair. Revert.
  5. In `settle`, delete the swap (`if _key(second) < _key(first): old_id, new_id = new_obligation_id, old_obligation_id`). Expected: `1 failed, 8 passed` — `test_a_newer_first_post_is_recorded_older_to_newer` fails on `body["old_id"]`; the record keeps request order and keys to a second decision beside the first. Revert.
  6. In `_write`, delete the whole `if body.verdict == PairingVerdict.PAIRED:` conflict loop. Expected: `1 failed, 8 passed` — `test_a_second_paired_verdict_on_one_clause_in_one_pair_is_a_409` gets 200, and the graph holds the two-live-paired state the diff cannot arbitrate. Revert.
  7. In `CONFLICTING`, delete both `AND EXISTS { ... :MANDATES ... }` clauses. Expected: `1 failed, 8 passed` — `test_a_middle_edition_pairs_into_both_adjacent_pairs` fails because the B→C POST returns 409 on the strength of the A→B verdict, prescribing the destruction of a verdict from a different diff. Revert.
  8. In `_work`, stop reading the settled list: replace the `settled = read_settled(...)` call with `settled = []`. Expected: `1 failed, 8 passed` — `test_a_distinct_pair_stays_reachable_after_a_rediff` fails on `body["settled"] == [...]`, which is the assertion that a settled pair stays visible after the edge that proposed it is gone. Revert.
  9. In `_CANDIDATES_TEMPLATE`, delete both `AND EXISTS { MATCH (to_version)-[:MANDATES]->(old_taker) }` and `AND EXISTS { MATCH (from_version)-[:MANDATES]->(new_taker) }` from the two taker `OPTIONAL MATCH`es. Expected: `1 failed, 8 passed` — `test_a_taker_from_a_third_edition_does_not_appear_in_taken_by` fails on `assert len(declined) == 1` with 2, because the unscoped join matches `FUNDS_LATER` in `pol@2022` as well as `FUNDS_OLD` in `pol@2018` and Cypher returns the declined pair once per taker. Revert.

#### The client half — the queue and its verdicts, reachable from the browser

The route is not finished until the browser can reach it, and in this repo that is a test rather than a sentiment: `test_the_browser_can_reach_every_route_the_server_declares` is red from the moment `main.py` registers the router until these two functions exist. The screen that uses them comes later; the functions ship here.

- [ ] **Write the failing test.** In `frontend/src/api/client.test.ts`, add `getPairingQueue` and `recordPairing` to the import list at lines 2–18 (alphabetical within the existing loose ordering — `getPairingQueue` after `getGraph`, `recordPairing` after `recordVerdict`), then append this block at the end of the file:

```ts
// A pairing verdict is canonical in the way a review verdict is — a thing a
// person did, which no rebuild may discard — so it carries the same obligation
// the review verdict does: the ADR-018 header the dev proxy injects the bearer
// token for. Posted without it the request 401s and nothing is recorded.
describe('pairings', () => {
  it('asks for one edition pair, naming both ends', async () => {
    const fetchMock = mockJson({
      items: [], settled: [], pairings_unapplied: 0, pending: 0,
    })
    vi.stubGlobal('fetch', fetchMock)

    await getPairingQueue('dodd-5000-01@2018-08-31', 'dodd-5000-01@2022-07-28')

    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('/api/pairings/queue?')
    // Both ends, and not merely one: the route 400s a from/to that is not
    // older→newer, so a call that dropped an end would be a queue asking the
    // wrong question rather than a request that failed.
    expect(url).toContain('from_version_id=dodd-5000-01%402018-08-31')
    expect(url).toContain('to_version_id=dodd-5000-01%402022-07-28')
    expect(url).not.toContain('limit=')
  })

  it('passes a limit when the caller sets one', async () => {
    const fetchMock = mockJson({
      items: [], settled: [], pairings_unapplied: 0, pending: 0,
    })
    vi.stubGlobal('fetch', fetchMock)

    await getPairingQueue('a', 'b', 25)

    expect(fetchMock.mock.calls[0][0] as string).toContain('limit=25')
  })

  it('posts a verdict older-first, with the dev-proxy header', async () => {
    const fetchMock = mockJson({
      old_id: 'old-1', new_id: 'new-1', verdict: 'paired', actor: 'tester',
    })
    vi.stubGlobal('fetch', fetchMock)

    const settled = await recordPairing('old-1', 'new-1', 'paired', 'Same duty, reworded.')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/pairings/old-1/new-1')
    expect(init.method).toBe('POST')
    expect(init.headers).toMatchObject({ 'x-policy-grapher-ui': '1' })
    expect(JSON.parse(init.body)).toEqual({
      verdict: 'paired',
      rationale: 'Same duty, reworded.',
    })
    expect(settled.verdict).toBe('paired')
  })

  it('escapes obligation ids into the verdict path', async () => {
    // An obligation id is a hex digest today, but the path is built from data
    // and `recordVerdict` learned this the same way.
    const fetchMock = mockJson({ old_id: 'a/b', new_id: 'c d', verdict: 'distinct', actor: 't' })
    vi.stubGlobal('fetch', fetchMock)

    await recordPairing('a/b', 'c d', 'distinct')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/pairings/a%2Fb/c%20d')
  })

  it('throws ApiError on the reversed-pair 400 rather than resolving empty', async () => {
    // An empty queue reads as "nothing to pair between these editions", which is
    // the one answer a reversed request must not be able to produce.
    vi.stubGlobal(
      'fetch',
      mockJson({ detail: 'from_version_id must be the older edition.' }, 400),
    )

    await expect(getPairingQueue('newer', 'older')).rejects.toBeInstanceOf(ApiError)
  })
})
```

- [ ] **Run it and read the failure.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/api/client.test.ts` — expected `Tests  5 failed | 22 passed (27)`, each new test failing with `TypeError: (0 , getPairingQueue) is not a function` (and `(0 , recordPairing) is not a function` for the last three). Vite's SSR transform resolves a missing *named* export to `undefined` rather than refusing to load the module, so the failure lands at the call site rather than at the import — `tsc -b`, which `npm test` runs, is what turns it into an import error.

- [ ] **Write the minimal implementation.** Insert into `frontend/src/api/types.ts` immediately after `export type Verdict = 'approve' | 'reject'` (line 172) — beside the review types, because the two vocabularies are told apart by being read next to each other:

```ts
/** What a reviewer may say about two clauses of one instrument.
 *
 *  Not `Verdict`'s vocabulary, deliberately. `approve`/`reject` answers "does our
 *  clause discharge that duty?"; this answers "is the newer clause the older one
 *  reworded?" — a different question, a different canonical node, and a shared
 *  word would let one screen's copy drift into describing the other's. */
export type PairingVerdict = 'paired' | 'distinct'

/** One pair the diff had an opinion about, and the opinion.
 *
 *  `outcome` is the first rule that fired, in the diff's code order —
 *  `auto_paired`, `partner_taken`, `contested`, `below_threshold` — not four
 *  disjoint conditions: `partner_taken` is contained in `contested`, and the
 *  labels record precedence. `taken_by` names zero to two obligations that
 *  already consumed an end of this pair, which is what makes `partner_taken`
 *  the actionable label rather than merely the narrower one. */
export interface PairingCandidate {
  old: ObligationCitation
  new: ObligationCitation
  confidence: number
  rationale: string
  outcome: string
  taken_by: string[]
}

/** A pair a person has already ruled on. Carries ids rather than statements: it
 *  is listed so a verdict stays reversible, and a settled pair is deliberately
 *  not re-recorded as a candidate — a candidate edge re-asking a settled question
 *  would put it straight back in the queue. */
export interface PairingSettled {
  old_id: string
  new_id: string
  verdict: string
  actor: string
}

export interface PairingQueue {
  items: PairingCandidate[]
  settled: PairingSettled[]
  /** Recorded pairings this diff could not apply, because pass 1 matched one of
   *  the clauses — it exists unchanged in both editions, so the "reworded" claim
   *  has nothing to attach to. Counted, never dropped: the decision is still
   *  recorded and the screen has to say it did not take effect. */
  pairings_unapplied: number
  /** Candidates in the graph, not rows in `items`. The queue is capped
   *  server-side, and the review queue read "Proposal 1 of 50" over 119 waiting
   *  because nothing distinguished the page from the backlog. */
  pending: number
}
```

  Then in `frontend/src/api/client.ts`, add `PairingQueue`, `PairingSettled` and `PairingVerdict` to the type import at lines 1–19 (alphabetically, between `ObligationsOut` and `QueryResult`), and append after `recordVerdict` (which ends at line 228):

```ts
// The queue runs the diff itself, exactly as `GET /triage` does — a queue reading
// only what a Triage visit happened to write would be empty for any edition pair
// nobody had opened, and a verdict would take effect the next time someone loaded
// that screen. Both ends are required: the route 400s a from/to that is not
// older→newer by the corpus's own ordering, which is what stops a reversed pair
// serving a reviewer a queue whose question is upside down.
export function getPairingQueue(
  fromVersionId: string,
  toVersionId: string,
  limit?: number,
): Promise<PairingQueue> {
  const params = new URLSearchParams({
    from_version_id: fromVersionId,
    to_version_id: toVersionId,
  })
  if (limit !== undefined) params.set('limit', String(limit))
  return request<PairingQueue>(`/pairings/queue?${params.toString()}`)
}

// A write, and therefore dependent on the ADR-018 header that `request` adds.
// Ordered older-first in the path because the record's key is a directional hash
// of the two ids: a pair sent the other way round would key to a second decision
// beside the first rather than replacing it.
export function recordPairing(
  oldId: string,
  newId: string,
  verdict: PairingVerdict,
  rationale = '',
): Promise<PairingSettled> {
  return request<PairingSettled>(
    `/pairings/${encodeURIComponent(oldId)}/${encodeURIComponent(newId)}`,
    { method: 'POST', body: JSON.stringify({ verdict, rationale }) },
  )
}
```

- [ ] **Run and confirm green.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/api/client.test.ts` — expected `Test Files  1 passed (1)` and `Tests  27 passed (27)` (22 existing + 5 new). Then the whole gate, which is what typechecks the new types against every consumer: `cd /home/rhagan/policy_grapher/frontend && npm test -- src/api/client.test.ts` — expected eslint silent, `tsc -b` silent, `Tests  27 passed (27)`.

- [ ] **THE MUTATION CHECK (frontend — runnable here).** In `client.ts::getPairingQueue`, delete the line `from_version_id: fromVersionId,` from the `URLSearchParams` literal, leaving `to_version_id` alone — a queue that names one end only, which the route's 400 could never catch because it would never see the pair. Run `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/api/client.test.ts` — expected `Tests  1 failed | 26 passed (27)`, the failure in `pairings > asks for one edition pair, naming both ends` reading `AssertionError: expected '/api/pairings/queue?to_version_id=dodd-5000-01%402022-07-28' to contain 'from_version_id=dodd-5000-01%402018-08-31'`. Restore the line and re-run: `Tests  27 passed (27)`.

- [ ] **Close the red this task opened.** `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_routers.py`

  Expected: `7 passed, 1 error` — `test_the_browser_can_reach_every_route_the_server_declares` is green again now that `client.ts` models `/pairings/queue` and `/pairings/{}/{}`, and the one error is the environmental `test_health_still_serves_through_the_router` (`DockerException`), exactly as it was before this task began. The task ends green.

- [ ] **Commit:**

  `git add backend/src/policy_grapher/models.py backend/src/policy_grapher/routers/pairings.py backend/src/policy_grapher/main.py backend/tests/test_pairings.py frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts`

  `git commit -m "feat: a pairing queue and verdicts for the pairs the diff declines"`

---

### Task 11: `TriageCitationOut` gains `version_id`

**Files:**
- Modify: `backend/src/policy_grapher/models.py` (`TriageCitationOut`, lines 260–269 at plan time — after Task 10's insertion the class sits lower; anchor by content)
- Modify: `backend/src/policy_grapher/changes/propagate.py` (the `RETURN` of `_TRIAGE_TEMPLATE` at 84–99, `TriageRow` at 140–158, the `TriageRow` construction in `triage()` at 195–214)
- Modify: `backend/src/policy_grapher/routers/triage.py` (the two `TriageCitationOut` constructors at 131–144)
- Modify: `frontend/src/api/types.ts` (`TriageCitation`, lines 174–180)
- Modify: `frontend/src/views/Triage.tsx` (the `Citation` component, lines 11–21)
- Modify: `frontend/src/views/Triage.test.tsx` (the `triage` fixture's two citation objects, ~lines 71–85 — forced, because `npm test` runs `tsc -b` and the fixture is typed `TriageOut` — and one new test in the `describe('Triage', …)` block)
- Test: `backend/tests/test_triage.py` (`test_the_route_answers_with_ranked_rows_and_both_citations`, lines 419–446)

The screen is on this list because the spec puts it there: §8 names `frontend/src/api/types.ts` as a site "**if the field is shown, which is the point of adding it**". A `version_id` carried to the browser and never printed leaves a reviewer reading two clauses from two editions of one instrument under the same document name on both sides — the defect the field exists to close, and the one `ObligationCitationOut.version_id` already closed on Review.

**Interfaces:**
- Consumes: the existing `TRIAGE` bindings `our_version` (`propagate.py:65`) and `higher_version` (`propagate.py:67`); `TriageCitationOut` (`models.py:260`); `TriageRow`/`triage()` (`propagate.py`); `Citation` and the `TriageCitation` type in `frontend/src/views/Triage.tsx`.
- Produces: `TriageCitationOut.version_id: str` (required); `TriageRow.our_version_id: str` and `TriageRow.higher_version_id: str`; `TRIAGE` result aliases `our_version_id`/`higher_version_id`; TS `TriageCitation.version_id: string`, printed by `Citation` — anything later rendering a triage citation may rely on these.

- [ ] **Write the failing test.** In `backend/tests/test_triage.py`, replace `test_the_route_answers_with_ranked_rows_and_both_citations` (lines 419–446) with:

```python
@pytest.mark.integration
def test_the_route_answers_with_ranked_rows_and_both_citations(triage_client):
    """Nothing in the response is unsourced — and since the sprint-12
    walkthrough, "sourced" includes the edition. A triage row's higher side
    comes from a diff of two editions of one instrument, so the document name
    alone cannot say which edition a quoted clause is from; both citations
    carry `version_id`, the same reasoning `ObligationCitationOut` and Ask's
    `CitationOut` already record."""
    response = triage_client.get(
        "/triage", params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["from_version_id"] == "higher-v1"
    assert body["to_version_id"] == "higher-v2"
    assert body["total_changes"] == 1
    assert body["unlinked_changes"] == 0

    row = body["rows"][0]
    assert row["kind"] == "MODIFIED"
    assert row["previous_statement"] == HIGHER_OLD
    assert row["ours"] == {
        "obligation_id": row["ours"]["obligation_id"],
        "statement": OURS,
        "document": "ORG 1.0",
        "version_id": "ours-v1",
        "section_path": ["2.4"],
        "page": 1,
    }
    assert row["higher"]["document"] == "DoDI 5000.88"
    assert row["higher"]["version_id"] == "higher-v2"
    assert row["higher"]["statement"] == HIGHER_NEW
    assert row["higher"]["section_path"] == ["3.2"]
```

  The two sides deliberately assert *different* edition ids — `ours-v1` against `higher-v2` — so a query that crossed the aliases cannot pass.

- [ ] **Run the collection check** (integration test; the merge gate executes it):

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q`

  Expected: `tests/test_triage.py: 24`, no errors. (The file holds 23 today; Task 5 added the `pairings_unapplied` triage test before this task, and this step replaces a test rather than adding one.) The failing state at the merge gate: `AssertionError` on the `row["ours"] == {...}` dict comparison — the response has no `"version_id"` key.

- [ ] **Give the model the field.** In `models.py`, replace `TriageCitationOut` with:

```python
class TriageCitationOut(BaseModel):
    """One side of a triage row, sourced. Nothing in a triage response is
    unattributed: a row naming a policy without saying which passage of it is
    affected would send a reviewer hunting.

    `version_id` is part of "sourced": the higher side comes from a diff of two
    editions of one instrument, so the document name alone matches a clause in
    each of them — the reasoning `ObligationCitationOut` and Ask's `CitationOut`
    already record, and it binds here because the two editions are on screen at
    once by construction."""

    obligation_id: str
    statement: str
    document: str
    version_id: str
    section_path: list[str]
    page: int
```

- [ ] **Return the ids from the traversal.** In `changes/propagate.py`, the `RETURN` of `_TRIAGE_TEMPLATE` (lines 84–99) becomes — the two `version_id` lines are the additions, read off the `our_version`/`higher_version` bindings that already exist at lines 65 and 67:

```
RETURN c.change_id          AS change_id,
       c.kind               AS kind,
       c.statement          AS higher_statement,
       c.previous_statement AS previous_statement,
       c.summary            AS summary,
       higher.modality      AS modality,
       higher.obligation_id AS higher_obligation_id,
       higher_chunk.section_path AS higher_section_path,
       higher_chunk.page    AS higher_page,
       higher_document.name AS higher_document,
       higher_version.version_id AS higher_version_id,
       ours.obligation_id   AS our_obligation_id,
       ours.statement       AS our_statement,
       our_chunk.section_path AS our_section_path,
       our_chunk.page       AS our_page,
       our_version.version_id AS our_version_id,
       document.name        AS document,
       document.slug        AS document_slug
```

- [ ] **Carry them through `TriageRow`.** The dataclass (`propagate.py:140-158`) becomes — frozen with no defaults, so the missing kwargs below would be a `TypeError` before anything else, which is why this and the next step land together:

```python
@dataclass(frozen=True)
class TriageRow:
    change_id: str
    kind: str
    score: float
    document: str
    document_slug: str
    our_obligation_id: str
    our_statement: str
    our_section_path: list[str]
    our_page: int
    our_version_id: str
    higher_obligation_id: str
    higher_statement: str
    previous_statement: str | None
    higher_section_path: list[str]
    higher_page: int
    higher_document: str
    higher_version_id: str
    modality: str
    summary: str
```

- [ ] **Construct them in `triage()`.** The `TriageRow(...)` construction (`propagate.py:196-214`) gains two lines; the full constructor:

```python
        TriageRow(
            change_id=record["change_id"],
            kind=record["kind"],
            score=score(record["kind"], record["modality"]),
            document=record["document"],
            document_slug=record["document_slug"],
            our_obligation_id=record["our_obligation_id"],
            our_statement=record["our_statement"],
            our_section_path=record["our_section_path"],
            our_page=record["our_page"],
            our_version_id=record["our_version_id"],
            higher_obligation_id=record["higher_obligation_id"],
            higher_statement=record["higher_statement"],
            previous_statement=record["previous_statement"],
            higher_section_path=record["higher_section_path"],
            higher_page=record["higher_page"],
            higher_document=record["higher_document"],
            higher_version_id=record["higher_version_id"],
            modality=record["modality"],
            summary=record["summary"],
        )
```

- [ ] **Thread them into the response.** In `routers/triage.py` the two citation constructors (lines 131–144) become:

```python
                ours=TriageCitationOut(
                    obligation_id=row.our_obligation_id,
                    statement=row.our_statement,
                    document=row.document,
                    version_id=row.our_version_id,
                    section_path=row.our_section_path,
                    page=row.our_page,
                ),
                higher=TriageCitationOut(
                    obligation_id=row.higher_obligation_id,
                    statement=row.higher_statement,
                    document=row.higher_document,
                    version_id=row.higher_version_id,
                    section_path=row.higher_section_path,
                    page=row.higher_page,
                ),
```

- [ ] **Mirror the type on the frontend.** In `frontend/src/api/types.ts`, `TriageCitation` (lines 174–180) becomes:

```ts
export interface TriageCitation {
  obligation_id: string
  statement: string
  document: string
  /** Which edition the clause is in. Triage compares two editions of one
   *  instrument by construction, so a citation without the edition prints the
   *  same document name on both sides — `ObligationCitation.version_id`'s
   *  reasoning, binding at least as hard here. */
  version_id: string
  section_path: string[]
  page: number
}
```

  and in `frontend/src/views/Triage.test.tsx` the fixture's two citations gain the field (`tsc -b` runs inside `npm test`, so the typed fixture must carry it):

```ts
      ours: {
        obligation_id: 'ours-1',
        statement: 'The Program Manager shall document the strategy.',
        document: 'ORG 1.0',
        version_id: 'org@2019-06-01',
        section_path: ['2', '2.4'],
        page: 7,
      },
      higher: {
        obligation_id: 'higher-1',
        statement: 'Components shall document the cybersecurity strategy annually.',
        document: 'DoDI 5000.88',
        version_id: 'dodi-5000-88@2020-11-18',
        section_path: ['3', '3.2'],
        page: 12,
      },
```

  The two sides carry *different* editions for the backend test's reason, and one of them names a different instrument entirely: the row is a comparison between our clause and a higher-level one, and a screen that printed one edition twice would be the defect wearing the fix's clothes.

- [ ] **Write the failing frontend test.** In `frontend/src/views/Triage.test.tsx`, insert inside the `describe('Triage', …)` block, immediately before `'shows what the clause used to say, so the change is visible'`:

```tsx
  it('names the edition each quoted clause is from', async () => {
    // Triage puts two editions of one instrument on screen at once, so the
    // document name alone matches a clause in either of them. This is
    // `ObligationCitation.version_id`'s reasoning arriving on the screen that
    // needs it most — the field was carried to the browser to be read.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/org@2019-06-01/)).toBeInTheDocument()
    expect(screen.getByText(/dodi-5000-88@2020-11-18/)).toBeInTheDocument()
  })
```

  Run it: `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Triage.test.tsx`

  Expected: `Tests  1 failed | 15 passed (16)`, the new test failing with `TestingLibraryElementError: Unable to find an element with the text: /org@2019-06-01/. This could be because the text is broken up by multiple elements…` followed by the printed DOM. Nothing else moves: the fixture's new field is data the screen currently ignores.

- [ ] **Print the edition.** In `frontend/src/views/Triage.tsx`, the `Citation` component (lines 11–21) becomes:

```tsx
function Citation({ heading, of }: { heading: string; of: TriageCitation }) {
  return (
    <div className="pane">
      <h4>{heading}</h4>
      <blockquote>{of.statement}</blockquote>
      <cite>
        {of.document} · <code>{of.version_id}</code> ·{' '}
        {of.section_path.join('/')} · p. {of.page}
      </cite>
    </div>
  )
}
```

  `<code>` rather than bare text, matching how the same screen already prints `result.from_version_id` two paragraphs down: an edition id is a machine identifier a reader types back into a filter, not prose.

- [ ] **Run what can run here.** Backend collection:

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q`

  Expected: `tests/test_triage.py: 24`, no errors. Frontend (runs natively):

  `cd /home/rhagan/policy_grapher/frontend && npm test -- src/views/Triage.test.tsx`

  Expected: eslint silent, `tsc -b` silent (this is what verifies the type change against every consumer), then `Tests  16 passed (16)`. The merge gate runs `.venv/bin/pytest tests/test_triage.py` where Docker exists — no second `-q`, which would suppress the count line — and must report `24 passed`.

- [ ] **Lint the backend files:**

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/models.py src/policy_grapher/changes/propagate.py src/policy_grapher/routers/triage.py tests/test_triage.py`

  Expected: `All checks passed!`

- [ ] **THE MUTATION CHECK (backend).** In `propagate.py`, swap the two new aliases so the query reads `higher_version.version_id AS our_version_id` and `our_version.version_id AS higher_version_id`. Command (merge gate, where Docker exists): `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest "tests/test_triage.py::test_the_route_answers_with_ranked_rows_and_both_citations"`. Expected: `1 failed` — the `row["ours"]` dict comparison fails with `"version_id": "higher-v2"` against the expected `"ours-v1"`; the fixture's two sides carry different editions precisely so this swap cannot pass. In this sandbox, confirm the file still collects (`cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q` → `tests/test_triage.py: 24`). Revert the swap.

- [ ] **THE MUTATION CHECK (frontend — runnable here).** In `Triage.tsx`, restore the original one-line `<cite>` body — `{of.document} · {of.section_path.join('/')} · p. {of.page}` — so the field is fetched, typed, and never printed, which is the state this task exists to leave behind. Command: `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Triage.test.tsx`. Expected: `Tests  1 failed | 15 passed (16)`, the failure being `names the edition each quoted clause is from` with `Unable to find an element with the text: /org@2019-06-01/`. Restore the `<code>` and re-run: `Tests  16 passed (16)`.

- [ ] **Commit:**

  `git add backend/src/policy_grapher/models.py backend/src/policy_grapher/changes/propagate.py backend/src/policy_grapher/routers/triage.py backend/tests/test_triage.py frontend/src/api/types.ts frontend/src/views/Triage.tsx frontend/src/views/Triage.test.tsx`

  `git commit -m "feat: a triage citation names the edition it quotes"`

---

### Task 12: The export carries the second canonical node

**Files:**
- Modify: `backend/src/policy_grapher/export.py` (insert the category after `"decisions"`, i.e. after line 93, before `"changes"`)
- Modify: `frontend/src/views/Reset.tsx` (the intro paragraph at 85–90, the confirm-dialog paragraph at 122–127)
- Test: `backend/tests/test_export.py` (imports at 11–17, `CATEGORIES` at 19–27, new test appended after line 136 — anchor by content, earlier tasks shift line numbers)
- Test: `frontend/src/views/Reset.test.tsx` (new test in the `Reset` describe block)

**Interfaces:**
- Consumes (from the `links/pairing.py` task): `record_pairing(tx, *, old_id, new_id, verdict, actor, rationale) -> None` and `pairing_key(old_id, new_id) -> str`; the `:PairingDecision` properties §4 names — `old_obligation_id`, `new_obligation_id`, `verdict`, `actor`, `rationale`, `at`, `key`.
- Produces: the export category `"pairing_decisions"` in `export_graph`'s return, carrying `key`/`old_obligation_id`/`new_obligation_id`/`verdict`/`actor`/`rationale`/`at` — the shape any future importer, and the Reset screen's promise, rely on.

- [ ] **Write the failing backend test.** In `backend/tests/test_export.py`: extend the imports (lines 11–17) with the pairing module —

```python
import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.links.decisions import decision_key, record_decision
from policy_grapher.links.pairing import pairing_key, record_pairing
from policy_grapher.obligations import write_obligations
```

  extend `CATEGORIES` (lines 18–26) —

```python
CATEGORIES = {
    "documents",
    "versions",
    "chunks",
    "obligations",
    "proposals",
    "decisions",
    "pairing_decisions",
    "changes",
}
```

  and append this test after `test_the_export_carries_the_decisions_a_rebuild_cannot_regenerate`:

```python
@pytest.mark.integration
def test_the_export_carries_the_pairing_decisions_reset_would_destroy(
    client_with_auth,
):
    """The second canonical node. A pairing verdict is a person's judgement
    that one edition's clause is — or is not — another's reworded; Reset
    deletes the only copy, and the screen promises the export is that copy.

    Recorded through `record_pairing`, not CREATEd with literal properties,
    for the reason the `:LinkDecision` test above states: a fixture carrying
    the export query's own column names asserts nothing about the real write
    path, which is exactly how the first decisions category shipped exporting
    a null key, no timestamp, and no rationale."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    with driver.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id="old-a",
            new_id="new-b",
            verdict="paired",
            actor="reviewer",
            rationale="the clause was reworded, not replaced",
        )

    body = client_with_auth.get("/export").json()

    assert len(body["pairing_decisions"]) == 1
    decision = body["pairing_decisions"][0]
    assert decision["key"] == pairing_key("old-a", "new-b")
    assert decision["verdict"] == "paired"
    assert decision["actor"] == "reviewer"
    assert decision["rationale"] == "the clause was reworded, not replaced"
    assert decision["at"], "the timestamp record_pairing writes must survive export"
    assert decision["old_obligation_id"] == "old-a"
    assert decision["new_obligation_id"] == "new-b"
```

- [ ] **Run the collection check** (integration; the merge gate executes it):

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_export.py --collect-only -q`

  Expected: `tests/test_export.py: 5`, no errors. The failing state at the merge gate: the new test and both empty-graph tests fail with `KeyError: 'pairing_decisions'` — the export has no such category yet, and `CATEGORIES` now demands one.

- [ ] **Add the category to `export.py`.** Insert into `QUERIES`, between `"decisions"` and `"changes"`:

```python
    # The second canonical node, exported for the same reason as the first: a
    # `:PairingDecision` is a person's verdict that one edition's clause is —
    # or is not — another's reworded, and Reset deletes the only copy.
    # Property names are the ones `record_pairing` writes — `key`, `at`,
    # `rationale` (links/pairing.py) — read as written, not renamed on the way
    # out; the `decisions` category above already paid for learning that.
    "pairing_decisions": """
        MATCH (decision:PairingDecision)
        RETURN decision.key               AS key,
               decision.old_obligation_id AS old_obligation_id,
               decision.new_obligation_id AS new_obligation_id,
               decision.verdict           AS verdict,
               decision.actor             AS actor,
               decision.rationale         AS rationale,
               toString(decision.at)      AS at
        ORDER BY decision.key
    """,
```

- [ ] **Re-collect and lint:**

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_export.py --collect-only -q` — expected `tests/test_export.py: 5`.

  `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src/policy_grapher/export.py tests/test_export.py` — expected `All checks passed!`. The merge gate runs `.venv/bin/pytest tests/test_export.py` — no second `-q`, which would suppress the count line — and must report `5 passed`.

- [ ] **THE MUTATION CHECK (backend).** In the new category, change `decision.key AS key` to `decision.decision_key AS key` — the exact defect the repaired `decisions` category had, resurrected. Command (merge gate): `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest "tests/test_export.py::test_the_export_carries_the_pairing_decisions_reset_would_destroy"`. Expected: `1 failed` — `assert decision["key"] == pairing_key("old-a", "new-b")` fails with `None` on the left, because nothing writes `decision_key`. In this sandbox, confirm collection stays at 5 (`cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_export.py --collect-only -q` → `tests/test_export.py: 5`). Revert.

- [ ] **Commit the backend half:**

  `git add backend/src/policy_grapher/export.py backend/tests/test_export.py`

  `git commit -m "feat: the export carries pairing decisions, the second canonical node"`

- [ ] **Write the failing frontend test.** In `frontend/src/views/Reset.test.tsx`, append inside the `describe('Reset', ...)` block, after `'reports a failed reset instead of claiming the graph is empty'`:

```tsx
  it('names pairing decisions among what is deleted', async () => {
    // The export gained a `pairing_decisions` category when `:PairingDecision`
    // became the second canonical node. A screen that enumerates what Reset
    // destroys while omitting one of the two records a machine cannot
    // regenerate promises a copy the export was not taking — the exact
    // wrongness the confirm dialog's own comment warns about.
    render(<Reset />)

    expect(screen.getByText(/empties the graph/i)).toHaveTextContent(
      /pairing decisions/i,
    )

    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))

    expect(screen.getByRole('dialog')).toHaveTextContent(/pairing decisions/i)
  })
```

- [ ] **Run it and watch it fail** (frontend tests run natively):

  `cd /home/rhagan/policy_grapher/frontend && npm test -- src/views/Reset.test.tsx`

  Expected failure: the new test fails on its first assertion with `expect(element).toHaveTextContent(/pairing decisions/i)` — the copy does not name them. (eslint and `tsc -b` pass; every other Reset test stays green.)

- [ ] **Update the copy.** In `frontend/src/views/Reset.tsx`, the intro paragraph (lines 85–90) becomes:

```tsx
      <p>
        Empties the graph: every document, edition, chunk, obligation, proposal and
        recorded decision — review verdicts and pairing decisions alike.{' '}
        <strong>There is no undo.</strong> Take a copy first if you might want one —
        the export below is a readable snapshot, not a restore.
      </p>
```

  and the confirm dialog's first paragraph (lines 122–127) becomes:

```tsx
          <p>
            This <strong>cannot be undone</strong>. Every document, edition, chunk,
            obligation, proposal and recorded decision is deleted — review verdicts
            and pairing decisions alike, both of which a rebuild replays and
            therefore cannot bring back once they are gone.
          </p>
```

- [ ] **Run it and watch it pass:**

  `cd /home/rhagan/policy_grapher/frontend && npm test -- src/views/Reset.test.tsx`

  Expected: all Reset tests green, including the new one; `states what is deleted and what survives` still passes (`/cannot be undone/i` and `/vector index/i` are both preserved).

- [ ] **THE MUTATION CHECK (frontend — runnable here).** In `Reset.tsx`, remove `— review verdicts and pairing decisions alike` from the intro paragraph (restore `recorded decision.`). Command: `cd /home/rhagan/policy_grapher/frontend && npm test -- src/views/Reset.test.tsx`. Expected failure: `names pairing decisions among what is deleted` fails on the intro-paragraph assertion. Revert the mutation and re-run to green.

- [ ] **Commit the frontend half:**

  `git add frontend/src/views/Reset.tsx frontend/src/views/Reset.test.tsx`

  `git commit -m "feat: Reset names the pairing decisions the export now carries"`
### Task 13: The pairing screen

**Files:**
- Create `frontend/src/views/Pairings.tsx`
- Create `frontend/src/views/Pairings.test.tsx`
- Modify `frontend/src/routes.tsx` (lines 1-21, whole file)
- Modify `frontend/src/App.test.tsx` (the `vi.mock` block at lines 6-13 and the `ROUTES` table at lines 24-32)

**Interfaces:**

*Consumes (from earlier tasks, exact signatures):*
- From Task 10, in `frontend/src/api/client.ts`: `getPairingQueue(fromVersionId: string, toVersionId: string, limit?: number): Promise<PairingQueue>` and `recordPairing(oldId: string, newId: string, verdict: PairingVerdict, rationale?: string): Promise<PairingSettled>`. They ship with the router rather than here because `backend/tests/test_routers.py::test_the_browser_can_reach_every_route_the_server_declares` is not an integration test: it asserts every registered route is modelled by a literal in `client.ts`, so a router committed without its two client functions leaves that test red across three tasks.
- From Task 10, in `frontend/src/api/types.ts`: `PairingVerdict = 'paired' | 'distinct'`; `PairingCandidate { old: ObligationCitation; new: ObligationCitation; confidence: number; rationale: string; outcome: string; taken_by: string[] }`; `PairingSettled { old_id: string; new_id: string; verdict: string; actor: string }`; `PairingQueue { items: PairingCandidate[]; settled: PairingSettled[]; pairings_unapplied: number; pending: number }`.
- The two routes those functions call, whose behaviour this screen has to render: `GET /pairings/queue?from_version_id&to_version_id&limit` → `PairingQueueOut { items: PairingCandidateOut[]; settled: PairingSettledOut[]; pairings_unapplied: int; pending: int }`, 400 unless `(from, to)` is older→newer by the corpus rule; `POST /pairings/{old_obligation_id}/{new_obligation_id}` with body `PairingVerdictIn { verdict: str; rationale: str = "" }` → `PairingSettledOut { old_id: str; new_id: str; verdict: str; actor: str }`. `outcome` ∈ `auto_paired | partner_taken | contested | below_threshold`.
- Already in the repo: `ObligationCitation` (`types.ts:136-150`), `listDocuments()`, `listVersions(slug)`, `request<T>` and `ApiError` (`client.ts`).

*Produces (what later tasks rely on):*
- `frontend/src/views/Pairings.tsx` default export `Pairings`.
- `routes.tsx`: the `{ to: '/pairings', label: 'Pairings', element: <Pairings /> }` entry, placed between Review and Ask (both before Reset).

---

#### Cycle A — the screen

- [ ] **Write the failing test.** Create `frontend/src/views/Pairings.test.tsx`:

```tsx
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PairingCandidate, PairingQueue } from '../api/types'

const getPairingQueue = vi.fn()
const recordPairing = vi.fn()
const listDocuments = vi.fn()
const listVersions = vi.fn()
vi.mock('../api/client', () => ({
  getPairingQueue: (...args: unknown[]) => getPairingQueue(...args),
  recordPairing: (...args: unknown[]) => recordPairing(...args),
  listDocuments: () => listDocuments(),
  listVersions: (slug: string) => listVersions(slug),
  ApiError: class extends Error {},
}))

import Pairings from './Pairings'

const OLDER = 'dodd-5000-01@2018-08-31'
const NEWER = 'dodd-5000-01@2022-07-28'

const documents = [
  {
    slug: 'dodd-5000-01',
    name: 'DoDD 5000.01',
    is_external: false,
    references: [],
    referenced_by: [],
    version_count: 2,
  },
]

const versions = [
  {
    version_id: OLDER,
    effective_date: '2018-08-31',
    checksum: '65e873',
    source_uri: 'file:///data/samples/500001p_2018.pdf',
    supersedes: null,
  },
  {
    version_id: NEWER,
    effective_date: '2022-07-28',
    checksum: 'a16e39',
    source_uri: 'file:///data/samples/500001p_2022.pdf',
    supersedes: OLDER,
  },
]

const candidate: PairingCandidate = {
  old: {
    obligation_id: 'old-1',
    statement: 'The Director shall notify the Comptroller within 24 hours.',
    modality: 'SHALL',
    document: 'DoDD 5000.01',
    version_id: OLDER,
    section_path: ['3', '3.2'],
    page: 7,
  },
  new: {
    obligation_id: 'new-1',
    statement: 'The Director will inform the Comptroller within one day.',
    modality: 'WILL',
    document: 'DoDD 5000.01',
    version_id: NEWER,
    section_path: ['4', '4.1'],
    page: 9,
  },
  confidence: 0.62,
  rationale: 'They share 62% of the shorter clause (comptroller, director, notify).',
  outcome: 'below_threshold',
  taken_by: [],
}

const takenCandidate: PairingCandidate = {
  ...candidate,
  old: { ...candidate.old, obligation_id: 'old-2', statement: 'Components shall retain records.' },
  new: { ...candidate.new, obligation_id: 'new-2', statement: 'Components will keep records.' },
  confidence: 0.81,
  // Its own sentence, not the spread one: two candidates quoting the same
  // percentage would make every "which pair is this?" assertion ambiguous, and a
  // query that matches two elements fails for a reason unrelated to the screen.
  rationale: 'They share 81% of the shorter clause (components, records, retain).',
  outcome: 'partner_taken',
  taken_by: ['new-9'],
}

const q = (over: Partial<PairingQueue> = {}): PairingQueue => ({
  items: [candidate],
  settled: [],
  pairings_unapplied: 0,
  pending: 1,
  ...over,
})

// A pairing queue is asked between two named editions, so every test has to get
// through the picker before it can assert anything about the queue.
async function choosePair() {
  render(
    <MemoryRouter>
      <Pairings />
    </MemoryRouter>,
  )
  await userEvent.selectOptions(await screen.findByLabelText(/document/i), 'dodd-5000-01')
  // Waiting on the options rather than on the `listVersions` call: the two edition
  // selects render empty and disabled the moment the document picker does, and
  // selecting a value that is not in the list yet is a failure about timing rather
  // than about the screen. `findAll`, because both selects carry the same option.
  await screen.findAllByRole('option', { name: /2018-08-31/ })
  await userEvent.selectOptions(screen.getByLabelText(/older edition/i), OLDER)
  await userEvent.selectOptions(screen.getByLabelText(/newer edition/i), NEWER)
}

beforeEach(() => {
  listDocuments.mockResolvedValue(documents)
  listVersions.mockResolvedValue(versions)
})

afterEach(() => {
  getPairingQueue.mockReset()
  recordPairing.mockReset()
  listDocuments.mockReset()
  listVersions.mockReset()
})

describe('Pairings', () => {
  it('asks the queue for the pair the reviewer chose', async () => {
    getPairingQueue.mockResolvedValue(q())
    await choosePair()

    await waitFor(() => expect(getPairingQueue).toHaveBeenCalledWith(OLDER, NEWER))
  })

  it('shows both clauses, the confidence, the rationale and which rule declined them', async () => {
    // The whole content of the judgement. A reviewer overruling the measure needs
    // to read both statements — the edition ids tell them apart, because a
    // pairing question always prints the same document name twice — and to know
    // which of the diff's four refusals this was.
    getPairingQueue.mockResolvedValue(q({ items: [candidate, takenCandidate], pending: 2 }))
    await choosePair()

    expect(await screen.findByText(candidate.old.statement)).toBeInTheDocument()
    expect(screen.getByText(candidate.new.statement)).toBeInTheDocument()
    expect(screen.getByText(/62%/)).toBeInTheDocument()
    expect(screen.getByText(/share 62% of the shorter clause/)).toBeInTheDocument()
    expect(screen.getAllByText(OLDER).length).toBeGreaterThan(0)
    expect(screen.getAllByText(NEWER).length).toBeGreaterThan(0)
    // Grouped by outcome, and `partner_taken` names the winner: an `auto_paired`
    // pair already holds one of these clauses, and that is the pairing the
    // reviewer has to mark distinct first.
    expect(screen.getByRole('heading', { name: /took one of these clauses/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /below the pairing bar/i })).toBeInTheDocument()
    expect(screen.getByText(/new-9/)).toBeInTheDocument()
  })

  it('lists the pairs already settled, with the verdict and who recorded it', async () => {
    // A settled pair is not re-recorded as a candidate, so this list is the only
    // route back to a verdict somebody wants to reverse.
    getPairingQueue.mockResolvedValue(
      q({
        items: [],
        settled: [{ old_id: 'old-7', new_id: 'new-7', verdict: 'distinct', actor: 'tester' }],
        pending: 0,
      }),
    )
    await choosePair()

    const settled = await screen.findByRole('list')
    expect(within(settled).getByText(/old-7/)).toBeInTheDocument()
    expect(within(settled).getByText(/distinct/)).toBeInTheDocument()
    expect(within(settled).getByText(/tester/)).toBeInTheDocument()
  })

  it('records a paired verdict older-first and reloads the queue', async () => {
    getPairingQueue
      .mockResolvedValueOnce(q())
      .mockResolvedValue(q({ items: [], pending: 0 }))
    recordPairing.mockResolvedValue({
      old_id: 'old-1', new_id: 'new-1', verdict: 'paired', actor: 'tester',
    })
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.type(screen.getByLabelText(/reason/i), 'Same duty, reworded.')
    await userEvent.click(screen.getByRole('button', { name: /^paired$/i }))

    expect(recordPairing).toHaveBeenCalledWith(
      'old-1',
      'new-1',
      'paired',
      'Same duty, reworded.',
    )
    // Reloaded, not merely posted: the verdict changes what the diff produces, so
    // a screen that kept showing the pre-verdict queue would be showing a
    // question that has been answered.
    expect(await screen.findByText(/nothing is waiting to be paired/i)).toBeInTheDocument()
  })

  it('records a distinct verdict on the same pair', async () => {
    getPairingQueue.mockResolvedValue(q())
    recordPairing.mockResolvedValue({
      old_id: 'old-1', new_id: 'new-1', verdict: 'distinct', actor: 'tester',
    })
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.click(screen.getByRole('button', { name: /^distinct$/i }))

    expect(recordPairing).toHaveBeenCalledWith('old-1', 'new-1', 'distinct', '')
  })

  it('surfaces the reversed-pair 400 instead of showing an empty queue', async () => {
    // The route refuses a from/to that is not older→newer, and an unreported
    // refusal reads as "nothing to pair between these editions" — a false
    // all-clear over a question that was never asked.
    getPairingQueue.mockRejectedValue(
      new Error(
        "from_version_id 'dodd-5000-01@2022-07-28' is not older than "
        + "to_version_id 'dodd-5000-01@2018-08-31'.",
      ),
    )
    await choosePair()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not load the pairing queue/i)
    expect(alert).toHaveTextContent(/is not older than/i)
    expect(screen.queryByText(/nothing is waiting to be paired/i)).not.toBeInTheDocument()
  })

  it('does not report a queue that failed to load as a verdict that failed to record', async () => {
    // Review shipped one shared error state and told readers their decision had
    // not been saved about a decision they had not made.
    getPairingQueue.mockRejectedValue(new Error('backend down'))
    await choosePair()

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i)
    expect(screen.queryByText(/could not record that/i)).not.toBeInTheDocument()
  })

  it('surfaces a failure to record a verdict rather than looking successful', async () => {
    getPairingQueue.mockResolvedValue(q())
    recordPairing.mockRejectedValue(new Error('409: already paired with new-9'))
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.click(screen.getByRole('button', { name: /^paired$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/already paired with new-9/i)
  })

  it('says a recorded pairing could not be applied rather than losing it', async () => {
    getPairingQueue.mockResolvedValue(q({ items: [], pending: 0, pairings_unapplied: 1 }))
    await choosePair()

    expect(await screen.findByText(/1 recorded pairing/i)).toBeInTheDocument()
  })

  it('says a corpus with no two-edition document cannot be paired yet', async () => {
    // The blank-that-reads-as-broken ADR-019 forbids: a picker with nothing in it
    // and no sentence saying why.
    listDocuments.mockResolvedValue([{ ...documents[0], version_count: 1 }])
    render(
      <MemoryRouter>
        <Pairings />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('status')).toHaveTextContent(/no document has two editions/i)
    expect(getPairingQueue).not.toHaveBeenCalled()
  })
})
```

- [ ] **Run it and read the failure.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Pairings.test.tsx` — expected `Failed Suites 1`: `Error: Failed to resolve import "./Pairings" from "src/views/Pairings.test.tsx". Does the file exist?` (`Plugin: vite:import-analysis`). No test runs, which is the correct failing state for a screen that does not exist yet.

- [ ] **Write the minimal implementation.** Create `frontend/src/views/Pairings.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react'
import {
  getPairingQueue,
  listDocuments,
  listVersions,
  recordPairing,
} from '../api/client'
import EmptyState from './EmptyState'
import type {
  DocumentOut,
  DocumentVersionOut,
  ObligationCitation,
  PairingCandidate,
  PairingQueue,
  PairingVerdict,
} from '../api/types'

// The four outcomes in the order the diff's rules fire. They are not four
// disjoint conditions: every pair declined because a partner was taken also
// satisfies the margin rule, so `partner_taken` is contained in `contested` and
// the labels record precedence. They stay two headings because `partner_taken`
// is the actionable one — a winner exists, and it is named.
const OUTCOME_ORDER = ['auto_paired', 'partner_taken', 'contested', 'below_threshold']

const OUTCOME_LABEL: Record<string, string> = {
  auto_paired: 'Paired by the diff',
  partner_taken: 'A higher-scoring pair took one of these clauses',
  contested: 'Two candidates too close to separate',
  below_threshold: 'Below the pairing bar',
}

const OUTCOME_BLURB: Record<string, string> = {
  auto_paired:
    'The wording pass made this pair and nobody reviewed it. Mark it distinct to undo it.',
  partner_taken:
    'One end of this pair is already held by a pair that scored higher. Mark that pairing distinct first if this one is the right answer.',
  contested:
    'Another candidate scored within a hair of this one, so the diff declined both rather than pick whichever came first.',
  below_threshold:
    'Scored, but under the confidence the diff pairs at, so it never entered the pairing loop.',
}

function rank(outcome: string): number {
  const at = OUTCOME_ORDER.indexOf(outcome)
  // An outcome this screen has no heading for still renders, last and under its
  // own raw name. A candidate dropped because its label is unfamiliar is a pair
  // nobody can reach, which is the failure this whole screen exists to end.
  return at === -1 ? OUTCOME_ORDER.length : at
}

function byOutcome(items: PairingCandidate[]): [string, PairingCandidate[]][] {
  const groups = new Map<string, PairingCandidate[]>()
  for (const item of items) {
    const found = groups.get(item.outcome)
    if (found) found.push(item)
    else groups.set(item.outcome, [item])
  }
  return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b))
}

function pairKey(item: PairingCandidate): string {
  return `${item.old.obligation_id}|${item.new.obligation_id}`
}

/** One clause of the pair, sourced.
 *
 *  No document name: both sides are editions of one instrument, so it is the
 *  same string twice and settles nothing. The edition id is the distinction
 *  being made here, exactly as it is on Review — where printing the document
 *  alone left a reviewer unable to tell the 2022 text from the 2018. */
function Side({ heading, of }: { heading: string; of: ObligationCitation }) {
  return (
    <section className="pane">
      <h3>{heading}</h3>
      <blockquote>{of.statement}</blockquote>
      <p>
        <cite className="citation">
          <code>{of.version_id}</code>
          <span>{of.section_path.join('/')}</span>
          <span>p. {of.page}</span>
        </cite>
      </p>
    </section>
  )
}

export default function Pairings() {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)
  const [slug, setSlug] = useState('')
  const [versions, setVersions] = useState<DocumentVersionOut[]>([])
  const [fromVersionId, setFromVersionId] = useState('')
  const [toVersionId, setToVersionId] = useState('')
  const [queue, setQueue] = useState<PairingQueue | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Keyed by pair, not one box for the screen. Every candidate is on screen at
  // once here, and a single shared field files the reason typed against one pair
  // with whichever pair is clicked next — the defect Review's walkthrough found,
  // where a verdict is permanent and replayed on every rebuild.
  const [rationales, setRationales] = useState<Record<string, string>>({})
  const [pending, setPending] = useState(false)

  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((found) => {
        if (cancelled) return
        // A pairing question is asked between two editions of one instrument, so
        // a document with one edition has nothing to ask. Offering it produces
        // two identical pickers and an explanation nobody wrote.
        setDocuments(found.filter((d) => d.version_count > 1))
        setCorpusEmpty(found.length === 0)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoadError(
            cause instanceof Error ? cause.message : 'Failed to load documents.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!slug) return
    let cancelled = false
    listVersions(slug)
      .then((found) => {
        if (!cancelled) setVersions(found)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoadError(
            cause instanceof Error ? cause.message : 'Failed to load editions.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  // Two failures, two states. A queue that failed to *load* — a stopped backend,
  // or the 400 a reversed pair earns — must not be reported under "could not
  // record that", about a verdict nobody cast.
  const load = useCallback(async () => {
    if (!fromVersionId || !toVersionId || fromVersionId === toVersionId) return
    try {
      const found = await getPairingQueue(fromVersionId, toVersionId)
      setQueue(found)
      setLoadError(null)
    } catch (cause: unknown) {
      // Cleared, not left standing: a stale queue under an error banner is the
      // previous pair's question wearing this pair's heading.
      setQueue(null)
      setLoadError(
        cause instanceof Error ? cause.message : 'Failed to load the pairing queue.',
      )
    }
  }, [fromVersionId, toVersionId])

  useEffect(() => {
    void load()
  }, [load])

  // Clearing what a choice invalidates belongs in the handler that made the
  // choice. A setState in an effect body is the cascading render the lint rule
  // forbids, and it has produced an intermittent failure in this suite before.
  function chooseDocument(next: string) {
    setSlug(next)
    setVersions([])
    setFromVersionId('')
    setToVersionId('')
    setQueue(null)
    setLoadError(null)
    setError(null)
  }

  function chooseEdition(side: 'from' | 'to', next: string) {
    if (side === 'from') setFromVersionId(next)
    else setToVersionId(next)
    setQueue(null)
    setLoadError(null)
    setError(null)
  }

  async function settle(item: PairingCandidate, verdict: PairingVerdict) {
    // `pending` gates every button for the whole round trip. A re-verdict
    // replaces rather than appends, so a double-click would silently overwrite
    // one judgement with whichever button was pressed last.
    setPending(true)
    setError(null)
    const key = pairKey(item)
    try {
      await recordPairing(
        item.old.obligation_id,
        item.new.obligation_id,
        verdict,
        rationales[key] ?? '',
      )
      setRationales((current) => {
        const next = { ...current }
        delete next[key]
        return next
      })
      // The verdict changes what the diff produces, so the queue is re-read
      // rather than edited in place: this screen must not be the one place that
      // believes something the graph does not.
      await load()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Failed to record the verdict.')
    } finally {
      setPending(false)
    }
  }

  const noPairableDocuments = corpusEmpty === false && documents.length === 0

  return (
    <div className="view">
      <h1>Pairings</h1>
      <p>
        Between two editions of one instrument the diff pairs what it can and
        declines the rest. This is where a person settles what it declined, and
        undoes what it guessed. Whether one of our clauses discharges another
        document&rsquo;s duty is a different question, and it is Review&rsquo;s.
      </p>

      {corpusEmpty ? (
        <EmptyState lead="There is nothing to pair." />
      ) : noPairableDocuments ? (
        <div role="status">
          <p>
            <strong>No document has two editions yet.</strong>
          </p>
          <p>
            A pairing question is asked between two editions of one instrument, so
            it needs both sides. Ingest a second edition of a document that
            already has one.
          </p>
        </div>
      ) : (
        <>
          <label>
            Document{' '}
            <select value={slug} onChange={(event) => chooseDocument(event.target.value)}>
              <option value="">Choose a document…</option>
              {documents.map((found) => (
                <option key={found.slug} value={found.slug}>
                  {found.name}
                </option>
              ))}
            </select>
          </label>{' '}
          <label>
            Older edition{' '}
            <select
              value={fromVersionId}
              onChange={(event) => chooseEdition('from', event.target.value)}
              disabled={versions.length === 0}
            >
              <option value="">Choose an edition…</option>
              {versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.effective_date
                    ? `${version.effective_date} (${version.version_id})`
                    : version.version_id}
                </option>
              ))}
            </select>
          </label>{' '}
          <label>
            Newer edition{' '}
            <select
              value={toVersionId}
              onChange={(event) => chooseEdition('to', event.target.value)}
              disabled={versions.length === 0}
            >
              <option value="">Choose an edition…</option>
              {versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.effective_date
                    ? `${version.effective_date} (${version.version_id})`
                    : version.version_id}
                </option>
              ))}
            </select>
          </label>

          {/* The screen does not work out for itself which edition is older. The
              corpus orders editions by effective date, then ingestion time, then
              version id — and ingestion time is not in this payload at all, so a
              guess here would either duplicate a rule that can drift or refuse a
              pair the route would have accepted. Named backwards, the route
              answers 400 and the banner below says so. */}

          {fromVersionId !== '' && fromVersionId === toVersionId && (
            <p>
              Those are the same edition. A pairing question runs between two of
              them.
            </p>
          )}

          {loadError && (
            <div role="alert">Could not load the pairing queue: {loadError}</div>
          )}
          {error && <div role="alert">Could not record that: {error}</div>}

          {queue && (
            <section>
              <p>
                {queue.items.length} candidate{queue.items.length === 1 ? '' : 's'}
                {queue.pending > queue.items.length && (
                  <> shown, {queue.pending} waiting</>
                )}
                . {queue.settled.length} already settled.
              </p>

              {queue.pairings_unapplied > 0 && (
                <p>
                  {queue.pairings_unapplied} recorded pairing
                  {queue.pairings_unapplied === 1 ? '' : 's'} could not be applied
                  to this diff: the clause it names is matched unchanged in both
                  editions, so there is no rewording for the verdict to attach to.
                  The decisions are still recorded.
                </p>
              )}

              {queue.items.length === 0 ? (
                <p>Nothing is waiting to be paired between these two editions.</p>
              ) : (
                byOutcome(queue.items).map(([outcome, items]) => (
                  <section key={outcome}>
                    <h2>{OUTCOME_LABEL[outcome] ?? outcome}</h2>
                    {OUTCOME_BLURB[outcome] && <p>{OUTCOME_BLURB[outcome]}</p>}
                    <ol>
                      {items.map((item) => (
                        <li key={pairKey(item)}>
                          <div className="panes">
                            <Side heading="Older clause" of={item.old} />
                            <Side heading="Newer clause" of={item.new} />
                          </div>
                          <p>
                            {Math.round(item.confidence * 100)}% confidence.{' '}
                            {item.rationale}
                          </p>
                          {item.taken_by.length > 0 && (
                            <p>
                              Already paired with <code>{item.taken_by.join(', ')}</code>.
                            </p>
                          )}
                          <label>
                            Reason (optional)
                            <textarea
                              value={rationales[pairKey(item)] ?? ''}
                              onChange={(event) =>
                                setRationales((current) => ({
                                  ...current,
                                  [pairKey(item)]: event.target.value,
                                }))
                              }
                            />
                          </label>
                          <p>
                            <button
                              type="button"
                              disabled={pending}
                              onClick={() => settle(item, 'paired')}
                            >
                              Paired
                            </button>{' '}
                            <button
                              type="button"
                              disabled={pending}
                              onClick={() => settle(item, 'distinct')}
                            >
                              Distinct
                            </button>
                          </p>
                        </li>
                      ))}
                    </ol>
                  </section>
                ))
              )}

              {queue.settled.length > 0 && (
                <section>
                  <h2>Settled</h2>
                  {/* A settled pair is deliberately not re-recorded as a
                      candidate — the decision is the record, and a candidate edge
                      re-asking a settled question would put it straight back in
                      the queue. It is listed here because a verdict has to stay
                      reversible: a `distinct` the reviewer wants back has no
                      candidate edge to find it by. */}
                  <ul>
                    {queue.settled.map((settled) => (
                      <li key={`${settled.old_id}|${settled.new_id}`}>
                        <code>{settled.old_id}</code> → <code>{settled.new_id}</code>:{' '}
                        <strong>{settled.verdict}</strong>, recorded by {settled.actor}.
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Run and confirm green.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Pairings.test.tsx` — expected: `Test Files 1 passed (1)`, `Tests 10 passed (10)`.

- [ ] **Mutation check (the verdict's orientation).** In `Pairings.tsx::settle`, swap the two id arguments to `recordPairing` — `recordPairing(item.new.obligation_id, item.old.obligation_id, verdict, …)` — the newer-first orientation that would key to a second decision beside the first rather than replacing it. Run `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Pairings.test.tsx` — expected: two failures, `records a paired verdict older-first and reloads the queue` and `records a distinct verdict on the same pair`, each `AssertionError: expected "spy" to be called with arguments: [ 'old-1', 'new-1', 'paired', … ]` (respectively `'distinct', ''`) with the received call showing `'new-1', 'old-1'`. Swap the arguments back and re-run to confirm 10 pass.

- [ ] **Mutation check (the other eight tests).** The swap above kills the two verdict tests; the remaining eight get one named mutation each. Apply exactly one at a time, run `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/Pairings.test.tsx`, confirm the named failure, then revert it and re-run to confirm `Tests 10 passed (10)` before applying the next.

  - **(a) the grouping.** In `byOutcome`, replace the whole body with `return [['all', items] as [string, PairingCandidate[]]]` — every candidate in one ungrouped bucket, which is the screen the reviewer had before this task. Expected failure in `shows both clauses, the confidence, the rationale and which rule declined them`: `TestingLibraryElementError: Unable to find an accessible element with the role "heading" and name \`/took one of these clauses/i\`` — the two headings collapse into one reading `all`, because `OUTCOME_LABEL` has no entry for that key.
  - **(b) the winner's name.** Delete the `{item.taken_by.length > 0 && (…)}` paragraph from the candidate `<li>`. Expected failure in the same test: `TestingLibraryElementError: Unable to find an element with the text: /new-9/` — the pair that took one of these clauses is no longer named, which leaves `partner_taken` a label with no instruction in it.
  - **(c) the settled list.** Delete the `{queue.settled.length > 0 && (…)}` section. Expected failure in `lists the pairs already settled, with the verdict and who recorded it`: `TestingLibraryElementError: Unable to find an accessible element with the role "list"` — that fixture's `items` is empty, so the `<ol>` of candidates is not rendered either and nothing on the screen is a list.
  - **(d) the two error states.** In `load`'s `catch`, call `setError(…)` where it calls `setLoadError(…)` — the single shared error state Review shipped. Expected: two failures, `surfaces the reversed-pair 400 instead of showing an empty queue` and `does not report a queue that failed to load as a verdict that failed to record`, both `Error: expect(element).toHaveTextContent()` with `Expected element to have text content: /could not load the pairing queue/i` (respectively `/could not load/i`) against `Received: Could not record that: …` — a reader told their verdict failed to record when they had cast none.
  - **(e) the unapplied banner.** Delete the `{queue.pairings_unapplied > 0 && (…)}` paragraph. Expected failure in `says a recorded pairing could not be applied rather than losing it`: `TestingLibraryElementError: Unable to find an element with the text: /1 recorded pairing/i` — the count is in the payload and nowhere on the screen, which is the verdict quietly disappearing.
  - **(f) the pairable-document filter.** Change `setDocuments(found.filter((d) => d.version_count > 1))` to `setDocuments(found)`. Expected failure in `says a corpus with no two-edition document cannot be paired yet`: `TestingLibraryElementError: Unable to find an accessible element with the role "status"` — the one-edition document is offered instead, and the reader gets two empty edition pickers and no sentence saying why.
  - **(g) which pair is asked for.** In `load`, swap the two arguments — `getPairingQueue(toVersionId, fromVersionId)`. Expected failure in `asks the queue for the pair the reviewer chose`: the `waitFor` times out on `AssertionError: expected "spy" to be called with arguments: [ 'dodd-5000-01@2018-08-31', 'dodd-5000-01@2022-07-28' ]`, the received call showing the two reversed — which is the request the route answers 400 to.
  - **(h) a verdict that failed to record.** In `settle`, replace the catch clause with `} catch { /* swallowed */ }`. Expected failure in `surfaces a failure to record a verdict rather than looking successful`: `TestingLibraryElementError: Unable to find an accessible element with the role "alert"` — the 409 is swallowed and the screen looks exactly as it does when the verdict was recorded.

- [ ] **Commit.** `git add frontend/src/views/Pairings.tsx frontend/src/views/Pairings.test.tsx` then `git commit -m "feat: a screen settles the pairs the diff declined"`.

#### Cycle B — the route and the navigation

- [ ] **Write the failing test.** In `frontend/src/App.test.tsx`, add a mock beside the others (after the `./views/Review` line, currently line 9):

```tsx
vi.mock('./views/Pairings', () => ({ default: () => <div>pairings</div> }))
```

and extend the `ROUTES` table (currently lines 24-32) to:

```tsx
const ROUTES = [
  [/graph/i, '/'],
  [/documents/i, '/documents'],
  [/ingest/i, '/ingest'],
  [/triage/i, '/triage'],
  [/review/i, '/review'],
  [/pairings/i, '/pairings'],
  [/ask/i, '/ask'],
  [/reset/i, '/reset'],
] as const
```

- [ ] **Run it and read the failure.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/App.test.tsx` — expected exactly one failure, `App > links to /pairings/i`: `TestingLibraryElementError: Unable to find an accessible element with the role "link" and name \`/pairings/i\``. Its neighbour, `App > renders the view behind /pairings/i`, passes already and is *not* the guard here: with no route matching, `App` falls through to `NoSuchScreen`, which prints "There is no screen at /pairings" — text that satisfies `getAllByText(/pairings/i)` perfectly well. The link assertion is the one that cannot be satisfied by a missing route, which is why the failure count is one and not two.

- [ ] **Write the minimal implementation.** Replace `frontend/src/routes.tsx` with:

```tsx
import Ask from './views/Ask'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'
import Ingest from './views/Ingest'
import Pairings from './views/Pairings'
import Reset from './views/Reset'
import Review from './views/Review'
import Triage from './views/Triage'

// DI-1 shipped two screens and no way to get from one to the other. Every route
// the app serves is named here, so a screen cannot exist without a way to reach
// it — App.test.tsx asserts one link per route.
export const ROUTES = [
  { to: '/', label: 'Graph', element: <GraphExplorer /> },
  { to: '/documents', label: 'Documents', element: <DocumentTable /> },
  { to: '/ingest', label: 'Ingest', element: <Ingest /> },
  { to: '/triage', label: 'Triage', element: <Triage /> },
  { to: '/review', label: 'Review', element: <Review /> },
  // Next to Review because the two are easy to confuse and the distinction is
  // the whole point: Review asks whether our clause discharges another
  // document's duty, Pairings whether this edition's clause is the previous
  // edition's reworded. Two questions, two vocabularies, two canonical nodes.
  { to: '/pairings', label: 'Pairings', element: <Pairings /> },
  { to: '/ask', label: 'Ask', element: <Ask /> },
  // Last in the navigation on purpose: it is the only destructive screen.
  { to: '/reset', label: 'Reset', element: <Reset /> },
]
```

- [ ] **Run and confirm green.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/App.test.tsx` — expected: `Test Files 1 passed (1)`, `Tests 22 passed (22)` (20 before; the two `it.each` tables each grow from 7 rows to 8).

- [ ] **Mutation check.** Delete the `{ to: '/pairings', label: 'Pairings', element: <Pairings /> }` entry from `ROUTES` (and the now-unused `Pairings` import, which `noUnusedLocals` would otherwise flag). Run `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/App.test.tsx` — expected failure in `App > links to /pairings/i`: `Unable to find an accessible element with the role "link" and name \`/pairings/i\``. Restore both lines and re-run to confirm 22 pass.

- [ ] **Run the whole frontend gate.** `cd /home/rhagan/policy_grapher/frontend && npm test` — this is `eslint . --max-warnings=0 && tsc -b && vitest run`, the same command CI runs (`backend/tests/test_ci.py:94`). Expected: eslint silent, `tsc -b` silent, and every test file passing with no new failures.

- [ ] **Commit.** `git add frontend/src/routes.tsx frontend/src/App.test.tsx` then `git commit -m "feat: pairings has a route and a link like every other screen"`.

---

### Task 14: The build fieldset offers other documents' editions

**Files:**
- Modify `frontend/src/views/DocumentDetail.tsx` — new state beside `namesBySlug` (line 47), a new effect after the reference-name effect (lines 109-127), and the fieldset itself (lines 376-403)
- Modify `frontend/src/views/DocumentDetail.test.tsx` — module-level fixtures beside `versions` (lines 38-53), and the `proposes against the editions the reader chose` test (lines 283-303)

**Interfaces:**

*Consumes (from earlier tasks, exact signatures):*
- The behaviour spec §1 gives `propose_links`: a pair whose two obligations share a `:Document` is skipped, so a same-document candidate can no longer yield a proposal. Nothing in this task calls it; the fieldset's pool changes because of it.
- Already in the repo, unchanged: `listDocuments(): Promise<DocumentOut[]>` (`client.ts:90-92`), `listVersions(slug: string): Promise<DocumentVersionOut[]>` (`client.ts:183-187`), `startRebuild(slug: string, versionId: string, candidateVersionIds?: string[]): Promise<RebuildStarted>` (`client.ts:193-205`).

*Produces (what later tasks rely on):* nothing. The fieldset is a leaf: no other module imports from `DocumentDetail.tsx`, and the shape of `startRebuild`'s third argument is unchanged — only which version ids can appear in it.

---

- [ ] **Write the failing test.** In `frontend/src/views/DocumentDetail.test.tsx`, add these fixtures immediately after the `versions` array (line 53):

```tsx
// A second document with an edition of its own. The build fieldset's pool after
// the pairing split: `IMPLEMENTS` is cross-document only, so this document's own
// editions can no longer produce a single proposal and are not offered.
const otherDocument = {
  slug: 'dodi-5000-88',
  name: 'DoDI 5000.88',
  is_external: false,
  references: [],
  referenced_by: [],
  version_count: 1,
}

const otherVersions = [
  {
    version_id: 'dodi-5000-88@2020-09-09',
    effective_date: '2020-09-09',
    checksum: 'b4c1f0',
    source_uri: 'file:///data/samples/500088p.pdf',
    supersedes: null,
  },
]

/** A two-document corpus, answered per slug. The fieldset makes two kinds of
 *  call — the document list to find the others, then one `listVersions` for each
 *  of them — so a single `mockResolvedValue` would hand this document's editions
 *  back for every slug and hide exactly the bug this fixture exists to catch. */
function corpusOfTwo() {
  listDocuments.mockResolvedValue([document, otherDocument])
  listVersions.mockImplementation((slug: string) =>
    Promise.resolve(slug === 'dodd-5000-01' ? versions : otherVersions),
  )
}
```

Then replace the existing `proposes against the editions the reader chose` test (lines 283-303) with the two below, inside the same `describe('DocumentDetail — building the derived layer')`:

```tsx
  it('offers other documents’ editions, and never this document’s own', async () => {
    // Spec §8. `versions` came from `GET /documents/{slug}/versions`, so the only
    // candidates this screen could name were other editions of the document being
    // read — and after `propose_links` skips a pair whose obligations share a
    // `:Document`, not one of them can produce a proposal. The rebuild API was
    // never this narrow: it validates candidates by version id alone, so other
    // documents' editions could always be named by a direct call and never by
    // this control.
    loaded()
    corpusOfTwo()
    renderAt()
    await screen.findByRole('article')

    expect(
      await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ }),
    ).toBeInTheDocument()
    // Grouped by document, because a bare list of version ids from several
    // documents is a list of strings nobody can read.
    expect(screen.getByText('DoDI 5000.88')).toBeInTheDocument()
    // This document's own editions are gone from the pool entirely — both of
    // them, including the one that is not selected, which is what the old
    // filter left standing.
    expect(
      screen.queryByRole('checkbox', { name: /dodd-5000-01@2018-08-31/ }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: /dodd-5000-01@2020-09-09/ }),
    ).not.toBeInTheDocument()
    // Choosing none stays a valid request, and still says so.
    expect(screen.getByText(/choosing none rebuilds/i)).toBeInTheDocument()
  })

  it('proposes against the editions the reader chose', async () => {
    loaded()
    corpusOfTwo()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09',
      candidate_version_ids: ['dodi-5000-88@2020-09-09'],
    })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 0, chunks_total: 34, counts: {}, rejections: [], error: null,
    })
    renderAt()
    await screen.findByRole('article')

    await userEvent.selectOptions(screen.getByLabelText(/edition/i), 'dodd-5000-01@2020-09-09')
    await userEvent.click(
      await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ }),
    )
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [
      'dodi-5000-88@2020-09-09',
    ])
  })
```

- [ ] **Run it and read the failure.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/DocumentDetail.test.tsx` — expected two failures. `offers other documents’ editions…`: `TestingLibraryElementError: Unable to find an accessible element with the role "checkbox" and name \`/dodi-5000-88@2020-09-09/\`` (the fieldset still lists `dodd-5000-01@2018-08-31`). `proposes against the editions the reader chose`: the same missing checkbox.

- [ ] **Write the minimal implementation.** In `frontend/src/views/DocumentDetail.tsx`, add this state declaration immediately after `namesBySlug` (line 47):

```tsx
  // What the build fieldset offers: every *other* document's editions, each with
  // the document it belongs to. Not derived from `namesBySlug`, which holds names
  // for this document's references only.
  const [pool, setPool] = useState<
    { slug: string; name: string; versions: DocumentVersionOut[] }[]
  >([])
```

Add this effect immediately after the reference-name effect (after line 127):

```tsx
  // The candidates the fieldset below can propose against. `IMPLEMENTS` is
  // cross-document only, so the pool is other documents' editions and the corpus
  // is small enough to fetch them one document at a time.
  //
  // Its own effect rather than an extra branch of the lookup above, and the
  // separate `listDocuments` call is the price: the names lookup is deliberately
  // fail-soft so a failure there leaves the references list rendering, and
  // sharing a `try` would let one document's failed version fetch blank it.
  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const all = await listDocuments()
        // Only documents with an edition. A manifest records 438 documents that
        // have no text at all, and a candidate with no obligations proposes
        // nothing while costing a request to discover it.
        const others = all.filter(
          (found) => found.slug !== slug && found.version_count > 0,
        )
        const editions = await Promise.all(
          others.map((found) => listVersions(found.slug)),
        )
        if (cancelled) return
        setPool(
          others
            .map((found, index) => ({
              slug: found.slug,
              name: found.name,
              versions: editions[index],
            }))
            .filter((entry) => entry.versions.length > 0),
        )
      } catch {
        // Fail soft: an empty pool renders no fieldset, and the build button
        // still queues a rebuild that proposes nothing — which is a valid
        // request, not a broken screen.
      }
    })()

    return () => {
      cancelled = true
    }
  }, [slug])
```

Replace the fieldset (lines 376-403) with:

```tsx
          {pool.length > 0 && (
            <fieldset>
              <legend>Propose links against</legend>
              {/* Other documents' editions, never this document's own. A
                  proposal whose two obligations share a `:Document` is skipped —
                  `IMPLEMENTS` means our lower-tier clause discharges a
                  higher-tier duty, and an edition does not discharge its
                  predecessor; that relationship is the diff's, and it is settled
                  on the Pairings screen. Offering this document's editions here
                  would offer candidates that cannot produce a single proposal.
                  The rebuild API was never this narrow: it validates candidates
                  by version id alone, so other documents' editions could always
                  be named by a direct call and never by this control. */}
              {pool.map((entry) => (
                <div key={entry.slug}>
                  <h4>{entry.name}</h4>
                  {entry.versions.map((v) => (
                    <label key={v.version_id} className="stacked">
                      <input
                        type="checkbox"
                        checked={candidates.includes(v.version_id)}
                        onChange={(event) =>
                          setCandidates((current) =>
                            event.target.checked
                              ? [...current, v.version_id]
                              : current.filter((c) => c !== v.version_id),
                          )
                        }
                      />{' '}
                      {v.version_id}
                    </label>
                  ))}
                </div>
              ))}
              {/* Naming candidates is the only way proposals are generated:
                  nothing in the graph records which documents are higher-tier, so
                  the caller states it and the route does not guess. Choosing none
                  is a valid request that rebuilds without proposing. */}
              <p>Choosing none rebuilds the edition without proposing any links.</p>
            </fieldset>
          )}
```

- [ ] **Run and confirm green.** `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/DocumentDetail.test.tsx` — expected: `Test Files 1 passed (1)`, `Tests 42 passed (42)` (41 before, one net new test — one replaced, two written).

- [ ] **Mutation check.** In the new effect, invert the pool filter — change `found.slug !== slug` to `found.slug === slug`, which is the old behaviour written the new way: the pool becomes this document's own editions and the fieldset offers exactly the candidates that can no longer produce a proposal. Run `cd /home/rhagan/policy_grapher/frontend && npx vitest run src/views/DocumentDetail.test.tsx` — expected: two failures, `offers other documents’ editions, and never this document’s own` and `proposes against the editions the reader chose`, both on `TestingLibraryElementError: Unable to find an accessible element with the role "checkbox" and name \`/dodi-5000-88@2020-09-09/\``. Restore `!==` and re-run to confirm 42 pass.

- [ ] **Run the whole frontend gate.** `cd /home/rhagan/policy_grapher/frontend && npm test` — expected: eslint silent (no `react-hooks/set-state-in-effect` violation: every `setState` here runs after an `await`), `tsc -b` silent, every test file passing.

- [ ] **Commit.** `git add frontend/src/views/DocumentDetail.tsx frontend/src/views/DocumentDetail.test.tsx` then `git commit -m "feat: the build fieldset offers other documents' editions, which are the only ones that can propose"`.

---

### Task 15: End to end

**Files:**
- Modify `backend/tests/test_triage.py` — import block (lines 3-10) and a new `@pytest.mark.integration` test appended at the end of the file (710 lines on `main`; by the time this task runs it also carries Task 5's `pairings_unapplied` test and Task 11's rewritten citation test, so the line numbers below have moved and the anchors are names, not offsets)

**Interfaces:**

*Consumes (from earlier tasks, exact signatures):*
- `policy_grapher.links.pairing.PairingVerdict` (`StrEnum`, `PAIRED = "paired"`).
- `policy_grapher.links.pairing.record_pairing(tx, *, old_id: str, new_id: str, verdict: str, actor: str, rationale: str) -> None`.
- `policy_grapher.changes.diff.diff_versions(tx, *, from_version_id, to_version_id) -> dict[str, int]`, which now reads `:PairingDecision`s scoped through `:MANDATES` to the two named editions and threads them into `_plan_changes`.
- Already in the repo, unchanged: `policy_grapher.links.decisions.record_decision(tx, *, source_id, target_id, verdict, actor, rationale)` and `replay_decisions(tx)` — the sole writer of `IMPLEMENTS`.
- Fixtures in this file: `client_with_auth` (`conftest.py`), `_seed_version`, `_obligation_id`, `HIGHER_OLD`, `OURS`.

*Produces (what later tasks rely on):* nothing — this is the plan's closing gate.

---

- [ ] **Write the failing test.** In `backend/tests/test_triage.py`, extend the import block (lines 3-10 on `main`) with whichever of these two lines is not already there:

```python
from policy_grapher.links.decisions import record_decision, replay_decisions
from policy_grapher.links.pairing import PairingVerdict, record_pairing
```

(placed after the `from policy_grapher.extraction.schema import …` line, keeping the block alphabetical by module. Task 5's last cycle already imports `PairingVerdict` and `record_pairing` into this file for its own test, so expect that line to be present and add only the `links.decisions` one; `ruff` will tell you if a duplicate import slips in.) Then append at the end of the file:

```python
# --- end to end ---------------------------------------------------------------

# The rewrite no measure can see, which is what makes this end-to-end rather than
# a second run of the wording pass. `score_pair` returns None when the two
# statements share no content word (`propose.py:61-62`), so this pair is never
# scored, no `PAIRING_CANDIDATE` edge is written for it, and the section rule
# cannot reach it either — the clause moved from 3.2 to 7.1. The diff alone
# reports a removal and an addition. A `paired` verdict is the only thing in the
# system that can turn the two into one `MODIFIED`, and the problem section names
# this class — a complete rewording — as the case a human most obviously beats
# the measure on.
REWORDED = "Program offices will record the protection approach."


@pytest.mark.integration
def test_a_confirmed_pairing_carries_the_previous_statement_into_triage(
    client_with_auth,
):
    """The whole feature, through the API a reader actually uses.

    A cross-document `IMPLEMENTS` over a confirmed pairing has to produce a
    Triage row whose `previous_statement` is the paired older clause. Every leg
    is load-bearing and each has failed on its own: the pairing verdict has to
    reach `_plan_changes` scoped to these two editions, the `MODIFIED` it emits
    has to `AFFECTS` the *new* obligation (which is the one a reviewer must now
    act on, and the end the `IMPLEMENTS` edge points at), and the traversal's
    `document <> higher_document` guard has to let a genuinely cross-document row
    through rather than suppressing every row.

    Without the verdict this graph produces two changes and a row with a null
    `previous_statement` — a reviewer told a duty vanished and a new one appeared,
    when one was rewritten into the other.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    old_ids = _seed_version(
        driver, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    new_ids = _seed_version(
        driver, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("7.1", REWORDED, Modality.WILL)],
    )
    our_ids = _seed_version(
        driver, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0", entries=[("2.4", OURS, Modality.SHALL)],
    )

    with driver.session(database=database) as session:
        # The pairing question, settled by a person: the newer clause is the older
        # one reworded. Recorded older→newer, which is the direction the key
        # hashes and the only orientation a later POST on this pair would compute.
        session.execute_write(
            record_pairing,
            old_id=old_ids[HIGHER_OLD],
            new_id=new_ids[REWORDED],
            verdict=PairingVerdict.PAIRED,
            actor="tester",
            rationale="The re-issue renamed the duty; it is the same obligation.",
        )
        # The implements question, settled by the same person and answering
        # something else entirely: our clause discharges the higher duty. Recorded
        # and replayed rather than MERGEd directly, because `replay_decisions` is
        # the only writer of `IMPLEMENTS` anywhere in the codebase and a test that
        # writes the edge itself is testing a path production does not have.
        session.execute_write(
            record_decision,
            source_id=our_ids[OURS],
            target_id=new_ids[REWORDED],
            verdict="approve",
            actor="tester",
            rationale="Our plan clause discharges the protection duty.",
        )
        replayed = session.execute_write(replay_decisions)
    # The fixture must actually have the edge. A replay that promoted nothing
    # would leave every assertion below testing an empty traversal, and an empty
    # traversal agrees with almost anything.
    assert replayed["promoted"] == 1

    body = client_with_auth.get(
        "/triage",
        params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"},
    ).json()

    # One change, not two: the verdict consumed both clauses before the section
    # rule and the wording pass could see them.
    assert body["total_changes"] == 1
    assert body["unlinked_changes"] == 0
    assert len(body["rows"]) == 1

    row = body["rows"][0]
    assert row["kind"] == "MODIFIED"
    assert row["previous_statement"] == HIGHER_OLD
    assert row["higher"]["statement"] == REWORDED
    assert row["higher"]["document"] == "DoDI 5000.88"
    assert row["ours"]["statement"] == OURS
    assert row["ours"]["document"] == "ORG 1.0"
```

- [ ] **Run it and state the expected result.** `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/test_triage.py --collect-only -q` — expected `tests/test_triage.py: 25`. The arithmetic: 23 on `main` today (`.venv/bin/pytest tests/test_triage.py --collect-only -q` reports `tests/test_triage.py: 23` before any of this plan is written), plus the one test Task 5's last cycle adds to this file for `pairings_unapplied` on the Triage GET, plus this one. Task 11 replaces a test in this file rather than adding one, so it moves nothing. The doubled `-q` — `addopts = "-q"` in `backend/pyproject.toml` and one more on the command line — is what makes the output this one terse line instead of the node list. This test is `@pytest.mark.integration`: it needs Neo4j and Redis through testcontainers, and the `docker` binary is invisible from this Flatpak namespace, so it cannot execute here. The merge gate runs `.venv/bin/pytest tests/test_triage.py -q` where Docker exists, and it is there that the test's own failing state appears: against a diff that does not apply the verdict it fails on `assert body["total_changes"] == 1` with `AssertionError: assert 2 == 1`, the removal and the addition the diff produces on its own. (If `policy_grapher.links.pairing` does not exist yet, this step reports a collection *error* on the file instead of `tests/test_triage.py: 25` — the earlier tasks are not finished, and this one cannot be started.)

- [ ] **Confirm no production code is owed.** Every path this test exercises — `links/pairing.record_pairing`, `diff_versions` reading the decisions and `_plan_changes` applying them, the `previous_statement` written onto the `:Change`, the `document <> higher_document` guard in `TRIAGE`, `replay_decisions` as the sole writer of `IMPLEMENTS` — was built by the earlier tasks, and this task deliberately adds none of its own: an end-to-end test that needs new production code is not testing the end-to-end path. Confirm that nothing in this task's working tree touches production code: `cd /home/rhagan/policy_grapher && git status --short backend/src` — expected: no output, because every earlier task committed its own work.

- [ ] **Mutation check.** The behaviour under test is `_plan_changes`'s handling of a `paired` verdict, and `_plan_changes` is pure — it takes two dicts and no `tx`, exactly so the rule is testable on its own — so the mutant can be killed in this sandbox even though the test that names it cannot run.

  The mutation: in `backend/src/policy_grapher/changes/diff.py`, inside `_plan_changes`'s decision loop, change `if verdict == PairingVerdict.DISTINCT:` to `if verdict == PairingVerdict.PAIRED:` — a paired verdict is then routed into `distinct` and skipped, the shape of "a human verdict silently does nothing". (Task 5 writes the loop this way round — everything that is not `distinct` is applied — so there is no `"paired"` literal in `_plan_changes` to typo, and a stray verdict string would be applied rather than dropped.)

  The command:

```
cd /home/rhagan/policy_grapher/backend && .venv/bin/python -c "
from policy_grapher.changes.diff import _plan_changes
old = {'a': {'id': 'o-old',
             'statement': 'Components shall document the cybersecurity strategy.',
             'modality': 'SHALL', 'section_path': ['3.2']}}
new = {'b': {'id': 'o-new',
             'statement': 'Program offices will record the protection approach.',
             'modality': 'WILL', 'section_path': ['7.1']}}
plan = _plan_changes(old, new, {('o-old', 'o-new'): 'paired'})
print([(c['kind'], c['previous_statement']) for c in plan.changes])
"
```

  Unmutated it prints `[('MODIFIED', 'Components shall document the cybersecurity strategy.')]` — the same one change, with the same `previous_statement`, that the integration test asserts through the API. With `PairingVerdict.PAIRED` in the comparison it prints `[('REMOVED', None), ('ADDED', None)]`: the verdict is skipped, the two clauses fall through to the section rule (which cannot pair `3.2` with `7.1`) and then to the wording pass (which never scores a pair sharing no content word), so the diff reports a removal and an addition. That is `assert body["total_changes"] == 1` failing on `assert 2 == 1` and `assert row["previous_statement"] == HIGHER_OLD` failing on `assert None == 'Components shall document the cybersecurity strategy.'`. Revert the comparison to `PairingVerdict.DISTINCT` and re-run the command to confirm the single `MODIFIED` comes back.

- [ ] **Run the backend gate.** `cd /home/rhagan/policy_grapher/backend && .venv/bin/pytest tests/ -m "not integration" -q`. Expected: no new failures beyond the environmental ones this sandbox always has, which are exactly the twelve entries in the short test summary — thirteen printed lines, because the `test_lint.py` assertion message wraps onto a second —

```
FAILED tests/test_compose_stack.py::test_the_default_stack_extracts_and_embeds_for_real - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_default_build_carries_the_embedding_extra - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_an_explicitly_empty_backend_extras_is_honoured - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_an_absent_backend_extras_still_gets_the_default - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_every_extra_compose_asks_for_actually_exists - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_lean_stack_runs_no_model_services - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_lean_stack_turns_the_adapters_back - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_lean_build_drops_the_embedding_extra - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_worker_waits_for_the_model_to_be_pulled - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_compose_stack.py::test_the_lean_worker_does_not_wait_for_a_pull_that_never_runs - FileNotFoundError: [Errno 2] No such file or directory: 'docker'
FAILED tests/test_lint.py::test_ruff_reports_no_violations - AssertionError: ruff is not on PATH. It ships in the `dev` dependency group — run `uv sync`, or invoke the suite as `uv run pytest`.
assert None is not None
ERROR tests/test_versions.py::test_ingesting_a_pdf_records_a_version - docker.errors.DockerException: Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))
```

  The ten `test_compose_stack.py` failures and the `test_lint.py` failure are the two causes the plan header names — the invisible `docker` binary, and `ruff` living in the venv rather than on PATH. The `test_versions.py` ERROR is a third failure of the first kind, and the header does not account for it: `test_ingesting_a_pdf_records_a_version` carries no `integration` marker, so `-m "not integration"` selects it, and its `client_with_auth` fixture then reaches for testcontainers and cannot find `docker`. It is present on `main` before any of this work — verify that by running the same command on a clean checkout if the list ever looks different. Anything beyond these twelve entries is a regression this task must not close over. (Note that under this pytest configuration the trailing `N failed, M passed` count line is not printed; the short summary above is the whole of the verdict.)

- [ ] **Lint the backend files this plan changed.** `cd /home/rhagan/policy_grapher/backend && .venv/bin/ruff check src tests` — expected `All checks passed!`. Run through `.venv/bin/ruff` rather than a bare `ruff`: the binary is in the venv and not on this shell's PATH, which is the whole cause of the `test_lint.py` failure above.

- [ ] **Commit.** `git add backend/tests/test_triage.py` then `git commit -m "feat: a confirmed pairing carries the previous statement into triage"`.
