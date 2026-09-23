---
title: Two adapters — a second ingestion source, and managed obligation extraction
date: 2026-09-22
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan
status: ready-for-implementation-in-part
---

# Two adapters — a second ingestion source, and managed obligation extraction

> **Readiness.** U1–U5, U7 and U8 are ready to implement. **U6 alone is blocked**, on the one
> prerequisite this plan cannot resolve from inside itself: a named managed service, without which
> no floor can be measured. U5 is built against a recorded endpoint, since every behaviour it owns
> is a property of the adapter rather than of a provider — see Outstanding Questions, where all five
> other questions were settled this session and only the provider stays open.

> **Superseded in part, 2026-09-23.** While
> [ADR-043](../specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md) is in force,
> U5 and U6 are replaced by `docs/superpowers/specs/2026-09-23-azure-openai-extraction-adapter-design.md`
> (the provider is Azure Government OpenAI), and U3 and U4 are suspended, since either one as written
> fails the suite for that adapter. All four return as written when ADR-043 ends. U1, U2, U7 and U8
> are unaffected.

## Goal Capsule

**Objective.** An analyst can put a policy document into the corpus in a second published format
beyond PDF, and can have its obligations extracted without a model running on anyone's machine.
Today both halves are closed: the corpus accepts exactly one document format, and the only real
extractor needs a model server on the operator's own hardware.

**Means.** Two adapters behind two ports that already exist — a second source behind the ingestion
dispatch, and an accredited managed extractor behind `ObligationExtractor` (KTD1, KTD4).

**Authority hierarchy.** ADR-041 governs what a managed adapter may send and on what grounds. Its
header amends ADR-016, which is the *embedding* port — but its Decision speaks of "an adapter"
generally, its ADR-020 clause governs "a managed endpoint's served model" (ADR-020 being the
*extraction* weights rule), and its Consequences open with clause-level extraction being what makes
this feature worth building. So its substance reaches extraction; only its amendment bookkeeping
does not say so, and ADR-013's status line records only ADR-034 — a gap U5 closes by adding the
cross-reference, following how ADR-016 records ADR-041 and how ADR-013 already records ADR-034.
ADR-020 governs where model weights may come from and is explicitly unaffected by ADR-041. ADR-042
governs what an unchanged re-ingest may skip, and is the constraint the ingestion half must not
break. Where this plan and an ADR disagree, the ADR wins and the plan is wrong.

**Stop conditions.** Stop and ask rather than proceed if: the only nameable managed service's
accreditation does not cover the material ADR-041 permitted sending (U6 cannot be configured
honestly without one — U5 still builds against a stub); the accreditation covers a service whose
served model is not US-origin (ADR-020 binds and widening its set is a review decision, not a
settings change); or measuring floors for the managed adapter produces numbers below the local
adapter's on the same gold set.

**Execution profile.** Proof-first for both halves. Every unit here either widens a gate that
currently passes vacuously or adds one; writing the test first is the only way to see it fail for
the right reason. The extraction ratchet in particular **skips rather than fails** today, so a unit
that does not first make it fail has not demonstrated anything.

**Who finishes it.** `ce-work` per unit, shipping through the repo's normal gates.

---

## Product Contract

### Summary

Two ports in this codebase accept adapters, and each currently admits a set too narrow for what the
product claims to do. `sources/` dispatches on file extension and `DOCUMENT_SUFFIXES = {".pdf"}`
(`backend/src/policy_grapher/sources/__init__.py:13`). `ObligationExtractor` admits `null` and
`local` (`backend/src/policy_grapher/extraction/__init__.py:58-73`). This plan adds one adapter to
each, and closes the three gates that would otherwise let the second one ship unmeasured.

### Problem Frame

**A corpus that accepts one format is a corpus with a queue in front of it.** DoD issuances are
published as PDFs often enough that `.pdf` was the right first choice, but policy also arrives as
Word documents, as HTML on a publisher's site, and as plain text in an email. Each of those today
requires someone to convert the file by hand before the tool will look at it, and a conversion done
by hand is a provenance gap: the corpus records a checksum of the converted file, not of what the
publisher issued.

**Clause detail that only sometimes exists reads as a broken feature.** U8 shipped the obligation
panel with interim behaviour by design: obligations appear where extraction has already recorded
them and the panel says plainly where it has not. On the live corpus only a minority of editions
show clauses. Two causes sit behind that, and this plan removes one: the only real extractor is
`local`, which needs a model server on the machine. The other — that obligations are written solely
by a hand-triggered, per-edition rebuild, with no bulk route — is untouched here and is what keeps
coverage patchy even after the managed adapter lands. Naming it is not a promise to fix it.

**And the gate that is supposed to stop a bad extractor shipping does not currently fire.**
`test_the_configured_extractor_clears_its_floors` skips when the configured adapter has no recorded
floors (`backend/tests/test_obligation_ratchet.py:327-331`). The one test that fails rather than
skipping on a missing entry hardcodes the local adapter
(`backend/tests/test_obligation_ratchet.py:386`). A managed adapter added today would pass a green
suite that checked nothing — the exact shape the corpus's own learning names, one level up from an
assertion.

### Actors

- **A1. Policy analyst** — the primary actor, carried from the dependency-map plan. Adds documents,
  reads dependencies, follows impact to clause level.
- **A2. Document source parser** — resolves a file into an issuance identity and its cited
  references. Deterministic, no model. Gains a second implementation here.
- **A3. Managed extraction service** — produces clause-level obligations on an accredited endpoint.
  Named as a prerequisite by the dependency-map plan; built here.

### Requirements

**The ingestion half**

- R1. A document published in a format other than PDF can be ingested from the picker without
  anyone converting it first, and produces the same document identity, references and text a PDF of
  the same issuance would. The one deliberate exception is the locator: a source with no page
  boundaries has no page to report, so per KTD7 its chunks carry a null `page` and cite by section
  path. Every other fact about the document is at parity.
- R2. The format a file will be treated as is visible before ingesting it, in the words the ingest
  screen already uses, read from the file rather than guessed.
- R3. A file whose format is recognised but whose content is not a recognisable issuance is refused
  with that cause named, exactly as a PDF is.
- R4. An edition ingested from any source carries a pipeline stamp that describes the path its
  chunks actually came from, so that an unchanged re-ingest of it is a no-op for the same reason a
  PDF's is, and a dependency upgrade on that path invalidates it.
- R5. Reference extraction from a new source format is measured against its own recorded floor
  before it ships, on the same terms as the PDF parser.

**The extraction half**

- R6. Obligations can be extracted through an accredited managed service, configured rather than
  code-changed, with no model server on the operator's machine.
