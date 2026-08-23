import { useCallback, useEffect, useState } from 'react'
import { getReviewQueue, listDocuments, recordVerdict } from '../api/client'
import EmptyState from './EmptyState'
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
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)
  // Where in the queue the reviewer is (STORY-042). Client-side and recorded
  // nowhere: skipping must not become a third verdict. ADR-014 keeps the decision
  // vocabulary closed at approve/reject because a verdict is permanent and replayed
  // on every rebuild, and "I could not judge this today" is not a judgement.
  const [index, setIndex] = useState(0)
  const [wrapped, setWrapped] = useState(false)

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

  // "Nothing is waiting for review" is true of an empty graph and tells the
  // reader the queue has been worked through. The two states need telling
  // apart, and only the corpus can say which this is (ADR-019).
  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((d) => {
        if (!cancelled) setCorpusEmpty(d.length === 0)
      })
      .catch(() => {
        if (!cancelled) setCorpusEmpty(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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

  // Deciding removes an item, so the cursor can be left pointing past the end.
  // Clamping at render rather than in the reload keeps the two independent.
  const total = queue?.length ?? 0
  const position = total === 0 ? 0 : Math.min(index, total - 1)
  const item = queue?.[position]

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Review</h1>
      {error && <div role="alert">Could not record that: {error}</div>}

      {corpusEmpty ? (
        <EmptyState lead="Nothing has been proposed for review." />
      ) : !item ? (
        queue && <p>Nothing is waiting for review.</p>
      ) : (
        <article>
          <p>
            Proposal {position + 1} of {total}. Proposed by {item.proposer} at{' '}
            {Math.round(item.confidence * 100)}% confidence.
          </p>

          {wrapped && (
            <p role="status">
              Back at the start — every proposal in the queue has been offered at
              least once. Skipping records nothing, so these are all still waiting.
            </p>
          )}

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
            {/* Only when there is somewhere to go. A skip button over a queue of one
                offers a way past a proposal and then does nothing. */}
            {total > 1 && (
              <>
                {' '}
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    setWrapped(false)
                    setIndex((current) => (current - 1 + total) % total)
                  }}
                >
                  Previous
                </button>{' '}
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    const next = (position + 1) % total
                    setWrapped(next === 0)
                    setIndex(next)
                  }}
                >
                  Skip
                </button>
              </>
            )}
          </p>
        </article>
      )}
    </div>
  )
}
