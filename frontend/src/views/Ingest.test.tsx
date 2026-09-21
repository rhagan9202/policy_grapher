import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const ingest = vi.fn()
const listSources = vi.fn()
vi.mock('../api/client', () => ({
  ingest: (filename: string) => ingest(filename),
  listSources: () => listSources(),
  ApiError: class extends Error {},
}))

import Ingest from './Ingest'

// The duplicates this screen reports link to the screen that rules on them, so
// it needs router context. MemoryRouter rather than a real one: these tests are
// about ingesting, not about navigation.
function showIngest() {
  return render(
    <MemoryRouter>
      <Ingest />
    </MemoryRouter>,
  )
}

/** Stands in for the map, so a test can see where the reader was sent and what
 *  was carried there without mounting the real graph and its fetches. */
function MapStub() {
  const location = useLocation()
  const carried = location.state as { ingest?: Record<string, unknown> } | null
  return (
    <div data-testid="map">
      <span data-testid="map-query">{location.search}</span>
      <span data-testid="map-state">{JSON.stringify(carried?.ingest ?? null)}</span>
    </div>
  )
}

/** The ingest screen with somewhere to land, and a way out while it works —
 *  the real navigation stays available during an ingest, so a test needs one
 *  too. */
function showIngestWithMap() {
  return render(
    <MemoryRouter initialEntries={['/ingest']}>
      <Link to="/documents">Documents</Link>
      <Routes>
        <Route path="/ingest" element={<Ingest />} />
        <Route path="/" element={<MapStub />} />
        <Route path="/documents" element={<div data-testid="documents" />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function chooseAndIngest(file = '500001p_2020.pdf') {
  await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), file)
  await userEvent.click(screen.getByRole('button', { name: /ingest/i }))
}

afterEach(() => {
  ingest.mockReset()
  listSources.mockReset()
})

const SOURCES = [
  { filename: '500001p_2020.pdf', size_bytes: 159349, kind: 'document', ingested: false },
  { filename: 'dod_policy_references_08122026.csv', size_bytes: 21776, kind: 'manifest', ingested: true },
]

// STORY-043. `POST /ingest` has existed since DI-1 and `ingest()` has been exposed
// since then; nothing called it. Loading the corpus was a curl command, which means
// the person this tool is for could not put a document into it.

describe('Ingest', () => {
  // These exercise what the screen does with an ingest *result*. The control
  // that starts one is the picker now, so it has to be populated for them to
  // reach it at all.
  beforeEach(() => {
    listSources.mockResolvedValue([
      { filename: 'corpus.csv', size_bytes: 21776, kind: 'manifest', ingested: false },
      { filename: 'broken.csv', size_bytes: 12, kind: 'manifest', ingested: false },
      { filename: '500001p_2020.pdf', size_bytes: 159349, kind: 'document', ingested: false },
    ])
  })

  it('ingests the named file', async () => {
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [],
    })
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), 'corpus.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(ingest).toHaveBeenCalledWith('corpus.csv')
  })

  it('reports what a manifest ingest created', async () => {
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [],
    })
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), 'corpus.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent(/438/)
    expect(result).toHaveTextContent(/672/)
  })

  it('surfaces the duplicates a manifest ingest suspected', async () => {
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [['Military Standard 882E', 'Military-Standard 882E']],
    })
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), 'corpus.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByText(/Military-Standard 882E/)).toBeInTheDocument()
  })

  it('reports a rejected file instead of pretending it loaded', async () => {
    ingest.mockRejectedValue(new Error('row 3: missing column "name"'))
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), 'broken.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/missing column/i)
  })

  it('refuses a blank filename rather than asking the API to', async () => {
    showIngest()
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))
    expect(ingest).not.toHaveBeenCalled()
  })
})