- R7. The adapter records the accreditation it relies on — which one, at what level, covering what
  material, and where that was verified — and an adapter that cannot name one does not run.
- R8. The managed adapter's served model satisfies the US-origin provenance rule, enforced by a
  test that examines the adapter actually configured rather than the local one.
- R9. The extraction gate fails rather than skips when an adapter that actually sends text has no
  recorded floors. `null` extracts nothing and is exempt — it is the default, and failing it would
  break R11.
- R10. The managed adapter's precision, recall and modality accuracy are recorded as floors before
  it is used for anything, measured on the existing gold set.
- R11. The `null` default stands: a fresh clone and CI still run with no model, no key, and no
  network.

**Both**

- R12. Neither adapter changes what an existing edition holds. Adding a source format does not
  re-chunk PDFs; adding an extractor does not re-extract editions already built.

### Acceptance Examples

- **AE1. A Word issuance enters the corpus.**
  **Given** a `.docx` of an issuance whose PDF is not to hand.
  **When** A1 picks it from the ingest screen and adds it.
  **Then** the map opens on that document with its references drawn, and its identity, effective
  date and reference list match what the same issuance's PDF would have produced. Its citations
  read `§ 4.2` rather than `p. 7`, and no citation anywhere in the corpus reports a page the source
  does not have.

- **AE2. A format the corpus does not read.**
  **Given** a file whose extension is not a recognised document or manifest source.
  **When** A1 opens the ingest picker.
  **Then** the file is listed with what it would be treated as, and that is neither "document" nor
  "manifest" — the screen does not offer an action that will fail.

- **AE3. A new source's chunks are stamped for their own path.**
  **Given** an edition ingested from a `.docx`.
  **When** the library that reads `.docx` text is upgraded and the same file is re-added.
  **Then** the ingest performs the full rewrite rather than reporting the edition unchanged,
  because the stamp named that library.

- **AE4. A managed adapter with no recorded floors.**
  **Given** `EXTRACTOR_ADAPTER` set to the managed adapter and no entry for it in `FLOORS`.
  **When** the backend suite runs.
  **Then** it **fails**, naming the adapter and what is missing. It does not skip, and it does not
  pass. Under the `null` default the same suite passes, because `null` sends nothing anywhere and
  has nothing to measure.

- **AE5. A managed adapter whose served model is not US-origin.**
  **Given** the managed adapter configured against a model outside the recorded US-origin set.
  **When** the backend suite runs.
  **Then** it fails on the provenance rule, naming the model and the set — the same failure a local
  adapter gets, reaching the adapter that is actually configured.

- **AE6. A fresh clone.**
  **Given** a clone with no `.env`, no model server and no API key.
  **When** the suite runs and the stack starts.
  **Then** both succeed, extraction is `null`, and nothing asks for a network.

- **AE7. An accreditation that cannot be named.**
  **Given** a managed adapter configured with no accreditation recorded for it.
  **When** the backend starts.
  **Then** it refuses at startup with that cause named, in the same way an unknown adapter name
  already does.

### Success Criteria

- A document the publisher issued as Word or HTML reaches the map without a manual conversion step,
  and its provenance records the file the publisher actually issued.
- An operator can extract clauses with no model installed, for any edition they rebuild. Coverage
  across the corpus is not what this delivers: obligations are written only by the per-edition
  rebuild job and there is no bulk route, so "one document in six" changes only as editions are
  rebuilt one at a time.
- No adapter — at either port — can ship without the gate that measures it having actually run.
- No citation anywhere in the product reports a page its source does not have, and a reader can
  still find the passage from what it does report.
- The three gates the dependency-map plan named as prerequisites are closed, and each is closed by a
  test that fails before the work and passes after.

### Scope Boundaries

- **Not** re-extracting the existing corpus. R12 holds: this plan adds capability, and running it
  over what is already there is an operator decision afterwards.
- **Not** OCR. A scanned PDF with no text layer is out of scope; it is a different problem with a
  different failure mode and its own quality gate.
- **Not** widening the US-origin set. If the accredited service's model is outside it, that is a
  stop condition and a review decision, not something this plan resolves.
- **Not** a second embedding adapter. ADR-024 governs embeddings and nothing here touches them.
- **Not** changing what the obligation panel renders. U8's interim behaviour becomes less visible
  as more editions get built, which is the point, but the panel's own states are unchanged.

### Dependencies

- **Prerequisite, met:** [ADR-041](../specs/adr/ADR-041-accredited-managed-inference-is-permitted.md)
  is accepted and supersedes ADR-016's blanket prohibition, replacing locality with accreditation.
- **Prerequisite, open:** a named managed service whose accreditation covers the material ADR-041
  permitted sending. Until one is named, U5 builds and its gate passes against a recorded endpoint,
  but nothing can be configured for real and no floor can be measured — which is U6 alone.
- **Prerequisite, open:** that service's served model must be in the US-origin set
  (`backend/tests/test_obligation_ratchet.py:33-40`) or the set widened by a recorded supply-chain
  decision first. ADR-041 states explicitly that ADR-020 is unaffected and still binds.

### Outstanding Questions

- **Which second source format first?** `.docx` and `.html` have different shapes: `python-docx`
  gives structured paragraphs and headings, which suits the section-path logic well; HTML gives a
  DOM whose heading structure is often more reliable than a PDF's but whose boilerplate is worse.
  Resolved in KTD2 as a decision for implementation to make on evidence, with the plan written so
  either fits.
- **Which managed provider?** The one question this plan leaves open, deliberately. The adapter is
  written to a port; the provider is a procurement decision with an accreditation attached, and
  naming one in a plan would make it look settled.

  **Settled this session (user-directed): U5 is built now against a stub, and only U6 waits.** Every
  behaviour U5 owns is a property of the adapter rather than of any provider, and each is testable
  against a recorded endpoint: the port contract, the accreditation gate that refuses to construct
  without a named accreditation, the https-only check, retry-on-429, the refusal of an empty or
  unsubstituted key, and the log redaction. What a stub cannot supply is a *number* — so U6, which
  measures and records floors, is the only unit that stays blocked, along with the Definition of
  Done clause that depends on those floors. U1–U5, U7 and U8 can all land while the provider
  question stays open.
- ~~**What does a chunk's `page` report for a source with no page boundaries?**~~ **Settled this
  session (user-directed).** `page` becomes nullable and a pageless source cites by section path.
  The reasoning and the three rejected alternatives are recorded in **KTD7**, which governs R1;
  R1's parity promise and AE1 are written to match. The work is **U8**, which lands before U2 —
  including the one-line ADR-026 amendment saying a pageless citation is still a citation
  (AGENTS.md:116).
