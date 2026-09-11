import { useCallback, useEffect, useState } from 'react'
import { getReviewQueue, listDocuments, recordVerdict } from '../api/client'
import EmptyState from './EmptyState'
import type { ObligationCitation, ReviewItem, ReviewQueue, Verdict } from '../api/types'

/** "DoDI 5000.88 · dodi-5000-88@2020-09-09 · 3/3.2 · p. 12" — where to go and
 *  read the passage, and which edition of it.
 *
 *  The edition is not decoration here, it is the distinction being reviewed. A
 *  proposal frequently runs between two editions of one instrument, and without
 *  it both sides of this screen print the same document name — measured on
 *  2026-09-09 across all 119 proposals in the live queue. Same treatment as the
 *  citation on Ask, which has carried the edition from the start. */
function Citation({ of }: { of: ObligationCitation }) {
  return (
    <p>
      <cite className="citation">
        <span className="citation-document">{of.document}</span>
        <code>{of.version_id}</code>
        <span>{of.section_path.join('/')}</span>
        <span>p. {of.page}</span>
      </cite>
    </p>
  )
}

function Side({ heading, of }: { heading: string; of: ObligationCitation }) {
  return (
    <section className="pane">
      <h3>{heading}</h3>
      <blockquote>{of.statement}</blockquote>
      <Citation of={of} />
    </section>
  )
}

export default function Review() {
  const [queue, setQueue] = useState<ReviewQueue | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [rationale, setRationale] = useState('')
  const [pending, setPending] = useState(false)
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)
  // Where in the queue the reviewer is (STORY-042). Client-side and recorded
  // nowhere: skipping must not become a third verdict. ADR-014 keeps the decision
  // vocabulary closed at approve/reject because a verdict is permanent and replayed
  // on every rebuild, and "I could not judge this today" is not a judgement.
  const [index, setIndex] = useState(0)
  const [wrapped, setWrapped] = useState(false)

  // Moving to another proposal drops whatever was typed for this one.
  //
  // `setRationale('')` ran when a verdict was recorded and nowhere else, so a
  // reason typed here and then skipped past stayed in the box and was filed
  // against whichever proposal was approved next. A verdict is permanent and
  // replayed on every rebuild (ADR-014), so that is a wrong reason in an audit
  // trail rather than a stray character in a form — and it reads as deliberate,
  // because someone did type it.
  //
  // Cleared in the handlers rather than in an effect on `index`: the navigation
  // is what invalidates the text, and a `setState` in an effect body is the
  // cascading render the lint rule forbids.
  function goTo(next: number) {
    setIndex(next)
    setRationale('')
  }

  // Two different failures, two different states. One shared `error` was rendered
  // under a single "Could not record that:" heading, so a queue that failed to
  // *load* — a stopped backend, most obviously — told the reader their verdict had
  // not been recorded, about a verdict they had not cast.
  const load = useCallback(() => {
    return getReviewQueue()
      .then((items) => {
        setQueue(items)
        setLoadError(null)
      })
      .catch((cause: unknown) => {
        setLoadError(cause instanceof Error ? cause.message : 'Failed to load the queue.')
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

  if (!queue && !loadError) return <p>Loading the review queue…</p>

  // Deciding removes an item, so the cursor can be left pointing past the end.
  // Clamping at render rather than in the reload keeps the two independent.
  const total = queue?.items.length ?? 0
  const position = total === 0 ? 0 : Math.min(index, total - 1)
  const item = queue?.items[position]

  return (
    <div className="view">
      <h1>Review</h1>
      {loadError && <div role="alert">Could not load the review queue: {loadError}</div>}
      {error && <div role="alert">Could not record that: {error}</div>}

      {corpusEmpty ? (
        <EmptyState lead="Nothing has been proposed for review." />
      ) : !item ? (
        // STORY-090. "Nothing is waiting for review" is true of three different
        // situations and tells a reader only one of them: that they are caught up.
        // On 2026-08-26 the graph held one edition with 114 obligations and three
        // with none, so no proposal could exist — and this screen said the queue
        // was clear. The same false all-clear ADR-015 and STORY-067 fixed on
        // Triage, on the screen those fixes did not touch.
        queue &&
        (queue.editions_with_obligations === 0 ? (
          <p>
            <strong>The queue cannot be filled yet.</strong> No edition in the
            corpus has any obligations extracted from it, so there is nothing for a
            proposal to be made between. Build an edition's derived layer with a
            real extraction model configured.
          </p>
        ) : queue.documents_with_obligations < 2 ? (
          <p>
            <strong>The queue cannot be filled yet.</strong> Obligations exist, but
            only one document holds any — and a proposal links a clause in one
            document to a clause in another, so it needs both sides. Ingest a
            second document and build an edition of it; comparing this
            document's own editions is the pairing screen's question.
          </p>
        ) : (
          <p>Nothing is waiting for review.</p>
        ))
      ) : (
        <article>
          <p>
            {/* `total` is the page, `queue.pending` is the backlog, and the
                screen has to say which is which. It read "Proposal 1 of 50" over
                119 undecided pairs and went on reading it after every verdict,
                because deciding one refilled the page from the remainder — so a
                reviewer had no measure of the work and no sign of progress. The
                waiting count falls as the queue is worked through. */}
            Proposal {position + 1} of {total}
            {queue && queue.pending > total && <> shown, {queue.pending} waiting</>}.
            {' '}Proposed by {item.proposer} at{' '}
            {Math.round(item.confidence * 100)}% confidence.
          </p>

          {wrapped && (
            <p role="status">
              Back at the start — every proposal in the queue has been offered at
              least once. Skipping records nothing, so these are all still waiting.
            </p>
          )}

          <div className="panes">
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
                    goTo((position - 1 + total) % total)
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
                    goTo(next)
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
