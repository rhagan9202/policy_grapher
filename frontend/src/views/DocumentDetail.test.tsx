import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { RebuildStatus } from '../api/types'

const getDocument = vi.fn()
const listVersions = vi.fn()
const listChunks = vi.fn()
const startRebuild = vi.fn()
// Typed, unlike its neighbours, because this payload is the one the panel reads
// field by field. An untyped mock accepts a fixture missing `rejections_total`
// — 21 of the 24 here did — and a screen reading a field no fixture supplies is
// tested against a response the backend never sends.
const getRebuild = vi.fn<(runId: string) => Promise<RebuildStatus>>()
const listDocuments = vi.fn()
const listObligations = vi.fn()
vi.mock('../api/client', () => ({
  getDocument: (slug: string) => getDocument(slug),
  listVersions: (slug: string) => listVersions(slug),
  listChunks: (slug: string, versionId?: string) => listChunks(slug, versionId),
  startRebuild: (slug: string, versionId: string, candidates: string[]) =>
    startRebuild(slug, versionId, candidates),
  getRebuild: (runId: string) => getRebuild(runId),
  listDocuments: () => listDocuments(),
  listObligations: (slug: string, versionId: string) =>
    listObligations(slug, versionId),
  ApiError: class extends Error {},
}))

import DocumentDetail from './DocumentDetail'
import { pollDelayMs, FIRST_POLL_MS, MAX_POLL_MS } from './pollDelay'

const document = {
  slug: 'dodd-5000-01',
  name: 'DoDD 5000.01',
  is_external: false,
  references: ['public-law-116-92'],
  referenced_by: [],
  version_count: 2,
}

const versions = [
  {
    version_id: 'dodd-5000-01@2018-08-31',
    effective_date: '2018-08-31',
    checksum: '65e873',
    source_uri: 'file:///data/samples/500001p_2003.pdf',
    supersedes: null,
  },
  {
    version_id: 'dodd-5000-01@2020-09-09',
    effective_date: '2020-09-09',
    checksum: 'a16e39',
    source_uri: 'file:///data/samples/500001p_2020.pdf',
    supersedes: 'dodd-5000-01@2018-08-31',
  },
]

// A second document with an edition of its own. The build fieldset's pool after
// the pairing split: `IMPLEMENTS` is cross-document only, so this document's own
// editions can no longer produce a single proposal and are not offered.
const otherDocument = {
  slug: 'dodi-5000-88',
  name: 'DoDI 5000.88',
  is_external: false,
  references: [],
  referenced_by: [],
  version_count: 1,
}

const otherVersions = [
  {
    version_id: 'dodi-5000-88@2020-09-09',
    effective_date: '2020-09-09',
    checksum: 'b4c1f0',
    source_uri: 'file:///data/samples/500088p.pdf',
    supersedes: null,
  },
]

/** A two-document corpus, answered per slug. The fieldset makes two kinds of
 *  call — the document list to find the others, then one `listVersions` for each
 *  of them — so a single `mockResolvedValue` would hand this document's editions
 *  back for every slug and hide exactly the bug this fixture exists to catch. */
function corpusOfTwo() {
  listDocuments.mockResolvedValue([document, otherDocument])
  listVersions.mockImplementation((slug: string) =>
    Promise.resolve(slug === 'dodd-5000-01' ? versions : otherVersions),
  )
}

// A third document, distinct from `otherDocument`, for the one thing a
// two-document corpus cannot pin: that each other document is zipped with its
// *own* editions. With only one other document, index 0 is the only index
// there is, so `editions[index]` and `editions[0]` answer identically and an
// off-by-one in that zip has nothing to disagree with.
const thirdDocument = {
  slug: 'dodi-1322-18',
  name: 'DoDI 1322.18',
  is_external: false,
  references: [],
  referenced_by: [],
  version_count: 1,
}

const thirdVersions = [
  {
    version_id: 'dodi-1322-18@2019-01-01',
    effective_date: '2019-01-01',
    checksum: 'c9d2e1',
    source_uri: 'file:///data/samples/132218p.pdf',
    supersedes: null,
  },
]

function corpusOfThree() {
  listDocuments.mockResolvedValue([document, otherDocument, thirdDocument])
  listVersions.mockImplementation((slug: string) => {
    if (slug === 'dodd-5000-01') return Promise.resolve(versions)
    if (slug === 'dodi-5000-88') return Promise.resolve(otherVersions)
    return Promise.resolve(thirdVersions)
  })
}

const chunks = [
  {
    chunk_id: 'c1',
    text: 'The Director shall notify the Comptroller within 24 hours.',
    page: 5,
    section_path: ['ENCLOSURE 1', '1.1'],
    ordinal: 0,
  },
  {
    chunk_id: 'c2',
    text: 'Test and evaluation will be integrated with modeling and simulation.',
    page: 6,
    section_path: ['ENCLOSURE 1', '1.2'],
    ordinal: 1,
  },
]