- ~~**Does ADR-013's status line need to record ADR-041?**~~ **Settled this session
  (user-directed): add the cross-reference.** ADR-041's substance already governs extraction (see
  Authority hierarchy); only the bookkeeping is missing, and a second accreditation ADR would
  duplicate a decision rather than record a new one. A status line is the amendment ledger, not the
  decision — ADR-016 already reads "Accepted, amended by ADR-041" and ADR-013 already reads
  "Accepted, amended by ADR-034", so this follows the precedent rather than setting one. The edit is U5's, in the same PR as the
  adapter it describes (AGENTS.md:116); the body of ADR-013 is not touched.
- ~~**Where is this corpus's classification recorded?**~~ **Settled this session (user-directed):
  ADR-041 already recorded it.** ADR-041 decided managed inference is permitted for *this* corpus,
  which is a judgment about exactly this material; treating that as unrecorded would reopen a
  decision already taken. R7's "covering what material" is therefore satisfied by citing ADR-041,
  and the accreditation gate checks a named accreditation against it rather than against a
  classification marking the repo does not hold. If a marking is ever assigned, it belongs in an ADR
  of its own and R7's check narrows to it.
- ~~**What per-edition and per-push spend is the managed adapter allowed?**~~ **Settled this
  session (user-directed): recorded as an operational note, not enforced as a cap.** A 204-chunk
  edition is 204 metered calls, and once U3 and U6 land a routine `uv run pytest` sends the whole
  gold set to the provider whenever `.env` names the managed adapter. That is permitted under
  ADR-041 and is a property of the `null` default being deliberately safe: a machine with no key
  spends nothing, so the exposure exists only where an operator has already chosen to configure one.
  A cap belongs to whoever holds the account, with the provider's own budget controls, rather than
  to this adapter — a spend limit enforced in the extractor would fail an edition halfway and leave
  it partly extracted, which is worse than a bill. U5 records the exposure in the adapter's
  docstring and in `.env.example` beside the key, so nobody configures one without reading it.

### Sources

- `docs/plans/2026-09-17-0801-feat-dependency-map-home-plan.md:203-205` — where the three
  prerequisites for a managed adapter were first written down, and the origin of this plan.
- `backend/src/policy_grapher/extraction/__init__.py` — the port, its contract, and the dispatch
  that must learn a third name.
- `backend/src/policy_grapher/sources/__init__.py` — the ingestion dispatch and `DOCUMENT_SUFFIXES`.
- `backend/src/policy_grapher/pipeline.py` — the stamp, and the docstring that explains why it is
  derived rather than declared.
- `backend/tests/test_obligation_ratchet.py` — the gate that skips, and the test that only examines
  the local adapter.

---

## Planning Contract

### Key Technical Decisions

- **KTD1. The new source is a module behind the existing dispatch, not a branch inside `pdf.py`.**
  `is_document_source` answers a suffix question and `ingest_file` dispatches on its result
  (`sources/__init__.py:20-22`). A second format becomes a sibling module exposing the same
  `extract_document(path) -> ExtractedDocument` shape, and the dispatch grows a mapping from suffix
  to reader rather than a conditional. The `ExtractedDocument` dataclass
  (`sources/document.py:28-39`) is already format-agnostic — name, references,
  `self_references_skipped`, report, effective date, pages — which is the evidence the port was
  designed for this. Governs R1, R3.

- **KTD2. Which format ships first is decided by a measured gate with four parts, not by
  preference.** A reader can clear reference recall and still get identity, date or text wrong, so
  the gate is: correct issuance identity on every fixture; correct effective date; reference recall
  at or above the floor the PDF parser already holds for a comparable corpus; and a section path
  good enough to locate a clause, since per KTD7 that is what a pageless source cites by. Ties go
  to the format with the higher recall on the larger fixture set. A format that cannot clear all
  four is not a format this corpus can accept, whatever its convenience. Governs R1, R5.

- **KTD3. The pipeline stamp becomes source-aware, and this is not optional.**
  `_STAGES = (pdf, chunking, chunks)` and the stamp's first part is literally
  `f"pypdf=={pypdf.__version__}"` (`pipeline.py:36,71`). A `.docx` edition ingested today would
  carry a stamp naming the PDF path — so a `python-docx` upgrade would change its stored text while
  the stamp stayed identical, and the next unchanged re-add would report "already present" over
  text the pipeline no longer produces. That is precisely the loss ADR-039 refused re-anchoring to
  avoid, reached by the route `pipeline.py`'s own docstring warns about. The stamp must name the
  reader that actually read the file and that reader's own dependency version. Governs R4, R12.

  *Rejected alternative:* one global stamp carrying every reader's dependency and digest
  (`_STAGES = (pdf, <new>, chunking, chunks)`), which closes the same hole with no signature change
  and no call-site churn. It loses because a bump to a reader an edition never used would
  invalidate that edition anyway, and under ADR-039 each spurious invalidation discards its
  obligations and reviewed links. So this is a preference with a reason rather than a necessity —
  worth saying, because a reader who tests "not optional" and finds an alternative stops trusting
  the rest of the section.

- **KTD4. The managed adapter is a peer of `local`, not a subclass of it.**
  Both speak to an HTTP endpoint, and the temptation is to parameterise `LocalExtractor` by base
  URL. Resist it: `adapter_id` participates in the cache key and in the floors table, and an
  adapter that can be pointed at two different providers under one id makes both meaningless. A
  separate module with its own `adapter_id`, its own `cache_variant`, and its own accreditation
  record. Governs R6, R7, R10.

- **KTD5. The accreditation is a required field on the adapter, checked at startup.**
  ADR-041 says an adapter that cannot name its accreditation is an unaccredited adapter. The
  cheapest way to make that true rather than aspirational is to make construction fail without it,
  in `build_extractor`, where an unknown adapter name already fails at startup rather than
  mid-ingest. Governs R7, AE7.

- **KTD6. The two gate widenings land before the adapter, not with it.**
  U6 and U7 in the dependency-map plan established the pattern: ship the protection before the
  thing it protects. `test_the_shipped_model_has_recorded_floors` must reach the configured adapter
  and the floors check must fail rather than skip **while `local` is still the only real adapter** —
  because `local` and its recorded floors give the gate change a control to check it against.
  Widening them alongside a new adapter means the first run of the new gate is also the first run
  of the new adapter, and a failure could be either. The constraint is isolation, not opportunity:
  `local` does not stop being a control once the managed adapter exists, so what matters is keeping
  the two changes out of the same first suite run. Governs R8, R9.