// The screen used to be a free-text box over a directory only the server can
// see: know the filename or guess it. `POST /ingest` still takes a bare
// filename — the backend reads from its own container — so the fix is to say
// what is in that container, not to change what the route accepts.
describe('Ingest — choosing a source', () => {
  it('offers what the backend actually has', async () => {
    listSources.mockResolvedValue(SOURCES)
    showIngest()

    expect(
      await screen.findByRole('option', { name: /500001p_2020\.pdf/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: /dod_policy_references_08122026\.csv/ }),
    ).toBeInTheDocument()
  })

  it('says what ingest will make of each file, and how big it is', async () => {
    listSources.mockResolvedValue(SOURCES)
    showIngest()

    // The screen's own prose distinguishes a manifest from a document; the
    // reader should not have to infer which is which from the extension.
    expect(await screen.findByRole('option', { name: /manifest/i })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /156 KB/ })).toBeInTheDocument()
  })

  it('switches to MB rather than reading "1463 KB"', async () => {
    listSources.mockResolvedValue([
      { filename: '818001m.pdf', size_bytes: 1498112, kind: 'document', ingested: false },
    ])
    showIngest()

    expect(await screen.findByRole('option', { name: /1\.4 MB/ })).toBeInTheDocument()
  })

  it('marks what has already been ingested without refusing it', async () => {
    listSources.mockResolvedValue(SOURCES)
    showIngest()

    const already = await screen.findByRole('option', { name: /already ingested/i })
    // Re-ingesting is how a second edition arrives (ADR-007 keeps it additive),
    // so this informs rather than blocks.
    expect(already).not.toBeDisabled()
  })

  it('ingests the file that was chosen', async () => {
    listSources.mockResolvedValue(SOURCES)
    ingest.mockResolvedValue({
      source: 'document', outcome: 'written', format: 'modern',
      document: { slug: 'd', name: 'DoDD 5000.01' },
      nodes_created: 1, relationships_created: 2, references_attributed: 16,
      references_unattributed: [], self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09', chunks_written: 34,
    })
    showIngest()

    const picker = await screen.findByLabelText(/file to ingest/i)
    await userEvent.selectOptions(picker, '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /^ingest$/i }))

    expect(ingest).toHaveBeenCalledWith('500001p_2020.pdf')
  })

  it('says the directory is empty rather than offering an empty picker', async () => {
    listSources.mockResolvedValue([])
    showIngest()

    expect(await screen.findByRole('status')).toHaveTextContent(/no files/i)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('falls back to typing a name when the listing cannot be loaded', async () => {
    // A picker that cannot load must not leave the reader with no way to act.
    listSources.mockRejectedValue(new Error('backend down'))
    ingest.mockResolvedValue({
      source: 'manifest', nodes_created: 1, relationships_created: 0,
      self_references_skipped: 0, suspected_duplicates: [],
    })
    showIngest()

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
    const box = screen.getByLabelText(/file to ingest/i)
    await userEvent.type(box, 'corpus.csv')
    await userEvent.click(screen.getByRole('button', { name: /^ingest$/i }))

    expect(ingest).toHaveBeenCalledWith('corpus.csv')
  })
})

// STORY-036 added XLSX manifests, and the picker went on calling every manifest a
// "CSV manifest" — found by ingesting one through this screen and reading the
// label it offered. A picker that names the wrong format is the same defect the
// picker was built to fix (STORY-077): a reader who cannot tell what a file is.

describe('Ingest, naming the format', () => {
  it('does not call a spreadsheet a CSV', async () => {
    listSources.mockResolvedValue([
      { filename: 'corpus.xlsx', kind: 'manifest', size_bytes: 9307 },
      { filename: 'corpus.csv', kind: 'manifest', size_bytes: 4096 },
    ])

    showIngest()

    const options = await screen.findAllByRole('option')
    const labels = options.map((o) => o.textContent ?? '')
    expect(labels.find((l) => l.includes('corpus.xlsx'))).not.toMatch(/CSV/i)
    expect(labels.find((l) => l.includes('corpus.xlsx'))).toMatch(/spreadsheet/i)
    expect(labels.find((l) => l.includes('corpus.csv'))).toMatch(/CSV/i)
  })
})

// Found in the sprint-12 walkthrough. Ingesting the sample manifest reports "2
// suspected duplicate names" and names them — and then stops. Nothing on the
// screen says that ruling on them is a thing you can do, or where. The control
// that does it has existed since STORY-031, one click away on Documents.
describe('Ingest when a manifest flags duplicates', () => {
  it('sends the reader to the screen that rules on them', async () => {
    listSources.mockResolvedValue([
      { filename: 'corpus.csv', size_bytes: 21776, kind: 'manifest', ingested: false },
    ])
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [['Military Standard 882E', 'Military-Standard 882E']],
    })
    showIngest()

    await userEvent.selectOptions(
      await screen.findByLabelText(/file to ingest/i),
      'corpus.csv',
    )
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const reported = await screen.findByRole('status')
    const link = within(reported).getByRole('link', { name: /documents/i })
    expect(link).toHaveAttribute('href', '/documents')
  })
})


// ---------------------------------------------------------------------------
// U6. Adding a document and seeing it are one action.
//
// The gap this closes is the plan's own acceptance test: the write happened on
// this screen and the reader had to go and find the result somewhere else.
// ---------------------------------------------------------------------------

const WRITTEN = {
  source: 'document' as const,
  outcome: 'written' as const,
  format: 'modern',
  document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
  nodes_created: 1,
  relationships_created: 2,
  references_attributed: 16,
  references_unattributed: [] as string[],
  self_references_skipped: 0,
  version_id: 'dodd-5000-01@2020-09-09',
  chunks_written: 34 as number | null,
}

// The five tests that asserted a document ingest's result on this screen moved
// to GraphExplorer.test.tsx, under "arriving from an ingest". A document ingest
// no longer reports here: it sends the reader to that document's map and the
// account of the write travels with them, so that is where naming the edition,
// distinguishing an unchanged re-add from a write, and listing the references
// that could not be attributed are now asserted.

