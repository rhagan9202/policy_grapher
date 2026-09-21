import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

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

  it('reports the document a PDF ingest produced, not just counts', async () => {
    // The two results are different shapes. A view that renders only the manifest
    // fields would show a PDF ingest as a row of blanks.
    ingest.mockResolvedValue({
      source: 'document',
      outcome: 'written',
      format: 'modern',
      document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
      nodes_created: 1,
      relationships_created: 2,
      references_attributed: 16,
      references_unattributed: ['Summary of the 2018 National Defense Strategy'],
      self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09',
      chunks_written: 34,
    })
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent(/DoDD 5000\.01/)
    expect(result).toHaveTextContent(/16/)
  })

  it('reports an unchanged re-add as its own outcome, not as an empty write', async () => {
    // ADR-042. Re-adding a file the corpus already holds discards nothing, so
    // there is no write to report — and reporting one with a chunk count of
    // nothing would read as a write that produced nothing. What the reader
    // needs to know is the opposite: everything built on this edition survived.
    ingest.mockResolvedValue({
      source: 'document',
      outcome: 'unchanged',
      format: 'modern',
      document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
      nodes_created: 0,
      relationships_created: 0,
      references_attributed: 16,
      references_unattributed: [],
      self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09',
      chunks_written: null,
    })
    showIngest()

    await userEvent.selectOptions(
      await screen.findByLabelText(/file to ingest/i), '500001p_2020.pdf',
    )
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent(/already present/i)
    expect(result).toHaveTextContent(/no text was rewritten/i)
    // Not "null chunks", and not a chunk count of any kind: there was no write.
    expect(result).not.toHaveTextContent(/null/i)
    expect(result).not.toHaveTextContent(/chunks of text/i)
    // Nothing was created either, so nothing to report.
    expect(result).not.toHaveTextContent(/nodes created/i)
  })

  it('still reports what a skipped re-add did create, rather than denying it', async () => {
    // The skip covers the text and the layer derived from it. The document
    // record and its reference edges refresh on every ingest, so a parse that
    // newly reads a references section creates the documents it names even on
    // this path — and a flat "nothing was written" over that is false in the
    // other direction.
    ingest.mockResolvedValue({
      source: 'document',
      outcome: 'unchanged',
      format: 'modern',
      document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
      nodes_created: 1,
      relationships_created: 1,
      references_attributed: 17,
      references_unattributed: [],
      self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09',
      chunks_written: null,
    })
    showIngest()

    await userEvent.selectOptions(
      await screen.findByLabelText(/file to ingest/i), '500001p_2020.pdf',
    )
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent(/no text was rewritten/i)
    expect(result).toHaveTextContent(/1 nodes created/i)
    expect(result).toHaveTextContent(/1 relationships created/i)
    // And still no chunk count: that is the part that genuinely did not happen.
    expect(result).not.toHaveTextContent(/chunks of text/i)
  })

  it('names the references it could not attribute, rather than only counting them', async () => {
    // An unattributed reference is a citation the graph does not hold. A count alone
    // tells the reader something is missing and not what.
    ingest.mockResolvedValue({
      source: 'document',
      outcome: 'written',
      format: 'modern',
      document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
      nodes_created: 1,
      relationships_created: 2,
      references_attributed: 16,
      references_unattributed: ['Summary of the 2018 National Defense Strategy'],
      self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09',
      chunks_written: 34,
    })
    showIngest()

    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByText(/Summary of the 2018 National Defense Strategy/)).toBeInTheDocument()
  })

  it('names the edition it recorded and how much text it read', async () => {
    const documentResult = {
      source: 'document',
      outcome: 'written',
      format: 'modern',
      document: { slug: 'dodd-5000-01', name: 'DoDD 5000.01' },
      nodes_created: 1,
      relationships_created: 2,
      references_attributed: 16,
      references_unattributed: [],
      self_references_skipped: 0,
      version_id: 'dodd-5000-01@2020-09-09',
      chunks_written: 34,
    }
    ingest.mockResolvedValue(documentResult)
    showIngest()
    await userEvent.selectOptions(await screen.findByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /^ingest$/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/dodd-5000-01@2020-09-09/)
    expect(status).toHaveTextContent(/34 chunks/i)
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