- **KTD7. A citation from a pageless source says what it has, and does not invent a page.**
  `page` becomes nullable. A source with no page boundaries cites by its section path — the reader
  sees `§ 4.2`, never `p. 7` standing for "the seventh section". ADR-026 already establishes that
  `page` "was never part of any identity — not `chunk_id`, not `obligation_id`", so this re-keys
  nothing; what changes is what a citation looks like when the locator is absent, which ADR-026 has
  to say is still a citation — U8 carries that edit and the eight call sites it implies.
  (session-settled: user-directed — chosen over requiring real page boundaries, which rules out
  both candidate formats and closes the ingestion half; over mapping a section index onto `page`,
  which would render "p. 7" for a seventh section and is the false precision this codebase designs
  against; and over deriving pages by rendering to PDF, whose
  pagination depends on fonts and renderer version and would have to join the pipeline stamp.)
  Governs R1, and is built by U8.

### High-level design

```
                    ingest_file(path)
                           │
              sources/__init__: dispatch on suffix
                    ┌──────┴───────┐
              manifest.py     DOCUMENT_READERS
                              ┌────┴────┐
                           pdf.py    <new>.py        ← U2
                              └────┬────┘
                          ExtractedDocument
                                   │
                          chunking → chunks
                                   │
                    pipeline stamp: reader + its dep    ← U1 (KTD3)
                                   │
                            :DocumentVersion

                    rebuild / extraction path
                                   │
                    build_extractor(settings)
                    ┌──────────┬───────────┐
                 null.py   local.py   managed.py       ← U5
                              accreditation required   ← U5 (KTD5)
                                   │
                    FLOORS[adapter_id] — gate fails,
                    never skips, whichever adapter     ← U3, U4
```

### Assumptions

- The gold set (`backend/tests/fixtures/gold`) is format-agnostic — it holds text passages and
  their expected obligations, not PDFs — so a managed adapter is scored on exactly the terms the
  local one is, and the ingestion half does not disturb it. **Verify before U6.**
- The obligation floors do not depend on which source produced the chunk. Chunk *text* is what the
  extractor sees, and two readers producing the same text produce the same obligations. A format
  whose text differs materially from the PDF path's is a KTD2 signal, not a floors problem.
- `ExtractedDocument.pages` is what chunking consumes, so a new reader's only obligation to the
  downstream pipeline is to produce page-ordered text. **Verify against `chunking.py` before U2.**

### Implementation constraints

- **Never widen `US_ORIGIN_MODELS` to make a test pass.** The comment above it says adding to the
  set is a supply-chain decision argued in review. A managed model outside it is a stop condition.
- **The `null` default is not negotiable** (R11, ADR-041). No unit may make a fresh clone need a
  key.
- **No unit re-extracts or re-chunks existing editions.** R12. The pipeline-stamp change in U1 will
  invalidate existing stamps by construction — see its unit note for why that is acceptable and
  what it costs.

### Sequencing

1. **U1 before U2.** The stamp must be able to describe a second reader before a second reader
   exists, or the first `.docx` edition ingested carries a stamp that lies about it.
2. **U8 before U2.** `page` must be able to be absent before the first edition that has no pages is
   ingested. Landing U2 first would either block on a non-null column or write a fabricated page
   into storage, and the second is unrecoverable without re-ingesting.
3. **U3 and U4 before U5.** KTD6: the gate widenings are demonstrated against `local`, where a
   failure can only mean the gate changed.
4. **U5 before U6, and U6 waits for a provider.** The adapter must exist before its floors can be
   measured, and the measurement needs a real endpoint. U5 lands against a stub; U6 is the only
   unit that stops here.
5. **U7 after U2.** The new format's fixtures cannot be ratcheted before the reader that produces
   them exists.
6. **U2 and U5 are independent of each other**, with one seam: `links/rebuild.py` is the only path
   that applies a newly configured extractor to an edition already ingested, so a non-PDF edition
   stays unreachable by the managed adapter until U2's reader dispatch reaches rebuild. U1, the
   gate units and U7 supply the rest of the internal ordering.

---

## Implementation Units

### U1. The pipeline stamp names the reader that actually read the file

- **Goal:** An edition's stamp describes the path its chunks came from, so that adding a second
  reader cannot produce editions whose stamp is about a different one.
- **Requirements:** R4, R12.
- **Dependencies:** none. This is the first unit.
- **Files:** `backend/src/policy_grapher/pipeline.py`, `backend/src/policy_grapher/ingest.py`,
  `backend/src/policy_grapher/chunks.py`, `backend/tests/test_chunks.py`,
  `backend/tests/test_ingest.py`, `backend/src/policy_grapher/links/rebuild.py`, and a new
  `backend/tests/test_pipeline_stamp.py`.
  The stamp already has two homes and they stay where they are:
  `test_chunks.py:560` covers writing it onto an edition and `:585` covers the empty-chunk case,
  while `test_ingest.py` covers the no-op it enables. What has no home today is the stamp's own
  *composition* — which stages contribute and what a reader's dependency adds — and that is what
  the new file is for.
- **Patterns to follow:** the existing `_stage_digest` reads a module's source off disk and hashes
  it; the reader-specific part is the same idea with the module chosen at call time rather than
  fixed in `_STAGES`. The docstring at `pipeline.py:1-22` is the reasoning to preserve — it already
  argues the general case, and this change is that argument applied to a second reader.
- **Approach:**
  1. `pipeline_stamp()` takes the reader module it is stamping for, rather than closing over `pdf`.
     **The parts list keeps its current order exactly**: the reader's declared dependency first
     (`pypdf==<version>` on the PDF path), then the reader's digest, then `chunking`, then `chunks`.
     The stamp is a hash over a joined list, so preserving those positions makes
     `pipeline_stamp(pdf)` byte-identical to the stamp every existing edition already carries.
     Appending the reader *after* the invariant stages would instead invalidate all six live
     editions — that ordering, and nothing else, is what turns this unit destructive.
  2. The reader's own external dependency version joins the stamp the way `pypdf` does. A reader
     declares the dependency it reads with, so the stamp does not have to know the mapping.
  3. Every call site passes the reader it used. `ingest.py` knows it, because it chose it.
     `links/rebuild.py:282-283` is the other one and is easy to miss: it calls `pipeline_stamp()`
     and then `pdf.extract_document(path)` on a path it resolves from the edition's stored
     `source_uri` (`:63,:91`), so it has no reader in hand and must re-dispatch on that URI's
     suffix through the same mapping U2 introduces. It is also the only path that applies a newly
     configured extractor to an edition already ingested — leave it PDF-only and the managed
     adapter can never reach a document added in the new format.
  4. Keep the derived-not-declared property: no reader supplies a version string by hand.
