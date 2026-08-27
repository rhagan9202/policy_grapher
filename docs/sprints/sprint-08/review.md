# Sprint 8 — Review

**Date:** 2026-08-27 · **Participants:** —

*Dated record. Written once, at the end of the sprint.*

## The goal

> The product meets its own definition of done, the definition is checked rather than attested,
> and the questions this project has been carrying get answered.

**Met on all three clauses**, on the largest commitment in this project's history.

## Committed and delivered

| ID | Item | Est. | Delivered |
| --- | --- | --- | --- |
| STORY-036 | Ingestion accepts an XLSX manifest | M | Yes |
| STORY-093 | The vision says which of its bars cannot be started | S | Yes |
| STORY-014 | Search by name or ID from anywhere | M | Yes |
| STORY-094 | The MVP's definition of done is checked, not attested | M | Yes |
| STORY-095 | The rejection rate is diagnosed | M | Yes |
| STORY-096 | How a reissue's edits are recognised is decided | S | Yes — ADR-031 |
| STORY-047 | A reissue's edits read as edits, not wholesale replacement | M | Yes |
| STORY-076 | A rebuild says how many rejections a re-key stranded | S | Yes |
| STORY-073 | Each edition is ratcheted against its own reference set | L | Yes |
| STORY-031 | Near-duplicate documents can be reconciled | L | Yes — ADR-032 |

**Ten of ten**, 2L + 5M + 3S. The plan called this roughly sixteen item-equivalents against a
session that had twice delivered six, and recorded a drop order in advance. Nothing was dropped.

**Why it held, since the plan asked the question honestly:** four of the ten produced a document
rather than a feature, three were contained changes to code whose shape was already known, and
the two L items were L because of decisions that turned out to be answerable from evidence
already in the repository rather than from new investigation. That is not a general licence to
commit sixteen item-equivalents; it is what happens when the expensive part of an L is a question
somebody has already gathered the evidence for.

## The MVP is met, except the bar that cannot be

Every bar in the vision's definition of done is now closed or recorded as blocked:

- **Corpus of 20 documents** — restored to **23**, ingested from the spreadsheet through the UI.
  It had silently fallen to 2.
- **PDF, DOCX, XLSX, CSV** — XLSX shipped. **DOCX is blocked and the vision now says so at the
  bar**: no `.docx` exists to design against, and rules fitted to a document we invented would be
  measured by a ratchet that could not tell us they were wrong.
- **Search by name or ID** — shipped, and the ID half is what STORY-010's filter never did.
- Everything else was already met, and **is now asserted rather than attested** (STORY-094).

## What the sprint found

**The corpus bar had stopped being met and nothing noticed.** 2 documents against a bar of 20,
while 50 `:Document` nodes existed — 48 of them `:External` references, so a naive count would
have reported the bar met. Every number sprints 6 and 7 published was measured against a single
document.

**Half of every document states no duty, and that is the answer to the rejection rate.** Chunks
containing no modal verb, per sample: 61%, 59%, 67%, 53%, 50%, 48%, 34%. DoDD 5143.01 is 67%
modal-free and rejected 69% of its chunks. Of the 21 chunks yielding nothing in DoDD 5000.01's
2020 edition, **18 contain no modal verb anywhere** — so the prompt has nothing to find and no
model could do better. The acceptance criterion asking for a second model was answered by
argument, because the ceiling is zero regardless of which model reads a page of dotted leaders.

**And the part of that answer nobody expected.** DoD writes its *Responsibilities* section — the
part that assigns duties to organisations — as bare third-person verbs under a role heading:
"The USD(R&E): a. Executes… b. Serves… c. Confirms…". Six duties, a named actor, no modal verb.
The schema refuses them correctly under its own rules, so **the product cannot see the section of
an issuance most directly about who must do what.** Filed as STORY-097 (L) and STORY-098 (M).

**Two editions were being measured against the wrong reference set.** Transcribing both lists by
hand from the documents turned "7% recall with 11 inventions" into **12 of 14 and 16 of 17, with
nothing invented**. The old number measured how much two editions disagree.

## What the closing walkthrough caught that nothing else could

`GET /documents/duplicates` answered **404**. FastAPI matches in declaration order and the route
was appended after `/documents/{slug}`, so the literal path was read as a document slug.

Every test passed. The frontend mocks the client, so its tests never reach the server — and
STORY-086's reachability check, written last sprint and correct for its own purpose, compares
declared paths against `client.ts` **without calling either**. A route that exists and cannot be
reached at runtime looks identical to one that works.

That is the fourth sprint running where the defect that mattered was found by using the product.

## Defects found while executing

- The ingest picker offered a spreadsheet as a **"CSV manifest"** — the backend correctly reports
  `manifest`, and the screen turned that into words that were true when CSV was the only kind.
- ADR-032's first implementation keyed merges on **slugs**. ADR-005 gives the incumbent the bare
  slug, so deleting the loser frees a slug the next ingest may reassign — a merge recorded by slug
  undoes itself on precisely the event it exists to survive. The re-ingest test found it.
- STORY-047's first ambiguity test was **vacuous**: it used candidates scoring identically, and
  passed with the margin set to zero. It was testing tie-breaking. Replaced with a near-tie
  (0.833 against 0.800), which fails when the margin is removed.
- The first pass at STORY-095 measured cache **presence** and reported 7 rejected chunks rather
  than 21. A cache entry can predate the modality rule and still fail on replay.

## Definition of done

- [x] **Corpus restored to at least 20 documents**, counted as non-`:External` — 23, via the
      spreadsheet, through the UI.
- [x] **A second instrument built, not a second edition** — DoDD 5143.01: 42 chunks, 16
      obligations, 29 chunks rejected, 196 items dropped. The first time anything here has been
      demonstrated on more than one document.
- [x] **Every acceptance criterion read back line by line.** It found two unmet: STORY-014's
      search control was asserted against a hardcoded list rather than the navigation
      declaration, and STORY-036's route criterion was covered only at the parser. Both closed.
- [x] **A browser walkthrough, every step a UI action**, including search from a screen that is
      not Documents, and merging a real near-duplicate pair.
- [x] **The extraction gate run against a real model**, passing at its raised floors.

## Numbers

- **330 backend unit, 362 backend integration, 204 frontend** — 896 tests, from 841 at sprint
  start. Counted, not recalled: an earlier draft of this line had three figures none of which
  were right.
- **23 corpus documents**, 451 nodes, two instruments with a derived layer, one recorded merge,
  one recorded link decision surviving three rebuilds.
