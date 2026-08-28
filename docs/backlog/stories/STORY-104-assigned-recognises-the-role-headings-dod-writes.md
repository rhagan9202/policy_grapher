# STORY-104: ASSIGNED recognises the role headings DoD actually writes

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As a policy analyst asking what a named office must do, I want every role section of a
responsibilities chapter read, so that the answer is not silently limited to the two offices whose
heading happens to match one syntactic pattern.

## Context

Sprint 10 closed reporting 19 positional duties on DoDD 5000.01 (2020) "against a hand count of
21". **Both numbers were wrong.** Counting the lettered items under role headings in that
document's `SECTION 2: RESPONSIBILITIES` gives **40**. The hand count came from the same coarse
detector sprint 9's spec used, and two sprints treated it as ground truth.

The real coverage is **19 of 40, 48%** — and it is not spread evenly. Four role sections yield
nothing at all:

| Para | Office | Items in the document | Extracted |
| --- | --- | ---: | ---: |
| 2.1 | USD(A&S) | 5 | 6 |
| 2.2 | USD(R&E) | 7 | 5 |
| 2.3 | USD(I&S) | 4 | 1 |
| 2.5 | CMO | 2 | 0 |
| 2.6 | DoD CIO | 6 | **0** |
| 2.7 | DOT&E | 6 | **0** |
| 2.8 | DCAPE | 4 | 4 |
| 2.9 | DoD Component Heads | 3 | 1 |
| 2.10 | CJCS | 3 | **0** |

**The cause is diagnosed, and it is not the guards.** Extracting paragraph 2.6 directly, the model
quotes its items correctly — `"Establishes cybersecurity policy and standards, and provides
guidance for incorporating cybersecurity…"` is verbatim — and labels every one `SHALL`. There is no
`shall` in the sentence, so the modality-word rule refuses each item, nothing survives, and
ADR-030 makes the whole chunk a rejection. The obligations are being read and then thrown away for
carrying the wrong label.

**It is syntactic.** `PROMPT_VERSION = 3` teaches one form of role heading, and DoD writes at
least three:

| Form | Example | Works |
| --- | --- | --- |
| Title, then the role and a colon | `2.1. UNDER SECRETARY … (USD(A&S)). The USD(A&S):` | Yes |
| A lead-in clause, then the role and a colon | `In accordance with applicable federal law … the DoD Chief Information Officer:` | No |
| A responsibility sentence ending `by:`, then **gerunds** | `the DOT&E has overarching responsibility … by: a. Prescribing policies…` | No |

Paragraphs 2.3, 2.6 and 2.10 are all the second form. Paragraph 2.7 is the third, and its items are
gerunds — `Prescribing`, `Reviewing`, `Providing` — not the third-person present verbs the prompt's
example shows.

Recovering the second and third forms would reach the 18 items in 2.3, 2.6, 2.7 and 2.10 alone.

## Acceptance criteria

- [ ] The prompt teaches the lead-in form and the `by:`-plus-gerund form, with a real example of
      each taken from `data/samples` rather than invented.
- [ ] The gold set gains a fixture for each of the two forms, transcribed from the document, with
      every statement verified verbatim against its chunk before the fixture is committed.
- [ ] `PROMPT_VERSION` is bumped once, in the same commit as the text, and this story is done
      **together with [STORY-103](STORY-103-the-prompt-stops-contradicting-itself.md)** — both
      change the prompt, and doing them separately means two cache invalidations and two full
      re-extractions for one sprint's worth of prompt work.
- [ ] The floors are re-measured three times at temperature 0 and recorded. **Truncated below the
      lowest observation, never rounded to it**, and if a floor moves down the review says so and
      says why.
- [ ] DoDD 5000.01 (2020) is rebuilt and its `ASSIGNED` count reported against the **40** items the
      document contains, per role section, so the remaining gap is visible rather than aggregate.
- [ ] The regression that started all of this stays fixed: no obligation attributes USD(A&S)'s
      duties to the DoD CIO, DOT&E or the CJCS. Those three sections currently yield nothing, so
      this story is precisely the change most likely to bring the echo back.

## Dependencies

- STORY-103, which must land in the same prompt change for the reason above.
- A rebuild. Three editions, roughly two hours cold.

## Notes

**The 48% is the honest number and it is the first time this project has had one.** Every previous
figure for responsibilities coverage — 91 across the corpus, 21 in this edition — came from a
regex that counted lettered lines beginning with a capitalised third-person verb, which misses
gerunds entirely and cannot see which role heading an item sits under. Sprint 9's spec described
that detector as coarse and then used its output as a denominator anyway.
