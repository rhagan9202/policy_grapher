import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReviewItem } from '../api/types'

const getReviewQueue = vi.fn()
const recordVerdict = vi.fn()
const listDocuments = vi.fn()
vi.mock('../api/client', () => ({
  getReviewQueue: () => getReviewQueue(),
  listDocuments: () => listDocuments(),
  recordVerdict: (...args: unknown[]) => recordVerdict(...args),
  ApiError: class extends Error {},
}))

import Review from './Review'

// EmptyState links to the Ingest screen, so any view that can render it
// needs router context.
const showReview = () =>
  render(
    <MemoryRouter>
      <Review />
    </MemoryRouter>,
  )

const item: ReviewItem = {
  source: {
    obligation_id: 'ours-1',
    statement: 'The Program Manager shall document the cybersecurity strategy.',
    modality: 'SHALL',
    document: 'ORG 1.0',
    section_path: ['2', '2.4'],
    page: 7,
  },
  target: {
    obligation_id: 'higher-1',
    statement: 'Components shall document the cybersecurity strategy.',
    modality: 'SHALL',
    document: 'DoDI 5000.88',
    section_path: ['3', '3.2'],
    page: 12,
  },
  confidence: 0.72,
  rationale: 'Both cite DoDI 5000.88; they share 60% of the shorter clause.',
  proposer: 'lexical-v1',
}

afterEach(() => {
  getReviewQueue.mockReset()
  recordVerdict.mockReset()
  listDocuments.mockReset()
})

// Every test below has a corpus unless it says otherwise.
beforeEach(() => listDocuments.mockResolvedValue([{ slug: 'd', name: 'D' }]))

describe('Review', () => {
  it('shows both obligations with their citations', async () => {
    // A reviewer cannot decide without knowing which document each clause is
    // from and where in it to go and read.
    getReviewQueue.mockResolvedValue([item])
    showReview()

    expect(await screen.findByText(item.source.statement)).toBeInTheDocument()
    expect(screen.getByText(item.target.statement)).toBeInTheDocument()
    expect(screen.getByText(/ORG 1\.0/)).toBeInTheDocument()
    // More than once: the rationale also quotes the designator the two clauses
    // share, which is exactly what made them a candidate.
    expect(screen.getAllByText(/DoDI 5000\.88/).length).toBeGreaterThan(0)
    expect(screen.getByText(/2\/2\.4/)).toBeInTheDocument()
    expect(screen.getByText(/p\.\s*7/)).toBeInTheDocument()
    expect(screen.getByText(/3\/3\.2/)).toBeInTheDocument()
    expect(screen.getByText(/p\.\s*12/)).toBeInTheDocument()
  })

  it('shows the rationale and confidence the proposer offered', async () => {
    getReviewQueue.mockResolvedValue([item])
    showReview()

    expect(await screen.findByText(/share 60%/)).toBeInTheDocument()
    expect(screen.getByText(/72%/)).toBeInTheDocument()
  })

  it('posts an approval for the pair being reviewed', async () => {
    getReviewQueue.mockResolvedValue([item])
    recordVerdict.mockResolvedValue({ promoted: 1 })
    showReview()
    await screen.findByText(item.source.statement)

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    expect(recordVerdict).toHaveBeenCalledWith('ours-1', 'higher-1', 'approve', '')
  })

  it('posts a rejection with the reviewer’s reason', async () => {
    getReviewQueue.mockResolvedValue([item])
    recordVerdict.mockResolvedValue({ suppressed: 1 })
    showReview()
    await screen.findByText(item.source.statement)

    await userEvent.type(screen.getByRole('textbox'), 'Different subject matter.')
    await userEvent.click(screen.getByRole('button', { name: /reject/i }))

    expect(recordVerdict).toHaveBeenCalledWith(
      'ours-1',
      'higher-1',
      'reject',
      'Different subject matter.',
    )
  })

  it('disables both buttons while a verdict is in flight', async () => {
    // A double-click would otherwise record two decisions for one judgement.
    getReviewQueue.mockResolvedValue([item])
    let settle: (value: unknown) => void = () => {}
    recordVerdict.mockReturnValue(new Promise((resolve) => (settle = resolve)))
    showReview()
    await screen.findByText(item.source.statement)

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /reject/i })).toBeDisabled()
    expect(recordVerdict).toHaveBeenCalledTimes(1)

    settle({ promoted: 1 })
    await waitFor(() => expect(getReviewQueue).toHaveBeenCalledTimes(2))
  })

  it('reloads the queue once a verdict is recorded', async () => {
    getReviewQueue.mockResolvedValueOnce([item]).mockResolvedValueOnce([])
    recordVerdict.mockResolvedValue({ promoted: 1 })
    showReview()
    await screen.findByText(item.source.statement)

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/nothing is waiting/i)).toBeInTheDocument()
  })

  it('says plainly when the queue is empty', async () => {
    getReviewQueue.mockResolvedValue([])
    showReview()

    expect(await screen.findByText(/nothing is waiting/i)).toBeInTheDocument()
  })

  it('surfaces a failure to record a verdict rather than looking successful', async () => {
    getReviewQueue.mockResolvedValue([item])
    recordVerdict.mockRejectedValue(new Error('backend down'))
    showReview()
    await screen.findByText(item.source.statement)

    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })

  it('surfaces a fetch failure', async () => {
    getReviewQueue.mockRejectedValue(new Error('backend down'))
    showReview()

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })
})