function renderAt(slug = 'dodd-5000-01') {
  return render(
    <MemoryRouter initialEntries={[`/documents/${slug}`]}>
      <Routes>
        <Route path="/documents/:slug" element={<DocumentDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

function loaded() {
  getDocument.mockResolvedValue(document)
  listVersions.mockResolvedValue(versions)
  listChunks.mockResolvedValue(chunks)
}

// Every test renders the whole screen, so the obligations fetch fires in all of
// them. A benign default keeps tests that are about something else from having to
// know this route exists; the ones that are about it override.
//
// These two are cleared rather than reset below, and the difference matters.
// `mockReset` removes the implementation as well as the calls, which leaves a
// window between one test's teardown and the next test's setup where a React
// passive effect that has not flushed yet calls a bare `vi.fn()`, gets
// `undefined`, and throws "Cannot read properties of undefined (reading 'then')"
// inside whichever test happens to be running. That was an intermittent failure
// at roughly one run in eight, and an intermittent failure is worse than a red
// one — it teaches people to re-run rather than to look.
beforeEach(() => {
  // A realistic default, not `undefined`: the build fieldset's pool effect
  // calls this on every render this file exercises, and a bare `vi.fn()`
  // answering `undefined` made every test but the two written for the pool
  // throw `TypeError: all is not iterable` off-screen, caught only because an
  // earlier version of the effect wrapped the whole computation — including
  // this bug's own symptom — in one `catch {}`. A corpus of the one document
  // under test is the default a test not about the pool should see.
  listDocuments.mockResolvedValue([document])
  listObligations.mockResolvedValue({
    obligations: [],
    total: 0,
    returned: 0,
    truncated: false,
  })
  getRebuild.mockResolvedValue({
    run_id: 'idle',
    version_id: 'idle',
    state: 'finished',
    chunks_done: 0,
    chunks_total: 0,
    counts: {},
    rejections: [],
    rejections_total: 0,
    extractor_adapter: '',
    embedder_adapter: '',
    error: null,
  })
})

afterEach(() => {
  getDocument.mockReset()
  listVersions.mockReset()
  listChunks.mockReset()
  startRebuild.mockReset()
  getRebuild.mockClear()
  listDocuments.mockReset()
  listObligations.mockClear()
})

// STORY-017, the "corpus management" MVP item. `GET /documents/{slug}/chunks` has
// served ordered text with page and section_path since ADR-012, and `client.ts` had
// no function for the route at all — so nothing in the UI could read a document's
// text.

describe('DocumentDetail', () => {
  it('shows the document it was asked for', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    expect(await screen.findByRole('heading', { name: /DoDD 5000\.01/ })).toBeInTheDocument()
    expect(getDocument).toHaveBeenCalledWith('dodd-5000-01')
  })

  it('renders the extracted text in order, with its page and section', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    const text = await screen.findByRole('article')
    expect(text).toHaveTextContent(/The Director shall notify/)
    expect(text).toHaveTextContent(/ENCLOSURE 1/)
    expect(text).toHaveTextContent(/5/)
  })

  it('reads the newest edition by default and lets another be chosen', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()
    await screen.findByRole('article')

    // Omitted version_id means "newest" at the API, which is the right default.
    expect(listChunks).toHaveBeenCalledWith('dodd-5000-01', undefined)

    await userEvent.selectOptions(
      screen.getByLabelText(/edition/i),
      'dodd-5000-01@2018-08-31',
    )
    expect(listChunks).toHaveBeenLastCalledWith('dodd-5000-01', 'dodd-5000-01@2018-08-31')
  })

  it('says a document has no text rather than rendering an empty page', async () => {
    // The state the sample CSV produces for all 438 of its documents: a manifest
    // records no text (ADR-011). Sprint 3 shipped a defect of exactly this shape.
    getDocument.mockResolvedValue({ ...document, version_count: 0 })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    renderAt()

    expect(await screen.findByText(/no ingested text/i)).toBeInTheDocument()
  })

  it('shows what the document cites', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    const references = await screen.findByRole('list', { name: /references/i })
    expect(within(references).getByText(/public-law-116-92/)).toBeInTheDocument()
  })

  it('names and links the documents this one cites', async () => {
    // The detail page listed raw slugs, unlinked, while the table two clicks
    // away resolved the same slugs to names and linked every row.
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    listDocuments.mockResolvedValue([
      { slug: 'dodd-1322-18', name: 'DoDD 1322.18', is_external: false, references: [], referenced_by: [], version_count: 0 },
    ])
    renderAt()

    const link = await screen.findByRole('link', { name: 'DoDD 1322.18' })
    expect(link).toHaveAttribute('href', '/documents/dodd-1322-18')
  })

  it('falls back to the slug when the name is not known yet, surviving a genuine lookup failure', async () => {
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])

    // A promise this test controls, so the final assertion cannot pass on the
    // pre-settle default state alone (the empty `namesBySlug` a component with
    // no lookup at all, or one whose `.catch` was deleted, would also show).
    let rejectLookup!: (error: Error) => void
    const lookup = new Promise<never>((_, reject) => {
      rejectLookup = reject
    })
    listDocuments.mockReturnValue(lookup)
    renderAt()

    await screen.findByRole('link', { name: 'dodd-1322-18' })
    // The lookup must actually have been attempted: a deleted effect renders the
    // same slug fallback without ever calling listDocuments.
    expect(listDocuments).toHaveBeenCalled()

    // The pool effect shares this same call, and now has its own reaction to
    // the rejection (`setPoolError`) that the old, silent `namesBySlug` catch
    // never had — wrapped here so that update is not the one React warns
    // about happening outside `act`.
    await act(async () => {
      rejectLookup(new Error('offline'))
      await lookup.catch(() => {})
    })

    // A failed name lookup must not blank the references list — the slug is
    // still a working link — and the rejection must not surface as an error
    // banner, which is what an unhandled `.catch` would do.
    expect(await screen.findByRole('link', { name: 'dodd-1322-18' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('reports a document that is not there instead of rendering blanks', async () => {
    getDocument.mockRejectedValue(new Error('No document with slug "nope"'))
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    renderAt('nope')

    expect(await screen.findByRole('alert')).toHaveTextContent(/No document with slug/)
  })
})

// --- STORY-061: the derived layer can be built from the UI ---------------------
//
// `POST .../rebuild` and `GET /rebuilds/{run_id}` shipped in sprint 4 and
// `api/client.ts` modelled neither, so sprint 4's whole deliverable could only be
// reached with curl. The same class of gap `listChunks` was, one sprint newer.
//
// The build fieldset's own pool paragraph ("Looking for other documents…" /
// "nothing else in the corpus…") is `role="status"` too, and — under
// `loaded()`'s default single-document corpus — settles to the second of
// those before any of the tests below click Build, then stays on screen for
// the rest of the test. A bare `findByRole('status')` here would find that
// one, or throw for finding two; every status assertion below picks the last
// one instead, which is always the run's own.

describe('DocumentDetail — building the derived layer', () => {
  it('queues a rebuild for the edition being read', async () => {
    loaded()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09', candidate_version_ids: [],
    })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09', state: 'started',
      chunks_done: 0, chunks_total: 34, counts: {}, rejections: [],
      rejections_total: 0, extractor_adapter: '', embedder_adapter: '', error: null,
    })
    renderAt()
    await screen.findByRole('article')

    await userEvent.selectOptions(screen.getByLabelText(/edition/i), 'dodd-5000-01@2020-09-09')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [])
  })

  it('offers other documents’ editions, and never this document’s own', async () => {
    // Spec §8. `versions` came from `GET /documents/{slug}/versions`, so the only
    // candidates this screen could name were other editions of the document being
    // read — and after `propose_links` skips a pair whose obligations share a
    // `:Document`, not one of them can produce a proposal. The rebuild API was
    // never this narrow: it validates candidates by version id alone, so other
    // documents' editions could always be named by a direct call and never by
    // this control.
    loaded()
    corpusOfTwo()
    renderAt()
    await screen.findByRole('article')

    expect(
      await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ }),
    ).toBeInTheDocument()
    // Grouped by document, because a bare list of version ids from several
    // documents is a list of strings nobody can read. Scoped to the fieldset
    // itself (a `<fieldset>`'s implicit role is `group`) — this document's own
    // name appears on the page too, in the `<h1>`, and a bare `getByText` would
    // still pass if the name were pointed there by mistake, or if the pool the
    // grouping loop reads from silently became this document's own editions.
    expect(
      within(screen.getByRole('group')).getByText('DoDI 5000.88'),
    ).toBeInTheDocument()
    // This document's own editions are gone from the pool entirely — both of
    // them, including the one that is not selected, which is what the old
    // filter left standing.
    expect(
      screen.queryByRole('checkbox', { name: /dodd-5000-01@2018-08-31/ }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: /dodd-5000-01@2020-09-09/ }),
    ).not.toBeInTheDocument()
    // Choosing none stays a valid request, and still says so.
    expect(screen.getByText(/choosing none rebuilds/i)).toBeInTheDocument()
  })

  it('proposes against the editions the reader chose', async () => {
    loaded()
    corpusOfTwo()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09',
      candidate_version_ids: ['dodi-5000-88@2020-09-09'],
    })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 0, chunks_total: 34, counts: {}, rejections: [],
      // `getRebuild` is the typed mock (see its declaration above): a fixture
      // missing any of `RebuildStatus`'s required fields fails `tsc`, not just
      // the test.
      rejections_total: 0, extractor_adapter: '', embedder_adapter: '', error: null,
    })
    renderAt()
    await screen.findByRole('article')

    await userEvent.selectOptions(screen.getByLabelText(/edition/i), 'dodd-5000-01@2020-09-09')
    await userEvent.click(
      await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ }),
    )
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [
      'dodi-5000-88@2020-09-09',
    ])
  })

  it('reports progress while the run is in flight', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 5, chunks_total: 34, counts: {}, rejections: [],
      rejections_total: 0, extractor_adapter: '', embedder_adapter: '', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/5 of 34/)).toBeInTheDocument()
  })

  it('says a run extracted nothing because it was configured to, not because it broke', async () => {
    // The default EXTRACTOR_ADAPTER is null. A rebuild under it finishes
    // cleanly with every chunk written and zero obligations — a correct result
    // that reads exactly like a broken pipeline, and the reader cannot see the
    // worker's configuration from this screen.
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 0, proposed: 0, chunks_rejected: 0 },
      rejections: [], rejections_total: 0,
      extractor_adapter: 'null', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/null.*extractor/i)
    expect(status).toHaveTextContent(/review and triage stay empty/i)
  })

  it('does not blame the null extractor when a real one ran', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265, chunks_rejected: 0 },
      rejections: [], rejections_total: 0,
      extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).not.toHaveTextContent(/null.*extractor/i)
  })

  it('reports what a finished run produced, including what it rejected', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 121, proposed: 313, chunks_rejected: 1 },
      rejections: [{ chunk_id: 'c9', reason: 'modality: Input should be SHALL, MUST, WILL, SHOULD or MAY' }],
      rejections_total: 1, extractor_adapter: 'local', embedder_adapter: 'local',
      error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/121/)
    expect(status).toHaveTextContent(/313/)
    // A rejected chunk is silent incompleteness unless the number is shown (ADR-023).
    expect(status).toHaveTextContent(/1 chunk/i)
  })

  it('surfaces a failed run rather than leaving it spinning', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'failed',
      chunks_done: 5, chunks_total: 38, counts: {}, rejections: [],
      rejections_total: 0, extractor_adapter: 'local', embedder_adapter: 'local',
      error: 'model output did not match the obligation schema',
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/did not match/i)
  })

  it('says a run is queued rather than reporting "0 of 0"', async () => {
    // Found by the sprint 5 walkthrough. A run reports chunks_total 0 until the
    // worker picks it up, and "Building: 0 of 0 chunks" reads as a rebuild that
    // found nothing to do rather than one that has not started.
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 0, chunks_total: 0, counts: {}, rejections: [],
      rejections_total: 0, extractor_adapter: '', embedder_adapter: '', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/queued/i)
    expect(status).not.toHaveTextContent(/0 of 0/)
  })

  it('says why chunks were rejected, not only how many', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 0, chunks_rejected: 2 },
      rejections: [
        { chunk_id: 'c9', reason: 'modality: Input should be SHALL, MUST, WILL, SHOULD or MAY' },
      ],
      rejections_total: 2, extractor_adapter: 'local', embedder_adapter: 'local',
      error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/2 chunks rejected/i)
    expect(status).toHaveTextContent(/Input should be SHALL/)
  })

  it('says how many refusals the capped list left out', async () => {
    // The worker keeps 20 reasons and counts every one. DoDD 5143.01's rebuild
    // showed 20 against 213 refusals and nothing said so, which is the silent
    // drop ADR-030 made a defect; `rejections_total` was added to the status
    // payload for it.
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 0, chunks_rejected: 213 },
      rejections: [
        { chunk_id: 'c9', reason: 'modality: Input should be SHALL, MUST, WILL, SHOULD or MAY' },
        { chunk_id: 'c11', reason: 'statement: Field required' },
      ],
      rejections_total: 213,
      extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/2 of 213/)
  })

  it('says nothing about a cap the run did not reach', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 0, chunks_rejected: 1 },
      rejections: [{ chunk_id: 'c9', reason: 'statement: Field required' }],
      rejections_total: 1,
      extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).not.toHaveTextContent(/of 1 refusal/i)
  })

  it('says when a recorded approval could not be replayed', async () => {
    // replay_decisions has returned this count since it was written and nothing
    // has ever shown it. An approval that stopped being represented in the graph
    // is exactly the case a healthy-looking rebuild must not hide (ADR-027).
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 2, unpromotable: 3 },
      rejections: [], rejections_total: 0,
      extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).toHaveTextContent(/3 recorded approvals could not be replayed/i)
    expect(status).toHaveTextContent(/2 .*carried across/i)
  })

  it('stays quiet about decisions when there were none to carry or lose', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 0, unpromotable: 0 },
      rejections: [], rejections_total: 0,
      extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    // The run's status is the *last* `status` region: the pool's own
    // ("Looking…"/"nothing else…") renders first and is also live now.
    const status = (await screen.findAllByRole('status')).at(-1)
    expect(status).not.toHaveTextContent(/could not be replayed/i)
    expect(status).not.toHaveTextContent(/carried across/i)
  })
})

