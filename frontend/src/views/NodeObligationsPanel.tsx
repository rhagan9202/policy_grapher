import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listObligations, listVersions } from '../api/client'
import type { DocumentVersionOut, ObligationsOut } from '../api/types'

/** What this panel has read about its document. It carries no slug: the
 *  component is keyed on one, so an instance only ever describes the document
 *  it was mounted for, and there is nothing to compare against.
 *
 *  `editions` is the whole answer, oldest-first, so which one is newest is read
 *  off it rather than stored beside it — a second copy of a fact is a second
 *  thing that can disagree with it. Empty means the document has no ingested
 *  edition, the common case on a focused map, where most nodes are documents
 *  the corpus holds by name because something cites them. */
type HeldNodeDetail = {
  /** `null` when the editions read itself failed, which is not the same fact as
   *  a document that has none — and must never render as one. Same null-versus-
   *  empty discipline the rest of this codebase uses wherever "nobody looked"
   *  and "nothing is there" share a shape. */
  editions: DocumentVersionOut[] | null
  editionsError: string | null
  obligations: ObligationsOut | null
  /** Scoped to the obligations read alone. A failure here leaves the editions
   *  standing: which editions exist is already known, and the drill-down and
   *  the one-edition message are built from that and nothing else. */
  obligationsError: string | null
}

/** Why an edition holds no obligations. A zero has several meanings and they
 *  call for opposite actions, which is the whole reason `build_state` is
 *  recorded on an edition (STORY-082): "extraction ran and found nothing" is a
 *  finding about the document, while "no build has run" is a fact about us.
 *  Rendering them the same way is the false all-clear ADR-015 exists to
 *  prevent, and R10 forbids on this screen in particular. */
function emptyObligationsReason(edition: DocumentVersionOut | undefined): string {
  if (!edition || edition.build_state == null) {
    return 'No build has run for it, so nothing has been extracted yet.'
  }
  if (edition.build_state === 'started') {
    return 'A build of it is running.'
  }
  if (edition.build_state === 'failed') {
    return 'Its last build failed, so they are missing rather than absent.'
  }
  // ADR-028: the `null` extractor writes chunks and no obligations by design,
  // so a finished run under it is not evidence about the document either.
  if (edition.build_extractor_adapter === 'null') {
    return 'It was built with the null extractor, which records none by design.'
  }
  return ''
}

/** How many obligations the panel prints before it stops. The document's own
 *  page is a link away and renders the edition in full; this is a look at what
 *  the node holds, not a second copy of that page.
 *
 *  Three rather than five, chosen against the live corpus: DoDD 5000.01's
 *  obligations run four lines each, and five of them pushed the Triage
 *  drill-down below the fold on a 900px viewport — so the panel's own bound was
 *  hiding the other half of what this unit exists to offer. The count above the
 *  list always states the edition's real total, so a smaller window costs the
 *  reader nothing they are not told about. */
const OBLIGATIONS_SHOWN = 3

/** What the map can say about one selected document, from its editions down to
 *  its obligations, with Triage offered beneath as the drill-down.
 *
 *  Rendered with `key={slug}` by its parent, which is what makes a stale
 *  render impossible rather than merely guarded: changing the selection
 *  remounts this component, so state cannot survive the document it was read
 *  for. An earlier arrangement held the answer beside the slug it belonged to
 *  and compared them on every render; the key does the same work structurally.
 *
 *  The `cancelled` flag is still load-bearing. It stops an answer arriving
 *  after this instance is gone from writing to it, and it is what makes the
 *  effect correct under StrictMode's mount/unmount/remount. */