describe('Review when nothing has been ingested', () => {
  it('distinguishes an empty corpus from a worked-through queue', async () => {
    // ADR-019: "Nothing is waiting for review" is true and misleading when
    // nothing has ever been ingested — it says the work is done.
    listDocuments.mockResolvedValue([])
    getReviewQueue.mockResolvedValue([])
    showReview()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
    expect(screen.queryByText(/nothing is waiting for review/i)).not.toBeInTheDocument()
  })
})

// --- STORY-042: the whole queue, not just its head ----------------------------
//
// Review rendered `queue[0]` with Approve and Reject as the only actions, so a
// proposal the reviewer could not judge — needing a colleague, or a document they do
// not have — blocked every proposal behind it. The only way past was to record a
// verdict, and ADR-014 makes a verdict permanent and replayed on every rebuild.
//
// Skip is therefore client-side and records nothing. It must not become a third
// verdict: the decision vocabulary is closed on purpose.

function queueOf(n: number): ReviewItem[] {
  return Array.from({ length: n }, (_, i) => ({
    ...item,
    source: { ...item.source, obligation_id: `ours-${i}`, statement: `Our clause ${i}.` },
    target: { ...item.target, obligation_id: `higher-${i}` },
  }))
}

describe('Review — working through the queue', () => {
  beforeEach(() => listDocuments.mockResolvedValue([{ slug: 'a' }]))

  it('says where in the queue the reviewer is', async () => {
    getReviewQueue.mockResolvedValue(queueOf(3))
    showReview()

    expect(await screen.findByText(/proposal 1 of 3/i)).toBeInTheDocument()
  })

  it('skips to the next proposal without recording anything', async () => {
    getReviewQueue.mockResolvedValue(queueOf(3))
    showReview()
    await screen.findByText(/Our clause 0\./)

    await userEvent.click(screen.getByRole('button', { name: /skip/i }))

    expect(await screen.findByText(/Our clause 1\./)).toBeInTheDocument()
    expect(recordVerdict).not.toHaveBeenCalled()
    expect(screen.getByText(/proposal 2 of 3/i)).toBeInTheDocument()
  })

  it('goes back to a proposal it skipped past', async () => {
    getReviewQueue.mockResolvedValue(queueOf(3))
    showReview()
    await screen.findByText(/Our clause 0\./)

    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    await userEvent.click(screen.getByRole('button', { name: /previous/i }))

    expect(await screen.findByText(/Our clause 0\./)).toBeInTheDocument()
    expect(recordVerdict).not.toHaveBeenCalled()
  })

  it('wraps to the first proposal after the last, and says so', async () => {
    getReviewQueue.mockResolvedValue(queueOf(2))
    showReview()
    await screen.findByText(/Our clause 0\./)

    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    await userEvent.click(screen.getByRole('button', { name: /skip/i }))

    expect(await screen.findByText(/Our clause 0\./)).toBeInTheDocument()
    expect(screen.getByText(/back at the start/i)).toBeInTheDocument()
  })

  it('offers no skip when there is only one proposal', async () => {
    getReviewQueue.mockResolvedValue(queueOf(1))
    showReview()
    await screen.findByText(/Our clause 0\./)

    expect(screen.queryByRole('button', { name: /skip/i })).not.toBeInTheDocument()
  })

  it('still records a verdict on the proposal actually being shown', async () => {
    getReviewQueue.mockResolvedValue(queueOf(3))
    recordVerdict.mockResolvedValue({ promoted: 1 })
    showReview()
    await screen.findByText(/Our clause 0\./)

    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    expect(recordVerdict).toHaveBeenCalledWith('ours-1', 'higher-1', 'approve', '')
  })

  it('does not run off the end when the queue shrinks under the cursor', async () => {
    // Deciding removes the item, so the index can point past the new last one.
    getReviewQueue.mockResolvedValueOnce(queueOf(2)).mockResolvedValueOnce(queueOf(1))
    recordVerdict.mockResolvedValue({ promoted: 1 })
    showReview()
    await screen.findByText(/Our clause 0\./)

    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))

    await waitFor(() => expect(screen.getByText(/proposal 1 of 1/i)).toBeInTheDocument())
  })
})
