# Audit Gap Fixes — Design

**Date:** 2026-08-24 · **Status:** Approved, ready for an implementation plan

Design for the eleven gaps left open by the end-to-end audit of 2026-08-24, which drove every
screen against a live stack from a wiped volume. Seven defects found by that audit were fixed
during it. These eleven were not, because each needed a decision, an ADR, or a judgement that
was not mine to make alone.

This is a *design* document, not a new spec. Nothing here extends the behavioural contract in
[SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md); it corrects places where the running
system does not honour contracts already written — chiefly
[ADR-012](../../specs/adr/ADR-012-chunks-follow-sections.md) on chunking and
[ADR-014](../../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md) on
decisions. Two of the corrections change a frozen decision and therefore carry their own ADRs.

## Goal

A citation in this product exists so a reader can go and check it. Today two of them cannot
be checked: a page number naming a page the quoted text is not on, and a section path naming a
section the quoted text is not in. Closing that is the spine of this work. The remaining nine
gaps are smaller, independent, and mostly cheap.

| Story | Delivers | Size |
| --- | --- | --- |
| STORY-062 | A citation names the page the quoted text is on | M |
| STORY-063 | Back matter is its own section, not the tail of the last numbered one | M |
| STORY-064 | A rebuild carries review decisions across a change of identity | L |
| STORY-065 | Ingestion finds the references on a legacy cover | M |
| STORY-066 | An ingest says which edition it recorded and how much text it read | S |
| STORY-067 | Triage distinguishes "nothing changed" from "nothing was extracted" | M |
| STORY-068 | The document table says which documents have text | S |
| STORY-069 | A document's references are named and reachable from its own page | S |
| STORY-070 | The document table is bounded, and says when it truncated | S |
| STORY-071 | No service listens beyond loopback | S |
| STORY-072 | No developer's own hostname is a committed default | S |

Eleven stories close ten gaps: STORY-064 answers no gap of its own, but STORY-063 cannot land
without it. The eleventh gap, a local `.env` that predates `.env.example`, is a README sentence
rather than a story — see *What this deliberately does not do*.

## What is already true

Verified against the running system during the audit of 2026-08-24, from a wiped volume with
the default `null` extractor and `null` embedder.

- Both suites pass: 570 backend tests pass with 5 skipped, and 151 frontend tests pass.
- The sample corpus is 438 documents, 672 `REFERENCES` edges, 4 self-references skipped and
  2 suspected duplicate names. The two editions of DoDD 5000.01 chunk to 38 and 34 chunks.
- `chunk_pages` receives a per-page list from `pages_of` and discards the boundary at
  `body.append(line)`. Each chunk's `page` is `page_of_section` — the page the section opened
  on, exactly as ADR-012 specifies.
- `NAMED` matches only `CHAPTER|SECTION|APPENDIX|ENCLOSURE`, and `NUMBERED` requires a leading
  digit. `GLOSSARY`, `REFERENCES` and `G.2.` therefore open no section, and the 2020 edition's
  final chunk (ordinal 33) carries `["SECTION 2", "2.10"]` over glossary and reference text
  that is on pages 15–16.
- Identity is layered, and each layer feeds the next:
  - `chunk_id = sha256(version_id | section_path | occurrence | ordinal)[:32]`
  - `obligation_id = sha256(version_id | section_path | normalize(statement))[:32]`
  - `decision_key = sha256(source_obligation_id | target_obligation_id)[:32]`
- `drop_chunks` and `drop_obligations` are scoped by `version_id` and `DETACH DELETE`, so a
  rebuild leaves no orphans *within* an edition.
- `replay_decisions` already returns `promoted`, `suppressed` and `unpromotable`.
  `unpromotable` reaches `counts` and is displayed nowhere.
- `_HEADING` requires `REFERENCES` alone on a line. `500001p_2003.pdf` carries the legacy
  inline form `References:  (a) DoD Directive 5000.1, …`, so `locate_references` returns
  `("unknown", None)` and the file contributes zero references. It is not in `RATCHETS`.
- There are two ratchets. `test_extraction_ratchet.py` pins the deterministic citation parser
  over five PDF fixtures. `test_obligation_ratchet.py` pins the model behind the extraction
  port. Sprint 5's carried-over "re-measure the floors" concerns the second; nothing here does.
- `GRAPH_RENDER_CAP` is 300, and the graph view reports `Showing N of M nodes` when it
  truncates. The document table renders every row uncapped.
- `scripts/init-env.sh` generates `.env` from `.env.example` by substitution, so a fresh clone
  receives every key the example documents.
