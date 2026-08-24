# Audit Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the eleven gaps the 2026-08-24 end-to-end audit left open, the spine of which is making a citation point at the page and section its quoted text is actually in.

**Architecture:** Three independent strands. The first corrects chunk metadata in `backend/src/policy_grapher/chunking.py` and repairs the review decisions that correcting it strands, inside `links/decisions.py` and `links/rebuild.py`. The second widens citation-section detection in `sources/pdf.py` and pins it with the existing ratchet. The third is seven small, unrelated reporting and configuration fixes across the API models, the React views, `docker-compose.yml` and `vite.config.ts`.

**Tech Stack:** Python 3.14 · FastAPI · Pydantic · Neo4j · pytest · uv — React 19 · TypeScript · Vite · Vitest · Testing Library — Docker Compose

**Spec:** [`docs/superpowers/specs/2026-08-24-audit-gap-fixes-design.md`](../specs/2026-08-24-audit-gap-fixes-design.md)

## Global Constraints

- **Backend tests:** `cd backend && uv run pytest`. Add `-m "not integration"` to skip Testcontainers. Lint runs inside the suite via `tests/test_lint.py` (Ruff).
- **Frontend tests:** `docker compose run --rm frontend npm test` — this is ESLint `--max-warnings=0`, then `tsc -b`, then Vitest. All three must pass.
- **The backend has no source volume mount.** A backend or worker code change needs `docker compose up -d --build backend worker`; `restart` runs the old image. Only `frontend/src` is mounted, so the UI hot-reloads.
- **Python:** 4-space indent, type-annotated, snake_case modules, `test_*.py`. Mark anything needing live Neo4j with `@pytest.mark.integration`.
- **TypeScript:** components PascalCase, view tests `*.test.tsx`.
- **Never lower a ratchet floor or raise a ceiling** to turn a red suite green. Either needs a reason in the commit message (`backend/tests/test_extraction_ratchet.py` module docstring).
- **Assert values, not types.** The audit's headline defect survived a green suite because its guard asserted `expect.any(Number)` where `0` was the bug. Every regression test here is run against the unfixed code first, and observed to fail, before the fix is written.
- **Commit style:** Conventional Commit prefixes (`fix:`, `feat:`, `docs:`), imperative subject.
- **Browser verification** (where a task calls for it): Playwright MCP cannot launch here. Use the bundled Chromium at `~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome` via `playwright` from the npx cache.

---

## Task 1: ADR-026 — a chunk's page is its own page

**Files:**
- Create: `docs/specs/adr/ADR-026-a-chunks-page-is-its-own-page.md`
- Modify: `docs/specs/adr/ADR-012-chunks-follow-sections.md` (mark the page rule superseded)

**Interfaces:**
- Consumes: nothing.
- Produces: the decision Task 6 implements. No code.

- [ ] **Step 1: Read the template and the decision being superseded**

Run: `cat docs/specs/adr/TEMPLATE-adr.md && grep -n "page" docs/specs/adr/ADR-012-chunks-follow-sections.md`

ADR-012 line 90 is the rule this supersedes: *"Each chunk's `page` is the page the section it belongs to opened on."*

- [ ] **Step 2: Write the ADR**

Follow `TEMPLATE-adr.md`. The content, in the house voice:

- **Context.** ADR-012 chose the section's opening page because reconstructing a per-chunk page after the fact meant guessing. It does not mean guessing: `pages_of` already returns a per-page list and `chunk_pages` already receives it — the boundary is discarded inside the function, at `body.append(line)`. The audit of 2026-08-24 measured the cost: `/ask` cited *DoDD 5000.01 · SECTION 2/2.10 · p. 14* while quoting the glossary and reference list, which are on pages 15–16.
- **Decision.** A chunk's `page` is the page the chunk's own text starts on.
- **Consequences.** `page` is in no identity, so nothing re-keys and no rebuild is needed for correctness — but an edition chunked before this keeps its old numbers until rebuilt. A chunk spanning a page break reports the page it starts on, not both; that is the honest simplification, and the section path plus the quote itself carry the rest.
- **Supersedes.** ADR-012, in part: only its page rule. Its chunk-identity and section-boundary decisions stand.

- [ ] **Step 3: Mark ADR-012's page rule superseded**

Add a note at ADR-012's page paragraph pointing at ADR-026. Do not edit the surrounding decision — ADR-012 is a dated document and only the pointer is added.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/adr/ADR-026-a-chunks-page-is-its-own-page.md docs/specs/adr/ADR-012-chunks-follow-sections.md
git commit -m "docs: ADR-026, a chunk's page is its own page"
```

---

## Task 2: ADR-027 — a rebuild re-points decisions across a change of identity

**Files:**
- Create: `docs/specs/adr/ADR-027-a-rebuild-repoints-decisions.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the decision Task 4 implements. No code.

- [ ] **Step 1: Write the ADR**

Content:

- **Context.** Identity is layered: `chunk_id = sha256(version_id | section_path | occurrence | ordinal)`, `obligation_id = sha256(version_id | section_path | normalize(statement))`, `decision_key = sha256(source_obligation_id | target_obligation_id)`. Changing a chunk's `section_path` therefore re-keys its obligations and strands the `:LinkDecision` rows recording a human's verdict. ADR-014 holds a decision to be a fact a human established; a re-key does not make it untrue.
- **Decision.** A rebuild re-points stranded decisions. The old obligation id maps to the new one through the statement, which the change does not move. The mapping is captured inside the rebuild's write transaction, reading the edition's obligations *before* `drop_obligations` and pairing them against the newly written set afterwards — `:LinkDecision` stores no statement of its own, and the node carrying it is deleted by the drop.
- **Decision.** Where a re-pointed decision's new `key` collides with a decision that already exists, the existing verdict wins and the stale one is left unrepaired. Two human verdicts are never silently merged.
- **Consequences.** Rebuilds stop costing review decisions, and this holds for future chunker changes, not just this one. A decision whose *statement* changed is not repairable this way and still lands in `unpromotable` — which is why this ADR requires that count to be on screen, not merely returned.
- **Alternative rejected.** A one-shot migration script: something a person must remember to run exactly once against a graph whose state cannot be verified afterwards, and which would not help the next chunker change.
- **Extends** ADR-014. Supersedes nothing.

- [ ] **Step 2: Commit**

```bash
git add docs/specs/adr/ADR-027-a-rebuild-repoints-decisions.md
git commit -m "docs: ADR-027, a rebuild re-points decisions across a change of identity"
```

---

## Task 3: Measure what Task 6 will re-key

**Files:**
- Create: `docs/artifacts/2026-08-24-rekey-blast-radius.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a measured count of affected chunks per sample PDF, which Task 8's live verification checks against.

The spec requires this before Task 7 lands: one chunk was observed during the audit, on one edition. That is an observation, not a survey, and the decision repair has to cover the real set.

- [ ] **Step 1: Write a throwaway measurement script**

Create `/tmp/measure_rekey.py` (throwaway — not committed):

```python
"""How many chunks change section_path under the Task 7 heading rules?"""
import re
from pathlib import Path