// Round 2 on the same fieldset. A mutation hunt against the first pass found
// eight of sixteen attempted mutations survived, and an independent read of
// the diff found a defect no mutation hunt was aimed at: this component is not
// remounted when the route's slug changes (no `key` on `<Route>`), so a
// selection made on one document's page can still name a *different*
// document's own edition once the reader follows a reference link to it.
describe('DocumentDetail, the build fieldset pool — closing what review found', () => {
  it('lists each other document under its own editions, not the first other document\'s', async () => {
    // Pins the document/editions zip. `otherDocument` alone cannot: with one
    // other document, index 0 is the only index there is, so `editions[index]`
    // and `editions[0]` cannot disagree.
    loaded()
    corpusOfThree()
    renderAt()
    await screen.findByRole('article')

    const group = await screen.findByRole('group')
    const otherHeading = within(group).getByRole('heading', { name: 'DoDI 5000.88' })
    const otherContainer = otherHeading.parentElement as HTMLElement
    const thirdHeading = within(group).getByRole('heading', { name: 'DoDI 1322.18' })
    const thirdContainer = thirdHeading.parentElement as HTMLElement

    expect(within(otherContainer).getByText(/dodi-5000-88@2020-09-09/)).toBeInTheDocument()
    expect(within(otherContainer).queryByText(/dodi-1322-18@2019-01-01/)).not.toBeInTheDocument()
    expect(within(thirdContainer).getByText(/dodi-1322-18@2019-01-01/)).toBeInTheDocument()
    expect(within(thirdContainer).queryByText(/dodi-5000-88@2020-09-09/)).not.toBeInTheDocument()
  })

  it('reflects a tick and an untick on the checkbox itself, not only on what gets submitted', async () => {
    // Pins two survivors at once: forcing `checked` to a constant, and making
    // the untick branch of the `onChange` handler a no-op. Both are invisible
    // to a test that only reads the submitted `candidates` array, because the
    // DOM checkbox still reports the browser's own toggle on the one click a
    // test like that drives — `onChange` fires from the real event, not from
    // the (possibly wrong) `checked` prop.
    loaded()
    corpusOfTwo()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09', candidate_version_ids: [],
    })
    renderAt()
    await screen.findByRole('article')

    const box = await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ })
    expect(box).not.toBeChecked()
    await userEvent.click(box)
    expect(box).toBeChecked()
    await userEvent.click(box)
    expect(box).not.toBeChecked()

    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))
    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [])
  })

  it('does not ask for the editions of a document the corpus says has none', async () => {
    // Pins the version-count guard. `manifestOnly` answers non-empty editions
    // if asked — the assertion is that it is never asked, not that it would
    // have answered empty anyway.
    loaded()
    const manifestOnly = {
      slug: 'manifest-only', name: 'Manifest Only', is_external: false,
      references: [], referenced_by: [], version_count: 0,
    }
    listDocuments.mockResolvedValue([document, otherDocument, manifestOnly])
    listVersions.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'dodd-5000-01' ? versions : otherVersions),
    )
    renderAt()
    await screen.findByRole('article')
    await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ })

    expect(listVersions).not.toHaveBeenCalledWith('manifest-only')
  })

  it('does not render a document heading for one whose editions turned out empty', async () => {
    // Pins the empty-editions filter, for a document whose `version_count`
    // disagrees with what `listVersions` actually answers — a manifest-vs-graph
    // drift PROBE G's fixture names `staleCount`, not the ordinary "has none"
    // case the guard above covers.
    loaded()
    const staleCount = {
      slug: 'stale-count', name: 'Stale Count', is_external: false,
      references: [], referenced_by: [], version_count: 3,
    }
    listDocuments.mockResolvedValue([document, otherDocument, staleCount])
    listVersions.mockImplementation((slug: string) => {
      if (slug === 'dodd-5000-01') return Promise.resolve(versions)
      if (slug === 'dodi-5000-88') return Promise.resolve(otherVersions)
      return Promise.resolve([])
    })
    renderAt()
    await screen.findByRole('article')
    await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ })

    expect(screen.queryByText('Stale Count')).not.toBeInTheDocument()
  })

  it('says it is still looking, distinctly from either state it might settle into', async () => {
    loaded()
    let resolveList: (docs: unknown[]) => void = () => {}
    listDocuments.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve
      }),
    )
    renderAt()
    await screen.findByRole('article')

    expect(
      screen.getByText(/looking for other documents to propose links against/i),
    ).toBeInTheDocument()
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await act(async () => {
      resolveList([document])
      await Promise.resolve()
    })
  })

  it('says there is nothing else in the corpus, rather than rendering nothing', async () => {
    // Pins the empty-pool gate: this and the two states above and below it must
    // each render something, and not the same something.
    loaded()
    listDocuments.mockResolvedValue([document])
    renderAt()
    await screen.findByRole('article')

    // A live region, like `EmptyState` and Pairings' equivalent block both
    // are: without it, a screen reader gets no announcement that "Looking…"
    // has settled into this.
    expect(await screen.findByRole('status')).toHaveTextContent(
      /nothing else in the corpus to propose links against/i,
    )
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says the corpus could not be listed, rather than looking like a one-document one', async () => {
    loaded()
    listDocuments.mockRejectedValue(new Error('corpus down'))
    renderAt()
    await screen.findByRole('article')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/corpus down/)
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
    expect(
      screen.queryByText(/nothing else in the corpus/i),
    ).not.toBeInTheDocument()
  })

  it('keeps the candidate that answered when a different one\'s editions could not be listed', async () => {
    // A `Promise.all` over the edition listings would let one rejection empty
    // the whole pool — `otherDocument`'s perfectly good editions included —
    // and say nothing about why. `Promise.allSettled` is what keeps the one
    // that answered; this pins that it actually does, and that the failure of
    // the other one is not simply dropped on the floor.
    loaded()
    corpusOfThree()
    listVersions.mockImplementation((slug: string) => {
      if (slug === 'dodd-5000-01') return Promise.resolve(versions)
      if (slug === 'dodi-5000-88') return Promise.resolve(otherVersions)
      return Promise.reject(new Error('timed out'))
    })
    renderAt()
    await screen.findByRole('article')

    // The document whose listing failed names no editions and gets no
    // heading — there is nothing under it to show.
    expect(
      await screen.findByRole('checkbox', { name: /dodi-5000-88@2020-09-09/ }),
    ).toBeInTheDocument()
    expect(screen.queryByText('DoDI 1322.18')).not.toBeInTheDocument()

    // The failure is on screen, not silent.
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/1 of 2/)
  })

  // The route carries no `key`, so following a reference link from one
  // document to another does not remount this component — `candidates` and
  // `pool` both outlive the navigation.
  it('drops a ticked candidate once it would name the document now being read', async () => {
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listVersions.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? edA : edB),
    )
    listChunks.mockResolvedValue(chunks)
    listDocuments.mockResolvedValue([a, b])
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'doc-b@2020-01-01', candidate_version_ids: [],
    })

    renderAt('doc-a')
    await screen.findByRole('article')

    // On A's page, tick B's edition — a legitimate cross-document candidate
    // there.
    await userEvent.click(
      await screen.findByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    )

    // Follow the reference link to B.
    await userEvent.click(screen.getByRole('link', { name: 'Document B' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })

    // B's own edition is not offered here...
    expect(
      screen.queryByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    ).not.toBeInTheDocument()

    // ...and the tick made on A's page, before B's own edition was ever
    // excludable, must not still name it.
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )
    expect(startRebuild).toHaveBeenCalledWith('doc-b', 'doc-b@2020-01-01', [])
  })

  it('never lets a late answer for the document just left overwrite the one already resolved for this document', async () => {
    // Pins the `cancelled` guard and the effect's dependency on `slug`
    // together: an empty dependency array would never recompute the pool for
    // B at all, so the first assertion below would time out; a deleted
    // `cancelled` check would let the held-open answer for A, released after
    // the reader has moved on, overwrite B's already-correct pool with one
    // keyed to A's slug — which no longer matches, and reads as still loading.
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listVersions.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? edA : edB),
    )
    listChunks.mockResolvedValue(chunks)

    // The corpus listing made while on A's page is held open until after the
    // reader has already navigated to B; the one B's own page makes answers
    // straight away.
    let releaseFirst: (docs: unknown[]) => void = () => {}
    let calls = 0
    listDocuments.mockImplementation(() => {
      calls += 1
      if (calls === 1) {
        return new Promise((resolve) => {
          releaseFirst = resolve
        })
      }
      return Promise.resolve([a, b])
    })

    renderAt('doc-a')
    await screen.findByRole('heading', { level: 1, name: /Document A/ })
    // The corpus listing is still held, so the reference has not resolved to
    // a name yet — the slug fallback is the link this click can use.
    await userEvent.click(screen.getByRole('link', { name: 'doc-b' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })

    // B's own pool, from its own (unheld) call, is already showing.
    expect(
      await screen.findByRole('checkbox', { name: /doc-a@2020-01-01/ }),
    ).toBeInTheDocument()

    // The held answer for A now arrives — reporting, as it would have all
    // along, a corpus of just `a` itself: from the *stale* closure's own
    // slug ('doc-a'), that leaves no other document at all, so an
    // unguarded continuation reaches `setPool` on the very next line rather
    // than after a second await.
    await act(async () => {
      releaseFirst([a])
      await Promise.resolve()
    })

    // It must not have overwritten what B already correctly resolved to.
    expect(
      screen.getByRole('checkbox', { name: /doc-a@2020-01-01/ }),
    ).toBeInTheDocument()
  })

  it('never lets a late edition answer for the document just left overwrite this document\'s pool', async () => {
    // The same guard, pinned at its other await: the corpus listing can
    // answer promptly while a *edition* listing it kicked off is what is
    // still in flight when the reader navigates away.
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listChunks.mockResolvedValue(chunks)
    listDocuments.mockResolvedValue([a, b])

    // A's page asks for B's editions twice over — once for B's own "Editions"
    // section once the reader has navigated there, and, before that, once
    // from A's pool effect asking about B as a candidate. Only the *first*
    // of those (A's pool effect) is the stale one; B's own page must get its
    // own editions back promptly or nothing about it would ever render.
    let releaseStale: (eds: unknown[]) => void = () => {}
    let docBCalls = 0
    listVersions.mockImplementation((slug: string) => {
      if (slug === 'doc-b') {
        docBCalls += 1
        if (docBCalls === 1) {
          return new Promise((resolve) => {
            releaseStale = resolve
          })
        }
        return Promise.resolve(edB)
      }
      return Promise.resolve(edA)
    })

    renderAt('doc-a')
    await screen.findByRole('heading', { level: 1, name: /Document A/ })
    await userEvent.click(screen.getByRole('link', { name: 'Document B' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })

    // B's own pool, from a call this held request has nothing to do with, is
    // already showing.
    expect(
      await screen.findByRole('checkbox', { name: /doc-a@2020-01-01/ }),
    ).toBeInTheDocument()

    // The held answer — for A's page, about B's editions — now arrives.
    await act(async () => {
      releaseStale(edB)
      await Promise.resolve()
    })

    // It must not have overwritten what B already correctly resolved to.
    expect(
      screen.getByRole('checkbox', { name: /doc-a@2020-01-01/ }),
    ).toBeInTheDocument()
  })

  // The two tests above pin the `cancelled` guards, and by the time either
  // asserts, the current document's own pool has already settled — so the
  // keyed read (`pool.slug === slug`) is never the thing actually stopping
  // the wrong answer from showing; `cancelled` already did that. This test
  // does not hold a *stale* request open at all: A's pool resolves and is
  // written to state completely normally. What it pins is whether that
  // already-correct, already-written value for A is misread as the answer
  // for B while B's own (separate, currently in-flight) request is still
  // settling — which only the slug comparison, not `cancelled`, can catch.
  it('does not read the previous document\'s already-settled pool as this document\'s own while this document\'s own answer is still in flight', async () => {
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listChunks.mockResolvedValue(chunks)
    listDocuments.mockResolvedValue([a, b])

    // `listVersions('doc-a')` is called twice, by two different callers: the
    // main document effect while A's own page is open (answered promptly),
    // and B's pool effect once the reader has navigated to B — asking about
    // A as a candidate. That second call is the one held open, so B's own
    // pool fetch is still unsettled at the point this test checks it.
    let releaseBsOwnPool: (eds: unknown[]) => void = () => {}
    let docACalls = 0
    listVersions.mockImplementation((slug: string) => {
      if (slug === 'doc-a') {
        docACalls += 1
        if (docACalls === 1) return Promise.resolve(edA)
        return new Promise((resolve) => {
          releaseBsOwnPool = resolve
        })
      }
      // A's pool effect asks this, promptly, so A's own pool (offering B) is
      // fully settled and written to state before the reader ever leaves.
      return Promise.resolve(edB)
    })

    renderAt('doc-a')
    await screen.findByRole('heading', { level: 1, name: /Document A/ })
    // A's pool is fully resolved before navigating away: it offers B.
    await screen.findByRole('checkbox', { name: /doc-b@2020-01-01/ })

    await userEvent.click(screen.getByRole('link', { name: 'Document B' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })

    // B's own pool fetch is still pending. Without the keyed read, `pool`
    // would still hold A's last-written value — whose one entry is B's own
    // edition — and B's page would offer it against itself, the same shape
    // of defect this whole round of work exists to close.
    expect(screen.getByRole('status')).toHaveTextContent(/looking for other documents/i)
    expect(
      screen.queryByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    ).not.toBeInTheDocument()

    await act(async () => {
      releaseBsOwnPool(edA)
      await Promise.resolve()
    })

    // B's own answer, once it settles, offers A.
    expect(
      await screen.findByRole('checkbox', { name: /doc-a@2020-01-01/ }),
    ).toBeInTheDocument()
  })

  it('clears an old listing failure once a later fetch for the same document succeeds', async () => {
    // Reproduces: A's listing fails; the reader navigates to B and back to
    // A, where it now succeeds. Without clearing, the alert from the first,
    // failed attempt would still be showing over a fieldset that now works.
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listVersions.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? edA : edB),
    )
    listChunks.mockResolvedValue(chunks)

    let calls = 0
    listDocuments.mockImplementation(() => {
      calls += 1
      // A's first visit fails; B's visit and A's retry both succeed.
      if (calls === 1) return Promise.reject(new Error('corpus down'))
      return Promise.resolve([a, b])
    })

    renderAt('doc-a')
    await screen.findByRole('heading', { level: 1, name: /Document A/ })
    expect(await screen.findByRole('alert')).toHaveTextContent(/corpus down/)

    // The corpus listing failed, so the reference has not resolved to a name
    // — the slug fallback is the link this click can use.
    await userEvent.click(screen.getByRole('link', { name: 'doc-b' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })

    await userEvent.click(screen.getByRole('link', { name: 'Document A' }))
    await screen.findByRole('heading', { level: 1, name: /Document A/ })

    // The retry succeeded: the stale failure must not still be reported.
    expect(
      await screen.findByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not let a listing failure held open past a successful retry revive the alert', async () => {
    // The same fix as above, pinned at the guard that makes it safe rather
    // than accidental: the `if (!cancelled)` inside the corpus-listing
    // catch. Held open, then rejected only after a *later* attempt for the
    // same document has already succeeded and cleared the slate.
    const a = {
      slug: 'doc-a', name: 'Document A', is_external: false,
      references: ['doc-b'], referenced_by: [], version_count: 1,
    }
    const b = {
      slug: 'doc-b', name: 'Document B', is_external: false,
      references: ['doc-a'], referenced_by: [], version_count: 1,
    }
    const edA = [{
      version_id: 'doc-a@2020-01-01', effective_date: '2020-01-01',
      checksum: 'aaaa', source_uri: 'file:///doc-a.pdf', supersedes: null,
    }]
    const edB = [{
      version_id: 'doc-b@2020-01-01', effective_date: '2020-01-01',
      checksum: 'bbbb', source_uri: 'file:///doc-b.pdf', supersedes: null,
    }]

    getDocument.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? a : b),
    )
    listVersions.mockImplementation((slug: string) =>
      Promise.resolve(slug === 'doc-a' ? edA : edB),
    )
    listChunks.mockResolvedValue(chunks)

    let rejectFirst: (error: Error) => void = () => {}
    let calls = 0
    listDocuments.mockImplementation(() => {
      calls += 1
      // A's first visit: held open, rejected only once the reader has been
      // to B and back, and the retry below has already succeeded.
      if (calls === 1) {
        return new Promise((_, reject) => {
          rejectFirst = reject
        })
      }
      return Promise.resolve([a, b])
    })

    renderAt('doc-a')
    await screen.findByRole('heading', { level: 1, name: /Document A/ })
    await userEvent.click(screen.getByRole('link', { name: 'doc-b' }))
    await screen.findByRole('heading', { level: 1, name: /Document B/ })
    await userEvent.click(screen.getByRole('link', { name: 'Document A' }))
    await screen.findByRole('heading', { level: 1, name: /Document A/ })

    // The retry (the third `listDocuments` call) succeeded.
    expect(
      await screen.findByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // The held-open first attempt now rejects — for a closure whose effect
    // was cleaned up two navigations ago.
    await act(async () => {
      rejectFirst(new Error('timed out'))
      await Promise.resolve()
    })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /doc-b@2020-01-01/ }),
    ).toBeInTheDocument()
  })

  it('says so when none of the other documents\' editions could be loaded', async () => {
    // The `failed === others.length` branch: distinct wording from the
    // partial-failure case, and untested until now — the string it produces
    // appeared only in the component.
    loaded()
    listDocuments.mockResolvedValue([document, otherDocument])
    listVersions.mockImplementation((slug: string) =>
      slug === 'dodd-5000-01' ? Promise.resolve(versions) : Promise.reject(new Error('timed out')),
    )
    renderAt()
    await screen.findByRole('article')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not load any other document's editions/i)
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
    expect(
      screen.queryByText(/nothing else in the corpus/i),
    ).not.toBeInTheDocument()
  })
})

