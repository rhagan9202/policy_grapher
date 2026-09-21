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
const showTriage = (entry = '/triage') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
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

/** In the corpus, cited by something, never ingested — 470 of the live corpus
 *  look like this. The picker filters it out (it has no edition to compare),
 *  which is exactly why arriving at it by address needs its own sentence. */
const citedOnly: DocumentOut = {
  slug: 'dodd-1322-18',
  name: 'DoDD 1322.18',
  is_external: false,
  references: [],
  referenced_by: [],
  version_count: 0,
}

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
  pairings_unapplied: 0,
  from_obligations: 96,
  to_obligations: 115,
  outbound_implements: 0,
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
        version_id: 'org@2019-06-01',
        section_path: ['2', '2.4'],
        page: 7,
      },
      higher: {
        obligation_id: 'higher-1',
        statement: 'Components shall document the cybersecurity strategy annually.',
        document: 'DoDI 5000.88',
        version_id: 'dodi-5000-88@2020-11-18',
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

  it('names the edition each quoted clause is from', async () => {
    // Triage puts two editions of one instrument on screen at once, so the
    // document name alone matches a clause in either of them. This is
    // `ObligationCitation.version_id`'s reasoning arriving on the screen that
    // needs it most — the field was carried to the browser to be read.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/org@2019-06-01/)).toBeInTheDocument()
    expect(screen.getByText(/dodi-5000-88@2020-11-18/)).toBeInTheDocument()
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

  it('puts the previous wording beside the clause it changed from', async () => {
    // A MODIFIED row is a before/after of one clause. The previous wording was
    // rendered after both panes, so with the panes stacked it sat below the
    // *other* document's clause — the old and new text of one obligation with
    // an unrelated one between them. Whatever the layout does, it belongs with
    // the clause it is previous to.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    const previous = await screen.findByText(
      /Components shall document the cybersecurity strategy\./,
    )
    const pane = previous.closest('.pane')
    expect(pane).not.toBeNull()
    expect(pane).toHaveTextContent(/cybersecurity strategy annually/)
    expect(pane).not.toHaveTextContent(/The Program Manager shall document the strategy/)
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

  it('says which recorded pairings this diff could not apply', async () => {
    // The count reaches this screen and was rendered nowhere. A reviewer's
    // pairing verdict that the diff could not act on is not a retraction — the
    // decision stands — but a shelved verdict nobody is told about is
    // indistinguishable from one that took effect.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({ ...triage, pairings_unapplied: 2 })
    showTriage()

    await chooseAnEdition()

    expect(await screen.findByText(/2 recorded pairings/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /pairings/i })).toHaveAttribute(
      'href',
      '/pairings',
    )
  })

  it('says nothing about unapplied pairings when the diff applied them all', async () => {
    // Without this the sentence above can be rendered unconditionally and still
    // satisfy its test — a warning that fires on every diff is one a reader
    // learns to skip, which is the state it exists to prevent.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue(triage)
    showTriage()

    await chooseAnEdition()

    await screen.findByText(/document the strategy/)
    expect(screen.queryByText(/recorded pairing/i)).not.toBeInTheDocument()
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

  it('says when outbound links exist but point the other way', async () => {
    // Measured live 2026-09-15: 25 IMPLEMENTS leave DoDD 5000.01 implementing
    // 5143, Triage on 5000.01's edition pair shows 133 unlinked / 0 rows, and
    // "Approve links in Review first" is a lie — Review is clear.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({
      ...triage,
      rows: [],
      unlinked_changes: 3,
      outbound_implements: 25,
    })
    showTriage()

    await chooseAnEdition()

    expect(
      await screen.findByText(/links from these editions point the other way/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/approve links in review first/i)).not.toBeInTheDocument()
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

  it('does not report "nothing changed" when nothing was ever extracted', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({
      from_version_id: 'd@2018-01-01', to_version_id: 'd@2020-01-01',
      rows: [], total_changes: 0, unlinked_changes: 0,
      from_obligations: 0, to_obligations: 0, outbound_implements: 0,
    })
    showTriage()
    await chooseAnEdition()

    expect(await screen.findByText(/no obligations have been extracted/i)).toBeInTheDocument()
    expect(screen.queryByText(/no obligation changed/i)).not.toBeInTheDocument()
  })

  it('still reports a genuine all-clear when both editions have obligations', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    getTriage.mockResolvedValue({
      from_version_id: 'd@2018-01-01', to_version_id: 'd@2020-01-01',
      rows: [], total_changes: 0, unlinked_changes: 0,
      from_obligations: 96, to_obligations: 115, outbound_implements: 0,
    })
    showTriage()
    await chooseAnEdition()

    expect(await screen.findByText(/no obligation changed/i)).toBeInTheDocument()
  })

  it('does not send the user to Review when the baseline edition was never built', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    // The live state on 2026-08-26, which is how this was found: the 2020 edition
    // had been rebuilt and held 113 obligations; the 2018 baseline held none. Every
    // obligation in the newer edition therefore reads as an addition, so
    // total_changes is 113 rather than 0 and STORY-067's guard — which asks
    // `total_changes === 0` first — misses entirely. The screen then told the user
    // to "Approve links in Review first" when Review cannot be filled at all: a
    // proposal needs obligations on both sides, and one side has none.
    getTriage.mockResolvedValue({
      from_version_id: 'd@2018-01-01', to_version_id: 'd@2020-01-01',
      rows: [], total_changes: 113, unlinked_changes: 113,
      from_obligations: 0, to_obligations: 113, outbound_implements: 0,
    })
    showTriage()
    await chooseAnEdition()

    expect(await screen.findByText(/no obligations have been extracted/i)).toBeInTheDocument()
    expect(screen.queryByText(/approve links in review/i)).not.toBeInTheDocument()
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


// ---------------------------------------------------------------------------
// U8. Triage as the drill-down from a document on the map.
//
// Re-parented, not replaced: the map links here with the document named, and
// this screen's own honesty guarantees — `unlinked_changes`, the excluded
// oldest edition — keep working exactly as they did.
// ---------------------------------------------------------------------------

describe('Triage, entered from a document on the map', () => {
  it('arrives with the document the map named already chosen', async () => {
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    showTriage('/triage?document=dodi-5000-88')

    await waitFor(() => expect(listVersions).toHaveBeenCalledWith('dodi-5000-88'))
    expect(await screen.findByRole('combobox', { name: /document/i })).toHaveValue(
      'dodi-5000-88',
    )
  })

  it('runs no diff on arrival, however the document got here', async () => {
    // KTD7, and the reason the edition is deliberately not pre-filled: GET
    // /triage diffs inside a write transaction, so an edition chosen by the
    // URL would write derived nodes for anyone who followed a link. Choosing
    // the edition stays the reader's gesture.
    // The address carries an edition as well as a document — the parameter a
    // future hand might reasonably decide to honour. Without one present there
    // is nothing for the code to read, so the guard would pass on a URL that
    // never tested it.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue(versions)
    showTriage(
      '/triage?document=dodi-5000-88&version=dodi-5000-88@2020-11-18'
      + '&versionId=dodi-5000-88@2020-11-18&edition=dodi-5000-88@2020-11-18'
      + '&to_version_id=dodi-5000-88@2020-11-18',
    )

    await waitFor(() => expect(listVersions).toHaveBeenCalledWith('dodi-5000-88'))
    expect(getTriage).not.toHaveBeenCalled()
    expect(screen.getByRole('combobox', { name: /edition/i })).toHaveValue('')
  })

  it('does not call a document editionless while its editions are still loading', async () => {
    // "Not answered yet" and "answered, and there are none" are the same empty
    // array, and only one of them is a finding. Held apart by a null until the
    // request lands — the same distinction ADR-015 draws one level up, where an
    // empty Triage table must not read as an all-clear.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockImplementation(() => new Promise(() => {}))
    showTriage('/triage?document=dodi-5000-88')

    await waitFor(() => expect(listVersions).toHaveBeenCalledWith('dodi-5000-88'))
    expect(
      screen.queryByText(/no edition of this document has been ingested/i),
    ).not.toBeInTheDocument()
  })

  it('names the document the address sent it, when that document has no edition', async () => {
    // The state the backend really produces for a cited-only document: present
    // in the corpus, filtered out of the picker because it has no edition. An
    // earlier version of this test set version_count: 2 on the same document
    // whose editions came back empty — a pair of numbers the graph cannot
    // produce together, certifying the branch from a state that cannot happen.
    listDocuments.mockResolvedValue([...documents, citedOnly])
    listVersions.mockResolvedValue([])
    showTriage('/triage?document=dodd-1322-18')

    const said = await screen.findByText(
      (_, el) =>
        el?.tagName === 'STRONG' &&
        /no edition of dodd-1322-18 has been ingested/i.test(el.textContent ?? ''),
    )
    expect(said).toBeInTheDocument()
  })

  it('does not diagnose a document the corpus has never heard of', async () => {
    // `GET /documents/{slug}/versions` does not check the slug exists — it
    // answers 200 and an empty list for a name nothing answers to, the same
    // shape a real editionless document gives. Saying "no edition has been
    // ingested" about an address that names nothing is a confident answer
    // about something that is not there.
    listDocuments.mockResolvedValue(documents)
    listVersions.mockResolvedValue([])
    showTriage('/triage?document=not-a-real-document')

    const said = await screen.findByText(
      (_, el) =>
        el?.tagName === 'STRONG' &&
        /nothing in the corpus answers to not-a-real-document/i.test(el.textContent ?? ''),
    )
    expect(said).toBeInTheDocument()
    // And never the sentence that would assert the document exists.
    expect(screen.queryByText(/has been ingested/i)).not.toBeInTheDocument()
  })
})