- `frontend` publishes on `127.0.0.1:5173` and `ollama` on `127.0.0.1:11434`, each with a
  comment explaining why. `neo4j` (7474, 7687) and `backend` (8000) publish on `0.0.0.0`.

## Decisions taken

Settled before design and binding on the plan.

**Citations are made correct in the data, not qualified in the UI.** The alternative — leaving
the chunker alone and rendering "section opens p. 14" — was considered and rejected. It makes
the number true without making it useful, and a reader still cannot turn to the page.

**A rebuild re-points review decisions across a change of identity.** Because `section_path`
is in `obligation_id`, re-keying a chunk re-keys the obligations extracted from it, and their
recorded `:LinkDecision` rows stop matching. The decision node survives — ADR-014 holds that a
decision is a fact a human established — but the approval no longer produces an `IMPLEMENTS`
edge, and today nothing on screen would say so.

The repair goes **inside `replay_decisions`**, not into a one-shot migration script. A script
is a thing somebody must remember to run exactly once, against a graph whose state cannot be
verified afterwards. `replay_decisions` already runs on every rebuild and already holds the
concept of an approval it could not apply; putting the repair there also makes it general, so
the next chunker improvement costs no review decisions either. The trade is that a rebuild now
silently repairs rather than reporting churn, which is why surfacing `unpromotable` ships in
the same story.

**`section_path` stays in the obligation identity.** Removing it would end this class of
breakage permanently, but two identical sentences in different sections of one edition would
collapse to a single node — which is the reason `section_path` is in the key. Rejected for now;
if it is ever revisited it needs a collision rule and an ADR of its own.

## The work

### 1. Citation accuracy, and the identity it disturbs

**STORY-062 — the page.** Contained to `chunking.py`; no change to the PDF source, the ingest
path or the schema.

- `body` accumulates `(page_number, line)` rather than `line`.
- `_split` returns `(start_offset, part)` rather than `part`. It already tracks `start`
  internally, so this exposes a value it holds rather than computing a new one.
- A chunk's `page` becomes the page of the line its own text starts on.

`page` is not part of any identity, so nothing re-keys and no rebuild is required for
correctness — though an edition chunked before this lands keeps its old numbers until it is
rebuilt, which the plan calls out as a step rather than leaving to be discovered.

**STORY-063 — the section.** `NAMED` gains `GLOSSARY`, `REFERENCES` and the lettered appendix
form (`G.2.`). The two obvious false positives are already guarded: a contents row by
`DOT_LEADER`, and a running header repeated across three or more pages by `_page_furniture`.

This re-keys every chunk whose `section_path` changes. One such chunk was identified during
the audit — ordinal 33 of the 2020 edition — and the earlier chunks of `SECTION 2/2.10` keep
their key, because a section closing earlier does not renumber the parts before the split. That
is one observation on one edition, not a survey: the plan re-measures the affected set across
all seven sample PDFs before the change lands, since the count of re-keyed chunks is what the
decision repair has to cover.

**STORY-064 — the decisions.** The repair matches an old obligation id to a new one through
the statement, which is stable across this change because only `section_path` moves. The old
statement is not recoverable from the decision — `:LinkDecision` stores obligation ids, a
verdict, an actor and a rationale, and no statement — so the mapping is captured inside the
rebuild's write transaction, reading the edition's obligations *before* `drop_obligations` runs
and pairing them against the newly written set afterwards.

Re-pointing a decision changes its `key`, which carries a uniqueness constraint
(`link_decision_key_unique`). Where a re-keyed decision would collide with a decision that
already exists, the existing one is left untouched and the stale one is not re-pointed: two
human verdicts must never be silently merged into one. Anything left unrepaired falls through
to the existing `unpromotable` count, which the rebuild screen now reports.

Ordering is load-bearing: **STORY-064 lands before STORY-063**, because STORY-063 is what
re-keys. STORY-062 does not re-key and may land either side.

**ADRs.** ADR-012 and ADR-014 are both frozen, so neither is edited — one is partly
superseded and one is extended:

- **ADR-026** — a chunk's page is its own page, superseding ADR-012's "the page the section
  opened on". Records what the old rule cost: a citation the reader cannot follow.
- **ADR-027** — a rebuild re-points decisions across an identity change, extending ADR-014.
  Records why the repair lives in the replay rather than in a migration, and what it does not
  do: it will not repair a decision whose statement itself changed.

