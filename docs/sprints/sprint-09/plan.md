# Sprint 9 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next one
> ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 8 asks this session to settle

**The product cannot see the responsibilities section of a DoD issuance.** DoD writes the part
that assigns duties to organisations as bare third-person verbs under a role heading — "The
USD(R&E): a. Executes… b. Serves… c. Confirms…" — with no modal verb anywhere. The schema refuses
them correctly under its own rules. Six such chunks in DoDD 5000.01's 2020 edition, thirteen in
DoDI 8500.01. This is the largest open question about whether the product does what it says, and
[STORY-097](../../backlog/stories/STORY-097-the-responsibilities-section-is-invisible.md) is L
because the decision is the work: a sixth modality, a separate node type, or narrowing the claim
the vision makes.

**A route can exist, be modelled by the client, and still 404.** `GET /documents/duplicates` did
for a whole sprint. STORY-086's reachability check compares declared paths against `client.ts`
and calls neither, which is correct for its purpose and blind to this. Sprint 8's retrospective
asks for an assertion that every declared route is exercised by at least one real request.

**The MVP is met.** Every bar in the [vision](../../planning/vision.md#what-success-looks-like) is
closed or recorded as blocked, and [STORY-094](../../backlog/stories/STORY-094-the-definition-of-done-is-checked.md)
now fails a build when one stops being true. What this project is *for* after its definition of
done is met is a question for this planning session and not one the backlog answers.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) is empty — all ten of sprint 8's items are in Done.

[Refining](../../backlog/backlog.md#refining) holds STORY-097 (L, above), STORY-098 (M, skip
front matter — the cheap half of the same finding), and STORY-035, still blocked because no
`.docx` exists in `data/samples` to design against.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023, STORY-045 and
STORY-075 — none refined, and two of them (STORY-020, STORY-021) are the schema migrations the
roadmap parks under *Later*, which STORY-097 may turn out to be the first step of.
