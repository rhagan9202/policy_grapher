import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState'

describe('EmptyState', () => {
  it('states the absence and names the action', () => {
    // ADR-019: an empty app must read as deliberately empty, not broken. The
    // message says what is missing and what to run.
    render(<EmptyState />)

    const panel = screen.getByRole('status')
    expect(panel).toHaveTextContent(/no documents have been ingested yet/i)
    // Says plainly that this is expected, so a blank screen is not read as a fault.
    expect(panel).toHaveTextContent(/not an error/i)
  })

  it('names a concrete command rather than gesturing at one', () => {
    render(<EmptyState />)
    const panel = screen.getByRole('status')
    expect(panel).toHaveTextContent('POST /ingest')
    expect(panel).toHaveTextContent('500001p.pdf')
  })

  it('can carry a screen-specific lead-in', () => {
    render(<EmptyState lead="Nothing to triage." />)
    expect(screen.getByText(/nothing to triage/i)).toBeInTheDocument()
  })
})
