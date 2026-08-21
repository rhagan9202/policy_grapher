# Velocity

*Living document — one row per completed sprint. Last reviewed: 2026-08-21*

| Sprint | Committed | Delivered | Notes |
| --- | --- | --- | --- |
| 1 | 10 stories | 11 stories | STORY-030 was uncommitted stretch, pulled in at review. No backlog item carries a point estimate ([backlog.md](../backlog/backlog.md) says so explicitly), so this row counts stories, not points — velocity in points is not yet measurable. |
| 2 | 7 stories | 7 stories | Closed EPIC-001 at 18 of 18. Also delivered two non-story items that no row can count: the router refactor and ADR-005. **Sprint 1 actually delivered 13, not 11** — STORY-004 and STORY-015 were recognised as complete only after its review was frozen ([sprint 2 review](sprint-02/review.md)). The row above is left as written; treat 11 as an undercount when reading the trend. |
| 3 | 7 stories | 7 stories | First sprint with every item estimated (1M + 6S, [t-shirt scale](../backlog/README.md#estimation)) and the first where Ready met its own Definition of Ready. One closed as *no change required* after inspection disproved its premise — counted as delivered, since deciding not to act is the work. Stretch (STORY-051) not started. |

**Rolling average (last 3):** 9 stories (13, 7, 7) — and read it loosely. Sprint 1's row
still says 11 against a true 13, sprint 1 and 2 counted unestimated items, and sprint 3 is the
first sized one. The signal so far: **7 items is a comfortable session when they are mostly
S**, which is the only thing this table can honestly support.

Use this to sanity-check how much to commit to. Early sprints are noisy — three or four
data points in, it starts to mean something. It measures this team's throughput on this
codebase and nothing else.