// STORY-081. Obligations are the product's central noun and had no screen at all:
// reachable only as a count in a rebuild report, two at a time in Review, or
// quoted in a Triage row. Confirming that a 2026-08-25 rebuild wrote 113 of them
// required `cypher-shell`.

describe('DocumentDetail obligations', () => {
  const threeObligations = {
    obligations: [
      {
        obligation_id: 'ob1',
        statement: 'Components shall apply this issuance.',
        modality: 'SHALL',
        section_path: ['SECTION 1', '1.1'],
        page: 3,
      },
      {
        obligation_id: 'ob2',
        statement: 'Components will record their compliance.',
        modality: 'WILL',
        section_path: ['SECTION 1', '1.1'],
        page: 3,
      },
    ],
    total: 2,
    returned: 2,
    truncated: false,
  }

  it('says how many obligations the edition holds and shows them', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue(threeObligations)

    renderAt()

    expect(
      await screen.findByText(/Components shall apply this issuance\./),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Components will record their compliance\./),
    ).toBeInTheDocument()
    // The section and page are what make a statement checkable against the source.
    expect(screen.getAllByText(/SECTION 1/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/p\. 3/).length).toBeGreaterThan(0)
  })

  it('does not report an unbuilt edition as one that yielded nothing', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      obligations: [],
      total: 0,
      returned: 0,
      truncated: false,
    })

    renderAt()

    // Three of four editions in the live graph on 2026-08-26 were in exactly this
    // state. "None found" and "never built" need opposite actions, and this is
    // STORY-081's AC6 — met once STORY-082 landed the build record that can tell
    // them apart. Before that the copy had to hedge between the two.
    expect(
      await screen.findByText(/no obligations recorded for this edition/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/this edition has never been built/i),
    ).toBeInTheDocument()
  })

  it('says so when it shows fewer obligations than the edition holds', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      ...threeObligations,
      total: 604,
      returned: 2,
      truncated: true,
    })

    renderAt()

    expect(await screen.findByText(/604/)).toBeInTheDocument()
    expect(screen.getByText(/showing the first 2/i)).toBeInTheDocument()
  })
})


