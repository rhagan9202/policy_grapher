# Settling the Pairs the Diff Declines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Same-document pairing becomes a first-class, human-settleable question with its own canonical decision node, its own queue, and its own screen; `IMPLEMENTS` becomes cross-document only.

**Architecture:** The diff's wording pass records its outcomes as `PAIRING_CANDIDATE` edges written by `diff_versions` (planning stays pure); a new canonical `:PairingDecision` node is threaded into the diff before the section rule; a new `/pairings` API runs the diff itself and lets a reviewer settle or undo any pair of the two editions; a startup migration converts the legacy same-document `:LinkDecision` and deletes the stranded edges.

**Tech Stack:** FastAPI + Neo4j (Cypher) backend, pytest (+testcontainers for integration), React + Vitest frontend.

**Spec:** `docs/superpowers/specs/2026-09-09-pairing-is-not-implementing-design.md` (rev. 7 — the plan argues from it; conflicts resolve against the spec).

## Global Constraints

- **Pass-3 pairing structure is identical before and after every change**: `scored`, `_best_elsewhere`, and the greedy loop stay restricted to `confidence >= PAIRING_CONFIDENCE` (0.75, `diff.py:100`). Recording candidates must not change which pairs are made or declined, at which confidences. A mutation test guards this (Task 3).
- **`outcome` is the first rule that fired, in code order**: `auto_paired` | `partner_taken` | `contested` | `below_threshold`. `partner_taken`'s predicate is a strict subset of `contested`'s — the labels record precedence, not disjoint conditions.
- **`:PairingDecision` direction is older→newer** with properties `old_obligation_id` / `new_obligation_id` / `verdict` / `actor` / `rationale` / `at` / `key`; `key = sha256(f"{old_id}|{new_id}")[:32]` (directional).
- **The corpus ordering rule** for two editions is the tuple `(coalesce(effective_date, ''), ingested_at, version_id)` — the `version_id` tie-breaker is this feature's addition, applied wherever the rule is applied.
- **`replay_decisions` stays the only writer of `IMPLEMENTS`** (`decisions.py:8`). Nothing in this plan writes that edge type.
- **`IMPLEMENTS` becomes cross-document only**: `propose_links` skips same-document pairs, `record_decision` refuses them, the migration retires the legacy ones.
- **Sub-threshold recording is bounded and post-loop**: a candidate scored in `[MIN_CONFIDENCE, PAIRING_CONFIDENCE)` is kept iff at least one endpoint finished the greedy loop unpaired AND it is that endpoint's best sub-threshold candidate or within `PAIRING_MARGIN` (0.05) of that best. `distinct`-settled pairs are excluded from recording and from "best".
- **Every new test is mutation-checked** before it is believed (sprint DoD, `docs/sprints/sprint-12/plan.md:96`): after it passes, deliberately break the code it guards and confirm it fails. Each task's steps name the mutation.
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
