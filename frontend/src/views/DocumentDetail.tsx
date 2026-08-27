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

  // Building the derived layer (STORY-061). The routes shipped in sprint 4 and the
  // client modelled neither, so this — sprint 4's whole deliverable — could only be
  // reached with curl.
  const [candidates, setCandidates] = useState<string[]>([])
  const [run, setRun] = useState<RebuildStatus | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [building, setBuilding] = useState(false)

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
  }, [slug])

  // Resolves this document's reference slugs to names — the same names the table
  // (STORY-017's neighbour, two clicks away) already shows. Kept out of the
  // document-fetch effect and made deliberately fail-soft: the slug is itself a
  // working link, so a failed lookup here must leave the references list
  // rendering rather than blank it.
  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const all = await listDocuments()
        if (cancelled) return
        const names = new Map<string, string>()
        for (const found of all) names.set(found.slug, found.name)
        setNamesBySlug(names)
      } catch {
        // Fail soft: leave namesBySlug empty and let the slug fallback carry it.
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

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
  }, [slug, obligationTarget])

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

  useEffect(() => {
    if (recordedState !== 'started' || !recordedRunId) return
    if (attachedRun.current === recordedRunId || run?.run_id === recordedRunId) {
      return
    }

    let cancelled = false
    attachedRun.current = recordedRunId

    getRebuild(recordedRunId)
      .then((found) => {
        if (!cancelled) setRun(found)
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
          if (!cancelled) setRun(next)
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
    try {
      const started = await startRebuild(slug, target, candidates)
      setRun(await getRebuild(started.run_id))
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
    <div style={{ padding: '1rem' }}>
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
        <ul aria-labelledby="references-heading">
          {document.references.map((target) => (
            <li key={target}>
              <Link to={`/documents/${target}`}>{namesBySlug.get(target) ?? target}</Link>
            </li>
          ))}
        </ul>
      )}

      <h2>Text</h2>

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

          {versions.length > 1 && (
            <fieldset>
              <legend>Propose links against</legend>
              {versions
                .filter((v) => v.version_id !== (edition ?? versions[versions.length - 1]?.version_id))
                .map((v) => (
                  <label key={v.version_id} style={{ display: 'block' }}>
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
              {/* Naming candidates is the only way proposals are generated: nothing
                  in the graph records which documents are higher-tier, so the caller
                  states it and the route does not guess. Choosing none is a valid
                  request that rebuilds without proposing. */}
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
              <p style={{ whiteSpace: 'pre-wrap' }}>{chunk.text}</p>
            </section>
          ))}
        </article>
      )}
    </div>
  )
}
