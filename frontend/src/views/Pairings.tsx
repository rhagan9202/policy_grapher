import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getPairingQueue,
  listDocuments,
  listVersions,
  recordPairing,
} from '../api/client'
import EmptyState from './EmptyState'
import type {
  DocumentOut,
  DocumentVersionOut,
  ObligationCitation,
  PairingCandidate,
  PairingQueue,
  PairingVerdict,
} from '../api/types'

// The four outcomes in the order the diff's rules fire. They are not four
// disjoint conditions: every pair declined because a partner was taken also
// satisfies the margin rule, so `partner_taken` is contained in `contested` and
// the labels record precedence. They stay two headings because `partner_taken`
// is the actionable one — a winner exists, and it is named.
const OUTCOME_ORDER = ['auto_paired', 'partner_taken', 'contested', 'below_threshold']

const OUTCOME_LABEL: Record<string, string> = {
  auto_paired: 'Paired by the diff',
  partner_taken: 'A higher-scoring pair took one of these clauses',
  contested: 'Two candidates too close to separate',
  below_threshold: 'Below the pairing bar',
}

const OUTCOME_BLURB: Record<string, string> = {
  auto_paired:
    'The wording pass made this pair and nobody reviewed it. Mark it distinct to undo it.',
  partner_taken:
    'One end of this pair is already held by a pair that scored higher. Mark that pairing distinct first if this one is the right answer.',
  contested:
    'Another candidate scored within a hair of this one, so the diff declined both rather than pick whichever came first.',
  below_threshold:
    'Scored, but under the confidence the diff pairs at, so it never entered the pairing loop.',
}

function rank(outcome: string): number {
  const at = OUTCOME_ORDER.indexOf(outcome)
  // An outcome this screen has no heading for still renders, last and under its
  // own raw name. A candidate dropped because its label is unfamiliar is a pair
  // nobody can reach, which is the failure this whole screen exists to end.
  return at === -1 ? OUTCOME_ORDER.length : at
}

function byOutcome(items: PairingCandidate[]): [string, PairingCandidate[]][] {
  const groups = new Map<string, PairingCandidate[]>()
  for (const item of items) {
    const found = groups.get(item.outcome)
    if (found) found.push(item)
    else groups.set(item.outcome, [item])
  }
  return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b))
}

type Pair = { old: ObligationCitation; new: ObligationCitation }

function pairKey(pair: Pair): string {
  return `${pair.old.obligation_id}|${pair.new.obligation_id}`
}

/** One clause of the pair, sourced.
 *
 *  No document name: both sides are editions of one instrument, so it is the
 *  same string twice and settles nothing. The edition id is the distinction
 *  being made here, exactly as it is on Review — where printing the document
 *  alone left a reviewer unable to tell the 2022 text from the 2018.
 *
 *  The obligation id is printed because this screen's instructions are written
 *  in them: `taken_by` and the POST's 409 both name the pairing to settle first
 *  by id, and an id nothing on the page carries is an instruction the reader
 *  cannot follow. */
function Side({ heading, of }: { heading: string; of: ObligationCitation }) {
  return (
    <section className="pane">
      <h3>{heading}</h3>
      <blockquote>{of.statement}</blockquote>
      <p>
        <cite className="citation">
          <code>{of.obligation_id}</code>
          <code>{of.version_id}</code>
          <span>{of.section_path.join('/')}</span>
          <span>p. {of.page}</span>
        </cite>
      </p>
    </section>
  )
}