from policy_grapher.chunking import chunk_pages
from policy_grapher.sources.pdf import pages_of

SAMPLES = Path("data/samples")
BACK_MATTER = re.compile(r"^(GLOSSARY|REFERENCES|ACRONYMS)\s*$")
LETTERED = re.compile(r"^[A-Z]\.\d+(?:\.\d+)*\.\s+\S")

for sample in sorted(SAMPLES.glob("*.pdf")):
    pages = pages_of(sample)
    chunks = chunk_pages(pages, version_id=sample.stem)
    would_open = sum(
        1
        for page in pages
        for line in page.splitlines()
        if BACK_MATTER.match(line.strip()) or LETTERED.match(line.strip())
    )
    print(f"{sample.name:24} {len(chunks):>4} chunks   {would_open:>3} lines would open a new section")
```

- [ ] **Step 2: Run it**

Run: `uv run --project backend python /tmp/measure_rekey.py` from the repository root — `--project backend` puts `policy_grapher` on the path, and the sample paths are relative to the root.
Expected: one line per sample PDF, with non-zero counts for at least `500001p_2020.pdf` and `500001p.pdf`.

- [ ] **Step 3: Record the numbers**

Write `docs/artifacts/2026-08-24-rekey-blast-radius.md`: a table of fixture, chunk count, and lines that would open a new back-matter section; a sentence naming the measurement date and the script; and the total, which is the number Task 7 expects the repair to cover.

- [ ] **Step 4: Commit**

```bash
git add docs/artifacts/2026-08-24-rekey-blast-radius.md
git commit -m "docs: measure what the back-matter heading change re-keys"
```

---

## Task 4: STORY-064a — a rebuild re-points stranded decisions

**Files:**
- Modify: `backend/src/policy_grapher/links/decisions.py`
- Modify: `backend/src/policy_grapher/links/rebuild.py`
- Test: `backend/tests/test_links.py` — already imports `decision_key`, `record_decision` and `replay_decisions`, and uses the `clean_graph` / `database` fixtures from `conftest.py`

**Interfaces:**
- Consumes: `decision_key(source_id, target_id) -> str` and `replay_decisions(tx) -> dict[str, int]`, both already in `links/decisions.py`.
- Produces:
  - `read_obligation_statements(tx, *, version_id: str) -> dict[str, str]` — `{obligation_id: normalize(statement)}` for one edition.
  - `repoint_decisions(tx, *, before: dict[str, str], after: dict[str, str]) -> int` — `before` is `{old_obligation_id: normalized_statement}`, `after` is `{normalized_statement: new_obligation_id}`. Returns how many decisions were re-pointed.
  - `rebuild_derived(...)` gains `"decisions_repointed"` in its returned counts.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_links.py`:

```python
@pytest.mark.integration
def test_a_decision_survives_its_obligations_being_re_keyed(clean_graph, database):
    """The identity of an obligation contains its section_path, so a chunker
    change re-keys it and strands the verdict a human recorded against it. The
    decision is a fact a human established (ADR-014); a re-key does not make it
    untrue, and ADR-027 requires the rebuild to carry it across."""
    from policy_grapher.links.decisions import repoint_decisions

    old_source, old_target = "old-source-id", "old-target-id"
    new_source, new_target = "new-source-id", "new-target-id"

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id=old_source,
            target_id=old_target,
            verdict="approve",
            actor="reviewer",
            rationale="checked against the source",
        )

        repointed = session.execute_write(
            repoint_decisions,
            before={old_source: "the director shall report", old_target: "components shall comply"},
            after={"the director shall report": new_source, "components shall comply": new_target},
        )

    assert repointed == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.source_obligation_id AS s, "
        "d.target_obligation_id AS t, d.key AS key, d.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["s"] == new_source
    assert records[0]["t"] == new_target
    assert records[0]["key"] == decision_key(new_source, new_target)
    # The verdict is what must survive. Re-pointing that dropped it would be
    # worse than not re-pointing at all.
    assert records[0]["verdict"] == "approve"
```

- [ ] **Step 2: Write the collision test**

```python
@pytest.mark.integration
def test_a_repoint_that_would_collide_leaves_the_existing_verdict_alone(clean_graph, database):
    """Two human verdicts must never be silently merged into one. If a stale
    decision would re-key onto a decision that already exists, the existing one
    wins and the stale one is left for the unpromotable count."""
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision, source_id="old-a", target_id="old-b",
            verdict="approve", actor="reviewer", rationale="stale",
        )
        session.execute_write(
            record_decision, source_id="new-a", target_id="new-b",
            verdict="reject", actor="reviewer", rationale="current",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-a", "statement two": "new-b"},
        )

    assert repointed == 0

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision {key: $key}) RETURN d.verdict AS verdict",
        {"key": decision_key("new-a", "new-b")},
        database_=database,
    )
    assert records[0]["verdict"] == "reject", "the existing verdict must win"
```

- [ ] **Step 3: Run both to verify they fail**

Run: `cd backend && uv run pytest tests/test_links.py -k "re_keyed or collide" -v`
Expected: FAIL with `ImportError: cannot import name 'repoint_decisions'`

- [ ] **Step 4: Implement `read_obligation_statements` and `repoint_decisions`**

Add to `backend/src/policy_grapher/links/decisions.py`, importing `normalize` from `policy_grapher.extraction.schema`:

