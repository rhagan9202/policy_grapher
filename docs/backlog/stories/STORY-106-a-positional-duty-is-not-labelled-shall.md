# STORY-106: A positional duty is not labelled SHALL

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As a policy analyst reading a responsibilities section, I want every role section read, so that
two offices are not missing from the answer because the model labelled their duties with a word
the passage does not contain.

## Context

Sprint 11 took DoDD 5000.01 (2020) from **19 of 40** lettered items to **34 of 40**. Two role
sections still read zero, and they are 5 of the 6 items missing:

| Para | Office | Items | Read |
| --- | --- | ---: | ---: |
| 2.5 | Chief Management Officer | 2 | 0 |
| 2.10 | CJCS | 3 | 0 |

**The cause is measured and it is the same one sprint 11 fixed for three other sections.** The
model quotes the items correctly and labels them `SHALL`:

    drop: statement does not contain its modality 'SHALL':
          'Provides advice and assessment on joint military capability needs …'
    drop: statement does not contain its modality 'SHALL':
          'Is responsible for preparing military analysis, options, and plans …'

Every item fails the modality-word rule, nothing survives, and ADR-030 correctly makes the chunk a
rejection. `PROMPT_VERSION 4` says in as many words *"Do not label such items SHALL: there is no
'shall' in them"*, and on these two sections the model does it anyway.

**Why it was not fixed in sprint 11, which is the useful part.** The prompt block that recovered
paragraphs 2.3, 2.6 and 2.7 was originally three times longer and included two worked examples. At
that length it drove the model into a *repetition loop* on an unrelated WILL-dense passage —
measured: 25 statement fields, 6 distinct, two of them repeated ten times, 2048 tokens and invalid
JSON. Bisecting the prompt located it exactly; compressing the block to a third its size stopped
the loop and kept 2.6 and 2.7 complete, but was evidently not emphatic enough for 2.5 and 2.10.

**So this is a trade, not an oversight: more prompt recovers these two sections and risks looping
elsewhere.** Sprint 11 chose the version that keeps the gate green and reads 34 of 40 over one
that might read 37 and fail. Reopening it means finding a way to teach the rule that does not
depend on prompt length.

## What is known about the trade

- Paragraph 2.5's text is prose, not a lettered list, for its first duty — the model produced
  `"The CMO executes the certification responsibilities …"`, which is a composed sentence and would
  have been refused by ADR-034 even had the modality been right.
- Paragraph 2.10 *also attempted the echo* sprint 9 found: two of its drops are
  `statement is not a quotation` on `'Executes the acquisition re…'` and `'Serves as an advisor
  in the…'`, the USD(A&S) sentences from the prompt's own example. **ADR-034 refused them.** The
  echo is still attempted and is now structurally impossible, which is the strongest evidence
  that guard is load-bearing rather than belt-and-braces.

## Acceptance criteria

- [ ] Paragraphs 2.5 and 2.10 of DoDD 5000.01 (2020) yield their items, or the review records a
      measured reason why one of them should not.
- [ ] `will_dense_dodd_5000_01_2020_section_1.json` still terminates: token count and
      `done_reason` recorded, not just a passing score. The loop is invisible in a score until it
      crosses the cap.
- [ ] Coverage is re-measured and `COVERAGE_FLOOR` raised, truncated below the observation with
      headroom for one item, per the reasoning recorded beside it.
- [ ] The floors are re-measured three times if the prompt changes, and the review says whether
      any moved.
- [ ] Whatever is tried, the prompt's length is reported before and after — sprint 11 established
      that this prompt is long enough for added text to degrade an unrelated passage, and that is
      now a property to measure rather than a surprise to rediscover.

## Dependencies

- None. It is a prompt change and a re-measurement.

## Open questions

- Is prompt length the real variable, or was it the two indented worked examples specifically?
  Sprint 11 bisected block-present against block-absent and compressed against full, but never
  tested the rule sentence alone without any example.
- Would a smaller model instruction help more than more prompt — for example asking for the
  modality *last*, after the statement is written, so the label is chosen with the quoted sentence
  already in view?
