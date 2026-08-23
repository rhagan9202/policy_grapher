# Sprint 4 — Retrospective

**Date:** 2026-08-22 · **Participants:** —

*Dated record. Never edited — the value is in what the team believed at the time.*

## What we're changing

**1. A sprint is not closeable while a gate is unmet, and that is not a judgement call.**
This sprint was closed once already, prematurely: review, retrospective, velocity row and the
next sprint's folder were all written while the second Definition-of-Done gate was demonstrably
unmet, with the two blocking defects filed as STORY-057 and STORY-058 rather than fixed. The
call was then offered to the project owner as something they might reasonably overrule. That
framing was the error — a closed sprint that did not meet its gates makes the velocity record a
fiction, and every later estimate reads off that record. The close-out was withdrawn, both
defects fixed, the gate walked, and this document rewritten. The rule is now in
[AGENTS.md](../../../AGENTS.md#standing-rules).

**2. A discovered bug gets fixed in the same turn, not filed.** Same incident, different half.
Three defects came out of the walkthrough; one was fixed and two were written up as stories on
the reasoning that they needed an ADR first. Writing ADR-023 took a fraction of the time the
write-ups did, and the fixes were 20 lines. "It needs a decision recorded" is a reason to write
the decision *and* the fix, never a reason to ship neither. Also in AGENTS.md.

**3. A decision enforced by a test is only enforced where the test can see.**
[ADR-020](../../specs/adr/ADR-020-model-weights-come-from-us-organisations.md) constrains
extraction weights to US-published models and says in as many words: "It is enforced by a test,
not by a convention." The test asserted on `Settings(_env_file=None).extractor_model`, which
resolves a *developer's shell*. `docker-compose.yml` passed `qwen3:8b` to backend and worker, so
every container ran the excluded model while the test passed on every machine anyone ran it on.
From now on, when an ADR constrains a *configured* value, the test asserts on **every place that
value is set** — application default and deployment configuration. Done for ADR-020; the same
gap plausibly exists elsewhere and nobody has looked.

**4. The walkthrough gains a leg: one rebuild against the real extractor.** Sprint 3 added "walk
the app in each state the data can be in"; this sprint added "a derived layer built through the
product". Both were satisfiable with `EXTRACTOR_ADAPTER=null`, which writes chunks and no
obligations — so the extraction path stayed unwalked for three sprints and failed twice within
twenty minutes of first being tried.

## What went well

- **The ports paid for themselves, visibly.** STORY-052 removed a 16GB dependency from the image
  and changed nothing outside `embedding/local.py` and packaging. ADR-016 built the port to make
  a *provider* swap cheap; it made a *packaging* swap cheap, which nobody was aiming at.
- **CI's integration step is structural rather than documentary.** `pytest` exits 5 when a marker
  selects nothing, so a step selecting `-m integration` fails if the marker is renamed or the
  tests vanish. Verified against this repository before being relied on, rather than assumed.
- **Every defect this sprint was found by running the thing, and every one was fixed.** Three
  from the walkthrough, plus the `uv run` re-sync found by running a container rather than
  measuring an image. None was visible to 550 tests.
- **STORY-048 landed with the design session, spec and plan its L had promised.** The estimation
  note — "an L in a sprint is a warning, not a plan" — was right, and taking it seriously worked.

## What didn't

- **The sprint was closed with two known bugs outstanding, and I did it.** Cost: the whole
  close-out had to be withdrawn and rewritten. It would have cost far more the other way — a
  velocity row and a sprint-5 plan built on a sprint that never met its gate.
- **`qwen3:8b` sat in `docker-compose.yml` for as long as ADR-020 has existed.** ADR-020 was
  written *because* someone finally asked where the weights came from. It changed `config.py`
  and the test and missed the two lines of compose that decide what a container actually asks
  Ollama for. The commit that introduced the model server is titled "with US-published weights".
- **Three test probes were written before checking the format being probed.** A Dockerfile `CMD`
  is a JSON array, so `"uv run"` never appears literally. The rebuild poll field is `state`, not
  `status` — which cost a poll loop reporting `None` forty times and briefly read as a broken
  product rather than a broken probe. Same pattern sprint 3 recorded about loose `getByText`
  assertions.
- **The backlog's estimate for STORY-052 was wrong by 3.4×** — 4.9GB from the virtualenv against
  16.6GB of image. Caught at planning rather than in the sprint, which is the system working,
  but the wrong number is the one that reached the backlog row and sat there.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Audit the remaining `Settings` fields for the ADR-020 gap: a constraint tested against the application default while compose supplies another | — | Sprint 5 |
| Add "one rebuild against the real extractor" to the Definition of Done walkthrough | — | Sprint 5 planning |
| Take the modality decision — [STORY-055](../../backlog/backlog.md#ready) — now that there are real numbers to argue from: 241 obligations extracted against `will` outnumbering `shall` 458 to 93 | — | Sprint 5 |
| Add the compose-build CI job deliberately left out of STORY-051, so the last Definition-of-Done gate stops being a human step | — | Sprint 5 |

## Follow-up on last sprint's actions

**"A survey finding is a hypothesis until something reads the code."** Held. STORY-052's backlog
row carried a 4.9GB figure from a mechanical measurement of the virtualenv; sprint 4's plan
re-measured the image before committing and wrote the real number down.

**"The suite cannot see composition, so the walkthrough is not optional."** Held, and paid three
times in one session. This is the third consecutive sprint in which the defect that mattered was
found by opening the thing rather than by running the suite. It should stop being filed under
"what went well" and start being read as a statement about what the suite is for: 550 tests
prove the parts work and say nothing about whether the assembled product does.