```python
READ_OBLIGATION_STATEMENTS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN o.obligation_id AS obligation_id, o.statement AS statement
"""

READ_DECISIONS_FOR = """
UNWIND $ids AS id
MATCH (d:LinkDecision)
WHERE d.source_obligation_id = id OR d.target_obligation_id = id
RETURN DISTINCT d.key AS key,
       d.source_obligation_id AS source_id,
       d.target_obligation_id AS target_id
"""

APPLY_REPOINT = """
UNWIND $moves AS m
MATCH (d:LinkDecision {key: m.old_key})
SET d.source_obligation_id = m.source_id,
    d.target_obligation_id = m.target_id,
    d.key                  = m.new_key
RETURN count(d) AS repointed
"""

EXISTING_KEYS = """
UNWIND $keys AS key
MATCH (d:LinkDecision {key: key})
RETURN collect(d.key) AS present
"""


def read_obligation_statements(tx: ManagedTransaction, *, version_id: str) -> dict[str, str]:
    """One edition's obligations as `{obligation_id: normalized statement}`.

    Read *before* `drop_obligations`, because that is the only moment the old
    ids and their statements exist together: `:LinkDecision` stores no
    statement, and the obligation carrying it is about to be deleted.
    """
    return {
        record["obligation_id"]: normalize(record["statement"])
        for record in tx.run(READ_OBLIGATION_STATEMENTS, {"version_id": version_id})
    }


def repoint_decisions(
    tx: ManagedTransaction, *, before: dict[str, str], after: dict[str, str]
) -> int:
    """Carry recorded verdicts across a change of obligation identity (ADR-027).

    `before` maps each old obligation id to its normalized statement; `after`
    maps each normalized statement to the id the rebuild has just written for
    it. A statement that did not move produces the same id on both sides and is
    skipped.

    A decision whose new key already belongs to another decision is left
    exactly as it was. Merging two human verdicts into one is the single
    outcome this must not have, and an unrepaired decision is still counted by
    `replay_decisions` as `unpromotable`.
    """
    moved = {
        old_id: after[statement]
        for old_id, statement in before.items()
        if statement in after and after[statement] != old_id
    }
    if not moved:
        return 0

    decisions = list(tx.run(READ_DECISIONS_FOR, {"ids": list(moved)}))
    if not decisions:
        return 0

    proposed = []
    for record in decisions:
        source_id = moved.get(record["source_id"], record["source_id"])
        target_id = moved.get(record["target_id"], record["target_id"])
        new_key = decision_key(source_id, target_id)
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
        tx.run(EXISTING_KEYS, {"keys": [m["new_key"] for m in proposed]}).single()["present"]
    )
    moves = [m for m in proposed if m["new_key"] not in taken]
    if not moves:
        return 0

    return tx.run(APPLY_REPOINT, {"moves": moves}).single()["repointed"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_links.py -k "re_keyed or collide" -v`
Expected: 2 passed

- [ ] **Step 6: Wire it into the rebuild**

In `backend/src/policy_grapher/links/rebuild.py`, import `read_obligation_statements` and `repoint_decisions` alongside `replay_decisions`, and `normalize` and `obligation_id` from `policy_grapher.extraction.schema` — `obligation_id` is what the rebuild must reproduce to know the new ids, and `normalize` is what makes the two sides comparable. Inside the write transaction function, capture the statements *before* the drop and re-point after the write:

```python
    before = read_obligation_statements(tx, version_id=version_id)
    # ... existing drop_changes / drop_chunks / drop_obligations ...
    # ... existing write_chunks / write_obligations ...
    after = {
        normalize(statement): obligation_id(version_id, section_path, statement)
        for _, section_path, found in extracted
        for statement in (o.statement for o in found)
    }
    repointed = repoint_decisions(tx, before=before, after=after)
```

Add `"decisions_repointed": repointed` to the returned counts dict, beside `**replayed`.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: all pass, count higher than 570 by the two new tests

- [ ] **Step 8: Commit**

```bash
git add backend/src/policy_grapher/links/decisions.py backend/src/policy_grapher/links/rebuild.py backend/tests/test_links.py
git commit -m "feat: a rebuild carries review decisions across a change of identity"
```

---

## Task 5: STORY-064b — the rebuild screen reports what it could not replay

**Files:**
- Modify: `backend/src/policy_grapher/models.py` (nothing — `counts` is already `dict[str, int]`)
- Modify: `frontend/src/views/DocumentDetail.tsx`
- Test: `frontend/src/views/DocumentDetail.test.tsx`

**Interfaces:**
- Consumes: `RebuildStatus.counts`, which already carries `unpromotable` and now `decisions_repointed` from Task 4.
- Produces: nothing other tasks depend on.

`unpromotable` has been computed, returned and displayed nowhere since it was written. ADR-027 requires it on screen.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/views/DocumentDetail.test.tsx`, in the rebuild `describe`:

```tsx
  it('says when a recorded approval could not be replayed', async () => {
    // replay_decisions has returned this count since it was written and nothing
    // has ever shown it. An approval that stopped being represented in the graph
    // is exactly the case a healthy-looking rebuild must not hide (ADR-027).
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 2, unpromotable: 3 },
      rejections: [], extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/3 recorded approvals could not be replayed/i)
    expect(status).toHaveTextContent(/2 .*carried across/i)
  })

  it('stays quiet about decisions when there were none to carry or lose', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 0, unpromotable: 0 },
      rejections: [], extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).not.toHaveTextContent(/could not be replayed/i)
    expect(status).not.toHaveTextContent(/carried across/i)
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose run --rm frontend npx vitest run src/views/DocumentDetail.test.tsx -t "replayed"`
Expected: FAIL — the text is not in the document

- [ ] **Step 3: Implement**

In `frontend/src/views/DocumentDetail.tsx`, inside the `run.state === 'finished'` block, after the rejected-chunks paragraph:

```tsx
              {/* ADR-027. A rebuild re-keys obligations when the chunker changes,
                  and carries the verdicts recorded against them across. What it
                  could not carry is the one number a healthy-looking rebuild
                  would otherwise hide. */}
              {(run.counts.decisions_repointed ?? 0) > 0 && (
                <p>
                  {run.counts.decisions_repointed} review decision
                  {run.counts.decisions_repointed === 1 ? ' was' : 's were'} carried across
                  a change of obligation identity.
                </p>
              )}

              {(run.counts.unpromotable ?? 0) > 0 && (
                <p>
                  {run.counts.unpromotable} recorded approval
                  {run.counts.unpromotable === 1 ? '' : 's'} could not be replayed — the
                  obligations they refer to no longer exist under those ids, and the
                  statements no longer match. They are still recorded, and need
                  re-reviewing.
                </p>
              )}
```

- [ ] **Step 4: Run the frontend suite**

Run: `docker compose run --rm frontend npm test`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/DocumentDetail.tsx frontend/src/views/DocumentDetail.test.tsx
git commit -m "fix: a rebuild says which review decisions it could not replay"
```

---

## Task 6: STORY-062 — a citation names the page the quoted text is on

**Files:**
- Modify: `backend/src/policy_grapher/chunking.py`
- Test: `backend/tests/test_chunking.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_split(text, max_chars, overlap_chars) -> list[tuple[int, str]]` — was `list[str]`; the int is the part's start offset in `text`. `Chunk.page` semantics change; the dataclass does not.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_chunking.py`:

```python
def test_a_chunk_reports_the_page_its_own_text_starts_on():
    """ADR-026. The old rule gave every chunk of a section the page the section
    opened on, so a section running across a page break cited text the reader
    would not find there — measured on DoDD 5000.01, where the glossary was
    cited as page 14 while sitting on page 16."""
    pages = [
        "2.10.  CJCS.\n" + "The CJCS shall advise. " * 60,
        "More of section 2.10 continues here. " * 60,
        "Still more of section 2.10 on the third page. " * 60,
    ]
    chunks = chunk_pages(pages, version_id="v", max_chars=800, overlap_chars=50)

    assert len(chunks) > 3, "the section must split into enough parts to span pages"
    assert chunks[0].page == 1
    # The section opened on page 1; under the old rule every chunk said page 1.
    assert max(chunk.page for chunk in chunks) > 1, (
        "a chunk whose text starts on a later page must say so"
    )
    assert [c.page for c in chunks] == sorted(c.page for c in chunks), (
        "pages must not go backwards in reading order"
    )


def test_split_reports_where_each_part_starts():
    """`page` is derived from the offset, so the offset has to be right."""
    text = "alpha. " * 200
    parts = _split(text, 300, 50)

    assert all(text[offset:].startswith(part) for offset, part in parts), (
        "each part must appear at the offset reported for it"
    )
    assert parts[0][0] == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_chunking.py -k "own_text_starts_on or where_each_part_starts" -v`
