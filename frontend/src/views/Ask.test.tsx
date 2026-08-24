import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Answer } from '../api/types'

const ask = vi.fn()
const listDocuments = vi.fn()
vi.mock('../api/client', () => ({
  ask: (question: string) => ask(question),
  listDocuments: () => listDocuments(),
  ApiError: class extends Error {},
}))

import Ask from './Ask'

// EmptyState links to the Ingest screen, so any view that can render it
// needs router context.
const showAsk = () =>
  render(
    <MemoryRouter>
      <Ask />
    </MemoryRouter>,
  )

const answered: Answer = {
  answer:
    'The corpus states:\n— "The Director shall notify the Comptroller." (DoDI 5000.88, 3/3.2, p. 12)',
  citations: [
    {
      document: 'DoDI 5000.88',
      section_path: ['3', '3.2'],
      page: 12,
      quote: 'The Director shall notify the Comptroller.',
    },
  ],
  template_used: 'obligations_for_actor',
}

const nothing: Answer = {
  answer:
    'Nothing in the corpus addresses that. No passage matched, so there is no grounded answer to give — this is an absence of evidence, not a statement that the answer is no.',
  citations: [],
  template_used: 'grounded_passages',
}

afterEach(() => {
  ask.mockReset()
  listDocuments.mockReset()
})

beforeEach(() => listDocuments.mockResolvedValue([{ slug: 'd', name: 'D' }]))

describe('Ask', () => {
  it('shows the answer and every citation behind it', async () => {
    ask.mockResolvedValue(answered)
    showAsk()

    await userEvent.type(screen.getByRole('searchbox'), 'what obliges the Director?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    // The quotation appears twice on purpose: the answer is composed *from*
    // the citations, so it shows in the answer and again under Sources
    // (ADR-017). The citation itself is asserted within the Sources list.
    expect((await screen.findAllByText(/notify the Comptroller/)).length).toBe(2)

    const sources = within(screen.getByRole('list'))
    expect(sources.getByText(/notify the Comptroller/)).toBeInTheDocument()
    expect(sources.getByText(/DoDI 5000\.88/)).toBeInTheDocument()
    expect(sources.getByText(/3\/3\.2/)).toBeInTheDocument()
    expect(sources.getByText(/12/)).toBeInTheDocument()
  })

  it('states the absence rather than showing an empty panel', async () => {
    // "The corpus does not say" and "the answer is no" are different things, and
    // a blank result would let a reader take the first for the second.
    ask.mockResolvedValue(nothing)
    showAsk()

    await userEvent.type(screen.getByRole('searchbox'), 'what obliges the Postmaster?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(await screen.findByText(/nothing in the corpus/i)).toBeInTheDocument()
    expect(screen.getByText(/no passage/i)).toBeInTheDocument()
  })

  it('names which template answered, so the answer is traceable', async () => {
    ask.mockResolvedValue(answered)
    showAsk()

    await userEvent.type(screen.getByRole('searchbox'), 'what obliges the Director?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(await screen.findByText(/obligations_for_actor/)).toBeInTheDocument()
  })

  it('will not ask an empty question', async () => {
    showAsk()

    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(ask).not.toHaveBeenCalled()
  })

  it('disables the button while an answer is in flight', async () => {
    let settle: (value: unknown) => void = () => {}
    ask.mockReturnValue(new Promise((resolve) => (settle = resolve)))
    showAsk()

    await userEvent.type(screen.getByRole('searchbox'), 'anything')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(screen.getByRole('button', { name: /ask/i })).toBeDisabled()
    settle(nothing)
    expect(await screen.findByText(/nothing in the corpus/i)).toBeInTheDocument()
  })

  it('surfaces a failure', async () => {
    ask.mockRejectedValue(new Error('backend down'))
    showAsk()

    await userEvent.type(screen.getByRole('searchbox'), 'anything')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })
})

describe('Ask when nothing has been ingested', () => {
  it('says the corpus is empty instead of inviting a question with no answer', async () => {
    listDocuments.mockResolvedValue([])
    showAsk()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
  })
})