- **Note on what this unit must not do.** Done as step 1 describes, no existing edition's stamp
  moves and there is no migration. Done with the reader appended after the invariant stages, every
  one of the six live editions is invalidated and its next unchanged re-add becomes a full rewrite,
  discarding 344 obligations and 27 approved review verdicts. There is no re-stamp script, doc or
  commit in this repo to fall back on, and `versions.py:134-137` treats an absent or mismatched
  stamp as a full rewrite by design — so the byte-identity check below is the safeguard, not a
  recovery plan.
- **The stamp digests module source bytes**, specifically `sources/pdf.py`, `chunking.py` and
  `chunks.py` (`pipeline.py:36,41-50`). Any later unit that edits one of those re-invalidates every
  edition even when chunk text is unchanged — U2's own approach invites exactly that, by lifting
  shared reference logic out of `pdf.py`. The pre-merge stamp check therefore belongs to every unit
  touching those three modules, not to U1 alone.
- **Test scenarios:**
  - Two readers with different module sources produce different stamps for the same bytes.
  - The same reader produces a stable stamp across calls, and a changed reader source changes it.
  - A bump in the reader's declared dependency version changes the stamp with no repo change.
  - An edition ingested through reader A and re-added through reader A is a no-op; one re-added
    after A's dependency changes is a full rewrite.
  - **An existing PDF edition's stored stamp still matches after the change.** This is the
    byte-identity guard; a difference is a stop, not a migration.
  - A rebuild of a PDF edition resolves the PDF reader from its `source_uri` and stamps with it.
  - The stamp is not memoised — a cached stamp leaked a monkeypatched value between tests once
    before, and the docstring recording that must survive this change.
- **Verification:** `cd backend && uv run pytest`; and against the live stack, `pipeline_stamp(pdf)`
  computed against the six stored stamps with every one matching, then `POST /ingest` on an
  unchanged file still reporting `outcome: unchanged`.

### U2. A second document format enters the corpus

- **Goal:** A document the publisher issued in a format other than PDF can be added from the
  picker and produces the same identity, references and text its PDF would — citing by section path
  where the format has no pages (KTD7).
- **Requirements:** R1, R2, R3.
- **Dependencies:** U1, U8. The reader emits `page=None` for a pageless format, which U8 makes
  representable; ingesting one before U8 would write a fabricated page into storage.
- **Files:** `backend/src/policy_grapher/sources/__init__.py`,
  `backend/src/policy_grapher/sources/<format>.py`, `backend/tests/test_<format>_extraction.py`,
  `backend/src/policy_grapher/links/rebuild.py`, `backend/tests/test_sources.py`,
  `frontend/src/views/Ingest.tsx`, `frontend/src/views/Ingest.test.tsx`
- **Patterns to follow:** `sources/pdf.py` is the whole shape — `pages_of`, `text_of`,
  `locate_references`, `identifier`, `document_name`, `_cover_page`. Much of it operates on text
  rather than on PDF structure and is reusable as-is; the format-specific part is getting
  page-ordered text out of the file. Note the regexes are tuned to pypdf's output shape — inline
  page footers, hard wrapping, line-anchored entry boundaries — so "format-independent" needs
  checking rather than assuming. On the frontend, `describeKind` labels by extension for manifests
  only and returns a literal `'PDF document'` for every document kind (`Ingest.tsx:19-20`); that is
  the line R2 exists to fix, not a pattern to follow.
- **Approach:**
  1. Decide the format on measured reference recall (KTD2) before committing to it.
  2. New reader module exposing `extract_document(path) -> ExtractedDocument`.
  3. `DOCUMENT_SUFFIXES` becomes a suffix→reader mapping; `is_document_source` keeps its signature.
  4. Reuse `pdf.py`'s text-level reference logic rather than reimplementing it — extract what is
     genuinely format-independent into a shared module if it is not already reachable.
  5. The ingest picker labels the new kind in its own words, **and the document branch has to learn
     to**: `describeKind` reads the extension only inside the manifest branch and hardcodes
     `'PDF document'` for every document kind, so a `.docx` would be offered as a PDF. The
     STORY-036 fix never reached the branch this unit widens.
  6. A file whose kind is neither document nor manifest is not selectable, per AE2.
- **Test scenarios:**
  - A fixture of the new format produces the identity, effective date and references its PDF twin
    produces.
  - A file of the new format with no recognisable issuance header raises `DocumentSourceError`, and
    `POST /ingest` answers 400 with that cause.
  - `list_sources` labels the new extension distinctly from both "PDF document" and "manifest".
  - A manifest is still dispatched as a manifest; nothing about the CSV/XLSX path changes.
  - An extension nothing reads is listed with a kind that is neither document nor manifest, **and
    the picker does not offer it as a selectable option** — AE2 requires that the screen not offer
    an action that will fail, which a label alone does not achieve.
  - The picker labels the new extension by its own name rather than as a PDF.
  - A malformed, oversized, or decompression-bomb file of the new format is refused within bounded
    memory and time rather than exhausting the process.
  - The reader resolves no external resource — no network fetch, no entity expansion — while
    parsing. Both candidate formats can reference outside themselves; a document source must not.
  - Re-adding the new format's fixture after bumping its reader's declared dependency performs a
    full rewrite rather than reporting `unchanged` (AE3).
- **Verification:** the new fixture ingests through the UI and lands on its map with references
  drawn; `POST /ingest` on it twice reports `unchanged` the second time.

### U3. The floors gate fails rather than skips, whichever adapter is configured

- **Goal:** An adapter with no recorded floors fails the suite instead of passing it quietly.
- **Requirements:** R9.
- **Dependencies:** none. Deliberately before U5 (KTD6).
- **Files:** `backend/tests/test_obligation_ratchet.py`
- **Patterns to follow:** the skip's own message already says the right thing — "THE EXTRACTION
  GATE DID NOT RUN" — it simply says it while passing. The reachability skip below it
  (`:332-336`) is a different case and stays a skip: a missing model server is an environment
  fact, not a missing measurement.