Expected: FAIL — `test_split_reports_where_each_part_starts` fails unpacking a `str`; the page test fails because every page is 1

- [ ] **Step 3: Make `_split` report offsets**

In `backend/src/policy_grapher/chunking.py`, change the signature and the append:

```python
def _split(text: str, max_chars: int, overlap_chars: int) -> list[tuple[int, str]]:
```

and, inside the loop, replace `parts.append(text[start:end])` with:

```python
        parts.append((start, text[start:end]))
```

Leave every other line of `_split` alone — the offsets it already tracks are exactly what is now returned.

- [ ] **Step 4: Carry the page with each line**

In `chunk_pages`, change `body` to hold `(page_number, line)` pairs and drop `page_of_section`:

```python
    sections: list[tuple[list[str], list[tuple[int, str]], int]] = []
    path: list[str] = [PREAMBLE]
    body: list[tuple[int, str]] = []
    occurrences: dict[tuple[str, ...], int] = {}

    def close() -> None:
        if any(line.strip() for _, line in body):
            key = tuple(path)
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            sections.append((list(path), list(body), occurrence))
        body.clear()

    furniture = _page_furniture(pages)
    for page_number, page_text in enumerate(pages, start=1):
        for line in page_text.splitlines():
            heading = None if line.strip() in furniture else section_heading(line)
            if heading:
                close()
                path = _push(path, heading)
            body.append((page_number, line))
    close()
```

- [ ] **Step 5: Add the offset-to-page lookup**

Add above `chunk_pages`:

```python
def _page_at(lines: list[tuple[int, str]], offset: int) -> int:
    """The page of the line containing `offset` in a section's joined text.

    `offset` is an index into `"\\n".join(line for _, line in lines)`, so each
    line consumes its own length plus the one newline the join inserted.
    """
    cursor = 0
    for page_number, line in lines:
        if offset <= cursor + len(line):
            return page_number
        cursor += len(line) + 1
    return lines[-1][0] if lines else 1
```

- [ ] **Step 6: Build each chunk's page from its offset**

Replace the chunk-building loop:

```python
    chunks: list[Chunk] = []
    ordinal = 0
    for section_path, lines, occurrence in sections:
        joined = "\n".join(line for _, line in lines)
        # `.strip()` shifts every offset by the leading whitespace it removes.
        lead = len(joined) - len(joined.lstrip())
        for within_section, (offset, part) in enumerate(
            _split(joined.strip(), max_chars, overlap_chars)
        ):
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(version_id, section_path, occurrence, within_section),
                    text=part,
                    # ADR-026: the page this chunk's own text starts on, not the
                    # page its section opened on.
                    page=_page_at(lines, offset + lead),
                    section_path=section_path,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return chunks
```

- [ ] **Step 7: Run the chunking tests**

Run: `cd backend && uv run pytest tests/test_chunking.py -v`
Expected: all pass, including the two new ones. If an existing test asserted a page that was the section's opening page for a *later* chunk, update it and say why in the commit — that assertion encoded the bug.

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add backend/src/policy_grapher/chunking.py backend/tests/test_chunking.py
git commit -m "fix: a chunk reports the page its own text starts on"
```

---

## Task 7: STORY-063 — back matter is its own section

**Files:**
- Modify: `backend/src/policy_grapher/chunking.py`
- Test: `backend/tests/test_chunking.py`

**Interfaces:**
- Consumes: `section_heading(line) -> str | None`, unchanged in signature.
- Produces: nothing other tasks depend on. This is the task that re-keys chunks, so Task 4 must already be merged.

**Do not start this task until Task 4 is merged.** It re-keys chunks, which re-keys obligations, which strands decisions — Task 4 is what carries them across.

- [ ] **Step 1: Write the failing test**

```python
def test_back_matter_opens_its_own_section():
    """GLOSSARY, REFERENCES and lettered appendix headings matched neither
    NAMED nor NUMBERED, so back matter was absorbed into whatever numbered
    section preceded it — DoDD 5000.01's reference list carried
    ["SECTION 2", "2.10"] and was cited as if it were the CJCS's duties."""
    assert section_heading("GLOSSARY") == "GLOSSARY"
    assert section_heading("REFERENCES") == "REFERENCES"
    assert section_heading("G.2.  DEFINITIONS.") == "G.2"


def test_a_reference_mentioned_in_prose_does_not_open_a_section():
    """The heading must be the whole line. A legacy cover runs
    "References:  (a) DoD Directive 5000.1," inline, and a sentence can name a
    glossary without being one."""
    assert section_heading("References:  (a) DoD Directive 5000.1, October 23, 2000") is None
    assert section_heading("See the GLOSSARY for the full list of terms.") is None
    assert section_heading("REFERENCES ....................................... 16") is None
    # Positive control: without these, the test would pass if section_heading
    # always returned None.
    assert section_heading("REFERENCES") == "REFERENCES"


def test_back_matter_closes_the_section_before_it():
    """The defect this fixes, at the level it was found."""
    pages = [
        "2.10.  CJCS.\nThe CJCS shall advise the Secretary.\n"
        "REFERENCES\n"
        'DoD Directive 1322.18, "Military Training," October 3, 2019\n'
    ]
    chunks = chunk_pages(pages, version_id="v")
    paths = [chunk.section_path for chunk in chunks]

    assert ["2.10"] in paths
    assert ["REFERENCES"] in paths
    reference_chunk = next(c for c in chunks if c.section_path == ["REFERENCES"])
    assert "Military Training" in reference_chunk.text
    assert "The CJCS shall advise" not in reference_chunk.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_chunking.py -k "back_matter or mentioned_in_prose" -v`
Expected: FAIL — `section_heading("GLOSSARY")` returns `None`

- [ ] **Step 3: Implement the two new heading forms**

In `backend/src/policy_grapher/chunking.py`, beside `NAMED`:

```python
# Back matter. These open no numbered section, so before ADR-026's companion
# change they were absorbed into whatever numbered section preceded them — the
# reference list of DoDD 5000.01 carried ["SECTION 2", "2.10"].
#
# Anchored at both ends on purpose. A legacy cover runs "References:  (a) DoD
# Directive 5000.1," inline and is a citation block, not a heading; requiring
# the word to be the whole line keeps it, and any prose mention, out.
# Uppercase-only for the same reason: these headings are set in caps in every
# DoD issuance in `data/samples`, and matching case-insensitively would catch
# ordinary sentences.
BACK_MATTER = re.compile(r"^(?P<kind>GLOSSARY|REFERENCES|ACRONYMS)\s*$")

