import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PairingCandidate, PairingQueue, PairingSettled } from '../api/types'

const getPairingQueue = vi.fn()
const recordPairing = vi.fn()
const listDocuments = vi.fn()
const listVersions = vi.fn()
vi.mock('../api/client', () => ({
  getPairingQueue: (...args: unknown[]) => getPairingQueue(...args),
  recordPairing: (...args: unknown[]) => recordPairing(...args),
  listDocuments: () => listDocuments(),
  listVersions: (slug: string) => listVersions(slug),
  ApiError: class extends Error {},
}))

import Pairings from './Pairings'

const OLDER = 'dodd-5000-01@2018-08-31'
const MIDDLE = 'dodd-5000-01@2020-01-15'
const NEWER = 'dodd-5000-01@2022-07-28'

/** A promise this test resolves by hand, to hold one request open while another
 *  overtakes it. Two queue requests in flight is the ordinary case on this
 *  screen — the GET runs a whole diff — so the order they answer in cannot be
 *  left to chance in the test either. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((settle) => {
    resolve = settle
  })
  return { promise, resolve }
}

const documents = [
  {
    slug: 'dodd-5000-01',
    name: 'DoDD 5000.01',
    is_external: false,
    references: [],
    referenced_by: [],
    version_count: 3,
  },
]

const versions = [
  {
    version_id: OLDER,
    effective_date: '2018-08-31',
    checksum: '65e873',
    source_uri: 'file:///data/samples/500001p_2018.pdf',
    supersedes: null,
  },
  {
    version_id: MIDDLE,
    effective_date: '2020-01-15',
    checksum: '31cd08',
    source_uri: 'file:///data/samples/500001p_2020.pdf',
    supersedes: OLDER,
  },
  {
    version_id: NEWER,
    effective_date: '2022-07-28',
    checksum: 'a16e39',
    source_uri: 'file:///data/samples/500001p_2022.pdf',
    supersedes: OLDER,
  },
]

const candidate: PairingCandidate = {
  old: {
    obligation_id: 'old-1',
    statement: 'The Director shall notify the Comptroller within 24 hours.',
    modality: 'SHALL',
    document: 'DoDD 5000.01',
    version_id: OLDER,
    section_path: ['3', '3.2'],
    page: 7,
  },
  new: {
    obligation_id: 'new-1',
    statement: 'The Director will inform the Comptroller within one day.',
    modality: 'WILL',
    document: 'DoDD 5000.01',
    version_id: NEWER,
    section_path: ['4', '4.1'],
    page: 9,
  },
  confidence: 0.62,
  // As the measure really writes them: a lowercase fragment restating the same
  // percentage. Capitalised prose whose number happened to differ from the
  // confidence was the one arrangement in which concatenating the two read well.
  rationale: "they share 62% of the shorter clause's distinctive wording (comptroller, director, notify).",
  outcome: 'below_threshold',
  taken_by: [],
}

const takenCandidate: PairingCandidate = {
  ...candidate,
  old: { ...candidate.old, obligation_id: 'old-2', statement: 'Components shall retain records.' },
  new: { ...candidate.new, obligation_id: 'new-2', statement: 'Components will keep records.' },
  confidence: 0.81,
  // Its own sentence, not the spread one: two candidates quoting the same
  // percentage would make every "which pair is this?" assertion ambiguous, and a
  // query that matches two elements fails for a reason unrelated to the screen.
  rationale: "they share 81% of the shorter clause's distinctive wording (components, records, retain).",
  outcome: 'partner_taken',
  // `new-9` is deliberately not an obligation on this page. `taken_by` carries
  // obligation ids and a candidate row holds no index from an id to a clause, so
  // the id is printed as it came.
  taken_by: ['new-9'],
}

// Citations, not ids: `PairingSettledOut` carries both clauses because a settled
// pair is never also a candidate, so there is no row in `items` to borrow the
// statements from — and `items` is empty in exactly the case this list is full.
const settledPair: PairingSettled = {
  old: {
    obligation_id: 'old-7',
    statement: 'The Component shall publish an annual inventory.',
    modality: 'SHALL',
    document: 'DoDD 5000.01',
    version_id: OLDER,
    section_path: ['5'],
    page: 11,
  },
  new: {
    obligation_id: 'new-7',
    statement: 'The Component will maintain a current inventory.',
    modality: 'WILL',
    document: 'DoDD 5000.01',
    version_id: NEWER,
    section_path: ['6'],
    page: 13,
  },
  verdict: 'distinct',
  actor: 'tester',
  rationale: 'One is an inventory, the other a publication duty.',
}

// A second settled row, and its verdict is the other word on purpose: with one
// fixture reading `distinct`, printing a constant `distinct` satisfies every
// assertion about it — and a reviewer who cannot see which verdict is on record
// cannot know what they are undoing.
const settledPaired: PairingSettled = {
  old: {
    ...settledPair.old,
    obligation_id: 'old-8',
    statement: 'Heads of components shall appoint a records officer.',
  },
  new: {
    ...settledPair.new,
    obligation_id: 'new-8',
    statement: 'Each component head will designate a records officer.',
  },
  verdict: 'paired',
  actor: 'auditor',
  rationale: '',
}

// Verbatim from `routers/pairings.py`. The refusal names its own remedy, and
// that sentence is the only instruction the reviewer gets — a generic "could not
// load" in its place leaves them with a screen that refuses and does not say
// what to do.
const REVERSED_DETAIL =
  `'${NEWER}' does not precede '${OLDER}' by the corpus ordering (effective `
  + "date, then ingest time, then version id). The queue's question is "
  + 'one-directional — is the newer clause the older one reworded? — so a '
  + 'reversed pair would be answered upside down and its candidate edges written '
  + 'backwards. Swap from and to: from_version_id must name the older edition.'

const CONFLICT_DETAIL =
  'A live paired verdict already links old-1 → new-9 within this edition '
  + 'pair, and the diff is one-to-one: two live paired verdicts on one clause '
  + 'would leave the loser chosen by iteration order. Mark that pairing distinct '
  + 'first, then re-record this one.'

const q = (over: Partial<PairingQueue> = {}): PairingQueue => ({
  items: [candidate],
  settled: [],
  pairings_unapplied: 0,
  pending: 1,
  // The backlog by label, as the route counts it: over the graph, never over the
  // page. Overridden wherever a test's items say something different.
  pending_by_outcome: { below_threshold: 1 },
  ...over,
})

// A pairing queue is asked between two named editions, so every test has to get
// through the picker before it can assert anything about the queue.
async function choosePair() {
  render(
    <MemoryRouter>
      <Pairings />
    </MemoryRouter>,
  )
  await userEvent.selectOptions(await screen.findByLabelText(/document/i), 'dodd-5000-01')
  // Waiting on the options rather than on the `listVersions` call: the two edition
  // selects render empty and disabled the moment the document picker does, and
  // selecting a value that is not in the list yet is a failure about timing rather
  // than about the screen. `findAll`, because both selects carry the same option.
  await screen.findAllByRole('option', { name: /2018-08-31/ })
  await userEvent.selectOptions(screen.getByLabelText(/older edition/i), OLDER)
  await userEvent.selectOptions(screen.getByLabelText(/newer edition/i), NEWER)
}

beforeEach(() => {
  listDocuments.mockResolvedValue(documents)
  listVersions.mockResolvedValue(versions)
})

afterEach(() => {
  getPairingQueue.mockReset()
  recordPairing.mockReset()
  listDocuments.mockReset()
  listVersions.mockReset()
})

describe('Pairings', () => {
  it('asks the queue for the pair the reviewer chose', async () => {
    getPairingQueue.mockResolvedValue(q())
    await choosePair()

    await waitFor(() =>
      // '' is every outcome: the screen asks for the whole page until a reviewer
      // narrows it, and the client drops a falsy outcome from the query string.
      expect(getPairingQueue).toHaveBeenCalledWith(OLDER, NEWER, { outcome: '' }),
    )
  })

  it('shows both clauses, the confidence, the rationale and which rule declined them', async () => {
    // The whole content of the judgement. A reviewer overruling the measure needs
    // to read both statements — the edition ids tell them apart, because a
    // pairing question always prints the same document name twice — and to know
    // which of the diff's four refusals this was.
    getPairingQueue.mockResolvedValue(q({ items: [candidate, takenCandidate], pending: 2 }))
    await choosePair()

    expect(await screen.findByText(candidate.old.statement)).toBeInTheDocument()
    expect(screen.getByText(candidate.new.statement)).toBeInTheDocument()
    // Two elements, deliberately: a real rationale repeats the percentage, so a
    // bare /62%/ would match both the confidence line and the rationale.
    expect(screen.getByText('62% confidence.')).toBeInTheDocument()
    expect(screen.getByText(/share 62% of the shorter clause/)).toBeInTheDocument()
    expect(screen.getAllByText(OLDER).length).toBeGreaterThan(0)
    expect(screen.getAllByText(NEWER).length).toBeGreaterThan(0)
    // Grouped by outcome, and `partner_taken` names the winner: an `auto_paired`
    // pair already holds one of these clauses, and that is the pairing the
    // reviewer has to mark distinct first.
    expect(screen.getByRole('heading', { name: /took one of these clauses/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /below the pairing bar/i })).toBeInTheDocument()
  })

  it('names the clause that took this one by id, with the row still whole', async () => {
    // `taken_by` carries obligation ids, and this row holds no index from an id to
    // a clause. The id is printed as the id; a screen that looked it up among the
    // rows it happens to hold would print nothing the moment the winner was on
    // another page, and this is the one row where the instruction lives.
    getPairingQueue.mockResolvedValue(q({ items: [takenCandidate], pending: 1 }))
    await choosePair()

    expect(await screen.findByText(/new-9/)).toBeInTheDocument()
    expect(screen.getByText(takenCandidate.old.statement)).toBeInTheDocument()
    expect(screen.getByText(takenCandidate.new.statement)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^paired$/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /^distinct$/i })).toBeEnabled()
  })

  it('lists the pairs already settled, with both clauses, the verdict and who recorded it', async () => {
    // A settled pair is never re-recorded as a candidate, so this list is the
    // only route back to a verdict somebody wants to reverse — and reversing one
    // is answering the question that was answered when it was made, which needs
    // the same two clauses in front of the reader.
    getPairingQueue.mockResolvedValue(
      q({ items: [], settled: [settledPair, settledPaired], pending: 0 }),
    )
    await choosePair()

    const settled = await screen.findByRole('list', { name: /settled pairs/i })
    expect(within(settled).getByText('old-7')).toBeInTheDocument()
    expect(within(settled).getByText('new-7')).toBeInTheDocument()
    expect(within(settled).getByText(settledPair.old.statement)).toBeInTheDocument()
    expect(within(settled).getByText(settledPair.new.statement)).toBeInTheDocument()
    // Both verdict words, from two rows: the value has to be read off the row
    // rather than assumed, or a reviewer cannot tell what they are undoing.
    // Exact strings, because "Mark distinct" is a button in this same list and a
    // /distinct/ regex would match both it and the recorded verdict.
    expect(within(settled).getByText('distinct')).toBeInTheDocument()
    expect(within(settled).getByText('paired')).toBeInTheDocument()
    expect(within(settled).getByText(/recorded by tester/i)).toBeInTheDocument()
    expect(within(settled).getByText(/recorded by auditor/i)).toBeInTheDocument()
  })

  it('shows the reason already recorded and re-posts it when nobody edits it', async () => {
    // Re-recording a verdict overwrites `rationale`. A box that starts empty
    // therefore erases the justification of the verdict being reversed, and the
    // reviewer never saw what they erased.
    getPairingQueue.mockResolvedValue(
      q({ items: [], settled: [settledPair], pending: 0 }),
    )
    recordPairing.mockResolvedValue({
      old_id: 'old-7', new_id: 'new-7', verdict: 'paired', actor: 'tester',
    })
    await choosePair()
    const settled = await screen.findByRole('list', { name: /settled pairs/i })

    expect(screen.getByLabelText(/reason/i)).toHaveValue(settledPair.rationale)

    await userEvent.click(within(settled).getByRole('button', { name: /mark paired/i }))

    expect(recordPairing).toHaveBeenCalledWith(
      'old-7',
      'new-7',
      'paired',
      settledPair.rationale,
    )
  })

  it('takes a settled verdict back to the other answer', async () => {
    // Without this the screen makes every verdict irreversible: one click and the
    // pair leaves `items` for good, a `distinct` skipped before scoring and a
    // `paired` consumed by the planner.
    getPairingQueue.mockResolvedValue(
      q({ items: [], settled: [settledPair], pending: 0 }),
    )
    recordPairing.mockResolvedValue({
      old_id: 'old-7', new_id: 'new-7', verdict: 'paired', actor: 'tester',
    })
    await choosePair()
    const settled = await screen.findByRole('list', { name: /settled pairs/i })

    // Cleared first: the box carries the reason on record, and a reversal with a
    // new reason replaces it rather than appending to it.
    await userEvent.clear(screen.getByLabelText(/reason/i))
    await userEvent.type(screen.getByLabelText(/reason/i), 'Same duty after all.')
    await userEvent.click(within(settled).getByRole('button', { name: /mark paired/i }))

    expect(recordPairing).toHaveBeenCalledWith(
      'old-7',
      'new-7',
      'paired',
      'Same duty after all.',
    )
  })

  it('lets a reviewer clear the recorded reason on purpose', async () => {
    // The prefill must not become a floor. Emptying the box is a reviewer saying
    // the old reason no longer applies, and '' has to reach the recorder as ''.
    // A logical-or instead of the nullish coalescing reads an emptied box as
    // "nothing typed" and silently re-posts the reason they just deleted.
    getPairingQueue.mockResolvedValue(
      q({ items: [], settled: [settledPair], pending: 0 }),
    )
    recordPairing.mockResolvedValue({
      old_id: 'old-7', new_id: 'new-7', verdict: 'distinct', actor: 'tester',
    })
    await choosePair()
    const settled = await screen.findByRole('list', { name: /settled pairs/i })

    await userEvent.clear(screen.getByLabelText(/reason/i))
    await userEvent.click(
      within(settled).getByRole('button', { name: /mark distinct/i }),
    )

    expect(recordPairing).toHaveBeenCalledWith('old-7', 'new-7', 'distinct', '')
  })

  it('records a paired verdict older-first and reloads the queue', async () => {
    // The reload returns the pair as settled, which is what the route really
    // does: the verdict moves it out of `items` and into `settled`, never out of
    // the response. A fixture that reloaded to an empty screen would assert the
    // pair vanishing — the defect the settled list exists to prevent — as the
    // success state.
    const nowSettled: PairingSettled = {
      old: candidate.old,
      new: candidate.new,
      verdict: 'paired',
      actor: 'tester',
      rationale: 'Same duty, reworded.',
    }
    getPairingQueue
      .mockResolvedValueOnce(q())
      .mockResolvedValue(q({ items: [], settled: [nowSettled], pending: 0 }))
    recordPairing.mockResolvedValue({
      old_id: 'old-1', new_id: 'new-1', verdict: 'paired', actor: 'tester',
    })
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.type(screen.getByLabelText(/reason/i), 'Same duty, reworded.')
    await userEvent.click(screen.getByRole('button', { name: /^paired$/i }))

    expect(recordPairing).toHaveBeenCalledWith(
      'old-1',
      'new-1',
      'paired',
      'Same duty, reworded.',
    )
    // Reloaded, not merely posted: the verdict changes what the diff produces, so
    // a screen that kept showing the pre-verdict queue would be showing a
    // question that has been answered.
    expect(await screen.findByText(/nothing is waiting to be paired/i)).toBeInTheDocument()
    // And the pair is still reachable, now as a settled row.
    const settled = screen.getByRole('list', { name: /settled pairs/i })
    expect(within(settled).getByText(candidate.old.statement)).toBeInTheDocument()
    expect(within(settled).getByText('paired')).toBeInTheDocument()
  })

  it('shows the candidates and the settled pairs at once', async () => {
    // The journey neither single-list test walks: mid-queue, some pairs settled
    // and some still waiting. The settled ones must not be mixed into the
    // candidates — they are answered — and must not push the unanswered ones off.
    getPairingQueue.mockResolvedValue(
      q({ items: [candidate], settled: [settledPair], pending: 1 }),
    )
    await choosePair()

    await screen.findByText(candidate.old.statement)
    const settled = screen.getByRole('list', { name: /settled pairs/i })
    expect(within(settled).getByText(settledPair.old.statement)).toBeInTheDocument()
    expect(
      within(settled).queryByText(candidate.old.statement),
    ).not.toBeInTheDocument()
    // The candidate keeps its own verdict buttons, which the settled row's
    // "Mark paired" must not be mistaken for.
    expect(screen.getByRole('button', { name: /^paired$/i })).toBeEnabled()
  })

  it('records a distinct verdict on the same pair', async () => {
    getPairingQueue.mockResolvedValue(q())
    recordPairing.mockResolvedValue({
      old_id: 'old-1', new_id: 'new-1', verdict: 'distinct', actor: 'tester',
    })
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.click(screen.getByRole('button', { name: /^distinct$/i }))

    expect(recordPairing).toHaveBeenCalledWith('old-1', 'new-1', 'distinct', '')
  })

  it('surfaces the reversed-pair 400 in full instead of showing an empty queue', async () => {
    // The route refuses a from/to that is not older→newer, and an unreported
    // refusal reads as "nothing to pair between these editions" — a false
    // all-clear over a question that was never asked. The whole detail, not a
    // paraphrase: it ends in the instruction that fixes it.
    getPairingQueue.mockRejectedValue(new Error(REVERSED_DETAIL))
    await choosePair()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not load the pairing queue/i)
    expect(alert).toHaveTextContent(REVERSED_DETAIL)
    expect(screen.queryByText(/nothing is waiting to be paired/i)).not.toBeInTheDocument()
  })

  it('does not report a queue that failed to load as a verdict that failed to record', async () => {
    // Review shipped one shared error state and told readers their decision had
    // not been saved about a decision they had not made.
    getPairingQueue.mockRejectedValue(new Error('backend down'))
    await choosePair()

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i)
    expect(screen.queryByText(/could not record that/i)).not.toBeInTheDocument()
  })

  it('surfaces a failure to record a verdict in full rather than looking successful', async () => {
    // The 409 names the pairing to mark distinct first. That sentence is the
    // remedy, and replacing it with "failed to record" leaves the reviewer
    // clicking the same button again.
    getPairingQueue.mockResolvedValue(q())
    recordPairing.mockRejectedValue(new Error(CONFLICT_DETAIL))
    await choosePair()
    await screen.findByText(candidate.old.statement)

    await userEvent.click(screen.getByRole('button', { name: /^paired$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(CONFLICT_DETAIL)
  })

  it('says a recorded pairing could not be applied rather than losing it', async () => {
    getPairingQueue.mockResolvedValue(q({ items: [], pending: 0, pairings_unapplied: 1 }))
    await choosePair()

    expect(await screen.findByText(/1 recorded pairing/i)).toBeInTheDocument()
  })

  it('says nothing about unapplied pairings when the diff applied them all', async () => {
    // Without this the sentence above can be rendered unconditionally and still
    // satisfy its test, so every load would read "0 recorded pairings could not
    // be applied" — a warning present on every screen is one nobody reads, which
    // is the state reporting the count exists to escape.
    getPairingQueue.mockResolvedValue(q())
    await choosePair()

    await screen.findByText(candidate.old.statement)
    expect(screen.queryByText(/recorded pairing/i)).not.toBeInTheDocument()
  })

  it('ignores a queue that arrives after the reviewer changed edition', async () => {
    // This GET runs the diff, so it is slow by construction and two requests are
    // routinely in flight. Answered in the order they were asked, the first
    // reply lands last and draws the previous pair's candidates under the
    // current pair's label — and a verdict recorded from one of those rows
    // settles a pair the reviewer never chose to look at.
    const stale = deferred<PairingQueue>()
    const current = deferred<PairingQueue>()
    getPairingQueue.mockImplementation((_from: string, to: string) =>
      to === NEWER ? stale.promise : current.promise,
    )
    await choosePair()
    await userEvent.selectOptions(screen.getByLabelText(/newer edition/i), MIDDLE)

    current.resolve(q({ items: [takenCandidate], pending: 1 }))
    await screen.findByText(takenCandidate.old.statement)

    await act(async () => {
      stale.resolve(q({ items: [candidate], pending: 1 }))
    })

    expect(screen.getByText(takenCandidate.old.statement)).toBeInTheDocument()
    expect(screen.queryByText(candidate.old.statement)).not.toBeInTheDocument()
  })

  it('reaches a decline the page is too small to hold', async () => {
    // The defect this control exists for. Every pair at or above the bar is
    // recorded, the page is ordered by confidence and capped, and a declined pair
    // never outscores the pairing that beat it — so a page full of `auto_paired`
    // rows is what a reviewer meets, and the pairs they came to settle are the
    // ones the cap cut. Measured live: 61 candidates between one edition pair
    // returned 50 rows, every one `auto_paired`, with the single decline
    // reachable only past the page.
    //
    // The counts are what make the filter usable: they are the backlog's, so the
    // screen can say a decline exists while showing none.
    const paired: PairingCandidate = {
      ...takenCandidate,
      outcome: 'auto_paired',
      confidence: 0.93,
      taken_by: [],
    }
    getPairingQueue.mockImplementation(
      (_from: string, _to: string, options: { outcome?: string }) =>
        Promise.resolve(
          options.outcome === 'below_threshold'
            ? q({
                items: [candidate],
                pending: 2,
                pending_by_outcome: { auto_paired: 1, below_threshold: 1 },
              })
            : q({
                items: [paired],
                pending: 2,
                pending_by_outcome: { auto_paired: 1, below_threshold: 1 },
              }),
        ),
    )
    await choosePair()

    // What the unfiltered page shows: the pairing the diff made, and no sign of
    // the pair it could not.
    expect(await screen.findByText(paired.old.statement)).toBeInTheDocument()
    expect(screen.queryByText(candidate.old.statement)).not.toBeInTheDocument()
    // But the count says a decline is there to ask for.
    expect(
      screen.getByRole('option', { name: /below the pairing bar \(1\)/i }),
    ).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText(/outcome/i), 'below_threshold')

    expect(await screen.findByText(candidate.old.statement)).toBeInTheDocument()
    expect(screen.queryByText(paired.old.statement)).not.toBeInTheDocument()
    expect(getPairingQueue).toHaveBeenLastCalledWith(OLDER, NEWER, {
      outcome: 'below_threshold',
    })
  })

  it('says a filtered page is empty without claiming the queue is', async () => {
    // "Nothing is waiting to be paired between these two editions" is a
    // different claim from "nothing here is below the bar", and printing the
    // first under a filter is the false all-clear ADR-019 forbids — with 40
    // contested pairs still waiting one select away.
    getPairingQueue.mockResolvedValue(
      q({
        items: [],
        pending: 40,
        pending_by_outcome: { contested: 40 },
      }),
    )
    await choosePair()
    await screen.findByLabelText(/outcome/i)

    await userEvent.selectOptions(screen.getByLabelText(/outcome/i), 'contested')

    expect(
      await screen.findByText(/no candidate between these two editions is labelled/i),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/nothing is waiting to be paired/i),
    ).not.toBeInTheDocument()
  })

  it('reports a corpus it could not list as that, not as a queue that failed', async () => {
    // Two failures, two claims. Reporting "could not load the pairing queue"
    // beside an empty document picker describes a request the reviewer has not
    // made yet — the same mislabelling the two queue states exist to avoid.
    listDocuments.mockRejectedValue(new Error('Failed to fetch'))
    render(
      <MemoryRouter>
        <Pairings />
      </MemoryRouter>,
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/could not load the documents/i)
    expect(alert).toHaveTextContent(/failed to fetch/i)
    expect(screen.queryByText(/pairing queue/i)).not.toBeInTheDocument()
  })

  it('says a corpus with no two-edition document cannot be paired yet', async () => {
    // The blank-that-reads-as-broken ADR-019 forbids: a picker with nothing in it
    // and no sentence saying why.
    listDocuments.mockResolvedValue([{ ...documents[0], version_count: 1 }])
    render(
      <MemoryRouter>
        <Pairings />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('status')).toHaveTextContent(/no document has two editions/i)
    expect(getPairingQueue).not.toHaveBeenCalled()
  })
})
