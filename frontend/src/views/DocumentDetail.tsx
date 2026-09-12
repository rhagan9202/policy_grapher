import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getDocument,
  getRebuild,
  listChunks,
  listDocuments,
  listObligations,
  listVersions,
  startRebuild,
} from '../api/client'
import { pollDelayMs } from './pollDelay'
import type {
  ChunkOut,
  DocumentOut,
  DocumentVersionOut,
  ObligationsOut,
  RebuildStatus,
} from '../api/types'

type PoolEntry = { slug: string; name: string; versions: DocumentVersionOut[] }

// STORY-017, the "corpus management" MVP item. `GET /documents/{slug}/chunks` has
// served ordered text with `page` and `section_path` since ADR-012, and `client.ts`
// had no function for the route at all — so nothing in the UI could read a
// document's text. This screen is the caller for that route, and for `getDocument`
// and `listVersions`.
export default function DocumentDetail() {
  const { slug = '' } = useParams()

  const [document, setDocument] = useState<DocumentOut | null>(null)
  const [versions, setVersions] = useState<DocumentVersionOut[]>([])
  const [chunks, setChunks] = useState<ChunkOut[] | null>(null)
  // Keyed by the edition each result describes rather than reset when the edition
  // changes. Clearing state in the effect body triggers cascading renders — the
  // lint rule says so and an intermittent test failure agreed — and the key makes
  // the reset unnecessary: a result for the previous edition simply stops matching.
  const [obligations, setObligations] = useState<{
    target: string
    data: ObligationsOut
  } | null>(null)
  const [runLost, setRunLost] = useState(false)
  const [obligationsError, setObligationsError] = useState<{
    target: string
    message: string
  } | null>(null)
  const [edition, setEdition] = useState<string | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [namesBySlug, setNamesBySlug] = useState<Map<string, string>>(new Map())

  // What the build fieldset offers: every *other* document's editions, each with
  // the document it belongs to. Not derived from `namesBySlug`, which holds names
  // for this document's references only.
  //
  // Keyed by the slug it was computed for — the `obligations` idiom below, not a
  // reset in the effect body (which trips `react-hooks/set-state-in-effect`).
  // The route carries no `key`, so navigating between documents does not remount
  // this component: a pool still in flight for the document just left, or one
  // that finished computing for it, must not be read as the answer for the
  // document now on screen. It was computed by excluding the OLD slug, not the
  // new one, so read that way it would offer the new document's own editions.
  const [pool, setPool] = useState<{ slug: string; entries: PoolEntry[] } | null>(null)
  // Its own state, not folded into a boolean on `pool`: a corpus that could not
  // be listed is not the same fact as one with nothing else in it, and the
  // fieldset's only way to say which happened is to hold the message.
  const [poolError, setPoolError] = useState<{ slug: string; message: string } | null>(
    null,
  )

  // Building the derived layer (STORY-061). The routes shipped in sprint 4 and the
  // client modelled neither, so this — sprint 4's whole deliverable — could only be
  // reached with curl.
  const [candidates, setCandidates] = useState<string[]>([])
  const [run, setRun] = useState<RebuildStatus | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [building, setBuilding] = useState(false)

  // A run that has come to rest rewrites the edition's build record and, with a
  // real extractor, its obligations. Both are fetched on mount, so without a
  // reason to fetch them again the page went on rendering what it read when it
  // opened: at the moment a build finished it said "Finished. 41 chunks" in the
  // panel above and "This edition has never been built" in the one below, over
  // an obligations list it could not see. Found in the sprint-12 walkthrough.
  //
  // Bumping a counter rather than copying the run's counts into the record by
  // hand — the record is the server's to write (STORY-082), and a page that
  // guesses at it is how the two came to disagree in the first place.
  const [buildsSettled, setBuildsSettled] = useState(0)

  // Which run, in which resting state, has already been fetched for. A ref
  // because it only suppresses a duplicate fetch; as state it would re-run the
  // effects it guards, which is the cascading render the lint rule forbids.
  const settledRun = useRef<string | null>(null)

  // Records a run, and when it has come to rest asks for what it wrote.
  function applyRun(next: RebuildStatus) {
    setRun(next)
    if (next.state !== 'finished' && next.state !== 'failed') return
    const settled = `${next.run_id}:${next.state}`
    if (settledRun.current === settled) return
    settledRun.current = settled
    setBuildsSettled((count) => count + 1)
  }

  useEffect(() => {
    let cancelled = false

    Promise.all([getDocument(slug), listVersions(slug)])
      .then(([found, editions]) => {
        if (cancelled) return
        setDocument(found)
        setVersions(editions)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load document.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [slug, buildsSettled])

  // Resolves this document's reference slugs to names — the same names the table
  // (STORY-017's neighbour, two clicks away) already shows — and, from the same
  // corpus listing, finds the pool the build fieldset below can propose against:
  // every *other* document with an edition, since `IMPLEMENTS` is cross-document
  // only and a same-document candidate can no longer produce a proposal.
  //
  // One `listDocuments()` call, not two: both consumers need the identical
  // unpaginated corpus listing, and issuing it twice on every navigation would
  // duplicate a corpus-wide request for an answer the caller already has. What
  // stays separate is the failure handling below the shared call — the name
  // lookup is deliberately fail-soft (the slug is itself a working link), while a
  // failed listing leaves the fieldset with nothing to offer and has to say so;
  // one `try` around both would either blank a working references list or hide a
  // broken control, depending on which failure it happened to catch.
  useEffect(() => {
    let cancelled = false

    void (async () => {
      let all: DocumentOut[]
      try {
        all = await listDocuments()
      } catch (cause: unknown) {
        // Fail soft for namesBySlug: leave it as it was and let the slug
        // fallback carry the references list. The pool cannot stay silent about
        // the same failure — it is the only thing that can say why the
        // fieldset offers nothing.
        if (!cancelled) {
          setPoolError({
            slug,
            message:
              cause instanceof Error ? cause.message : 'The request failed.',
          })
        }
        return
      }
      if (cancelled) return

      // A retry for this same document can succeed after an earlier one
      // failed — most directly, navigating away and back. Nothing else
      // clears a `poolError` this old; left standing, it would go on
      // describing a listing that has already recovered. Cleared here,
      // before the checks below decide whether this run has a failure of
      // its own to report.
      setPoolError(null)

      // Nothing past this point can throw on `all` itself — it is not wrapped
      // in the try above, because a bug in this logic is a defect in this
      // component, not a failed request, and must not be swallowed as one.
      const names = new Map<string, string>()
      for (const found of all) names.set(found.slug, found.name)
      setNamesBySlug(names)

      // Only documents with an edition. A manifest records 438 documents that
      // have no text at all, and a candidate with no obligations proposes
      // nothing while costing a request to discover it.
      const others = all.filter(
        (found) => found.slug !== slug && found.version_count > 0,
      )
      if (others.length === 0) {
        setPool({ slug, entries: [] })
        return
      }

      // `allSettled`, not `all`: one other document's edition listing failing
      // must not cost the reader every candidate from the documents that did
      // answer.
      const settled = await Promise.allSettled(
        others.map((found) => listVersions(found.slug)),
      )
      if (cancelled) return

      const entries: PoolEntry[] = []
      let failed = 0
      others.forEach((found, index) => {
        const result = settled[index]
        if (result.status === 'fulfilled') {
          if (result.value.length > 0) {
            entries.push({ slug: found.slug, name: found.name, versions: result.value })
          }
        } else {
          failed += 1
        }
      })
      setPool({ slug, entries })
      if (failed > 0) {
        setPoolError({
          slug,
          message:
            failed === others.length
              ? "Could not load any other document's editions."
              : `${failed} of ${others.length} other documents' editions could not be loaded; showing the rest.`,
        })
      }
    })()

    return () => {
      cancelled = true
    }
  }, [slug])

  // Separate from the document fetch because it re-runs when the edition changes.
  // `edition` starts undefined, which the API reads as "newest" — the right default,
  // and one the client should not try to compute for itself.
  useEffect(() => {
    let cancelled = false

    listChunks(slug, edition)
      .then((result) => {
        if (!cancelled) setChunks(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load text.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [slug, edition])

  // STORY-081. Unlike `/chunks`, the obligations route takes an explicit edition:
  // it answers 404 for one that does not exist, and resolving "newest" on the
  // server would make that 404 ambiguous. `versions` is ordered oldest-first by
  // `LIST_VERSIONS`, so the last entry is the newest — the same edition the chunks
  // route would have picked.
  const obligationTarget = edition ?? versions[versions.length - 1]?.version_id

  useEffect(() => {
    if (!obligationTarget) return

    let cancelled = false
    listObligations(slug, obligationTarget)
      .then((result) => {
        if (!cancelled) setObligations({ target: obligationTarget, data: result })
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setObligationsError({
            target: obligationTarget,
            message:
              cause instanceof Error ? cause.message : 'Failed to load obligations.',
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [slug, obligationTarget, buildsSettled])

  // STORY-082. The run id used to live only in this component's state, so
  // reloading the tab stranded a rebuild that was still going — a nuisance when a
  // job timed out after thirty minutes, a real loss once it could run for eight
  // hours. The edition now carries the id of its current or last run, so the page
  // can find one it did not start.
  //
  // A ref, not state: this only guards against re-fetching, and setting state in
  // an effect body triggers cascading renders — the lint rule rejects it and it
  // produced an intermittent failure earlier in this sprint.
  const attachedRun = useRef<string | null>(null)
  const selectedVersion = versions.find(
    (version) => version.version_id === obligationTarget,
  )
  const recordedRunId = selectedVersion?.build_run_id ?? null
  const recordedState = selectedVersion?.build_state ?? null

  // Only ever read a pool answer that belongs to the document currently being
  // read — the same guard `shownObligations` applies below, and for the same
  // reason: a stale `pool` here was computed excluding the OLD slug, so read
  // against the new one it would offer this document's own editions.
  const poolForThisSlug = pool && pool.slug === slug ? pool.entries : null
  const poolErrorForThisSlug =
    poolError && poolError.slug === slug ? poolError.message : null

  useEffect(() => {
    if (recordedState !== 'started' || !recordedRunId) return
    if (attachedRun.current === recordedRunId || run?.run_id === recordedRunId) {
      return
    }

    let cancelled = false
    attachedRun.current = recordedRunId

    getRebuild(recordedRunId)
      .then((found) => {
        // A run the page did not start can already have come to rest — the tab
        // was reloaded, or closed for the eight hours the job is allowed. It
        // goes through `applyRun` for the same reason a run this page started
        // does: the record it wrote is newer than the one `versions` holds.
        if (!cancelled) applyRun(found)
      })
      .catch(() => {
        // RQ no longer knows this job, and the record still says "started". A
        // worker died without reporting, and without reconciling the two the
        // edition reads as permanently building. `rebuild_result_ttl_seconds`
        // also expires a legitimate result after a day, so an old record reaches
        // here too — both mean the same thing to a reader: it did not finish.
        if (!cancelled) setRunLost(true)
      })

    return () => {
      cancelled = true
    }
  }, [recordedRunId, recordedState, run])

  // Polls until the run leaves a running state. Deliberately not a fixed number of
  // attempts: with a real model a rebuild is one call per chunk over dozens of
  // chunks and can take hours (ADR-023), so a poll budget would give up on
  // exactly the runs worth watching.
  //
  // STORY-089: the interval backs off instead. `pollCount` is a ref rather than
  // state because it only chooses the next delay — as state it would re-run this
  // effect on every tick, which is the cascading render the lint rule forbids.
  const pollCount = useRef(0)
  useEffect(() => {
    if (!run || (run.state !== 'started' && run.state !== 'queued')) {
      pollCount.current = 0
      return
    }

    let cancelled = false
    const timer = setTimeout(() => {
      pollCount.current += 1
      getRebuild(run.run_id)
        .then((next) => {
          if (!cancelled) applyRun(next)
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setRunError(cause instanceof Error ? cause.message : 'Lost track of the run.')
          }
        })
    }, pollDelayMs(pollCount.current))

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [run])

  async function onRebuild() {
    // The edition being read. `edition` is undefined when the picker says "newest",
    // so fall back to the newest version rather than sending nothing — the route
    // takes a version_id in its path and has no "newest" form.
    const target = edition ?? versions[versions.length - 1]?.version_id
    if (!target) return

    setBuilding(true)
    setRunError(null)
    setRun(null)
    // The previous run's verdict, cleared before the new one has a verdict of its
    // own. Left standing it outlived the run it described: an edition whose
    // stranded run was reported as "did not finish" went on saying so over a
    // rebuild that had since succeeded.
    setRunLost(false)
    // Scoped to the pool actually offered for this document, not to whatever
    // `candidates` still holds. A tick made on another document's page survives
    // navigation here — this component is not remounted when the route's slug
    // changes — and an id ticked there can name this document's own edition:
    // the fieldset already never shows it as checkable here, but nothing before
    // this line stopped it from being submitted anyway.
    const offered = new Set(
      (poolForThisSlug ?? []).flatMap((entry) => entry.versions.map((v) => v.version_id)),
    )
    const scopedCandidates = candidates.filter((id) => offered.has(id))
    try {
      const started = await startRebuild(slug, target, scopedCandidates)
      applyRun(await getRebuild(started.run_id))
    } catch (cause: unknown) {
      setRunError(cause instanceof Error ? cause.message : 'Could not start the rebuild.')
    } finally {
      setBuilding(false)
    }
  }

  if (error) return <div role="alert">Could not load this document: {error}</div>
  if (!document) return <p>Loading document…</p>

  // Only ever show a result that belongs to the edition currently selected.
  const shownObligations =
    obligations && obligations.target === obligationTarget ? obligations.data : null
  const shownObligationsError =
    obligationsError && obligationsError.target === obligationTarget
      ? obligationsError.message
      : null

  // STORY-082. `null` writes chunks and no obligations by design (ADR-028), so an
  // empty result under it is a setting to change, not a document to debug.
  const builtWithoutAModel =
    selectedVersion?.build_state === 'finished' &&
    selectedVersion?.build_extractor_adapter === 'null'
  // No record at all has two meanings, and obligations are what separate them.
  // The build record began on 2026-08-26; an edition built before that holds its
  // obligations and carries no record of where they came from. Calling that
  // "never built" over a list of them is a contradiction a user meets on the
  // first edition they open — `dodd-5000-01@2020-09-09` was in exactly this state
  // with 113 obligations when this shipped.
  const hasNoBuildRecord =
    selectedVersion != null && selectedVersion.build_state == null
  const builtBeforeRecording =
    hasNoBuildRecord && (shownObligations?.total ?? 0) > 0
  const neverBuilt = hasNoBuildRecord && !builtBeforeRecording

  // Only ever show a result that belongs to the edition currently selected.
  return (
    <div className="view">
      <h1>
        {document.name}
        {document.is_external && <span> (external)</span>}
      </h1>
      <p>
        <code>{document.slug}</code>
      </p>

      <h2 id="references-heading">References</h2>
      {document.references.length === 0 ? (
        <p>This document cites nothing in the corpus.</p>
      ) : (
        <ul className="reference-list" aria-labelledby="references-heading">
          {document.references.map((target) => (
            <li key={target}>
              <Link to={`/documents/${target}`}>{namesBySlug.get(target) ?? target}</Link>
            </li>
          ))}
        </ul>
      )}

      {/* "Editions", not "Text": what follows is the edition picker and the
          builder that derives obligations from an edition. The page carried two
          `<h2>Text</h2>` headings until the sprint-12 walkthrough — this one over
          controls, the other over the document body — so navigating by heading
          gave a reader "Text… Obligations… Text" and no way to tell them apart. */}
      <h2>Editions</h2>

      {versions.length > 0 && (
        <p>
          <label htmlFor="edition">Edition</label>{' '}
          <select
            id="edition"
            value={edition ?? ''}
            onChange={(event) => setEdition(event.target.value || undefined)}
          >
            <option value="">Newest</option>
            {versions.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {version.effective_date} ({version.version_id})
              </option>
            ))}
          </select>
        </p>
      )}

      {versions.length > 0 && (
        <section>
          <h3>Derived layer</h3>
          <p>
            Chunks the text, extracts obligations, and — for each edition named below
            — proposes links between them. With a real extractor this is one model
            call per chunk, at roughly a minute and a half each: about an hour for a
            38-chunk edition and most of a working day for the largest. You can close
            this tab — the run is recorded against the edition and this page finds it
            again.
          </p>

          {/* Three states a blank fieldset used to hide as the same thing:
              still looking, nothing else in the corpus to offer, and a listing
              that failed outright. Sprint 3's walkthrough found a control
              rendered empty and unexplained on Triage; this is that shape
              again, one screen over. */}
          {poolErrorForThisSlug && (
            <p role="alert">
              Could not fully list other documents to propose links against:{' '}
              {poolErrorForThisSlug}
            </p>
          )}

          {poolForThisSlug === null ? (
            !poolErrorForThisSlug && (
              // A live region, like `EmptyState` and Pairings' equivalent
              // block both are: without it, a screen-reader user gets no
              // announcement when this settles from "Looking…" into either
              // the fieldset or the paragraph below.
              <p role="status">Looking for other documents to propose links against…</p>
            )
          ) : poolForThisSlug.length === 0 ? (
            !poolErrorForThisSlug && (
              <p role="status">
                <strong>
                  There is nothing else in the corpus to propose links against.
                </strong>{' '}
                A proposal runs between two documents' clauses, and this is the
                only document with an edition. Ingest and build a second one to
                unlock this.
              </p>
            )
          ) : (
            <fieldset>
              <legend>Propose links against</legend>
              {/* Other documents' editions, never this document's own. A
                  proposal whose two obligations share a `:Document` is skipped —
                  `IMPLEMENTS` means our lower-tier clause discharges a
                  higher-tier duty, and an edition does not discharge its
                  predecessor; that relationship is the diff's, and it is settled
                  on the Pairings screen. Offering this document's editions here
                  would offer candidates that cannot produce a single proposal.
                  The rebuild API was never this narrow: it validates candidates
                  by version id alone, so other documents' editions could always
                  be named by a direct call and never by this control. */}
              {poolForThisSlug.map((entry) => (
                <div key={entry.slug}>
                  <h4>{entry.name}</h4>
                  {entry.versions.map((v) => (
                    <label key={v.version_id} className="stacked">
                      <input
                        type="checkbox"
                        checked={candidates.includes(v.version_id)}
                        onChange={(event) =>
                          setCandidates((current) =>
                            event.target.checked
                              ? [...current, v.version_id]
                              : current.filter((c) => c !== v.version_id),
                          )
                        }
                      />{' '}
                      {v.version_id}
                    </label>
                  ))}
                </div>
              ))}
              {/* Naming candidates is the only way proposals are generated:
                  nothing in the graph records which documents are higher-tier, so
                  the caller states it and the route does not guess. Choosing none
                  is a valid request that rebuilds without proposing. */}
              <p>Choosing none rebuilds the edition without proposing any links.</p>
            </fieldset>
          )}

          <button type="button" onClick={onRebuild} disabled={building}>
            Build derived layer
          </button>

          {runError && <div role="alert">Rebuild failed: {runError}</div>}

          {run && run.state === 'failed' && (
            <div role="alert">
              The run failed after {run.chunks_done} of {run.chunks_total} chunks:{' '}
              {run.error}
            </div>
          )}

          {run && (run.state === 'started' || run.state === 'queued') && (
            <p role="status">
              {run.chunks_total === 0
                ? // A run reports no total until a worker picks it up. "0 of 0"
                  // reads as a rebuild that found nothing to do, which is a
                  // different and much worse thing than one that has not started.
                  'Queued — waiting for a worker to pick this run up.'
                : `Building: ${run.chunks_done} of ${run.chunks_total} chunks.`}
            </p>
          )}

          {run && run.state === 'finished' && (
            <div role="status">
              <p>
                Finished. {run.counts.chunks_written ?? 0} chunks,{' '}
                {run.counts.obligations_written ?? 0} obligations,{' '}
                {run.counts.proposed ?? 0} link proposals.
              </p>
              {/* A run that extracted nothing because it was configured to extract
                  nothing looks exactly like one that failed to extract. The
                  count alone reads as a broken pipeline, and the reader has no
                  way to see the worker's configuration from here. */}
              {run.extractor_adapter === 'null' && (
                <p>
                  No obligations were extracted because this worker runs the{' '}
                  <code>null</code> extractor, which produces none. Chunks and
                  text are still written; Review and Triage stay empty until a
                  real extraction model is configured
                  (<code>EXTRACTOR_ADAPTER=local</code>).
                </p>
              )}

              {/* Not optional. A rejected chunk is silent incompleteness unless the
                  number is on screen — the reason ADR-023 reports it at all. */}
              <p>
                {run.counts.chunks_rejected ?? 0} chunk
                {(run.counts.chunks_rejected ?? 0) === 1 ? '' : 's'} rejected by the
                schema and skipped.
                {(run.counts.items_dropped ?? 0) > 0 && (
                  <>
                    {' '}
                    A further {run.counts.items_dropped} statement
                    {run.counts.items_dropped === 1 ? '' : 's'} dropped from chunks
                    that were otherwise kept.
                  </>
                )}
              </p>

              {/* The counts say the edition is incomplete; these say what is
                  missing from it. Reading container logs is not an answer for an
                  operator, which is what STORY-057's criteria asked for. Since
                  ADR-030 the list covers both losses — a chunk rejected whole and
                  a statement dropped from a chunk that survived — because both are
                  a sentence the model returned and the schema refused. */}
              {run.rejections.length > 0 && (
                <ul>
                  {run.rejections.map((rejection) => (
                    <li key={rejection.chunk_id}>
                      <code>{rejection.chunk_id}</code>: {rejection.reason}
                    </li>
                  ))}
                </ul>
              )}

              {/* The list is capped at 20 by the worker and the count is not, so
                  a list of 20 over 213 refusals looks like a complete account of
                  a modest problem. ADR-030's silent drop, one level up. */}
              {run.rejections_total > run.rejections.length && (
                <p>
                  Showing {run.rejections.length} of {run.rejections_total}{' '}
                  refusals; the list is capped and the count is not.
                </p>
              )}

              {/* ADR-027. A rebuild re-keys obligations when the chunker changes,
                  and carries the verdicts recorded against them across. What it
                  could not carry is the one number a healthy-looking rebuild
                  would otherwise hide. */}
              {(run.counts.decisions_repointed ?? 0) > 0 && (
                <p>
                  {run.counts.decisions_repointed} review decision
                  {run.counts.decisions_repointed === 1 ? ' was' : 's were'} carried across
                  a change of obligation identity.
                </p>
              )}

              {(run.counts.unpromotable ?? 0) > 0 && (
                <p>
                  {run.counts.unpromotable} recorded approval
                  {run.counts.unpromotable === 1 ? '' : 's'} could not be replayed — the
                  obligations they refer to no longer exist under those ids, and the
                  statements no longer match. They are still recorded, and need
                  re-reviewing.
                </p>
              )}

              {/* STORY-076. Reported separately from the approvals above because
                  the two losses are different events, and this one is worse: a
                  stranded approval leaves a link missing and the proposal comes
                  back to the queue, where it is met again. A stranded rejection
                  leaves a refusal nobody is applying — the proposal returns and
                  nothing says it was already refused. */}
              {(run.counts.rejections_stranded ?? 0) > 0 && (
                <p>
                  {run.counts.rejections_stranded} recorded rejection
                  {run.counts.rejections_stranded === 1 ? '' : 's'} could not be
                  replayed. The proposals they refused can return to the review
                  queue, and nothing there will say they were refused before — so
                  these need deciding again.
                </p>
              )}

              {/* The pairing vocabulary's half of the same repoint. One number
                  covers both pairing verdicts where the link side has two,
                  because `paired` and `distinct` lose identically: the clause
                  the verdict named is gone, so the pair returns to the pairing
                  queue unanswered rather than leaving a link missing or a
                  suppression unapplied (ADR-027). */}
              {(run.counts.pairing_decisions_repointed ?? 0) > 0 && (
                <p>
                  {run.counts.pairing_decisions_repointed} pairing decision
                  {run.counts.pairing_decisions_repointed === 1 ? ' was' : 's were'}{' '}
                  carried across a change of obligation identity.
                </p>
              )}

              {(run.counts.pairing_decisions_stranded ?? 0) > 0 && (
                <p>
                  {run.counts.pairing_decisions_stranded} recorded pairing verdict
                  {run.counts.pairing_decisions_stranded === 1 ? '' : 's'} could not
                  be carried across — the clauses they named no longer exist under
                  those ids, and the statements no longer match. Those pairs come
                  back to the pairing queue unanswered, and nothing there will say
                  they were settled before.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <h2>Obligations</h2>

      {selectedVersion && (
        <p>
          {builtBeforeRecording ? (
            <>
              <strong>Built before builds were recorded.</strong> This edition
              holds obligations, but nothing recorded which extractor produced
              them or when. Build it again to record that; extraction is cached,
              so a rebuild over unchanged text calls no model.
            </>
          ) : neverBuilt ? (
            <>
              <strong>This edition has never been built.</strong> Its text is
              ingested; nothing has been extracted from it yet.
            </>
          ) : runLost ? (
            <>
              <strong>The last build did not finish.</strong> It was recorded as
              running and the queue no longer knows it, which means the worker
              stopped without reporting — or the result has aged out. Build it
              again; extraction is cached, so chunks already paid for are not
              repeated.
            </>
          ) : selectedVersion.build_state === 'failed' ? (
            <>
              <strong>The last build failed.</strong>{' '}
              {selectedVersion.build_error}
            </>
          ) : selectedVersion.build_state === 'started' ? (
            <>Building — this edition has a run in progress.</>
          ) : (
            <>
              Built {selectedVersion.build_changed_at?.slice(0, 10)} with extractor{' '}
              <code>{selectedVersion.build_extractor_adapter}</code>.
              {builtWithoutAModel && (
                <>
                  {' '}
                  <strong>No extraction model was configured</strong>, so it wrote
                  text and no obligations — that is what <code>null</code> does, not
                  a failure. Set an extractor and build again.
                </>
              )}
            </>
          )}
        </p>
      )}

      {shownObligationsError && (
        <div role="alert">Could not load obligations: {shownObligationsError}</div>
      )}

      {shownObligations === null ? (
        !shownObligationsError && <p>Loading obligations…</p>
      ) : shownObligations.total === 0 ? (
        // STORY-081 AC6, completed once STORY-082 landed the build record. The
        // paragraph above now names the actual cause — never built, built with
        // `null`, failed — so this no longer has to hedge between them. It says
        // only what is true of every case: extraction recorded nothing here.
        <p>
          <strong>No obligations recorded for this edition.</strong>{' '}
          {neverBuilt
            ? 'Build the derived layer to extract them.'
            : 'See what the last build did, above.'}
        </p>
      ) : (
        <>
          <p>
            {shownObligations.total} obligation
            {shownObligations.total === 1 ? '' : 's'}.
            {shownObligations.truncated && (
              <> Showing the first {shownObligations.returned}.</>
            )}
          </p>
          <ol>
            {shownObligations.obligations.map((obligation) => (
              <li key={obligation.obligation_id}>
                <p>{obligation.statement}</p>
                <p>
                  <small>
                    {obligation.modality} · {obligation.section_path.join(' / ')} ·
                    p. {obligation.page}
                  </small>
                </p>
              </li>
            ))}
          </ol>
        </>
      )}

      <h2>Text</h2>

      {chunks === null ? (
        <p>Loading text…</p>
      ) : chunks.length === 0 ? (
        // The state the sample CSV produces for all 438 of its documents: a
        // manifest records no text (ADR-011). Sprint 3's walkthrough found a defect
        // of exactly this shape in Triage — a control rendered empty and
        // unexplained — so this says which of the two it is.
        <p>
          This document has <strong>no ingested text</strong>. It was recorded from a
          manifest, which lists documents and references but carries no document
          body. Ingest the source PDF to read it here.
        </p>
      ) : (
        <article>
          {chunks.map((chunk) => (
            <section key={chunk.chunk_id}>
              <h3>
                {chunk.section_path.join(' / ') || '(preamble)'} — page {chunk.page}
              </h3>
              <p className="chunk-text">{chunk.text}</p>
            </section>
          ))}
        </article>
      )}
    </div>
  )
}