# "G.2.  DEFINITIONS." — a lettered appendix subsection. NUMBERED requires a
# leading digit and so never matched these.
LETTERED = re.compile(r"^(?P<id>[A-Z]\.\d+(?:\.\d+)*)\.\s+\S")
```

In `section_heading`, after the `DOT_LEADER` guard and before `NAMED`:

```python
    back_matter = BACK_MATTER.match(stripped)
    if back_matter:
        return back_matter["kind"]
    lettered = LETTERED.match(stripped)
    if lettered:
        return lettered["id"]
```

`_push` needs no change: `"GLOSSARY"` and `"G.2"` both start with a non-digit, so the existing `if not heading[0].isdigit(): return [heading]` resets them to the top level, which is what a back-matter section is.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && uv run pytest tests/test_chunking.py -v`
Expected: all pass

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: all pass. Chunk counts asserted anywhere will have moved — a section that now closes early produces one more chunk. Update those assertions and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher/chunking.py backend/tests/test_chunking.py
git commit -m "fix: back matter is its own section, not the tail of the last numbered one"
```

---

## Task 8: Prove decisions survive the re-key, against the live stack

**Files:**
- Modify: `docs/artifacts/2026-08-24-rekey-blast-radius.md` (append the result)

**Interfaces:**
- Consumes: Tasks 4, 6 and 7, all merged.
- Produces: evidence, not code.

A unit test that a decision is re-pointed is necessary and not sufficient. This is the run that proves it.

- [ ] **Step 1: Bring the stack up on the pre-change images**

```bash
git stash && docker compose down -v && docker compose up -d --build && git stash pop
```

Wait for `curl -s localhost:8000/health` to return `{"status":"ok"}`.

- [ ] **Step 2: Ingest, build, and record an approval on the old chunker**

```bash
TOKEN=$(grep -E '^API_TOKEN=' .env | cut -d= -f2); H="Authorization: Bearer $TOKEN"
curl -sX POST localhost:8000/ingest -H "$H" -H 'Content-Type: application/json' -d '{"filename": "500001p_2020.pdf"}'
```

This needs obligations, so it needs a real extractor: `docker compose --profile models up -d`, set `EXTRACTOR_ADAPTER=local` in `.env`, then `docker compose up -d --force-recreate worker`. Rebuild the edition and wait — measured at ~104 seconds a chunk on CPU, so budget about an hour for 34 chunks.

Then approve one proposal from the review queue:

```bash
curl -H "$H" localhost:8000/review/queue | head -c 600
curl -sX POST "localhost:8000/review/<source_id>/<target_id>" -H "$H" \
     -H 'Content-Type: application/json' -d '{"verdict": "approve"}'
```

Record the two obligation ids. Confirm the edge exists:

```bash
docker compose exec neo4j cypher-shell -u neo4j -p "$(grep -E '^NEO4J_PASSWORD=' .env | cut -d= -f2)" \
  "MATCH (:Obligation)-[r:IMPLEMENTS]->(:Obligation) RETURN count(r) AS edges"
```

- [ ] **Step 3: Deploy the re-keying change and rebuild**

```bash
docker compose up -d --build backend worker
```

Rebuild the same edition from the UI, or `POST /documents/dodd-5000-01/versions/dodd-5000-01@2020-09-09/rebuild`. Extraction is cached (ADR-013), so this run calls the model zero times and finishes in under a minute.

- [ ] **Step 4: Confirm the decision survived**

Expected in the rebuild status and on screen:
- `decisions_repointed` ≥ 1
- `unpromotable` == 0
- the `IMPLEMENTS` edge count is unchanged from Step 2

If `unpromotable` is non-zero, stop: a verdict was stranded, and the repair does not cover the real set. Compare against Task 3's measured numbers before going further.

- [ ] **Step 5: Record the result and commit**

Append to `docs/artifacts/2026-08-24-rekey-blast-radius.md`: the date, the edition, the counts before and after, and the `IMPLEMENTS` edge count on both sides of the change.

```bash
git add docs/artifacts/2026-08-24-rekey-blast-radius.md
git commit -m "docs: record that review decisions survived the re-key on a live run"
```

---

## Task 9: STORY-065 — ingestion finds the references on a legacy cover

**Files:**
- Modify: `backend/src/policy_grapher/sources/pdf.py`
- Test: `backend/tests/test_pdf_stages.py`, `backend/tests/test_extraction_ratchet.py`

**Interfaces:**
- Consumes: nothing from earlier tasks; independent of Tasks 1–8.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_pdf_stages.py`:

```python
LEGACY = SAMPLES / "500001p_2003.pdf"  # DoDD 5000.01, May 12 2003, Change 2


def test_a_legacy_inline_references_block_is_found():
    """`_HEADING` wanted REFERENCES alone on a line. A legacy cover runs
    "References:  (a) DoD Directive 5000.1," inline, so `locate_references`
    returned ("unknown", None) and the file contributed no references at all —
    while its cover lists ten."""
    fmt, section = pdf.locate_references(pdf.text_of(LEGACY))

    assert fmt == "legacy", f"expected the legacy format, got {fmt!r}"
    assert section is not None
    assert "DoD Directive 5000.1" in section


def test_the_word_references_in_prose_is_not_a_references_section():
    """The lookahead is what keeps this out: a heading only counts when a
    lettered entry follows it."""
    fmt, section = pdf.locate_references(
        "Policy.\nReferences to the Comptroller are made throughout.\nMore prose.\n"
    )

    assert fmt == "unknown"
    assert section is None


def test_a_legacy_cover_yields_its_citations():
    result = pdf.extract_document(LEGACY)

    assert result.format == "legacy"
    assert "DoD Instruction 5000.2" in result.references
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_pdf_stages.py -k "legacy or prose_is_not" -v`
Expected: FAIL — `locate_references` returns `("unknown", None)`

- [ ] **Step 3: Add the inline heading form**

In `backend/src/policy_grapher/sources/pdf.py`, beside `_HEADING`:

```python
# A legacy cover carries its citations inline — "References:  (a) DoD Directive
# 5000.1, October 23, 2000" — with no standalone REFERENCES line for `_HEADING`
# to find, so `locate_references` returned ("unknown", None) for every one of
# them. The lookahead is the whole guard: a heading only counts when a lettered
# entry follows it, which a prose mention of "references" never has.
_INLINE_HEADING = re.compile(r"References:\s*(?=\(\s*[a-z]{1,3}\s*\))", re.IGNORECASE)
```

In `locate_references`, iterate over both patterns' matches in document order:

```python
    candidates = sorted(
        [*_HEADING.finditer(full), *_INLINE_HEADING.finditer(full)],
        key=lambda match: match.start(),
    )
    for match in candidates:
```

