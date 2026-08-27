# STORY-094: The MVP's definition of done is checked, not attested

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As someone deciding whether this product meets its own bar, I want the checkable parts of the
definition of done to be asserted by something that runs, so that a bar can stop being met
without a person happening to notice.

## Context

The [vision](../../planning/vision.md#what-success-looks-like) lists the MVP definition of done
in prose, and **nothing verifies any of it.** Each bar is met, or not, according to whoever last
read the list.

That is not hypothetical. **The corpus bar — "handles a corpus of 20 documents" — silently
stopped being met.** Sprints 6 and 7 rebuilt the graph around two editions of one directive, and
at sprint 8 planning the graph held **2** corpus documents against a bar of 20. Nothing failed,
nothing said anything, and every measurement those two sprints reported was taken against one
document without that being stated.

This project has spent two sprints turning claims into gates: the extraction ratchet that could
not fail, the reachability check written as prose and never automated, the modality rule the
prompt asked for and nothing enforced. The definition of done is the last big claim in that
shape, and it is the one the others are judged against.

## Acceptance criteria

- [ ] A test asserts the bars that can be checked cheaply against a running graph and a built
      image, and names the vision as the source of each.
- [ ] The corpus bar is one of them: a full manifest ingest yields at least 20 corpus documents,
      counted as documents that are not `:External` — 48 of the 50 nodes present at sprint 8
      planning were external references, and counting nodes would have reported the bar met.
- [ ] The file-type bar is checked as "the suffixes ingestion accepts", against the list the
      vision names, with DOCX recorded as the known exception rather than silently absent.
- [ ] The render-cap bar is checked as configurable, not as a specific number.
- [ ] Bars that cannot be checked by a test say so in one place, with the reason — "runs under
      `docker compose up` from a clean checkout" is a human step and
      [ADR-022](../../specs/adr/ADR-022-both-suites-run-on-every-push.md) already says why.
- [ ] Each assertion fails with a message naming the bar it is about, so a red build says which
      part of the definition of done stopped being true.

## Dependencies

- STORY-036 lands the XLSX half of the file-type bar; this asserts it. Either order works, but
  the assertion should not be written to expect a bar that has not shipped.
- The corpus assertion needs a manifest ingest, which sprint 8's Definition of Done performs
  anyway.

## Open questions

- Does the corpus assertion belong in the integration suite, which has a real Neo4j and could
  ingest the manifest itself, or is it a check on the walkthrough? The criteria above assume the
  integration suite, because a check that only runs when a person does a walkthrough is the thing
  this story exists to replace.

## Notes

**The scope risk is "checked" being read expansively**, and it is called out here so the answer
is not invented mid-sprint. This asserts bars that are cheap to check against a running graph and
records the ones that are not. It does not build an end-to-end harness for "API calls return
successful queries with correct payloads" — the suites already are that, and restating it here
would be a check that cannot fail.