// STORY-082. Three of four editions in the live graph on 2026-08-26 held chunks
// and zero obligations, with nothing to say whether that meant never-built,
// built-with-null, or a run that died. And the run id lived only in React state,
// so reloading the tab stranded a rebuild that was still going — which the
// eight-hour job timeout set the same day made a real loss rather than a nuisance.

const built = (over: Record<string, unknown> = {}) => ({
  ...versions[1],
  build_state: 'finished',
  build_run_id: 'run-9',
  build_started_at: '2026-08-25T10:00:00+00:00',
  build_changed_at: '2026-08-25T11:00:00+00:00',
  build_extractor_adapter: 'local',
  build_embedder_adapter: 'local',
  build_counts: { chunks_written: 37, obligations_written: 113 },
  build_error: null,
  ...over,
})

describe('DocumentDetail build state', () => {
  it('says an edition has never been built', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([versions[0], { ...versions[1] }])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(
      await screen.findByText(/has never been built/i),
    ).toBeInTheDocument()
  })

  it('names when an edition was built and with which extractor', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([versions[0], built()])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(await screen.findByText(/built/i)).toBeInTheDocument()
    expect(screen.getByText(/local/)).toBeInTheDocument()
  })

  it('explains a build that used no extraction model', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({
        build_extractor_adapter: 'null',
        build_counts: { chunks_written: 41, obligations_written: 0 },
      }),
    ])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    // Not "extraction found nothing": the null adapter writes no obligations by
    // design (ADR-028), and saying otherwise sends a user to debug a document
    // when the answer is a setting.
    expect(
      await screen.findByText(/no extraction model was configured/i),
    ).toBeInTheDocument()
  })

  it('reports a build that failed, and why', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({
        build_state: 'failed',
        build_error: 'JobTimeoutException: Task exceeded maximum timeout value',
        build_counts: {},
      }),
    ])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(await screen.findByText(/last build failed/i)).toBeInTheDocument()
    expect(screen.getByText(/JobTimeoutException/)).toBeInTheDocument()
  })

  it('re-attaches to a rebuild that is still running after a reload', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({ build_state: 'started', build_run_id: 'run-live', build_counts: {} }),
    ])
    listChunks.mockResolvedValue(chunks)
    getRebuild.mockResolvedValue({
      run_id: 'run-live',
      version_id: versions[1].version_id,
      state: 'started',
      chunks_done: 12,
      chunks_total: 37,
      counts: {},
      rejections: [],
      rejections_total: 0,
      extractor_adapter: 'local',
      embedder_adapter: 'local',
      error: null,
    })

    renderAt()

    // The whole point: no one clicked Build in this session, and the page still
    // finds the run. Before this, the id existed only in the state of the tab
    // that started it.
    expect(await screen.findByText(/12 of 37/i)).toBeInTheDocument()
    expect(getRebuild).toHaveBeenCalledWith('run-live')
  })

  it('does not leave a dead run reading as one still building', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({ build_state: 'started', build_run_id: 'run-gone', build_counts: {} }),
    ])
    listChunks.mockResolvedValue(chunks)
    // The worker died without reporting, so RQ no longer knows the job. The
    // record says "started" and will say so for ever unless the two are
    // reconciled against each other.
    getRebuild.mockRejectedValue(new Error('No such run.'))

    renderAt()

    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument()
  })


  it('does not call an edition unbuilt when it plainly holds obligations', async () => {
    getDocument.mockResolvedValue(document)
    // Exactly the live state on 2026-08-26: dodd-5000-01@2020-09-09 holds 113
    // obligations from a rebuild that predates the build record, so it has none.
    // Saying "never built" over a list of its obligations is a contradiction the
    // screen would put in front of a user on the very first edition they open.
    listVersions.mockResolvedValue([versions[0], { ...versions[1] }])
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      obligations: [
        {
          obligation_id: 'ob1',
          statement: 'Components shall apply this issuance.',
          modality: 'SHALL',
          section_path: ['SECTION 1'],
          page: 3,
        },
      ],
      total: 113,
      returned: 1,
      truncated: true,
    })

    renderAt()

    expect(await screen.findByText(/113/)).toBeInTheDocument()
    expect(
      screen.queryByText(/has never been built/i),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/before builds were recorded/i)).toBeInTheDocument()
  })
})


