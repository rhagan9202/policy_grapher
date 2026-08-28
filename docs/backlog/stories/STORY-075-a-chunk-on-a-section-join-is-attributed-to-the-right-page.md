# STORY-075: A chunk starting on a section join is attributed to the right page

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a reader following a citation back to the document, I want the page a chunk reports to be the
page its text actually starts on, so that a quote I am checking is on the page the product sent
me to.

## Context

`_page_at` in `backend/src/policy_grapher/chunking.py:194` resolves an offset to a page by walking
the section's lines:

```python
    for page_number, line in lines:
        if offset <= cursor + len(line):
            return page_number
        cursor += len(line) + 1
```

The `+ 1` is the newline `"\n".join(...)` inserted. So `cursor + len(line)` is the index *of* that
newline, and `<=` claims it for the line before it. A chunk whose start offset lands exactly there
is attributed to the earlier line's page — which is the page before the one its text is on.

**Confirmed reachable at sprint 9 planning.** The story was filed with a note that it might not
be, on the theory that something upstream stripped leading whitespace. It does not: `lead` at
`chunking.py:248` is computed once for the whole joined section —
`len(joined) - len(joined.lstrip())` — as a constant correction for `.strip()` shifting every
offset. It is not applied per chunk, so a part boundary chosen by `_split` can still land on a
join newline, and `offset + lead` then indexes it directly.

**Filed rather than fixed, which this project's standing rule prohibits.** It has sat in
[Ideas](../backlog.md#ideas) since sprint 7 with the note "real, but marginal". Marginal is a
reason to size it S, not a reason to leave a known defect in the code. That is why it is in this
sprint.

## The question the fix has to answer first

The Ideas note said it was not clear whether the fix is the boundary check or the leading newline,
and that is still the right question — the two are different bugs with the same symptom:

- If the boundary is wrong, `<` is the fix and the chunk keeps its leading newline.
- If the leading newline is the bug, the chunk's text should not begin with one at all, and the
  offset question dissolves because no part starts on a join.

**Decide it with a test, not an argument.** A test that pins a chunk starting exactly on a join
distinguishes them: it says both which page is reported and what the text begins with, and only
one fix satisfies both halves.

## Acceptance criteria

- [ ] A test constructs a section whose `_split` boundary falls exactly on a join newline, and
      asserts the reported page is the page the chunk's first *visible* character is on.
- [ ] That test is watched failing before the fix, and the failure names the wrong page rather
      than erroring — a test that errors has not demonstrated this bug.
- [ ] The test also asserts what the chunk's text begins with, so it distinguishes the two
      candidate fixes rather than passing under either.
- [ ] The fix is one of the two named above, and the code says in a comment which bug it decided
      this was and why — the next reader should not have to re-derive the question.
- [ ] `test_chunking.py` still passes unchanged otherwise; page attribution for chunks that do not
      start on a join must not move. ADR-026 decided that a chunk reports the page its own text
      starts on, and this fixes an exception to that rule rather than amending it.
- [ ] A mutation check: reverting the fix must make the new test fail. Three sprints running have
      produced a guard that did not guard, and each tell was the same — it passed first run.

## Dependencies

- None. Contained to `chunking.py` and its unit tests; needs no model, no database and no rebuild.

## Notes

Chunk ids are keyed on a chunk's place in the section hierarchy, not on its page
([ADR-012](../../specs/adr/ADR-012-chunks-follow-sections.md)), so correcting a page does not move
any id and no rebuild is required to adopt it. Existing `:Chunk` nodes keep whatever page they
were written with until their edition is next rebuilt, which is worth saying out loud in the
review rather than discovering later.