describe('Ingest, landing on the map', () => {
  beforeEach(() => {
    listSources.mockResolvedValue(SOURCES)
  })

  it('leaves the reader on the map with the new document focused', async () => {
    // AE1, the ten-second test. Adding a document and reading what it depends
    // on were two screens and a search apart; the response already names the
    // document, so nothing has to be looked up to close that.
    ingest.mockResolvedValue(WRITTEN)
    showIngestWithMap()
    await chooseAndIngest()

    const map = await screen.findByTestId('map')
    expect(map).toBeInTheDocument()
    expect(screen.getByTestId('map-query')).toHaveTextContent('focus=dodd-5000-01')
  })

  it('lands on the map for an unchanged re-add, and says nothing was done', async () => {
    // AE5. The destination is the same — this document is what the reader
    // asked to see — but the account of the write is different and has to
    // survive the trip, or "already present" is said to nobody.
    ingest.mockResolvedValue({
      ...WRITTEN, outcome: 'unchanged', chunks_written: null,
      nodes_created: 0, relationships_created: 0,
    })
    showIngestWithMap()
    await chooseAndIngest()

    await screen.findByTestId('map')
    expect(screen.getByTestId('map-query')).toHaveTextContent('focus=dodd-5000-01')
    const carried = JSON.parse(screen.getByTestId('map-state').textContent ?? 'null')
    // Every field the map declares, exactly — no subset. A payload missing one
    // renders an empty edition or a silent notice at the other end, and the
    // only thing joining the two files is a type.
    expect(carried).toEqual({
      outcome: 'unchanged',
      slug: 'dodd-5000-01',
      name: 'DoDD 5000.01',
      versionId: 'dodd-5000-01@2020-09-09',
      unresolved: [],
    })
    // No write counts travel with it: there was no write to count.
    expect(carried).not.toHaveProperty('chunksWritten')
  })

  it('carries the names the parse could not attribute to the map', async () => {
    // They are also stored on the node (U1/U3) and drawn there, so this is the
    // immediate account rather than the only one — but a reader who has just
    // added a document should not have to go looking for what went unread.
    ingest.mockResolvedValue({
      ...WRITTEN,
      references_unattributed: ['Public Law 116-92', 'An entry nobody could parse'],
    })
    showIngestWithMap()
    await chooseAndIngest()

    // Wait for the landing, rather than assuming the navigation has already
    // flushed: it is a state update behind an awaited promise, so a loaded
    // machine gets here first. This test passed locally and failed in CI.
    await screen.findByTestId('map')
    const carried = JSON.parse(screen.getByTestId('map-state').textContent ?? 'null')
    expect(carried.unresolved).toEqual([
      'Public Law 116-92',
      'An entry nobody could parse',
    ])
  })

  it('stays put and names the conflict when two files claim one edition', async () => {
    // AE8. A refusal is not a destination: the reader's view is left alone and
    // the cause is named where they are.
    ingest.mockRejectedValue(
      new Error(
        "version 'dodd-5000-01@2020-09-09' is already recorded with checksum 'abc', "
        + 'but this ingest presents checksum \'def\' for the same effective date '
        + '— two different files claim the same edition',
      ),
    )
    showIngestWithMap()
    await chooseAndIngest()

    expect(screen.queryByTestId('map')).not.toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /two different files claim the same edition/i,
    )
  })

  it('stays put and names the cause when the file is not an issuance', async () => {
    // AE3. The same rule for a different refusal: no node, no navigation, and
    // a message that says which of the two things went wrong.
    ingest.mockRejectedValue(
      new Error("'notes.pdf' has no recognisable issuance header"),
    )
    showIngestWithMap()
    await chooseAndIngest()

    expect(screen.queryByTestId('map')).not.toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /no recognisable issuance header/i,
    )
  })

  it('does not haul back a reader who left while the ingest was running', async () => {
    // An ingest resolves in the foreground but not instantly, and the reader
    // can leave for another screen while it does. `useNavigate` is bound to the
    // router rather than to the screen, so the continuation still fires after
    // the screen is gone — and a navigation nobody asked for, landing on a
    // document they chose to walk away from, is worse than never hearing the
    // outcome of a write they abandoned.
    let finishIngest: ((value: unknown) => void) | undefined
    ingest.mockImplementation(
      () => new Promise((resolve) => { finishIngest = resolve }),
    )
    showIngestWithMap()
    await chooseAndIngest()

    await userEvent.click(screen.getByRole('link', { name: /documents/i }))
    expect(screen.getByTestId('documents')).toBeInTheDocument()

    await act(async () => { finishIngest?.(WRITTEN) })

    expect(screen.queryByTestId('map')).not.toBeInTheDocument()
    expect(screen.getByTestId('documents')).toBeInTheDocument()
  })

  it('keeps a manifest ingest on this screen, having no one document to show', async () => {
    // A manifest is many documents at once, so there is no slug to focus and
    // nowhere to send the reader. Reported here, as it always was.
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 1210,
      self_references_skipped: 0,
      suspected_duplicates: [],
    })
    showIngestWithMap()
    await chooseAndIngest('dod_policy_references_08122026.csv')

    expect(screen.queryByTestId('map')).not.toBeInTheDocument()
    expect(await screen.findByRole('status')).toHaveTextContent(/438/)
  })
})