// ADR-030 moved the blast radius from the chunk to the item, and the count is
// the condition attached to that decision. Reporting only `chunks_rejected`
// while listing item drops beside it says "0 chunks rejected" above eight
// entries — which is worse than either number alone.

describe('DocumentDetail rebuild reporting', () => {
  const finishedRun = (
    counts: Record<string, number>,
    rejections: RebuildStatus['rejections'],
  ): RebuildStatus => ({
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 38, chunks_total: 38, counts, rejections,
    // Every refusal, against the capped list — kept consistent here rather than
    // per fixture, so none of them can describe a run reporting fewer refusals
    // than it counted.
    rejections_total: Math.max(
      rejections.length,
      (counts.chunks_rejected ?? 0) + (counts.items_dropped ?? 0),
    ),
    extractor_adapter: 'local', embedder_adapter: 'local', error: null,
  })

  it('reports dropped items separately from rejected chunks', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finishedRun(
        { chunks_written: 38, obligations_written: 90, chunks_rejected: 1, items_dropped: 8 },
        [{ chunk_id: 'c1', reason: 'modality' }],
      ),
    )

    renderAt()
    await screen.findByRole('button', { name: /build derived layer/i })
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/8 statements dropped/i)).toBeInTheDocument()
    expect(screen.getByText(/1 chunk rejected/i)).toBeInTheDocument()
  })

  it('says nothing about drops when there were none', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finishedRun({ chunks_written: 38, obligations_written: 90, chunks_rejected: 0, items_dropped: 0 }, []),
    )

    renderAt()
    await screen.findByRole('button', { name: /build derived layer/i })
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/0 chunks rejected/i)).toBeInTheDocument()
    expect(screen.queryByText(/statements dropped/i)).not.toBeInTheDocument()
  })
})