Leave the body of the loop exactly as it is: the `_LETTERED` branch already returns `("legacy", section)`, so an inline block needs no new format path.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && uv run pytest tests/test_pdf_stages.py -v`
Expected: all pass. If the section runs past its real end — `_SECTION_END` looks for `ENCLOSURE`, `GLOSSARY` or `APPENDIX` alone on a line, and a legacy cover may carry none — the third test will show it, as citations from the body leaking into `result.references`. If so, add a bound for the inline form: the legacy block ends at the first line that is neither a continuation nor a new lettered entry. Measure it against the fixture rather than guessing.

- [ ] **Step 5: Measure the new fixture's numbers**

```bash
cd backend && uv run python -c "
import ast, csv
from pathlib import Path
from policy_grapher.sources import pdf
samples = Path('../data/samples')
expected = {}
with (samples / 'dod_policy_references_08122026.csv').open(newline='', encoding='utf-8') as h:
    for row in csv.DictReader(h):
        expected[row['Document Name'].strip()] = set(ast.literal_eval(row['References'] or '[]'))
want = expected['DoDD 5000.01'] - {'DoDD 5000.01'}
found = set(pdf.extract_document(samples / '500001p_2003.pdf').references)
print('matched', len(want & found) / len(want))
print('invented', len(found - want))
"
```

- [ ] **Step 6: Add the fixture to the ratchet**

In `backend/tests/test_extraction_ratchet.py`, add a row to `RATCHETS` with the floor at the measured fraction **rounded down to the nearest 5%** and the ceiling at the measured invented count **exactly**, per that file's own rule:

```python
    "500001p_2003.pdf": ("DoDD 5000.01", <measured floor>, <measured ceiling>),
```

Note that this fixture and `500001p.pdf` are two editions of one instrument and share a corpus name; the ratchet keys on filename, so both rows coexist.

- [ ] **Step 7: Run the whole ratchet**

Run: `cd backend && uv run pytest tests/test_extraction_ratchet.py -v`
Expected: all pass, six fixtures. The five existing ones are the regression net — if the new heading steals a match from any of them, their floors fail here.

- [ ] **Step 8: Run the full backend suite and commit**

```bash
cd backend && uv run pytest
git add backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py backend/tests/test_extraction_ratchet.py
git commit -m "fix: ingestion finds the references on a legacy cover"
```

---

## Task 10: STORY-066 — an ingest says which edition it recorded

**Files:**
- Modify: `backend/src/policy_grapher/models.py`, `backend/src/policy_grapher/ingest.py`
- Modify: `frontend/src/api/types.ts`, `frontend/src/views/Ingest.tsx`
- Test: `backend/tests/test_pdf_ingest.py`, `frontend/src/views/Ingest.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `DocumentIngestResult` gains `version_id: str` and `chunks_written: int`; the TypeScript `DocumentIngestResult` gains the same two fields.

- [ ] **Step 1: Write the failing backend test**

```python
@pytest.mark.integration
def test_ingesting_a_pdf_reports_the_edition_and_the_text_it_read(client_with_auth):
    """"0 nodes created" is what a second edition of an already-known document
    reports, and it reads as "nothing happened" while 38 chunks land."""
    body = client_with_auth.post("/ingest", json={"filename": "500001p_2020.pdf"}).json()

    assert body["source"] == "document"
    assert body["version_id"] == "dodd-5000-01@2020-09-09"
    assert body["chunks_written"] > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pdf_ingest.py -k reports_the_edition -v`
Expected: FAIL with `KeyError: 'version_id'`

- [ ] **Step 3: Implement**

Add to the document-ingest response model in `backend/src/policy_grapher/models.py`:

```python
    # An ingest of a second edition creates no :Document node, so "0 nodes
    # created" is both true and unreadable. The edition and its chunk count are
    # what the reader needs in order to do the next thing.
    version_id: str
    chunks_written: int
```

In `backend/src/policy_grapher/ingest.py`, thread the resolved `version_id` from `merge_version` and the count returned by `write_chunks` into the result the document path builds.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_pdf_ingest.py -v`
Expected: all pass

- [ ] **Step 5: Write the failing frontend test**

In `frontend/src/views/Ingest.test.tsx`, extend the document-result fixture with `version_id: 'dodd-5000-01@2020-09-09'` and `chunks_written: 34`, and add:

```tsx
  it('names the edition it recorded and how much text it read', async () => {
    ingest.mockResolvedValue(documentResult)
    render(<Ingest />)
    await userEvent.type(screen.getByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /^ingest$/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/dodd-5000-01@2020-09-09/)
    expect(status).toHaveTextContent(/34 chunks/i)
  })
```

- [ ] **Step 6: Run to verify it fails, then implement**

Run: `docker compose run --rm frontend npx vitest run src/views/Ingest.test.tsx`
Expected: FAIL

Add the two fields to `DocumentIngestResult` in `frontend/src/api/types.ts`, and to the document branch of `Ingest.tsx`'s result list:

```tsx
                <li>
                  edition <code>{result.version_id}</code>, {result.chunks_written} chunks
                  of text
                </li>
