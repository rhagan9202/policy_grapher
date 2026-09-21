import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getTriage, listDocuments, listVersions } from '../api/client'
import type {
  DocumentOut,
  DocumentVersionOut,
  TriageCitation,
  TriageOut,
} from '../api/types'
import EmptyState from './EmptyState'

function Citation({
  heading,
  of,
  previously,
}: {
  heading: string
  of: TriageCitation
  previously?: string | null
}) {
  return (
    <div className="pane">
      <h4>{heading}</h4>
      <blockquote>{of.statement}</blockquote>
      {/* Inside the pane, because it is the previous wording *of this clause*.
          Rendered after both panes it sat under the other document's clause,
          putting the before and after of one obligation either side of an
          unrelated one. */}
      {previously && (
        <p>
          Previously: <q>{previously}</q>
        </p>
      )}
      <cite>
        {of.document} · <code>{of.version_id}</code> ·{' '}
        {of.section_path.join('/')} · p. {of.page}
      </cite>
    </div>
  )
}

/** One document's triage state, held with the slug it belongs to. */
type HeldTriage = {
  slug: string
  versions: DocumentVersionOut[] | null
  versionId: string
  result: TriageOut | null
  error: string | null
}

export default function Triage() {
  // U8. The map links here with the document it was drawn around, so the reader
  // arrives on the right row rather than finding it again in a picker of every
  // document that has an edition. The edition is deliberately not carried:
  // choosing one runs the diff, and that route writes (see `chooseEdition`), so
  // following a link must never be enough to start it.
  // The chosen document lives in the address, not beside it. An earlier draft
  // seeded state from the parameter once at mount, which left the two able to
  // disagree: clicking Triage in the navigation while already on
  // `/triage?document=x` is a same-route navigation, so the component does not
  // remount — the address dropped the document while the picker went on showing
  // it, and the link was no longer the view the reader was looking at. One
  // source of truth removes the question, and makes this screen addressable the
  // way the map is (KTD5).
  const [searchParams, setSearchParams] = useSearchParams()
  const slug = searchParams.get('document') ?? ''
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  // Every slug the corpus holds, editions or not — the picker above is filtered
  // to those with editions, so it cannot answer "does this name exist".
  const [allSlugs, setAllSlugs] = useState<Set<string>>(new Set())
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)
  // Everything below is about one document, so it is held with the slug it was
  // loaded for. The address can change under this screen without a remount, and
  // a held answer that outlives the document it describes is the defect the map
  // side of this feature guards against with the same idiom.
  const [held, setHeld] = useState<HeldTriage | null>(null)
  const current = held && held.slug === slug ? held : null
  // `null` until the editions for `slug` have answered. An empty array is a
  // real answer — this document has no ingested edition — and the two need
  // different sentences, so they cannot share a value.
  const versions = current?.versions ?? null
  const versionId = current?.versionId ?? ''
  const result = current?.result ?? null
  const error = current?.error ?? null
  const [documentsError, setDocumentsError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((result) => {
        // STORY-040: only a document with editions can be triaged. Offering the
        // other 439 leads to an empty edition list and no explanation.
        if (cancelled) return
        setDocuments(result.filter((d) => d.version_count > 0))
        setAllSlugs(new Set(result.map((d) => d.slug)))
        setCorpusEmpty(result.length === 0)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setDocumentsError(
            cause instanceof Error ? cause.message : 'Failed to load documents.',
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
      .then((editions) => {
        if (!cancelled) {
          setHeld({ slug, versions: editions, versionId: '', result: null, error: null })
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setHeld({
            slug,
            versions: null,
            versionId: '',
            result: null,
            error: cause instanceof Error ? cause.message : 'Failed to load editions.',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  useEffect(() => {
    if (!versionId) return
    let cancelled = false
    // Updated through the previous hold rather than rebuilt from the values in
    // scope. `slug` and `versions` in the closure would have to join the
    // dependency list, and this effect calls a route that WRITES — re-running
    // it because the editions list changed would run a second diff nobody
    // asked for. `versionId` names its own document, so a hold that still
    // carries it is the hold this answer belongs to.
    getTriage(versionId)
      .then((answer) => {
        if (cancelled) return
        setHeld((prev) =>
          prev && prev.versionId === versionId
            ? { ...prev, result: answer, error: null }
            : prev,
        )
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        const message = cause instanceof Error ? cause.message : 'Failed to load triage.'
        setHeld((prev) =>
          prev && prev.versionId === versionId
            ? { ...prev, result: null, error: message }
            : prev,
        )
      })
    return () => {
      cancelled = true
    }
  }, [versionId])

  // Clearing stale state belongs in the handler that invalidates it, not in an
  // effect: a synchronous setState in an effect body cascades a second render
  // for something the event already knew (react-hooks/set-state-in-effect).
  // The oldest edition supersedes nothing, so GET /triage answers 400 for it
  // every time (ADR-015). Offering a choice we can predict will fail is worse
  // than not offering it. Editions arrive oldest-first from the API.
  const comparableEditions = (versions ?? []).slice(1)
  const noEditions = corpusEmpty === false && documents.length === 0
  // `GET /documents/{slug}/versions` does not check that the slug names
  // anything (`list_versions` in routers/documents.py runs its query and
  // returns what it finds), so an address naming no document answers 200 with
  // an empty list — the same shape a real document with no ingested edition
  // gives. Verified live against this backend. Without the corpus listing to
  // tell them apart, a mistyped drill-down would be diagnosed as a document
  // that exists and has no text, which is a confident answer about something
  // that is not there.
  //
  // `documents` is filtered to documents that have editions, so it cannot
  // settle this on its own: absence from it is the ordinary case here. The
  // question is only whether the corpus knows the name at all, and that is
  // what `corpusKnowsSlug` answers — `null` while the listing is outstanding,
  // so neither sentence is said before there is ground for it.
  const corpusKnowsSlug =
    slug === '' || corpusEmpty === null
      ? null
      : allSlugs.has(slug)

  function chooseDocument(next: string) {
    // The address is the state. Nothing is cleared here: everything held is
    // keyed to the slug it was loaded for, so changing the slug retires it —
    // by this route, by the back button, or by a link from the map alike.
    setSearchParams(next ? { document: next } : {})
  }

  function chooseEdition(next: string) {
    setHeld({ slug, versions, versionId: next, result: null, error: null })
  }

  // A triage answer is about *changes* only when both editions have obligations
  // to compare. With one side empty every obligation on the other counts as a
  // change, so `total_changes` is an artefact of an unbuilt edition rather than a
  // finding — and both the unlinked-changes line and the "approve links in Review"
  // prompt would mislead: Review's queue cannot be filled at all, because a
  // proposal needs obligations on both sides. STORY-067 drew this distinction only
  // for `total_changes === 0`, so the one-sided case reached neither branch and
  // fell through to the Review prompt. Found live on 2026-08-26 against
  // from_obligations 0 / to_obligations 113 / total_changes 113.
  const bothSidesExtracted =
    result !== null && result.from_obligations > 0 && result.to_obligations > 0
  return (
    <div className="view">
      <h1>Triage</h1>

      {/* A failed document listing is not a failed triage. Folded into the same
          slot they read as one, and the reader cannot tell that the picker
          below is empty because the list never arrived. */}
      {documentsError && (
        <div role="alert">Could not load the documents to triage: {documentsError}</div>
      )}

      {corpusEmpty ? (
        <EmptyState lead="There is nothing to triage." />
      ) : noEditions ? (
        /* A manifest records documents but no text (ADR-011), so a corpus
           ingested from CSV alone has 438 documents and nothing to compare.
           Without this the picker renders empty and unexplained. */
        <div role="status">
          <p>
            <strong>No document has an ingested edition yet.</strong>
          </p>
          <p>
            Triage compares two editions of the same instrument. A CSV manifest
            records which documents cite which, but carries no text — ingest a
            PDF, such as <code>500001p.pdf</code>, to give a document an edition.
          </p>
        </div>
      ) : (
      <>
      <label>
        Document{' '}
        <select value={slug} onChange={(event) => chooseDocument(event.target.value)}>
          <option value="">Choose a document…</option>
          {documents.map((document) => (
            <option key={document.slug} value={document.slug}>
              {document.name}
            </option>
          ))}
        </select>
      </label>{' '}
      <label>
        Edition{' '}
        <select
          value={versionId}
          onChange={(event) => chooseEdition(event.target.value)}
          disabled={comparableEditions.length === 0}
        >
          <option value="">Choose an edition…</option>
          {comparableEditions.map((version) => (
            <option key={version.version_id} value={version.version_id}>
              {version.effective_date ?? version.version_id}
            </option>
          ))}
        </select>
      </label>

      {versions?.length === 1 && (
        <p>
          This document has only one edition, so there is nothing to compare it
          against.
        </p>
      )}

      {/* The picker only offers documents with an edition, so this is reachable
          only by an address someone wrote by hand — which the map's drill-down
          now makes an ordinary thing to do. An edition picker rendered empty
          with no reason given is the defect the empty-corpus branch above
          exists to prevent, one level further down. */}
      {slug !== '' && versions?.length === 0 && corpusKnowsSlug === false && (
        <p>
          <strong>
            Nothing in the corpus answers to <code>{slug}</code>.
          </strong>{' '}
          The address may be mistyped, or the document may have been removed.
        </p>
      )}

      {slug !== '' && versions?.length === 0 && corpusKnowsSlug === true && (
        <p>
          <strong>
            No edition of <code>{slug}</code> has been ingested.
          </strong>{' '}
          Triage compares two editions of the same instrument, and this one has
          no text in the graph to compare.
        </p>
      )}

      {error && <div role="alert">Could not triage that edition: {error}</div>}

      {result && (
        <section>
          <p>
            Compared against <code>{result.from_version_id}</code>.
          </p>

          {/*
            ADR-015: this number is what keeps an empty table honest. Without it,
            "nothing you own is affected" and "nothing has been reviewed yet" are
            the same blank screen, and one of them is a false all-clear.
          */}
          {result.unlinked_changes > 0 && bothSidesExtracted && (
            <p>
              {result.unlinked_changes} of {result.total_changes} changes have no
              reviewed link to anything of ours, so they do not appear below.
            </p>
          )}

          {/*
            Not gated on `bothSidesExtracted`, unlike the line above: this counts
            a person's verdicts rather than the diff's findings, and a shelved
            verdict is shelved whether or not both editions were extracted. The
            decision stands — the diff simply had nothing to attach it to,
            because pass 1 matched the clause unchanged in both editions — so
            saying nothing leaves it indistinguishable from one that took effect.
          */}
          {result.pairings_unapplied > 0 && (
            <p>
              {result.pairings_unapplied} recorded pairing
              {result.pairings_unapplied === 1 ? '' : 's'} could not be applied to
              this diff: the clause each names is matched unchanged in both
              editions, so there is no rewording for the verdict to attach to.
              They are still recorded, on <Link to="/pairings">Pairings</Link>.
            </p>
          )}

          {result.rows.length === 0 ? (
            !bothSidesExtracted ? (
              <p>
                <strong>
                  No obligations have been extracted for{' '}
                  {result.from_obligations === 0 && result.to_obligations === 0
                    ? 'either edition'
                    : result.from_obligations === 0
                      ? `${result.from_version_id}`
                      : `${result.to_version_id}`}
                  .
                </strong>{' '}
                {result.total_changes === 0
                  ? `Nothing can have changed between them, because there is nothing
                     yet to compare.`
                  : `The ${result.total_changes} changes counted above are an artefact
                     of that: with one side empty, every obligation on the other reads
                     as ${result.from_obligations === 0 ? 'an addition' : 'a removal'}.
                     Review cannot help here either — a proposal needs obligations on
                     both sides, so its queue cannot be filled until this edition is
                     built.`}{' '}
                Build the derived layer for both editions with a real extraction
                model configured.
              </p>
            ) : result.total_changes === 0 ? (
              <p>No obligation changed between these editions.</p>
            ) : result.outbound_implements > 0 ? (
              <p>
                <strong>Links from these editions point the other way.</strong>{' '}
                {result.outbound_implements} reviewed{' '}
                {result.outbound_implements === 1 ? 'link' : 'links'} leave a clause in
                these editions implementing another document — and Triage asks the
                opposite question: which of ours implements a clause that{' '}
                <em>changed here</em>. Those outbound links surface when you open
                Triage on the other document&apos;s edition pair (it needs two
                editions to compare). To fill <em>this</em> table, rebuild a
                lower-tier document with this one ticked under Propose links
                against, then approve in Review.
              </p>
            ) : (
              <p>
                Nothing has been linked to these changes yet — this is not a
                finding that nothing is affected. Approve links in Review first.
              </p>
            )
          ) : (
            <ol className="triage-rows">
              {result.rows.map((row) => (
                <li key={row.change_id}>
                  <p>
                    <strong>{row.kind}</strong> · {row.modality} · score{' '}
                    {row.score.toFixed(1)}
                  </p>
                  <p>{row.summary}</p>
                  <div className="panes">
                    <Citation
                      heading="What changed"
                      of={row.higher}
                      previously={row.previous_statement}
                    />
                    <Citation heading="What it reaches" of={row.ours} />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
      </>
      )}
    </div>
  )
}
