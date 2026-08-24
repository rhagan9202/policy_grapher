import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

const ingest = vi.fn()
vi.mock('../api/client', () => ({
  ingest: (filename: string) => ingest(filename),
  ApiError: class extends Error {},
}))

import Ingest from './Ingest'

afterEach(() => ingest.mockReset())

// STORY-043. `POST /ingest` has existed since DI-1 and `ingest()` has been exposed
// since then; nothing called it. Loading the corpus was a curl command, which means
// the person this tool is for could not put a document into it.

describe('Ingest', () => {
  it('ingests the named file', async () => {
    ingest.mockResolvedValue({
      source: 'manifest',
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [],
    })
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), 'corpus.csv')
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
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), 'corpus.csv')
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
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent(/DoDD 5000\.01/)
    expect(result).toHaveTextContent(/16/)
  })

  it('names the references it could not attribute, rather than only counting them', async () => {
    // An unattributed reference is a citation the graph does not hold. A count alone
    // tells the reader something is missing and not what.
    ingest.mockResolvedValue({
      source: 'document',
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
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), '500001p_2020.pdf')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByText(/Summary of the 2018 National Defense Strategy/)).toBeInTheDocument()
  })

  it('names the edition it recorded and how much text it read', async () => {
    const documentResult = {
      source: 'document',
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
    render(<Ingest />)
    await userEvent.type(screen.getByLabelText(/file to ingest/i), '500001p_2020.pdf')
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
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), 'corpus.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByText(/Military-Standard 882E/)).toBeInTheDocument()
  })

  it('reports a rejected file instead of pretending it loaded', async () => {
    ingest.mockRejectedValue(new Error('row 3: missing column "name"'))
    render(<Ingest />)

    await userEvent.type(screen.getByLabelText(/file to ingest/i), 'broken.csv')
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/missing column/i)
  })

  it('refuses a blank filename rather than asking the API to', async () => {
    render(<Ingest />)
    await userEvent.click(screen.getByRole('button', { name: /ingest/i }))
    expect(ingest).not.toHaveBeenCalled()
  })
})