// STORY-089. Asserting the interval that gets computed, not that a timer was set:
// a test that only checks `setTimeout` was called passes against the flat
// two-second poll this exists to replace.
describe('pollDelayMs', () => {
  it('answers a short run as quickly as the flat poll did', () => {
    expect(pollDelayMs(0)).toBe(FIRST_POLL_MS)
  })

  it('grows between successive polls', () => {
    const delays = [0, 1, 2, 3].map(pollDelayMs)
    for (let i = 1; i < delays.length; i += 1) {
      expect(delays[i]).toBeGreaterThan(delays[i - 1])
    }
  })

  it('settles at a ceiling rather than growing without bound', () => {
    expect(pollDelayMs(50)).toBe(MAX_POLL_MS)
    expect(pollDelayMs(500)).toBe(MAX_POLL_MS)
  })

  it('cuts an eight-hour run from ~14,400 requests to under a thousand', () => {
    // The number that motivated the story, computed rather than asserted from
    // memory: how many polls an 8h run costs at this curve.
    let elapsed = 0
    let polls = 0
    while (elapsed < 8 * 60 * 60 * 1000) {
      elapsed += pollDelayMs(polls)
      polls += 1
    }
    expect(polls).toBeLessThan(1000)
    expect(8 * 60 * 60 * 1000 / FIRST_POLL_MS).toBeGreaterThan(14000)
  })
})

// STORY-076. `UNPROMOTABLE` filtered on approvals, so a stranded rejection was
// counted by nothing — and it is the worse of the two losses, because the
// proposal returns to the queue with no sign it was already refused.