function Reason({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  return (
    <label>
      Reason (optional)
      <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}

export default function Pairings() {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)
  const [slug, setSlug] = useState('')
  const [versions, setVersions] = useState<DocumentVersionOut[]>([])
  const [fromVersionId, setFromVersionId] = useState('')
  const [toVersionId, setToVersionId] = useState('')
  const [queue, setQueue] = useState<PairingQueue | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Which queue request the screen is still waiting for. This GET runs the diff,
  // so it is slow by construction and a reviewer can change edition twice before
  // the first answers; an answer that arrives after they moved on would draw one
  // pair's candidates under another pair's label, and verdicts recorded from
  // those rows would settle pairs the reviewer never looked at.
  const request = useRef(0)
  // Keyed by pair, not one box for the screen. Every candidate is on screen at
  // once here, and a single shared field files the reason typed against one pair
  // with whichever pair is clicked next — the defect Review's walkthrough found,
  // where a verdict is permanent and replayed on every rebuild.
  const [rationales, setRationales] = useState<Record<string, string>>({})
  const [pending, setPending] = useState(false)

  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((found) => {
        if (cancelled) return
        // A pairing question is asked between two editions of one instrument, so
        // a document with one edition has nothing to ask. Offering it produces
        // two identical pickers and an explanation nobody wrote.
        setDocuments(found.filter((d) => d.version_count > 1))
        setCorpusEmpty(found.length === 0)
      })
      // Its own state, not the queue's. A corpus that could not be listed is not
      // a queue that failed to load: the reviewer has not asked for a queue yet,
      // and saying one failed points them at a question they never put.
      .catch((cause: unknown) => {
        if (!cancelled) {
          setCatalogError(
            `Could not load the documents: ${
              cause instanceof Error ? cause.message : 'the request failed.'
            }`,
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!slug) return
    let cancelled = false
    listVersions(slug)
      .then((found) => {
        if (!cancelled) setVersions(found)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setCatalogError(
            `Could not load the editions of ${slug}: ${
              cause instanceof Error ? cause.message : 'the request failed.'
            }`,
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  // Two failures, two states. A queue that failed to *load* — a stopped backend,
  // or the 400 a reversed pair earns — must not be reported under "could not
  // record that", about a verdict nobody cast.
  //
  // Written with `.then`/`.catch` rather than `async`/`await`, as Review's
  // loader is: `react-hooks/set-state-in-effect` reads an awaited setState as a
  // synchronous one and fails the lint gate, while a setState inside a promise
  // callback is the shape the rule allows.
  const load = useCallback((): Promise<void> => {
    // Bumped even when nothing is fetched: clearing the pair has to invalidate
    // whatever is already in flight, or choosing a different document mid-request
    // lands the old pair's queue on the new one's screen.
    const mine = (request.current += 1)
    if (!fromVersionId || !toVersionId || fromVersionId === toVersionId) {
      return Promise.resolve()
    }
    return getPairingQueue(fromVersionId, toVersionId)
      .then((found) => {
        if (request.current !== mine) return
        setQueue(found)
        setLoadError(null)
      })
      .catch((cause: unknown) => {
        if (request.current !== mine) return
        // Cleared, not left standing: a stale queue under an error banner is the
        // previous pair's question wearing this pair's heading.
        setQueue(null)
        // The message and nothing else. Every refusal this route makes names its
        // own remedy — which pairing to mark distinct first, which admissibility
        // it wanted — and a generic sentence in its place is a screen that
        // refuses without saying what to do about it.
        setLoadError(
          cause instanceof Error ? cause.message : 'Failed to load the pairing queue.',
        )
      })
  }, [fromVersionId, toVersionId])

  useEffect(() => {
    void load()
    // The pair being asked about has changed, so the answer to the previous
    // question is no longer an answer to anything on screen.
    return () => {
      request.current += 1
    }
  }, [load])

  // Clearing what a choice invalidates belongs in the handler that made the
  // choice. A setState in an effect body is the cascading render the lint rule
  // forbids, and it has produced an intermittent failure in this suite before.
  function chooseDocument(next: string) {
    setSlug(next)
    setVersions([])
    setFromVersionId('')
    setToVersionId('')
    setQueue(null)
    setLoadError(null)
    setError(null)
  }

  function chooseEdition(side: 'from' | 'to', next: string) {
    if (side === 'from') setFromVersionId(next)
    else setToVersionId(next)
    setQueue(null)
    setLoadError(null)
    setError(null)
  }

  // `recorded` is the reason already on the decision, for a pair that has one.
  // Sending '' where the reviewer edited nothing would erase it: the recorder
  // SETs `rationale` on every write.
  async function settle(pair: Pair, verdict: PairingVerdict, recorded = '') {
    // `pending` gates every button for the whole round trip. A re-verdict
    // replaces rather than appends, so a double-click would silently overwrite
    // one judgement with whichever button was pressed last.
    setPending(true)
    setError(null)
    const key = pairKey(pair)
    try {
      await recordPairing(
        pair.old.obligation_id,
        pair.new.obligation_id,
        verdict,
        rationales[key] ?? recorded,
      )
      setRationales((current) => {
        const next = { ...current }
        delete next[key]
        return next
      })
      // The verdict changes what the diff produces, so the queue is re-read
      // rather than edited in place: this screen must not be the one place that
      // believes something the graph does not.
      await load()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Failed to record the verdict.')
    } finally {
      setPending(false)
    }
  }

  // Both verdicts on a settled pair too, not only the one that reverses it. A
  // verdict outside the closed pair of words has no "other" to offer, and
  // re-recording the same one with a corrected reason is a thing a reviewer may
  // legitimately want — the record keeps the latest rationale.
  function verdictButtons(
    pair: Pair,
    paired: string,
    distinct: string,
    recorded = '',
  ) {
    return (
      <p>
        <button
          type="button"
          disabled={pending}
          onClick={() => settle(pair, 'paired', recorded)}
        >
          {paired}
        </button>{' '}
        <button
          type="button"
          disabled={pending}
          onClick={() => settle(pair, 'distinct', recorded)}
        >
          {distinct}
        </button>
      </p>
    )
  }

  const noPairableDocuments = corpusEmpty === false && documents.length === 0

  return (
    <div className="view">
      <h1>Pairings</h1>
      <p>
        Between two editions of one instrument the diff pairs what it can and
        declines the rest. This is where a person settles what it declined, and
        undoes what it guessed. Whether one of our clauses discharges another
        document&rsquo;s duty is a different question, and it is Review&rsquo;s.
      </p>

      {corpusEmpty ? (
        <EmptyState lead="There is nothing to pair." />
      ) : noPairableDocuments ? (
        <div role="status">
          <p>
            <strong>No document has two editions yet.</strong>
          </p>
          <p>
            A pairing question is asked between two editions of one instrument, so
            it needs both sides. Ingest a second edition of a document that
            already has one.
          </p>
        </div>
      ) : (
        <>
          <label>
            Document{' '}
            <select value={slug} onChange={(event) => chooseDocument(event.target.value)}>
              <option value="">Choose a document…</option>
              {documents.map((found) => (
                <option key={found.slug} value={found.slug}>
                  {found.name}
                </option>
              ))}
            </select>
          </label>{' '}
          <label>
            Older edition{' '}
            <select
              value={fromVersionId}
              onChange={(event) => chooseEdition('from', event.target.value)}
              disabled={versions.length === 0}
            >
              <option value="">Choose an edition…</option>
              {versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.effective_date
                    ? `${version.effective_date} (${version.version_id})`
                    : version.version_id}
                </option>
              ))}
            </select>
          </label>{' '}
          <label>
            Newer edition{' '}
            <select
              value={toVersionId}
              onChange={(event) => chooseEdition('to', event.target.value)}
              disabled={versions.length === 0}
            >
              <option value="">Choose an edition…</option>
              {versions.map((version) => (
                <option key={version.version_id} value={version.version_id}>
                  {version.effective_date
                    ? `${version.effective_date} (${version.version_id})`
                    : version.version_id}
                </option>
              ))}
            </select>
          </label>

          {/* The screen does not work out for itself which edition is older. The
              corpus orders editions by effective date, then ingestion time, then
              version id — and ingestion time is not in this payload at all, so a
              guess here would either duplicate a rule that can drift or refuse a
              pair the route would have accepted. Named backwards, the route
              answers 400 and the banner below says so. */}

          {fromVersionId !== '' && fromVersionId === toVersionId && (
            <p>
              Those are the same edition. A pairing question runs between two of
              them.
            </p>
          )}

          {loadError && (
            <div role="alert">Could not load the pairing queue: {loadError}</div>
          )}
          {catalogError && <div role="alert">{catalogError}</div>}
          {error && <div role="alert">Could not record that: {error}</div>}

          {queue && (
            <section>
              <p>
                {queue.items.length} candidate{queue.items.length === 1 ? '' : 's'}
                {queue.pending > queue.items.length && (
                  <> shown, {queue.pending} waiting</>
                )}
                . {queue.settled.length} already settled.
              </p>

              {queue.pairings_unapplied > 0 && (
                <p>
                  {queue.pairings_unapplied} recorded pairing
                  {queue.pairings_unapplied === 1 ? '' : 's'} could not be applied
                  to this diff: the clause it names is matched unchanged in both
                  editions, so there is no rewording for the verdict to attach to.
                  The decisions are still recorded.
                </p>
              )}

              {queue.items.length === 0 ? (
                <p>Nothing is waiting to be paired between these two editions.</p>
              ) : (
                byOutcome(queue.items).map(([outcome, items]) => (
                  <section key={outcome}>
                    <h2>{OUTCOME_LABEL[outcome] ?? outcome}</h2>
                    {OUTCOME_BLURB[outcome] && <p>{OUTCOME_BLURB[outcome]}</p>}
                    <ol>
                      {items.map((item) => (
                        <li key={pairKey(item)}>
                          <div className="panes">
                            <Side heading="Older clause" of={item.old} />
                            <Side heading="Newer clause" of={item.new} />
                          </div>
                          {/* Two sentences from two authors, so two paragraphs.
                              The measure's rationale is a lowercase fragment
                              that restates the same percentage — "they share 88%
                              of the shorter clause's distinctive wording (…)" —
                              and concatenating them onto the confidence reads as
                              a sentence beginning in lower case with its number
                              said twice. Review keeps them apart for the same
                              reason. */}
                          <p>{Math.round(item.confidence * 100)}% confidence.</p>
                          <p>{item.rationale}</p>
                          {/* The ids as they came. `taken_by` names obligations,
                              the queue is capped, and the winner is routinely
                              outside the page — so there is nothing on this
                              screen to resolve them against, and a row that went
                              blank when the lookup missed would lose the one
                              instruction it carries. */}
                          {item.taken_by.length > 0 && (
                            <p>
                              Already paired with <code>{item.taken_by.join(', ')}</code>.
                            </p>
                          )}
                          <Reason
                            value={rationales[pairKey(item)] ?? ''}
                            onChange={(next) =>
                              setRationales((current) => ({
                                ...current,
                                [pairKey(item)]: next,
                              }))
                            }
                          />
                          {verdictButtons(item, 'Paired', 'Distinct')}
                        </li>
                      ))}
                    </ol>
                  </section>
                ))
              )}

              {queue.settled.length > 0 && (
                <section>
                  <h2>Settled</h2>
                  {/* A settled pair is deliberately not re-recorded as a
                      candidate — the decision is the record, and a candidate edge
                      re-asking a settled question would put it straight back in
                      the queue. It is listed here because a verdict has to stay
                      reversible: a `distinct` the reviewer wants back is skipped
                      before scoring, so no candidate edge exists to find it by.
                      Both clauses are drawn for the same reason the candidate's
                      are — reversing a verdict is answering the question that was
                      answered when it was made. */}
                  <p>
                    Recording the other verdict replaces this one. Nothing deletes
                    a decision, so a pair settled here stays on this list whichever
                    way it is answered.
                  </p>
                  <ul aria-label="Settled pairs">
                    {queue.settled.map((settled) => (
                      <li key={pairKey(settled)}>
                        <div className="panes">
                          <Side heading="Older clause" of={settled.old} />
                          <Side heading="Newer clause" of={settled.new} />
                        </div>
                        <p>
                          <strong>{settled.verdict}</strong>, recorded by{' '}
                          {settled.actor}.
                        </p>
                        {/* Prefilled with the reason on record, not blank. The
                            reversal overwrites `rationale`, so a box that starts
                            empty erases the justification of the verdict being
                            reversed — and the reviewer would never have seen
                            what they erased. Clearing it deliberately still
                            works: '' is a value, and `??` only falls through for
                            a pair nobody has typed into. */}
                        <Reason
                          value={rationales[pairKey(settled)] ?? settled.rationale}
                          onChange={(next) =>
                            setRationales((current) => ({
                              ...current,
                              [pairKey(settled)]: next,
                            }))
                          }
                        />
                        {verdictButtons(
                          settled,
                          'Mark paired',
                          'Mark distinct',
                          settled.rationale,
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
