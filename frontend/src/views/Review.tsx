import { useCallback, useEffect, useState } from 'react'
import { getReviewQueue, recordVerdict } from '../api/client'
import type { ObligationCitation, ReviewItem, Verdict } from '../api/types'

/** "DoDI 5000.88 · 3/3.2 · p. 12" — where to go and read the passage. */
function Citation({ of }: { of: ObligationCitation }) {
  return (
    <p>
      <cite>
        {of.document} · {of.section_path.join('/')} · p. {of.page}
      </cite>
    </p>
  )
}

function Side({ heading, of }: { heading: string; of: ObligationCitation }) {
  return (
    <section style={{ flex: 1, minWidth: '18rem' }}>
      <h3>{heading}</h3>
      <blockquote>{of.statement}</blockquote>
      <Citation of={of} />
    </section>
  )
}

export default function Review() {
  const [queue, setQueue] = useState<ReviewItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rationale, setRationale] = useState('')
  const [pending, setPending] = useState(false)

  const load = useCallback(() => {
    return getReviewQueue()
      .then(setQueue)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : 'Failed to load the queue.')
      })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function decide(item: ReviewItem, verdict: Verdict) {
    // `pending` gates both buttons for the whole round trip. Without it a
    // double-click records two decisions for one judgement — and since a
    // re-decision replaces rather than appends (ADR-014), the second would
    // silently overwrite the first with whatever was clicked last.
    setPending(true)
    setError(null)
    try {
      await recordVerdict(
        item.source.obligation_id,
        item.target.obligation_id,
        verdict,
        rationale,
      )
      setRationale('')
      await load()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Failed to record the verdict.')
    } finally {
      setPending(false)
    }
  }

  if (!queue && !error) return <p>Loading the review queue…</p>

  const item = queue?.[0]

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Review</h1>
      {error && <div role="alert">Could not record that: {error}</div>}

      {!item ? (
        queue && <p>Nothing is waiting for review.</p>
      ) : (
        <article>
          <p>
            {queue.length} proposal{queue.length === 1 ? '' : 's'} waiting.
            Proposed by {item.proposer} at {Math.round(item.confidence * 100)}%
            confidence.
          </p>

          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
            <Side heading="Our clause" of={item.source} />
            <Side heading="Implements" of={item.target} />
          </div>

          <p>{item.rationale}</p>

          <label>
            Reason (optional)
            <textarea
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
            />
          </label>

          <p>
            <button type="button" disabled={pending} onClick={() => decide(item, 'approve')}>
              Approve
            </button>{' '}
            <button type="button" disabled={pending} onClick={() => decide(item, 'reject')}>
              Reject
            </button>
          </p>
        </article>
      )}
    </div>
  )
}