- **Approach:**
  1. The no-floors arm becomes a failure for every adapter that sends text somewhere, and keeps its
     skip for `null`. Guard it the way the arm immediately below already guards itself
     (`settings.extractor_adapter != "null"`, `:332`). **Do not give `null` a `FLOORS` entry** — the
     file's own comment records `FLOORS["null"]` having been removed for making the gate vacuous.
  2. The unreachable-server arm asks the *configured adapter* whether its own service answered,
     rather than probing `settings.extractor_base_url`. That probe pings `/api/tags` on
     `http://localhost:11434` (`:216-220`, `config.py:61`) — Ollama's endpoint — so with the managed
     adapter configured it finds nothing and skips, leaving a green suite that measured nothing.
     That is the defect this unit exists to close, surviving the unit. Reachability joins
     `adapter_id` and `cache_variant` on the port.
  3. Keep the two messages distinguishable, so a reader can tell "nobody measured this" from "the
     measurer could not run here".
  4. Confirm the change fails for the right reason by configuring an adapter name with no floors
     entry and observing the failure, then restoring.
- **Test scenarios:**
  - With floors recorded and a reachable model, the gate runs and passes as before.
  - With no floors recorded for a text-sending adapter, the suite **fails**, naming the adapter.
  - **On a fresh clone with no `.env` — adapter `null` — the suite passes.** This is R11 and AE6,
    and it is the scenario that makes the rest of this unit safe to land.
  - With floors recorded but no server, the suite still skips, and its message says which of the
    two cases it is.
  - **With the managed adapter configured and its floors recorded, the gate runs rather than
    skipping on the local model server's URL.**
- **Verification:** `cd backend && uv run pytest -k obligation_ratchet`, and the deliberate
  no-floors run failing.

### U4. The provenance and floors tests examine the configured adapter

- **Goal:** The two tests that currently only ever look at `local` reach whichever adapter the
  stack is actually running.
- **Requirements:** R8.
- **Dependencies:** none. Independent of U3; both precede U5.
- **Files:** `backend/tests/test_obligation_ratchet.py`, `backend/tests/test_config_composition.py`,
  `docker-compose.yml`, `.env.example`
- **Patterns to follow:** `test_the_shipped_model_has_recorded_floors` constructs
  `Settings(_env_file=None, extractor_adapter="local")` (`:386`) — the hardcoding is the defect.
  `test_the_default_extraction_model_is_us_origin` reads `Settings().extractor_model`, which is the
  *local* adapter's model field, so a managed adapter with its own model setting would evade it
  entirely.
- **Approach:**
  1. Both tests resolve the adapter under test from `Settings()` — the repo `.env`, the
     configuration the stack actually runs — **not** `Settings(_env_file=None)`. That distinction is
     the whole of STORY-060: `test_config_composition.py`'s docstring records the ADR-020 test
     asserting on `_env_file=None`, passing on every machine, while compose shipped `qwen3:8b` to
     every container.
  2. The provenance test asserts against the served model the configured adapter reports, not
     against a field that belongs to one adapter.
  3. Both tests short-circuit when the configured adapter sends text nowhere (`null`), asserting
     that it reports no served model rather than failing on a model that does not exist or passing
     vacuously.
  4. The served model comes out of the `adapter_id` convention `FLOORS` already uses
     (`local:llama3.1:8b`), so no new field joins the port for this.
- **Test scenarios:**
  - Under the default (`null`), both tests pass by short-circuit, asserting that `null` reports no
    served model — not by skipping and not vacuously.
  - Under `local`, both behave exactly as they do today — this unit changes reach, not verdicts.
  - A hand-constructed settings object naming a non-US-origin model fails the provenance test,
    whichever adapter names it.
  - The shipped `docker-compose.yml` and `.env.example` `EXTRACTOR_ADAPTER` defaults are not the
    managed adapter. `DELIBERATE_DIFFERENCES` exempts `extractor_adapter` **by name**
    (`test_config_composition.py:48`), so a compose default naming it is otherwise compared against
    nothing.
- **Verification:** `cd backend && uv run pytest -k "ratchet or provenance"`, green before and
  after under `null` and `local`.

### U5. The managed extraction adapter

- **Goal:** Obligations can be extracted through an accredited managed service, configured rather
  than code-changed, with no model on the operator's machine.
- **Requirements:** R6, R7, R11.
- **Dependencies:** U3, U4.
- **Built against a recorded endpoint, not a named provider** (session-settled: user-directed).
  Every behaviour below is a property of the adapter rather than of any one provider, and each of
  its test scenarios runs against a stubbed transport: the port contract, the accreditation gate,
  the https check, retry-on-429, the key refusal, and the log redaction. Only a *measured number*
  needs a real endpoint, which is U6. Where the accreditation record's fields are not yet knowable,
  they are written as the constant the gate reads and the gate is tested by withholding them — a
  placeholder that makes construction succeed would invert the unit's whole point.
- **Files:** `backend/src/policy_grapher/extraction/managed.py`,
  `backend/src/policy_grapher/extraction/__init__.py`, `backend/src/policy_grapher/config.py`,
  `backend/tests/test_extraction_adapters.py`, `.env.example`,
  `docs/specs/adr/ADR-013-obligation-extraction-is-a-port.md`
- **Patterns to follow:** `extraction/local.py` is the reference implementation — `adapter_id` as a
  property, `cache_variant`, the `extract` signature with `on_drop`, and the schema-constrained
  decoding. `null.py` shows the minimum. `build_extractor` is where the third name is learned, and
  its existing `ValueError` on an unknown name is the pattern KTD5 extends.