describe('DocumentDetail, stranded rejections', () => {
  const finished = (counts: Record<string, number>): RebuildStatus => ({
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 37, chunks_total: 37, counts, rejections: [],
    rejections_total: (counts.chunks_rejected ?? 0) + (counts.items_dropped ?? 0),
    extractor_adapter: 'local', embedder_adapter: 'local', error: null,
  })

  it('reports a stranded rejection and says what it costs', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({ chunks_written: 37, obligations_written: 56, rejections_stranded: 2 }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    expect(await screen.findByText(/2 recorded rejections/i)).toBeInTheDocument()
    expect(screen.getByText(/refused before/i)).toBeInTheDocument()
  })

  it('says nothing about rejections when none were stranded', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({ chunks_written: 37, obligations_written: 56, rejections_stranded: 0 }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    await screen.findByText(/37 chunks written|chunks rejected/i)
    expect(screen.queryByText(/recorded rejection/i)).not.toBeInTheDocument()
  })
})

// ADR-027 requires the count of decisions a rebuild could not carry to be on
// screen rather than merely returned, and the pairing split added a second
// decision vocabulary that the rebuild repoints through the same path. Both its
// counts reached this payload and neither was drawn.

describe('DocumentDetail, pairing decisions across a rebuild', () => {
  const finished = (counts: Record<string, number>): RebuildStatus => ({
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 37, chunks_total: 37, counts, rejections: [],
    rejections_total: (counts.chunks_rejected ?? 0) + (counts.items_dropped ?? 0),
    extractor_adapter: 'local', embedder_adapter: 'local', error: null,
  })

  it('reports the pairing verdicts it carried and the ones it lost', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({
        chunks_written: 37,
        obligations_written: 56,
        pairing_decisions_repointed: 4,
        pairing_decisions_stranded: 2,
      }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    const lost = await screen.findByText(/2 recorded pairing verdicts/i)
    expect(lost).toBeInTheDocument()
    // A standing condition, not this run's loss: the count is graph-wide, so
    // attributing it to this build would report a verdict stranded months ago on
    // another document as something this build just did — on every build, forever.
    expect(lost).toHaveTextContent(/not only this build/i)
    // And not a claim the query does not make: it asks whether a clause is still
    // held by an edition, which is also true of a deleted document and of a
    // statement that became ambiguous, so "the statements no longer match" was
    // describing a narrower cause than the one being counted.
    expect(lost).not.toHaveTextContent(/statements no longer match/i)
    expect(screen.getByText(/4 pairing decisions/i)).toBeInTheDocument()
  })

  it('says nothing about pairing verdicts when none were carried or lost', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({
        chunks_written: 37,
        obligations_written: 56,
        pairing_decisions_repointed: 0,
        pairing_decisions_stranded: 0,
      }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    await screen.findByText(/37 chunks written|chunks rejected/i)
    expect(screen.queryByText(/pairing verdict/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/pairing decisions/i)).not.toBeInTheDocument()
  })
})

// Found in the sprint-12 walkthrough, driving the real stack. `versions` was read
// once on mount, so the build record the run had just written was never re-read:
// the moment a build finished, the page said "Finished. 41 chunks…" in one panel
// and "This edition has never been built" in the next. Two statements about one
// edition, on one screen, contradicting each other — and the obligations the run
// wrote stayed invisible behind "No obligations recorded for this edition" until
// someone thought to reload.
//
// That is the false negative STORY-082 and ADR-019 exist to prevent, met at the
// one moment a reader is certain to be looking: the end of a build they started
// and, with a real extractor, waited hours for.
describe('DocumentDetail after a build finishes', () => {
  const unbuilt = { ...versions[1] }
  const rebuilt = built({
    build_changed_at: '2026-09-08T18:08:00+00:00',
    build_counts: { chunks_written: 41, obligations_written: 113 },
  })
  const run = {
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 41, chunks_total: 41,
    counts: { chunks_written: 41, obligations_written: 113 },
    rejections: [], rejections_total: 0,
    extractor_adapter: 'local', embedder_adapter: 'local',
    error: null,
  }

  async function build() {
    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )
    await screen.findByText(/finished\. 41 chunks/i)
  }

  it('stops calling the edition never-built once a run has built it', async () => {
    getDocument.mockResolvedValue(document)
    listVersions
      .mockResolvedValueOnce([versions[0], unbuilt])
      .mockResolvedValue([versions[0], rebuilt])
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(run)

    await build()

    await waitFor(() =>
      expect(screen.queryByText(/has never been built/i)).not.toBeInTheDocument(),
    )
    expect(screen.getByText(/built 2026-09-08 with extractor/i)).toBeInTheDocument()
  })

  it('shows the obligations the run just wrote', async () => {
    getDocument.mockResolvedValue(document)
    listVersions
      .mockResolvedValueOnce([versions[0], unbuilt])
      .mockResolvedValue([versions[0], rebuilt])
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(run)
    listObligations
      .mockResolvedValueOnce({ obligations: [], total: 0, returned: 0, truncated: false })
      .mockResolvedValue({
        obligations: [
          {
            obligation_id: 'o1',
            // Deliberately not one of the `chunks` texts above: the same words in
            // both lists match twice and the query fails for a reason that has
            // nothing to do with what this test is about.
            statement: 'The program manager will conduct industrial base assessments.',
            modality: 'will',
            section_path: ['SECTION 1'],
            page: 9,
          },
        ],
        total: 1,
        returned: 1,
        truncated: false,
      })

    await build()

    expect(
      await screen.findByText(/conduct industrial base assessments/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/no obligations recorded for this edition/i),
    ).not.toBeInTheDocument()
  })

  // The same staleness one state further on. `runLost` is set when a recorded
  // run has vanished from the queue, and nothing cleared it — so a rebuild that
  // then succeeded was still described as the run that did not finish.
  it('stops reporting a lost run once a later build succeeds', async () => {
    getDocument.mockResolvedValue(document)
    listVersions
      .mockResolvedValueOnce([
        versions[0],
        built({ build_state: 'started', build_run_id: 'run-gone', build_counts: {} }),
      ])
      .mockResolvedValue([versions[0], rebuilt])
    listChunks.mockResolvedValue(chunks)
    getRebuild.mockRejectedValueOnce(new Error('no such job'))
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(run)

    renderAt()
    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: /build derived layer/i }),
    )
    await screen.findByText(/finished\. 41 chunks/i)

    await waitFor(() =>
      expect(screen.queryByText(/did not finish/i)).not.toBeInTheDocument(),
    )
  })
})

// Found in the sprint-12 walkthrough. The outline read H1 → References → Text →
// Obligations → Text: "Text" twice, and the first one labelled a section that
// holds no text at all — the edition picker and the derived-layer builder. A
// reader navigating this page by heading heard "Text… Obligations… Text" and had
// no way to tell which was which.
describe('DocumentDetail heading outline', () => {
  it('names each section once, and names it for what it holds', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)

    renderAt()
    await screen.findByRole('heading', { name: /DoDD 5000\.01/ })

    const outline = screen
      .getAllByRole('heading', { level: 2 })
      .map((heading) => heading.textContent)

    expect(outline).toEqual(['References', 'Editions', 'Obligations', 'Text'])
  })
})
