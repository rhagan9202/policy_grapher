import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState'

// The message links to the Ingest screen, so it needs router context.
const show = (lead?: string) =>
  render(
    <MemoryRouter>
      <EmptyState lead={lead} />
    </MemoryRouter>,
  )

describe('EmptyState', () => {
  it('states the absence and names the action', () => {
    // ADR-019: an empty app must read as deliberately empty, not broken. The
    // message says what is missing and what to run.
    show()

    const panel = screen.getByRole('status')
    expect(panel).toHaveTextContent(/no documents have been ingested yet/i)
    // Says plainly that this is expected, so a blank screen is not read as a fault.
    expect(panel).toHaveTextContent(/not an error/i)
  })

  it('names a concrete command rather than gesturing at one', () => {
    show()
    const panel = screen.getByRole('status')
    expect(panel).toHaveTextContent('POST /ingest')
    expect(panel).toHaveTextContent('500001p.pdf')
  })

  it('can carry a screen-specific lead-in', () => {
    show('Nothing to triage.')
    expect(screen.getByText(/nothing to triage/i)).toBeInTheDocument()
  })

  it('offers the screen that does it, now that one exists', () => {
    // Written when this component was: "the ingest control is STORY-043, in sprint
    // 5. Until then this is actionable from a terminal and nowhere else, which is a
    // known and dated gap." STORY-043 landed. Telling a reader to call an endpoint
    // when a screen is one click away in the nav is the gap reopened as prose.
    show()

    const link = screen.getByRole('link', { name: /ingest/i })
    expect(link).toHaveAttribute('href', '/ingest')
  })
})