- **Approach:**
  1. New module implementing the port, with its own `adapter_id` embedding the served model the way
     `local`'s does.
  2. `cache_variant` carries whatever else varies the answer — decoding mode, prompt version.
  3. **The accreditation record is a module-level constant in `managed.py`, never a Settings
     field** — which accreditation, at what level, covering what material, the endpoint and served
     model it was verified against, and the date. "Covering what material" cites ADR-041, which is
     where the judgment about this corpus was recorded; there is no separate classification marking
     to check against, and inventing one would be the false precision this codebase designs against.
     In `.env` it would be a string an operator types,
     and ADR-041's "recorded, not assumed" would be satisfied by typing anything. `US_ORIGIN_MODELS`
     is an in-repo frozenset for exactly this reason: changing it has to show up in a diff.
     Construction fails when the configured endpoint is not the one the record names (KTD5, AE7).
  4. **The base URL must be `https`**, checked at construction on the same startup-failure route.
     `local.py` does `base_url.rstrip("/")` with no scheme check because it targets loopback; an
     `http://` managed URL would put policy text on the open network with a key attached.
  5. Settings gain the managed adapter's own fields. `extractor_adapter` default stays `null`.
  6. **The key ships in `.env.example` as an empty value, not an `init-env.sh` placeholder** — that
     script substitutes exactly three tokens (`__NEO4J_PASSWORD__`, `__API_TOKENS__`,
     `__API_TOKEN__`), so a fourth would be copied verbatim into `.env` and sent to the provider as
     a credential. Construction refuses an empty or unsubstituted key, the way
     `neo4j_password`'s deliberately non-functional default fails loudly at startup.
  7. **`adapter_id` carries the provider's immutable model or deployment revision**, not just a
     configured alias. A provider retargeting an alias behind a stable name would otherwise reuse
     cached extractions and keep floors measured against a model that is no longer there. Fail
     closed if the provider exposes no such revision.
  8. **Nothing the adapter logs or raises contains the key or the chunk text.** A diagnostic that
     echoes either moves the egress decision out of the adapter boundary, which is where ADR-041
     puts it.
  9. **ADR-013's status line gains ADR-041**, in this PR with the adapter it describes
     (AGENTS.md:116). Bookkeeping only: the body of ADR-013 is not touched, and the wording follows
     how ADR-013 already records ADR-034.
  10. **The metered-call exposure is written down where an operator will meet it** — the adapter's
      module docstring and a comment beside the key in `.env.example`: a 204-chunk edition is 204
      metered calls, and a `uv run pytest` on a machine whose `.env` names this adapter sends the
      whole gold set. No cap is enforced here (session-settled: user-directed). A limit inside the
      extractor would fail an edition halfway and leave it partly extracted, which is worse than a
      bill; the account holder's own budget controls are the right place. The `null` default means a
      machine with no key spends nothing, so the exposure only exists where someone configured one.
- **Test scenarios:**
  - `build_extractor` returns the managed adapter when configured, and still raises on an unknown
    name.
  - Constructing it without an accreditation record raises, and the message names what is missing.
  - `adapter_id` changes when the served model changes — the cache-key contract the port states.
  - `on_drop` is called once per discarded item with a reason, as ADR-030 requires of every adapter.
  - A response the schema rejects drops the item and reports it rather than raising.
  - A base URL that is not `https` raises at construction, naming the scheme.
  - An endpoint the recorded accreditation does not name raises at construction.
  - An empty or unsubstituted key raises at construction rather than failing at the provider.
  - A throttled response (429) is retried honouring `Retry-After`; an exhausted quota ends the run
    with that cause named rather than as an unhandled transport error. `local.py`'s
    `RETRYABLE_STATUS` is `{500, 502, 503, 504}` and `links/rebuild.py:334` catches only
    `ValueError`, so a 429 inherited unchanged would end a whole rebuild.
  - Neither the key nor chunk text appears in any log line or exception message.
  - With `EXTRACTOR_ADAPTER` unset, nothing constructs the managed adapter and nothing reads a key.
  - Every scenario above runs against a stubbed transport; none requires a named provider. Confirm
    that by running the unit's tests with no network reachable — a scenario that needs one has
    strayed into U6.
- **Verification:** `cd backend && uv run pytest`; and a fresh clone with no `.env` still starting
  and still passing (AE6).

### U6. The managed adapter's floors are measured and recorded

- **Goal:** The gate that U3 made real has something to gate the new adapter with.
- **Requirements:** R10.
- **Dependencies:** U5, **and a named managed service** — the one open prerequisite in this plan.
  This is the only blocked unit: a floor is a measurement, and a measurement needs the real
  endpoint. Do not record a provisional floor to unblock it. A guessed floor either sits low enough
  to pass anything, which makes the gate vacuous again in exactly the way U3 existed to fix, or
  high enough to fail honestly-good extraction. The gate skipping for a configured-but-unmeasured
  adapter is not an option either — U3 removes that skip deliberately.
- **Files:** `backend/tests/test_obligation_ratchet.py`
- **Patterns to follow:** `FLOORS` is keyed by `adapter_id` and holds `precision`, `recall` and
  `modality_accuracy` separately, for the reason the module docstring gives: an aggregate absorbs a
  SHALL read as a SHOULD, and this is a compliance tool. Floors ratchet up only.
- **Approach:**
  1. Run the adapter against the existing gold set.
  2. Record the three numbers as its floors, at or below the measured run, with the measurement
     date and the served model in the comment — matching how `local:llama3.1:8b` is recorded.
  3. If any number is below the local adapter's on the same set, stop: that is a stop condition,
     not a floor to record.
- **Test scenarios:**
  - With the managed adapter configured and floors recorded, the gate runs and passes.
  - Lowering a recorded floor without a reason is visible in review — the comment convention is the
    control, and this unit keeps it.
  - `test_the_gate_has_teeth` still demonstrates the gate can fail.
- **Verification:** the gate running rather than skipping against the managed adapter, with its
  scores recorded in the commit message.

### U7. A new source format's reference extraction is ratcheted

- **Goal:** The second format's reference recall is measured before it ships, on the same terms as
  the PDF parser's.
- **Requirements:** R5.
- **Dependencies:** U2.
- **Files:** `backend/tests/test_extraction_ratchet.py`, `backend/tests/fixtures/editions`,
  `data/samples` — the directory `SAMPLES` resolves to and where the new format's fixture file has
  to be committed for the widened glob to see it.
- **Patterns to follow:** `test_every_sample_pdf_is_ratcheted` refuses an exclusion list on purpose
  — "the absence of one is the claim that none is needed" — and globs `SAMPLES.glob("*.pdf")`. That
  glob is PDF-shaped and will not see a new format's fixtures.
- **Approach:**
  1. The completeness test covers every sample file the ingestion *document* dispatch would accept,
     not every PDF — and not the manifests, which share `data/samples` and have no reference floor
     to hold.
  2. The new format's fixtures get `RATCHETS` entries with measured floors.
  3. Keep the no-exclusion-list property: if a fixture cannot be ratcheted, that is a finding.
- **Test scenarios:**
  - A sample file of the new format with no ratchet entry fails the completeness test.
  - The new format's fixtures meet their recorded floors.
  - Existing PDF ratchets are unchanged — this unit widens reach, not numbers.
- **Verification:** `cd backend && uv run pytest -k extraction_ratchet`, and a deliberately
  unratcheted fixture failing.

---

### U8. A citation with no page says so, rather than reporting one

- **Goal:** `page` can be absent, and every surface that renders a citation says where the passage
  is without claiming a page the source does not have (KTD7).
- **Requirements:** R1 (its locator clause).
- **Dependencies:** none. **Lands before U2**, because the first pageless edition must not be
  ingested into a model that cannot represent it.
