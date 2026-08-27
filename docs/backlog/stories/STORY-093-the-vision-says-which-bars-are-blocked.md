# STORY-093: The vision says which of its bars cannot be started

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As someone reading the definition of done to judge how close this is, I want a bar that cannot be
started to say so where it is stated, so that the list describes the project's real position
rather than looking like a list of things nobody got to.

## Context

The [vision](../../planning/vision.md#what-success-looks-like) lists "Processes PDF, DOCX, XLSX,
and CSV file types" as an MVP bar. DOCX has been blocked across sprints 5, 6 and 7 for a reason
that is recorded only in a backlog note: **no `.docx` exists anywhere in this repository**, so
there is nothing to design extraction rules against. Verified again at sprint 8 planning.

The blocker is real and it is not laziness. PDF extraction was built against seven genuine DoD
issuances and its ratchet scores against a corpus CSV describing those documents; a DOCX path
designed against a file we invented would be fitted to our own guess at DoD's DOCX conventions,
and the ratchet could not tell us it was wrong. That is precisely the kind of evidence this
project has been burned by twice.

Meanwhile XLSX, in the same bar and the same sentence, is *not* blocked — the manifest format is
ours (STORY-036). A reader cannot tell those two apart from the vision, and the difference is the
whole reason one ships this sprint and one does not.

## Acceptance criteria

- [ ] The vision's file-types bar names DOCX as blocked, at the bar itself rather than only in
      the backlog.
- [ ] It says what would unblock it — a real DoD issuance in DOCX in `data/samples` — so the
      blocker reads as a missing input rather than a missing intention.
- [ ] It distinguishes DOCX from XLSX in that sentence, since one is blocked and one is not.
- [ ] The roadmap and backlog do not now contradict the vision about DOCX's status.

## Dependencies

- None. This is one document telling the truth about itself.

## Open questions

- None.
