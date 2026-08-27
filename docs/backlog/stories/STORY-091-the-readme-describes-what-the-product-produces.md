# STORY-091: The README's corpus numbers describe what the product produces

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As someone deciding whether to run this, I want the numbers in the README to describe what the
pipeline actually produces now, so that the first thing I read is not a measurement of a defect.

## Context

The README's walkthrough records what a real run produced: **38 and 34 chunks, 96 and 115
obligations, 265 proposals**, and a Triage showing 204 changes and one row. Every one of those
numbers was measured under `PROMPT_VERSION 1`, and sprint 6 established what that prompt was
doing — recording section headings as obligations, dropping sentence subjects, and writing the
literal string "no actor specified" as an actor.

So the obligation counts are inflated by junk, and the proposal count is derived from it. The
2026-08-26 rebuild of one edition produced **114 obligations where v1 produced 113**, with the
headings gone — which suggests the totals will not move much and their composition will move
completely.

[CONVENTIONS](../../CONVENTIONS.md#what-to-update-when) is explicit: anything contradicting a
canonical doc means the doc wins or gets corrected. The README is the first thing a reader sees.

## Acceptance criteria

- [ ] The walkthrough's numbers are re-measured against `PROMPT_VERSION 2` output and replaced.
- [ ] The rejection rate is stated alongside them, because it is now roughly one chunk in five
      and a reader comparing their own run to these numbers needs to know that.
- [ ] Any number that cannot be re-measured this sprint is removed rather than left standing —
      an uncorrected figure is worse than an absent one.
- [ ] The extraction rate is checked against the "~104 seconds a chunk" the README quotes; sprint
      6 measured 91 s a chunk under the longer v2 prompt.

## Dependencies

- Needs a real-model run over at least two editions, which sprint 7's Definition of Done requires
  anyway for the loop it is proving. This item should be written **after** that walkthrough, from
  its output.

## Open questions

- None.