export default function NodeObligationsPanel({
  slug,
  label,
}: {
  slug: string
  label: string
}) {
  const [nodeDetail, setNodeDetail] = useState<HeldNodeDetail | null>(null)
  useEffect(() => {
    let cancelled = false
    const read = async () => {
      let editions: DocumentVersionOut[]
      let newest: DocumentVersionOut | undefined
      try {
        // Two reads, not one: the obligations route takes an explicit edition
        // (STORY-081), so which edition is the newest has to be answered first.
        editions = await listVersions(slug)
        if (cancelled) return
        // Inside the guard, not after it. Anything this read hands back that is
        // not a list of editions fails here, and failing here is reported; an
        // earlier arrangement left this line outside and a malformed answer
        // threw past every branch, leaving the panel reading for ever.
        newest = editions.at(-1)
      } catch (cause: unknown) {
        if (cancelled) return
        // Nothing is known, and `editions: null` says so. Reporting `[]` here
        // would turn a failed read into the claim that this document has no
        // edition — an unknown rendered as a known-empty (R10).
        setNodeDetail({
          editions: null,
          editionsError: cause instanceof Error ? cause.message : 'Failed to read its editions.',
          obligations: null,
          obligationsError: null,
        })
        return
      }
      if (!newest) {
        // Nothing was ever ingested, so there is no edition to ask about and
        // no request to make. Asking anyway would answer for an edition that
        // does not exist.
        setNodeDetail({
          editions,
          editionsError: null,
          obligations: null,
          obligationsError: null,
        })
        return
      }
      try {
        const obligations = await listObligations(slug, newest.version_id)
        if (cancelled) return
        setNodeDetail({
          editions, editionsError: null, obligations, obligationsError: null,
        })
      } catch (cause: unknown) {
        if (cancelled) return
        // The editions survive. Which editions exist was already answered, and
        // the drill-down rests on that alone — losing it here would hide a
        // working control because an unrelated read failed.
        setNodeDetail({
          editions,
          editionsError: null,
          obligations: null,
          obligationsError:
            cause instanceof Error ? cause.message : 'Failed to read its obligations.',
        })
      }
    }
    void read()
    return () => {
      cancelled = true
    }
  }, [slug])

  // What the panel will actually print, against what the edition holds. Derived
  // once: the comparison and the printed number have to be the same figure, and
  // computing it twice is two places for them to stop being.
  const detail = nodeDetail
  const shown = Math.min(
    detail?.obligations?.obligations.length ?? 0,
    OBLIGATIONS_SHOWN,
  )

  return (
    <>
      {/* R8, F2. Structure down to specific obligations without leaving
          the map.

          The interim shape U8 ships with, stated in the plan rather than
          assumed: obligation detail where extraction has recorded any,
          and a plain statement where it has not. Building them on demand
          waits on the managed extraction adapter, which does not exist
          yet — so this never offers an action it cannot perform. */}
      {detail === null ? (
        <p>Reading what it holds…</p>
      ) : detail.editions === null ? (
        /* The read failed, so nothing is known. Disjoint from the empty
           case below by construction — `null` and `[]` are different
           values, so no branch ordering decides which of these two
           renders, and a reordering cannot turn a failure into the claim
           that this document has no edition. */
        <p role="alert">
          Could not read its editions: {detail.editionsError}
        </p>
      ) : detail.editions.length === 0 ? (
        /* R10. The common node on a focused map, and the one a check
           written only for the single-edition case leaves bare. The
           corpus holds this document because something cites it, so an
           absence here is a fact about what was never read — not a
           finding that the document imposes nothing. */
        <p>
          <strong>
            No edition of {label} has been ingested.
          </strong>{' '}
          The corpus holds its name because another document cites it, not
          its text — so there are no obligations to open, and nothing to
          compare.
        </p>
      ) : (
        <>
          {/* "Obligations", not "clauses": the word the rest of this
              screen already uses, in the tier ladder beside every node
              and on the document's own page. */}
          <h3>Obligations</h3>
          {detail.obligationsError ? (
            /* Said on its own line, above a drill-down that still works.
               Which editions exist came from the other read. */
            <p role="alert">
              Could not read its obligations: {detail.obligationsError}
            </p>
          ) : detail.obligations === null ||
            detail.obligations.total === 0 ? (
            /* A zero has several meanings and they call for opposite
               actions. "Extraction ran and found none" is a finding
               about the document; "no build has run" is a fact about us,
               and saying the second when the first is true — or the
               reverse — is the false all-clear ADR-015 forbids. */
            (() => {
              const newest = detail.editions.at(-1)
              const reason = emptyObligationsReason(newest)
              return reason === '' ? (
                <p>
                  <strong>
                    Extraction found no obligations in edition{' '}
                    <code>{newest?.version_id}</code>.
                  </strong>
                </p>
              ) : (
                <p>
                  <strong>
                    No obligations recorded for edition{' '}
                    <code>{newest?.version_id}</code>.
                  </strong>{' '}
                  {reason}
                </p>
              )
            })()
          ) : (
            <>
              <p>
                {detail.obligations.total} obligation
                {detail.obligations.total === 1 ? '' : 's'} in edition{' '}
                <code>{detail.editions.at(-1)?.version_id}</code>.
                {/* Two bounds can cut this list — the route's own, and
                    this panel's — so the sentence counts what is on
                    screen against what the edition holds, rather than
                    repeating either bound's idea of "returned". */}
                {shown < detail.obligations.total && (
                  <> Showing the first {shown}.</>
                )}
              </p>
              <ol>
                {detail.obligations.obligations
                  .slice(0, OBLIGATIONS_SHOWN)
                  .map((obligation) => (
                    <li key={obligation.obligation_id}>
                      <p>{obligation.statement}</p>
                      <p>
                        <small>
                          {obligation.modality} ·{' '}
                          {obligation.section_path.join(' / ')} · p.{' '}
                          {obligation.page}
                        </small>
                      </p>
                    </li>
                  ))}
              </ol>
            </>
          )}

          {/* R9, KTD7. Triage is re-parented as the drill-down from a
              document, not rebuilt inside the map: its unlinked-changes
              guarantee is the thing ADR-015 exists to protect, and a
              second implementation of it is a second place to lose it.

              A link, never a fetch. The route diffs inside a write
              transaction, so entering it is a gesture the reader makes.
              The document is pre-filled and the edition deliberately is
              not — pre-filling an edition would run the diff on
              arrival, which is the same write by another route. */}
          {detail.editions.length > 1 ? (
            <p>
              <Link to={`/triage?document=${slug}`}>
                Compare its editions in Triage
              </Link>
            </p>
          ) : (
            /* AE7. Said where the control would have been, and distinct
               from Triage running and reporting no changes: one is a
               comparison that cannot be made, the other is its result. */
            <p>
              This document has only one edition, so there is nothing to
              compare it against.
            </p>
          )}
        </>
      )}
    </>
  )
}
