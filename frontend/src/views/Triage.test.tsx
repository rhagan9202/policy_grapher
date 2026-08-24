import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut, DocumentVersionOut, TriageOut } from '../api/types'

const listDocuments = vi.fn()
const listVersions = vi.fn()
const getTriage = vi.fn()
vi.mock('../api/client', () => ({
  listDocuments: () => listDocuments(),
  listVersions: (slug: string) => listVersions(slug),
  getTriage: (to: string, from?: string) => getTriage(to, from),
  ApiError: class extends Error {},
}))

import Triage from './Triage'

// EmptyState links to the Ingest screen, so any view that can render it
// needs router context.
const showTriage = () =>
  render(
    <MemoryRouter>
      <Triage />
    </MemoryRouter>,
  )

const documents: DocumentOut[] = [
  {
    slug: 'dodi-5000-88',
    name: 'DoDI 5000.88',
    is_external: false,
    references: [],
    referenced_by: [],
    version_count: 2,
  },
]

const versions: DocumentVersionOut[] = [
  {
    version_id: 'dodi-5000-88@2019-01-01',
    effective_date: '2019-01-01',
    checksum: 'a',
    source_uri: 'file:///a.pdf',
    supersedes: null,
  },
  {
    version_id: 'dodi-5000-88@2020-11-18',
    effective_date: '2020-11-18',
    checksum: 'b',
    source_uri: 'file:///b.pdf',
    supersedes: 'dodi-5000-88@2019-01-01',
  },
]

const triage: TriageOut = {
  from_version_id: 'dodi-5000-88@2019-01-01',
  to_version_id: 'dodi-5000-88@2020-11-18',
  total_changes: 3,
  unlinked_changes: 2,
  rows: [
    {
      change_id: 'c1',
      kind: 'MODIFIED',
      score: 8,
      modality: 'SHALL',
      summary: 'The obligation in section 3.2 was reworded.',
      previous_statement: 'Components shall document the cybersecurity strategy.',
      ours: {
        obligation_id: 'ours-1',
        statement: 'The Program Manager shall document the strategy.',
        document: 'ORG 1.0',
        section_path: ['2', '2.4'],
        page: 7,
      },
      higher: {
        obligation_id: 'higher-1',
        statement: 'Components shall document the cybersecurity strategy annually.',
        document: 'DoDI 5000.88',
        section_path: ['3', '3.2'],
        page: 12,
      },
    },
  ],
}

async function chooseAnEdition() {
  await userEvent.selectOptions(
    await screen.findByLabelText(/document/i),
    'dodi-5000-88',
  )
  await waitFor(() => expect(listVersions).toHaveBeenCalledWith('dodi-5000-88'))
  await userEvent.selectOptions(
    await screen.findByLabelText(/edition/i),
    'dodi-5000-88@2020-11-18',
  )
}

afterEach(() => {
  listDocuments.mockReset()
  listVersions.mockReset()
  getTriage.mockReset()
})

describe('Triage', () => {
  it('shows a ranked row with both citations', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/document the strategy/)).toBeInTheDocument()
    expect(screen.getByText(/document the cybersecurity strategy annually/)).toBeInTheDocument()
    expect(screen.getByText(/ORG 1\.0/)).toBeInTheDocument()
    expect(screen.getByText(/2\/2\.4/)).toBeInTheDocument()
    expect(screen.getByText(/p\.\s*7/)).toBeInTheDocument()
    expect(screen.getByText(/3\/3\.2/)).toBeInTheDocument()
    expect(screen.getByText(/p\.\s*12/)).toBeInTheDocument()
    expect(screen.getByText('MODIFIED')).toBeInTheDocument()
  })

  it('shows what the clause used to say, so the change is visible', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(
      await screen.findByText(/Components shall document the cybersecurity strategy\./),
    ).toBeInTheDocument()
  })

  it('shows the unlinked count rather than hiding it', async () => {
    // ADR-015: an empty triage with unlinked changes means "nothing reviewed
    // yet", not "nothing affected", and only this number tells them apart.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/2 of 3/)).toBeInTheDocument()
    expect(screen.getByText(/no reviewed link/i)).toBeInTheDocument()
  })

  it('reads an empty result as nothing linked yet, never as nothing affected', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({ ...triage, rows: [], unlinked_changes: 3 })
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/nothing has been linked/i)).toBeInTheDocument()
    // The all-clear message belongs to the no-changes case alone. Showing it
    // here would turn "nothing reviewed yet" into a false finding of safety.
    expect(screen.queryByText(/no obligation changed/i)).not.toBeInTheDocument()
    expect(screen.getByText(/approve links in review/i)).toBeInTheDocument()
  })

  it('says nothing changed when the editions agree', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({
      ...triage,
      rows: [],
      total_changes: 0,
      unlinked_changes: 0,
    })
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/no obligation changed/i)).toBeInTheDocument()
  })

  it('names which earlier edition it compared against', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/dodi-5000-88@2019-01-01/)).toBeInTheDocument()
  })

  it('surfaces a failure', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockRejectedValue(new Error('supersedes no earlier edition'))
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByRole('alert')).toHaveTextContent(/supersedes no earlier/i)
  })
})

describe('Triage when nothing has been ingested', () => {
  it('says the corpus is empty rather than offering an empty picker', async () => {
    listDocuments.mockResolvedValue([])
    showTriage()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
    expect(screen.queryByLabelText(/document/i)).not.toBeInTheDocument()
  })
})

describe('Triage document picker', () => {
  it('offers only documents that have editions to compare', async () => {
    // STORY-040: 439 of 440 documents on the sample corpus have no edition, so
    // choosing one leads to an empty list and no explanation.
    listDocuments.mockResolvedValue([
      ...documents,
      {
        slug: 'public-law-116-92',
        name: 'Public Law 116-92',
        is_external: true,
        references: [],
        referenced_by: [],
        version_count: 0,
      },
    ])
    listVersions.mockResolvedValue(versions)
    showTriage()

    const picker = await screen.findByLabelText(/document/i)
    const options = within(picker).getAllByRole('option').map((o) => o.textContent)
    expect(options).toContain('DoDI 5000.88')
    expect(options).not.toContain('Public Law 116-92')
  })

  it('does not offer the oldest edition, which can never be compared', async () => {
    // STORY-040: it supersedes nothing, so /triage answers 400 every time.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    showTriage()

    await userEvent.selectOptions(await screen.findByLabelText(/document/i), 'dodi-5000-88')
    const editions = await screen.findByLabelText(/edition/i)
    const options = within(editions).getAllByRole('option').map((o) => o.textContent)

    expect(options).toContain('2020-11-18')
    expect(options).not.toContain('2019-01-01')
  })

  it('says so when a document has no edition that can be compared', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue([versions[0]])
    showTriage()

    await userEvent.selectOptions(await screen.findByLabelText(/document/i), 'dodi-5000-88')

    expect(await screen.findByText(/only one edition/i)).toBeInTheDocument()
  })
})

describe('Triage when the corpus has no editions', () => {
  it('explains that no document has an edition, rather than showing an empty picker', async () => {
    // Found on the sprint-3 cold-start walkthrough: ingesting the sample CSV
    // gives 438 documents and zero editions, because a manifest records no text
    // (ADR-011). The picker then renders with no options and no explanation —
    // the STORY-040 dead end in a second guise.
    listDocuments.mockResolvedValue(
      documents.map((d) => ({ ...d, version_count: 0 })),
    )
    showTriage()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no document has an ingested edition/i,
    )
    expect(screen.queryByLabelText(/document/i)).not.toBeInTheDocument()
  })
})