```

- [ ] **Step 7: Run both suites and commit**

```bash
cd backend && uv run pytest && cd .. && docker compose run --rm frontend npm test
git add backend/src/policy_grapher/models.py backend/src/policy_grapher/ingest.py backend/tests/test_pdf_ingest.py frontend/src/api/types.ts frontend/src/views/Ingest.tsx frontend/src/views/Ingest.test.tsx
git commit -m "fix: an ingest says which edition it recorded and how much text it read"
```

---

## Task 11: STORY-067 — Triage distinguishes "nothing changed" from "nothing was extracted"

**Files:**
- Modify: `backend/src/policy_grapher/models.py`, `backend/src/policy_grapher/routers/triage.py`
- Modify: `frontend/src/api/types.ts`, `frontend/src/views/Triage.tsx`
- Test: `backend/tests/test_triage.py`, `frontend/src/views/Triage.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TriageOut` gains `from_obligations: int` and `to_obligations: int`; the TypeScript `TriageOut` gains the same.

- [ ] **Step 1: Write the failing backend test**

```python
@pytest.mark.integration
def test_triage_reports_how_many_obligations_each_edition_has(client_with_auth):
    """"No obligation changed between these editions" is true and misleading
    when neither edition has any obligations to change — which is what the
    default null extractor produces. This is the same discipline
    `unlinked_changes` already applies to an empty table (ADR-015)."""
    _seed_two_editions_without_obligations(client_with_auth)

    body = client_with_auth.get(
        "/triage", params={"to_version_id": "d@2020-01-01"}
    ).json()

    assert body["total_changes"] == 0
    assert body["from_obligations"] == 0
    assert body["to_obligations"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_triage.py -k how_many_obligations -v`
Expected: FAIL with `KeyError: 'from_obligations'`

- [ ] **Step 3: Implement**

Add to `TriageOut` in `backend/src/policy_grapher/models.py`:

```python
    # An empty `rows` has three causes, and they are not the same finding:
    # nothing is linked (unlinked_changes), nothing changed (total_changes), or
    # nothing was ever extracted. Only these two can tell the third from the
    # second, and the default `null` extractor makes the third the common case.
    from_obligations: int
    to_obligations: int
```

In `backend/src/policy_grapher/routers/triage.py`, add the count query and read it inside the existing `_work` transaction:

```python
COUNT_OBLIGATIONS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN count(o) AS obligations
"""
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_triage.py -v`
Expected: all pass

- [ ] **Step 5: Write the failing frontend test**

```tsx
  it('does not report "nothing changed" when nothing was ever extracted', async () => {
    getTriage.mockResolvedValue({
      from_version_id: 'd@2018-01-01', to_version_id: 'd@2020-01-01',
      rows: [], total_changes: 0, unlinked_changes: 0,
      from_obligations: 0, to_obligations: 0,
    })
    await chooseAnEdition()

    expect(await screen.findByText(/no obligations have been extracted/i)).toBeInTheDocument()
    expect(screen.queryByText(/no obligation changed/i)).not.toBeInTheDocument()
  })

  it('still reports a genuine all-clear when both editions have obligations', async () => {
    getTriage.mockResolvedValue({
      from_version_id: 'd@2018-01-01', to_version_id: 'd@2020-01-01',
      rows: [], total_changes: 0, unlinked_changes: 0,
      from_obligations: 96, to_obligations: 115,
    })
    await chooseAnEdition()

    expect(await screen.findByText(/no obligation changed/i)).toBeInTheDocument()
  })
```

- [ ] **Step 6: Run to verify it fails, then implement**

In `frontend/src/views/Triage.tsx`, replace the `total_changes === 0` branch:

```tsx
            result.total_changes === 0 ? (
              result.from_obligations === 0 || result.to_obligations === 0 ? (
                <p>
                  <strong>
                    No obligations have been extracted for{' '}
                    {result.from_obligations === 0 && result.to_obligations === 0
                      ? 'either edition'
                      : result.from_obligations === 0
                        ? `${result.from_version_id}`
                        : `${result.to_version_id}`}
                    .
                  </strong>{' '}
                  Nothing can have changed between them, because there is nothing
                  yet to compare. Build the derived layer for both editions with a
                  real extraction model configured.
                </p>
              ) : (
                <p>No obligation changed between these editions.</p>
              )
            ) : (
```

Update every existing `getTriage.mockResolvedValue` in the test file to carry the two new fields.

- [ ] **Step 7: Run both suites and commit**

```bash
cd backend && uv run pytest && cd .. && docker compose run --rm frontend npm test
git add backend/src/policy_grapher/models.py backend/src/policy_grapher/routers/triage.py backend/tests/test_triage.py frontend/src/api/types.ts frontend/src/views/Triage.tsx frontend/src/views/Triage.test.tsx
git commit -m "fix: triage tells nothing-changed from nothing-extracted"
```

---

## Task 12: STORY-068 — the document table says which documents have text

**Files:**
- Modify: `frontend/src/views/DocumentTable.tsx`
- Test: `frontend/src/views/DocumentTable.test.tsx`

**Interfaces:**
- Consumes: `DocumentOut.version_count`, which the API already returns and Triage already filters on.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```tsx
  it('says which documents have ingested text', async () => {
    // 439 rows look identical, and only two or three have an edition behind
    // them. version_count has been in the payload since STORY-040 and the table
    // has never shown it.
    listDocuments.mockResolvedValue([
      { slug: 'a', name: 'DoDD 5000.01', is_external: false, references: [], referenced_by: [], version_count: 2 },
      { slug: 'b', name: 'DoDD 9999.99', is_external: true, references: [], referenced_by: [], version_count: 0 },
    ])
    renderTable()
    await screen.findByRole('table')

    const withText = screen.getByRole('row', { name: /DoDD 5000\.01/ })
    expect(within(withText).getByText('2')).toBeInTheDocument()
  })

  it('can show only the documents that have text', async () => {
    listDocuments.mockResolvedValue([
      { slug: 'a', name: 'DoDD 5000.01', is_external: false, references: [], referenced_by: [], version_count: 2 },
      { slug: 'b', name: 'DoDD 9999.99', is_external: true, references: [], referenced_by: [], version_count: 0 },
    ])
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('checkbox', { name: /only documents with text/i }))

    expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 9999.99')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm frontend npx vitest run src/views/DocumentTable.test.tsx -t "text"`
Expected: FAIL

- [ ] **Step 3: Implement**

Add an `Editions` column rendering `document.version_count`, and a `withText` checkbox state folded into the existing `visible` memo:

```tsx
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    return (documents ?? []).filter(
      (d) =>
        (!needle || d.name.toLowerCase().includes(needle)) &&
        (!withText || d.version_count > 0),
    )
  }, [documents, filter, withText])
```

- [ ] **Step 4: Run and commit**

```bash
docker compose run --rm frontend npm test
git add frontend/src/views/DocumentTable.tsx frontend/src/views/DocumentTable.test.tsx
git commit -m "feat: the document table says which documents have ingested text"
```

---

## Task 13: STORY-069 — a document's references are named and reachable from its own page

**Files:**
- Modify: `frontend/src/views/DocumentDetail.tsx`
- Test: `frontend/src/views/DocumentDetail.test.tsx`

**Interfaces:**
- Consumes: `listDocuments()` from `api/client`, already imported by four other views.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```tsx
  it('names and links the documents this one cites', async () => {
    // The detail page listed raw slugs, unlinked, while the table two clicks
    // away resolved the same slugs to names and linked every row.
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    listDocuments.mockResolvedValue([
      { slug: 'dodd-1322-18', name: 'DoDD 1322.18', is_external: false, references: [], referenced_by: [], version_count: 0 },
    ])
    renderAt()

    const link = await screen.findByRole('link', { name: 'DoDD 1322.18' })
    expect(link).toHaveAttribute('href', '/documents/dodd-1322-18')
  })

  it('falls back to the slug when the name is not known yet', async () => {
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    listDocuments.mockRejectedValue(new Error('offline'))
    renderAt()

    // A failed name lookup must not blank the references list — the slug is
    // still a working link.
    expect(await screen.findByRole('link', { name: 'dodd-1322-18' })).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify they fail, then implement**

Add `listDocuments` to the imports, a `namesBySlug` state fetched in its own effect that fails silently, and render each reference as a `<Link>`:

```tsx
          {document.references.map((target) => (
            <li key={target}>
              <Link to={`/documents/${target}`}>{namesBySlug.get(target) ?? target}</Link>
            </li>
          ))}
```

- [ ] **Step 3: Run and commit**

```bash
docker compose run --rm frontend npm test
git add frontend/src/views/DocumentDetail.tsx frontend/src/views/DocumentDetail.test.tsx
git commit -m "feat: a document's references are named and reachable from its own page"
```

---

## Task 14: STORY-070 — the document table is bounded, and says when it truncated

**Files:**
- Modify: `frontend/src/views/DocumentTable.tsx`
- Test: `frontend/src/views/DocumentTable.test.tsx`

**Interfaces:**
- Consumes: the `visible` memo from Task 12.
- Produces: nothing.

The idiom is the graph view's: cap, and say so. `GRAPH_RENDER_CAP` is 300 and the graph reports `Showing N of M nodes`.

- [ ] **Step 1: Write the failing test**

```tsx
  it('caps the rendered rows and says it did', async () => {
    listDocuments.mockResolvedValue(
      Array.from({ length: 250 }, (_, i) => ({
        slug: `d-${i}`, name: `Document ${i}`, is_external: false,
        references: [], referenced_by: [], version_count: 0,
      })),
    )
    renderTable()
    await screen.findByRole('table')

    expect(screen.getAllByRole('row').length).toBe(TABLE_RENDER_CAP + 1) // + header
    expect(screen.getByText(new RegExp(`showing ${TABLE_RENDER_CAP} of 250`, 'i'))).toBeInTheDocument()
    expect(screen.getByText(/filter to narrow/i)).toBeInTheDocument()
  })

  it('does not claim truncation when everything fits', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await screen.findByRole('table')

    expect(screen.queryByText(/filter to narrow/i)).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify they fail, then implement**

Export the cap so the test names the same number the component uses:

```tsx
/** The graph view has capped its render since STORY-015 and says so when it
 *  truncates; the table rendered all 439 rows. Same idiom, same wording: the
 *  filter is the way through, and it already exists. */
export const TABLE_RENDER_CAP = 200
```

Slice `visible` to the cap for rendering, keep `visible.length` for the count, and add the truncation line beside the existing `Showing N of M`.

- [ ] **Step 3: Run and commit**

```bash
docker compose run --rm frontend npm test
git add frontend/src/views/DocumentTable.tsx frontend/src/views/DocumentTable.test.tsx
git commit -m "feat: the document table is bounded, and says when it truncated"
```

---

## Task 15: STORY-071 and STORY-072 — no service listens beyond loopback, no hostname is a committed default

**Files:**
- Modify: `docker-compose.yml`
- Modify: `frontend/vite.config.ts`
- Modify: `.env.example`, `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Bind the three published ports to loopback**

In `docker-compose.yml`, change `neo4j` and `backend`:

```yaml
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
```

```yaml
    ports:
      - "127.0.0.1:8000:8000"
```

Add a comment above each pointing at the reasoning already recorded for port 5173 in ADR-018: anything that can reach these reads the corpus as the dev principal, and the Neo4j browser reaches the graph with the password `init-env.sh` generated.

- [ ] **Step 2: Verify nothing the README documents broke**

```bash
docker compose up -d
curl -s -o /dev/null -w "api %{http_code}\n" localhost:8000/health
curl -s -o /dev/null -w "neo4j %{http_code}\n" localhost:7474
ss -tlnp | grep -E "7474|7687|8000|5173"
```

Expected: `api 200`, `neo4j 200`, and every line in `ss` bound to `127.0.0.1`, none to `0.0.0.0`.

- [ ] **Step 3: Move the hostname out of the committed default**

In `frontend/vite.config.ts`:

```ts
// Hosts Vite will serve to, beyond localhost. Empty by default: a remote
// workspace hostname belongs to whoever is using it, not to the repository.
const defaultAllowedHosts: string[] = [];
```

The `VITE_ALLOWED_HOSTS` plumbing beneath it already handles the rest, and `.env.example` already documents the variable with that hostname as its example value — which is the right home for it.

- [ ] **Step 4: Add the README sentence for G-09**

In the README's model-configuration section, after the instruction to set `EXTRACTOR_ADAPTER=local` in `.env`:

> An `.env` generated before these settings existed will not have the line — `init-env.sh` writes whatever `.env.example` holds at the time it runs. Add it, or delete `.env` and re-run the script for a fresh set of keys and secrets.

- [ ] **Step 5: Confirm the frontend still serves**

```bash
docker compose up -d --force-recreate frontend
curl -s -o /dev/null -w "ui %{http_code}\n" localhost:5173
```

Expected: `ui 200`

- [ ] **Step 6: Run the frontend suite and commit**

```bash
docker compose run --rm frontend npm test
git add docker-compose.yml frontend/vite.config.ts README.md
git commit -m "fix: no service listens beyond loopback, and no hostname is a committed default"
```

---

## Task 16: Refine the backlog

**Files:**
- Modify: `docs/backlog/backlog.md`
- Create: `docs/backlog/stories/STORY-064-decisions-survive-a-change-of-identity.md`
- Create: `docs/backlog/stories/STORY-065-legacy-covers-yield-their-references.md`

**Interfaces:**
- Consumes: the whole plan.
- Produces: a Ready section that meets the Definition of Ready, which sprint 6's planning session needs before it can commit anything.

- [ ] **Step 1: Add eleven rows to Ready**

Ready is currently empty and says so. Replace that paragraph with the eleven rows, each carrying a size from the [t-shirt scale](../backlog/README.md#estimation), in the order the plan sequences them. Use the ID, title and size from the spec's table. Note in the Notes column which task in this plan implements each.

- [ ] **Step 2: Write the two story files**

CONVENTIONS says a row graduates to a file only when it needs acceptance criteria or discussion that would bloat the table. Two do:

- **STORY-064** — it carries ADR-027, the ordering constraint against STORY-063, and the collision rule. Acceptance criteria as a checklist: a re-pointed decision keeps its verdict; a colliding re-point leaves the existing verdict alone; `unpromotable` is on screen; a live rebuild after STORY-063 shows `unpromotable == 0`.
- **STORY-065** — it carries a ratchet floor that has to be measured before it can be written down, which is an open question a row cannot hold.

The other nine stay as rows.

- [ ] **Step 3: Update the Last reviewed date**

`backlog.md` carries `*Living document — edit in place. Last reviewed: 2026-08-23*`. Set it to the date this lands.

- [ ] **Step 4: Commit**

```bash
git add docs/backlog/backlog.md docs/backlog/stories/STORY-064-decisions-survive-a-change-of-identity.md docs/backlog/stories/STORY-065-legacy-covers-yield-their-references.md
git commit -m "docs: refine the eleven audit gaps into Ready"
```

---

## Done when

- [ ] `cd backend && uv run pytest` passes, including six ratchet fixtures.
- [ ] `docker compose run --rm frontend npm test` passes.
- [ ] A live rebuild after Task 7 reports `unpromotable == 0` and an unchanged `IMPLEMENTS` count (Task 8).
- [ ] `ss -tlnp` shows no service on `0.0.0.0`.
- [ ] `/ask` cites a page a reader can turn to, and back matter cites `REFERENCES` rather than the last numbered section.
- [ ] Ready holds eleven sized rows and sprint 6's planning session can start from it.