Both ADRs are written before any code in this section is cut, per the
[estimation](../../backlog/README.md#estimation) rule that an L containing an unmade decision
means the decision is the work.

### 2. Extraction coverage

**STORY-065.** `_HEADING` gains one alternative for the legacy inline form, anchored on the
lettered entry that must follow it:

```
References:\s*(?=\(\s*[a-z]{1,3}\s*\))
```

The lookahead is what keeps a prose mention of "references" out of the heading set. Once the
heading matches, `locate_references`'s existing `_LETTERED` branch carries it — no new format
path.

The risky stage is not detection but termination: `_SECTION_END` looks for `ENCLOSURE`,
`GLOSSARY` or `APPENDIX` alone on a line, and a legacy cover may carry none of them. That is
measured against `500001p_2003.pdf` rather than assumed, and it is why this is M and not S.

`500001p_2003.pdf` then joins `RATCHETS` with a floor at the measured fraction rounded down to
the nearest 5% and a ceiling at the measured invented count exactly, per the rule already
written into that file. The five existing fixtures are the regression net: a new heading that
steals a match from any of them fails their floors loudly.

### 3. Screens that under-report

Three places compute something true and do not say it.

**STORY-066.** `POST /ingest` reports nodes and relationships but not the edition it recorded
or the text it read, so ingesting the 2003 edition reads as *0 nodes created* while 38 chunks
land. `DocumentIngestResult` gains `version_id` and `chunks_written`; the Ingest screen shows
both.

**STORY-067.** Triage answers *No obligation changed between these editions* when there were no
obligations on either side to change. `TriageOut` gains the obligation count for each edition,
and the screen distinguishes the two cases — the same discipline `unlinked_changes` already
applies to an empty table under
[ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md).

**`unpromotable`** is the third, and ships with STORY-064.

### 4. Finding your way around

**STORY-068.** `version_count` is already in the payload and already filters Triage's picker.
Surface it in the document table as a column and a "has text" filter.

**STORY-069.** The detail page's References list resolves slugs to names and links each entry,
matching what the table already does.

**STORY-070.** Cap the rendered rows rather than paginating, and say so — the idiom
`GRAPH_RENDER_CAP` already establishes on the graph view. The filter is the way through and
already exists. The reference picker becomes a typeahead over the same list rather than a
`<select>` of 439 options.

### 5. Configuration hygiene

**STORY-071.** `neo4j` and `backend` bind to `127.0.0.1`, matching `frontend` and `ollama`. No
ADR: [ADR-018](../../specs/adr/ADR-018-the-dev-proxy-forwards-writes.md) already records this
reasoning for port 5173, and this applies that decision rather than making a new one. Host
`curl localhost:8000` and the Neo4j browser at `localhost:7474` both keep working, which is
all the README documents.

**STORY-072.** The Coder hostname moves out of `defaultAllowedHosts` into
`VITE_ALLOWED_HOSTS`, which `vite.config.ts` already reads and `.env.example` already
documents.

## Sequencing

1. **ADR-026 and ADR-027.** Nothing in section 1 starts before both are written.
2. **STORY-064**, then **STORY-062** and **STORY-063**, then a rebuild of both editions of
   DoDD 5000.01 to prove decisions survived the re-key.
3. **STORY-065**, independent of everything above.
4. **STORY-066 – STORY-072**, independent of each other and of the rest. These are where the
   quick wins are, and any of them can be pulled forward to fill a gap.

## Testing

Each story carries its own tests; three points are worth stating once.

**A test that cannot fail for its bug is worse than no test.** The audit's headline defect
survived a green suite because its guard asserted a *type* where it meant a *value*. Every test
written here asserts the observed value, and every regression test is run against the
unfixed code first to watch it fail.

**The re-key is proved end to end, not in isolation.** A unit test that a decision is
re-pointed is necessary and not sufficient. The plan includes a live run: record an approval,
land STORY-063, rebuild, and confirm the `IMPLEMENTS` edge is still there and `unpromotable`
is zero.

**The ratchets are the gate for STORY-065**, and they are already written to be exactly that.
No new test framework is needed; one fixture row is.

## What this deliberately does not do

- **No pagination.** A cap and a filter answer the same need at a fraction of the cost, and
  match an idiom already in the product.
- **No `.env` validator.** G-09 turned out not to be a repo defect — `init-env.sh` already
  writes every key. A stale local file gets a README sentence, not a startup check.
- **No change to the obligation identity.** See *Decisions taken*.
- **No re-measuring of the obligation ratchet's floors.** That is sprint 5's carry-over against
  a different gate, and folding it in here would conflate two ratchets that pin two different
  things.
