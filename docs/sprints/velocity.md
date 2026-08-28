# Velocity

*Living document — one row per completed sprint, plus any interval that delivered work
without being one. Last reviewed: 2026-08-28 (sprint 9 closed)*

| Sprint | Committed | Delivered | Notes |
| --- | --- | --- | --- |
| 1 | 10 stories | 11 stories | STORY-030 was uncommitted stretch, pulled in at review. No backlog item carries a point estimate ([backlog.md](../backlog/backlog.md) says so explicitly), so this row counts stories, not points — velocity in points is not yet measurable. |
| 2 | 7 stories | 7 stories | Closed EPIC-001 at 18 of 18. Also delivered two non-story items that no row can count: the router refactor and ADR-005. **Sprint 1 actually delivered 13, not 11** — STORY-004 and STORY-015 were recognised as complete only after its review was frozen ([sprint 2 review](sprint-02/review.md)). The row above is left as written; treat 11 as an undercount when reading the trend. |
| 3 | 7 stories | 7 stories | First sprint with every item estimated (1M + 6S, [t-shirt scale](../backlog/README.md#estimation)) and the first where Ready met its own Definition of Ready. One closed as *no change required* after inspection disproved its premise — counted as delivered, since deciding not to act is the work. Stretch (STORY-051) not started. |
| 4 | 4 stories | 7 stories | 1L + 2M + 1S committed, all four delivered, plus the stretch (STORY-054) and two defects found by the closing walkthrough and fixed in-sprint (STORY-057, STORY-058). Deliberately the smallest commitment yet, because of the L. **All four committed items were finished a day before the sprint could close:** its Definition-of-Done walkthrough was what surfaced the two defects, and the gate was only met once they were fixed. Third consecutive sprint in which the defect that mattered was found by running the product, not the suite. |
| 5 | 8 stories | 9 stories | 1L + 4M + 3S committed — the largest commitment in the project's history, [recorded at planning as a deliberate overcommit](sprint-05/plan.md#committed) at roughly ten item-equivalents against a session that had delivered six. All eight landed, plus STORY-061, found while preparing the walkthrough and without which the sprint goal was unreachable. The plan's reasoning for why the overcommit might hold is what held: five of eight were UI work over an API that already existed, and the L was breadth rather than an unmade decision. **Item-equivalents are not the unit** — sprint 4's four items took longer than sprint 5's nine. |

| *(no sprint)* | — | 16 stories | **Not a sprint, and the row says so on purpose.** Between sprint 5 closing on 2026-08-23 and sprint 6's planning on 2026-08-26, **16 items (STORY-062…080) and 75 commits** landed with no plan, no review, no retrospective and no acceptance criteria read back — an eleven-item audit of the running app, a default-stack inversion, and a rebuild job-timeout fix. Backfilled at sprint 6 planning so this table describes the project rather than only its ceremonies. It cannot be read as throughput: nothing was sized before it was built, so "16" counts outcomes chosen after the fact, which is the measurement error every row above warns about. Its real signal is governance, not velocity — **more items reached Done outside a sprint in three days than sprint 5 delivered inside one.** |

| 6 | 6 stories | 6 stories | 3M + 3S committed, all six delivered, plus three defects found by the planning review and fixed before the sprint opened. The estimation scale was amended at planning so those three M items were not forced to L — see [backlog README](../backlog/README.md#estimation). **STORY-084 was committed as S and delivered as L**: it asked for a re-measurement, the re-measurement failed, and the work became fixing the extractor rather than recording a number. That is the sprint in one row — the value was in a check that could finally fail, not in the six items. Counting stories says nothing about it. |

| 7 | 6 stories | 6 stories | 1M + 5S committed, all six delivered, plus four defects found while executing — three of them this sprint's own changes meeting live data. **The sprint's value is not in the six rows.** It is that the product's loop ran end to end for the first time, on obligations worth trusting, and the first `:LinkDecision` in the project's history was recorded and survived two rebuilds. Also the sprint that found sprint 6's heading measurement was false: a check written against five exact strings, invalidated by the same change it was verifying. |

| 8 | 10 stories | 10 stories | 2L + 5M + 3S — **by a wide margin the largest commitment in this project's history**, roughly sixteen item-equivalents against a session that had twice delivered six, and half again sprint 5's record overcommit. Every deferred item was pulled in on request and the goal widened to match. Nothing was dropped, and the plan's own explanation is why it is readable rather than lucky: four of the ten produced a document rather than a feature, and both L items were L because of decisions answerable from evidence already in the repository. **Do not read this row as a new baseline.** It is what happens when the expensive part of an L is a question somebody has already gathered the evidence for; the session that closed the MVP was also the session with the least unknown work in it. |

| 9 | 4 stories | 4 stories | 2M + 2S, and the smallest commitment since sprint 4 — deliberately, because both M items end in a measurement and a measurement that comes back wrong becomes the sprint. **The four rows are not the sprint.** What it delivered is that `Modality` can express a duty DoD imposes by position, which it never could: one edition went from 56 obligations to 76, and the 31 recovered are the section a compliance reader asks for first. Five defects were found and fixed while executing, and **the extraction gate itself was one of them** — it failed at recall 0.61 because it never passed the section title ADR-033's guard now depends on, so it was measuring the guard rejecting its own gold set. A sixth defect was found only by rebuilding a real document: two obligations came back with the whole statement copied into `actor`, which no fixture could have caught, because the gold set is what a correct answer looks like. Floors rose on both legs measured and neither ever moved down — precision to 0.842 and recall to 0.888, against observations of 0.905 and 0.889. Setting them took two attempts and both failures are now recorded beside the numbers: a floor rounded up sits above the measurement it came from and fails on itself, and "identical on three consecutive runs" is determinism within one process, not across two. |

**Rolling average (last 3):** 7.3 stories (6, 6, 10) — and read it loosely. Sprint 1's row still
says 11 against a true 13, sprints 1 and 2 counted unestimated items, and sprint 3 is the first
sized one. Counting *stories* is now actively misleading in a second way: sprint 4's seven
includes one L that consumed a design session, a spec and a plan before any code, and two
defects that were found and fixed inside the sprint and never sized at all. The signal this
table can honestly support is narrow: **7 items is a comfortable session when they are mostly
S, and an L displaces roughly three of them.**

**A row is added when a sprint closes, and a sprint closes when its Definition of Done is met** —
and, since 2026-08-26, also when a stretch of work delivered outside any sprint would otherwise
leave this table describing less than the project did. Such a row is marked *(no sprint)* and
carries no committed figure, because nothing was committed. —
not when its committed items are individually finished. Sprint 4 had all four committed items
done a day before it could be closed. See [AGENTS.md](../../AGENTS.md#standing-rules).

**Sprint 5 is where counting stories stopped meaning anything.** It delivered nine against sprint
4's seven and was the easier session, because eight of its nine were UI work over an API that
already existed, while sprint 4's four included a queue, a worker and the removal of a 16GB
dependency. Use this table to notice a sprint committing far more than the last one — which is
all it caught for sprint 5, correctly — and not to predict how long anything takes.

Use this to sanity-check how much to commit to. Early sprints are noisy — three or four
data points in, it starts to mean something. It measures this team's throughput on this
codebase and nothing else.
