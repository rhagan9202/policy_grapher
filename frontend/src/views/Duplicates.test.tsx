import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

const listDuplicates = vi.fn()
const mergeDocuments = vi.fn()
const markNotDuplicates = vi.fn()
vi.mock('../api/client', () => ({
  listDuplicates: () => listDuplicates(),
  mergeDocuments: (a: string, b: string) => mergeDocuments(a, b),
  markNotDuplicates: (a: string, b: string) => markNotDuplicates(a, b),
  ApiError: class extends Error {},
}))

import Duplicates from './Duplicates'

afterEach(() => {
  listDuplicates.mockReset()
  mergeDocuments.mockReset()
  markNotDuplicates.mockReset()
})

const pair = {
  names: ['Military Standard 882E', 'Military-Standard 882E'],
  slugs: ['military-standard-882e-a1b2', 'military-standard-882e'],
  cited_by: [1, 3],
  has_text: [false, false],
  mergeable: true,
}

// STORY-031, ADR-032. Ingest has flagged near-duplicate names since STORY-003 and
// nothing acted on the flag. The corpus produces two real pairs.

describe('Duplicates', () => {
  it('shows both sides with enough to tell them apart', async () => {
    listDuplicates.mockResolvedValue([pair])

    render(<Duplicates />)

    // A name alone is not enough to rule on: what cites each is the evidence.
    // Each name appears twice — once as the pair member and once on its Keep
    // button — so the assertion is on the evidence, which appears once.
    await screen.findByRole('heading', { name: /possible duplicates/i })
    expect(screen.getByText(/cited by 1/)).toBeInTheDocument()
    expect(screen.getByText(/cited by 3/)).toBeInTheDocument()
    expect(screen.getAllByText(/Military Standard 882E/).length).toBeGreaterThan(0)
  })

  it('merges only when a person chooses which name survives', async () => {
    listDuplicates.mockResolvedValue([pair])
    mergeDocuments.mockResolvedValue({ applied: 1 })

    render(<Duplicates />)
    await userEvent.click(
      await screen.findByRole('button', { name: /Keep “Military-Standard 882E”/ }),
    )

    await waitFor(() =>
      expect(mergeDocuments).toHaveBeenCalledWith(
        'Military-Standard 882E',
        'Military Standard 882E',
      ),
    )
  })

  it('records that a pair is different, so it stops being asked about', async () => {
    listDuplicates.mockResolvedValue([pair])
    markNotDuplicates.mockResolvedValue(undefined)

    render(<Duplicates />)
    await userEvent.click(
      await screen.findByRole('button', { name: /these are different/i }),
    )

    await waitFor(() => expect(markNotDuplicates).toHaveBeenCalled())
    expect(mergeDocuments).not.toHaveBeenCalled()
  })

  it('refuses a pair where either side carries text, and says why', async () => {
    listDuplicates.mockResolvedValue([
      { ...pair, has_text: [true, false], mergeable: false },
    ])

    render(<Duplicates />)

    expect(await screen.findByText(/cannot be merged/i)).toBeInTheDocument()
    expect(screen.getByText(/owner cannot simply change/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Keep/ })).not.toBeInTheDocument()
  })

  it('says so when every flagged pair has been ruled on', async () => {
    listDuplicates.mockResolvedValue([])

    render(<Duplicates />)

    // An empty section with no words is the blank that reads as broken.
    expect(
      await screen.findByText(/no unreconciled near-duplicate names/i),
    ).toBeInTheDocument()
  })
})
