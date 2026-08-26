import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

const reset = vi.fn()
const exportGraph = vi.fn()
vi.mock('../api/client', () => ({
  reset: () => reset(),
  exportGraph: () => exportGraph(),
  ApiError: class extends Error {},
}))

import Reset from './Reset'

afterEach(() => {
  reset.mockReset()
  exportGraph.mockClear()
})

// STORY-046. `POST /reset` and `reset()` were both built and unreachable. It is
// destructive and irreversible, so the confirmation carries the whole weight here.

describe('Reset', () => {
  it('does not empty the graph without confirmation', async () => {
    render(<Reset />)

    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))

    expect(reset).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('states what is deleted and what survives', async () => {
    // The plan's risk note: a confirmation that describes this wrongly is worse than
    // no confirmation. `clear_graph` deletes the :EmbeddingIndex marker node but
    // cannot delete a Neo4j index, which is why ensure_vector_index rebuilds it
    // (ADR-016). Saying "everything is deleted" would be false.
    render(<Reset />)

    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    const dialog = screen.getByRole('dialog')

    expect(dialog).toHaveTextContent(/cannot be undone/i)
    expect(dialog).toHaveTextContent(/vector index/i)
  })

  it('requires the confirmation to be typed, not just clicked', async () => {
    // One misplaced click should not empty a corpus that took a model an hour to
    // build. Typing is the cheapest gate that cannot be hit by accident.
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))

    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))
    expect(reset).not.toHaveBeenCalled()

    await userEvent.type(screen.getByLabelText(/type/i), 'empty the graph')
    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))
    expect(reset).toHaveBeenCalled()
  })

  it('reports what it deleted', async () => {
    reset.mockResolvedValue({ nodes_deleted: 438, relationships_deleted: 672 })
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    await userEvent.type(screen.getByLabelText(/type/i), 'empty the graph')
    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/438/)
    expect(status).toHaveTextContent(/672/)
  })

  it('keeps the graph when the confirmation is cancelled', async () => {
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(reset).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('says why nothing happened when the confirmation phrase is wrong', async () => {
    // The button is deliberately enabled while the phrase is unmatched. A press
    // that deleted nothing and said nothing was indistinguishable from a screen
    // that does not work.
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    await userEvent.type(screen.getByLabelText(/type/i), 'empty teh graph')
    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))

    expect(reset).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/not the phrase/i)
  })

  it('clears the mismatch warning once the reader edits the phrase', async () => {
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    const field = screen.getByLabelText(/type/i)
    await userEvent.type(field, 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not the phrase/i)

    await userEvent.type(field, 'x')

    expect(screen.queryByText(/not the phrase/i)).not.toBeInTheDocument()
  })

  it('reports a failed reset instead of claiming the graph is empty', async () => {
    reset.mockRejectedValue(new Error('Neo4j is unreachable'))
    render(<Reset />)
    await userEvent.click(screen.getByRole('button', { name: /empty the graph/i }))
    await userEvent.type(screen.getByLabelText(/type/i), 'empty the graph')
    await userEvent.click(screen.getByRole('button', { name: /^delete everything$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/unreachable/i)
  })
})


// STORY-083. The screen said "There is no undo and no export" and was right —
// no export route existed anywhere in the API. Half of that stops being true
// here, and the copy has to stop saying it in the same change, because Reset is
// the one screen where being behind on documentation is actively dangerous.

describe('Reset export', () => {
  it('offers a copy before the destructive action', async () => {
    exportGraph.mockResolvedValue({ documents: [], decisions: [] })
    render(<Reset />)

    const download = screen.getByRole('button', { name: /export/i })
    await userEvent.click(download)

    expect(exportGraph).toHaveBeenCalled()
  })

  it('no longer claims there is no export', () => {
    render(<Reset />)

    expect(screen.queryByText(/no undo and no export/i)).not.toBeInTheDocument()
    expect(screen.getByText(/no undo/i)).toBeInTheDocument()
  })

  it('does not promise the export makes this reversible', () => {
    render(<Reset />)

    // Export is not restore. Saying or implying otherwise would be worse than
    // having no export at all: a user would empty the graph believing they could
    // put it back. Restore is a separate, larger item — writing decisions back
    // means deciding what happens when the graph beneath them has moved, which is
    // what ADR-027 had to work through for rebuilds.
    expect(screen.queryByText(/can be restored/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/undo/i)).toBeInTheDocument()
  })
})
