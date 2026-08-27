/**
 * How long to wait before asking about a running rebuild again — STORY-089.
 *
 * The poll used to be a flat two seconds with no backoff and no ceiling. Its
 * reason for having no attempt *limit* was sound and still holds: a rebuild with
 * a real model is one call per chunk over dozens of chunks, so a poll budget
 * would give up on exactly the runs worth watching.
 *
 * What changed is how long those runs can be. `rebuild_job_timeout_seconds` went
 * from 1800 to 28800 on 2026-08-26 so a 204-chunk edition could finish, and at
 * two seconds a single open tab issues roughly 14,400 requests over one run —
 * each a `Job.fetch` plus `latest_result()` round trip to Redis.
 *
 * The shape matters as much as the numbers. A run that finishes in twenty seconds
 * must still feel live, so the first few polls stay fast; a run that lasts hours
 * settles at a rate nobody has to think about. Doubling from 2s and capping at
 * 30s takes an eight-hour run from ~14,400 requests to under 1,000, and answers
 * a short run just as quickly as before.
 */
export const FIRST_POLL_MS = 2_000
export const MAX_POLL_MS = 30_000

export function pollDelayMs(attempt: number): number {
  const grown = FIRST_POLL_MS * 2 ** Math.max(0, attempt)
  return Math.min(grown, MAX_POLL_MS)
}