- **Files:** `backend/src/policy_grapher/chunking.py`, `backend/src/policy_grapher/models.py`,
  `backend/src/policy_grapher/routers/ask.py`, `backend/src/policy_grapher/export.py`,
  `frontend/src/api/types.ts`, `frontend/src/views/Ask.tsx`, `frontend/src/views/Pairings.tsx`,
  `frontend/src/views/Review.tsx`, `frontend/src/views/Triage.tsx`,
  `frontend/src/views/NodeObligationsPanel.tsx`, `frontend/src/views/DocumentDetail.tsx`,
  `docs/specs/adr/ADR-026-a-chunks-page-is-its-own-page.md`
- **Patterns to follow:** the repo's existing way of holding two empty-looking states apart — `null`
  against `[]` for an editions read that failed versus a document with none (GraphExplorer), and the
  five readings of a zero obligation count. A missing page is the same shape: "this source has no
  pages" is a fact about the format, not a failure to record one.
- **Scope, measured rather than estimated.** `page: int` is declared in six places — the stored
  chunk (`chunking.py:54`) and five response models (`models.py:206,222,260,454,532`) — and read in
  eight: the prose citation the answer is built from (`routers/ask.py:135`), the export column
  (`export.py:51`), and six render sites (`Ask.tsx:99`, `Pairings.tsx:108`, `Review.tsx:21`,
  `Triage.tsx:36`, `NodeObligationsPanel.tsx:257`, `DocumentDetail.tsx:979`). Every one is in scope;
  a missed site renders `p. None` or `p. null` to a reader, which is worse than the false precision
  KTD7 refused.
- **Approach:**
  1. `page` becomes `int | None` at the six declarations, and the frontend type follows.
  2. **Each of the eight readers renders the section path alone when `page` is absent**, rather than
     a placeholder. `§ 4.2` is a locator; `p. —` is a gap where one should be.
  3. `routers/ask.py:135` is the one that matters most: it composes the citation string that goes
     into the answer's prose, so an unhandled `None` becomes `p. None` in text a reader is asked to
     trust. Its `_cite` grows the same branch, and a test asserts on the composed string.
  4. `export.py:51` carries the null through rather than defaulting it — an export that invents
     `page 0` is the same lie in a different file format.
  5. **ADR-026 gains a line** saying a citation whose source has no pages is still a citation, and
     cites by section path. Its existing decision — that a page "was never part of any identity" —
     is what makes this additive rather than a supersession; the body is otherwise untouched
     (AGENTS.md:116).
- **Test scenarios:**
  - A chunk with `page=None` round-trips through storage and each of the five response models.
  - `_cite` on a pageless citation composes a string with no `p.` in it, and with the section path
     still present — assert on the whole string, since that is what a reader sees.
  - Each of the six render sites shows the section path and no `p.` for a pageless obligation, and
    is unchanged for one with a page.
  - The export of a pageless chunk carries an empty page rather than a zero.
  - **The mutation that must fail:** make any one reader fall back to a literal (`page or 0`,
    `page ?? 1`). The test that catches it asserts the rendered text contains no `p.`, not merely
    that the component rendered — per rule 4, a gate must exercise the thing it gates.
- **Verification:** `cd backend && uv run pytest`; `cd frontend && npm test`, judged by exit code.
  Then by hand: a pageless document's citations read as section paths on all six surfaces.

## Verification Contract

- **Backend:** `cd backend && uv run pytest`. The full run is the gate. `-m "not integration"`
  skips the container-backed tests during iteration only.
- **Frontend:** `cd frontend && npm test` — lint at zero warnings, then a full type build, then the
  tests. **Judge it by its exit code, not by the printed count**: this runner reports work that
  throws outside a test body as an unhandled error while every per-test tally still says passed
  (`docs/solutions/workflow-issues/the-test-count-is-not-the-verdict.md`).
- **The extraction gate must be seen to fail.** U3's change is only demonstrated by configuring an
  adapter with no floors and watching the suite go red. A green suite after U3 proves nothing on its
  own, because a green suite is exactly what the defect produced.
- **Floors are recorded from a measured run, not chosen.** U6's numbers come from running the
  adapter on the gold set, and the commit message carries them.
- **The stamp check is a gate on every unit that touches a digested module, run before merge.**
  Compute `pipeline_stamp(pdf)` and compare against the six stored stamps; any difference is a stop,
  not a migration. It applies to U1 and to any later unit editing `sources/pdf.py`, `chunking.py` or
  `chunks.py` — U2's shared-logic extraction being the likely one. The six live editions hold 344
  obligations and 27 approved review verdicts between them, there is no re-stamp procedure in this
  repo, and `versions.py:134-137` treats a mismatched stamp as a full rewrite by design.
- **A fresh clone with no `.env` is part of the gate for U5.** AE6 is not a nicety; it is ADR-041's
  third clause.
- **U5 is verified against a stubbed transport, with no network reachable.** A scenario that needs a
  live provider belongs to U6; running U5's tests offline is how that boundary is kept honest.
- **U8 is verified by what is absent.** Its render tests assert the absence of `p.` in the output
  rather than the presence of a component, because a fallback literal (`page or 0`) would satisfy
  any test that only checks the surface rendered — rule 4, a gate must exercise the thing it gates.

## Definition of Done

- R1–R12 hold, and AE1–AE7 are each covered by a named test.
- The three prerequisites the dependency-map plan recorded are closed: the floors gate fails rather
  than skips, the provenance and floors tests reach the configured adapter, and the managed
  adapter's floors are recorded from a measured run. **The third closes with U6 and therefore with
  the provider**; U1–U5 and U7 satisfy every other clause here without it, which is what makes this
  plan implementable in part rather than blocked in whole.
- A document in the new format is added through the UI, is labelled as its own format rather than
  as a PDF, and lands on its map with references drawn — verified by hand as well as by test.
- A citation from a pageless source reads as its section path in the UI, with no `p.` anywhere on
  screen for that document, and ADR-026 says a pageless citation is still a citation (KTD7).
- A non-PDF edition can be rebuilt, so the configured extractor reaches it.
- Re-adding an unchanged document of either format is a no-op, and a dependency bump on either
  reader's path stops it being one.
- The six live editions' stamps are unchanged by this work — verified, not assumed — with their
  obligations and reviewed links intact.
- A fresh clone with the default `null` adapter passes the backend suite, including the floors gate.
- A fresh clone with no `.env`, no model server and no key passes the suite and starts the stack.
- Both suites pass in full, judged by exit code, with the frontend's lint and type gates clean.
- Abandoned approaches are removed — a format evaluated under KTD2 and rejected leaves no reader
  module behind.
- The ADR edits this work implies have landed in the PRs that imply them (AGENTS.md:116): ADR-026's
  pageless-citation line with U2, and ADR-013's status line recording ADR-041 with U5.
