import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('./views/GraphExplorer', () => ({ default: () => <div>graph</div> }))
vi.mock('./views/DocumentTable', () => ({ default: () => <div>documents</div> }))
vi.mock('./views/Triage', () => ({ default: () => <div>triage</div> }))
vi.mock('./views/Review', () => ({ default: () => <div>review</div> }))
vi.mock('./views/Ask', () => ({ default: () => <div>ask</div> }))

import App from './App'

const ROUTES = [
  [/graph/i, '/'],
  [/documents/i, '/documents'],
  [/triage/i, '/triage'],
  [/review/i, '/review'],
  [/ask/i, '/ask'],
] as const

describe('App', () => {
  it.each(ROUTES)('links to %s', (label, href) => {
    // DI-1 shipped two screens with no way to get from one to the other. This
    // is the defect this asserts closed — a route nothing links to is a route
    // nobody reaches.
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', href)
  })

  it.each(ROUTES)('renders the view behind %s', (label, href) => {
    render(
      <MemoryRouter initialEntries={[href]}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getAllByText(label).length).toBeGreaterThan(0)
  })

  it('marks the route currently being viewed', () => {
    render(
      <MemoryRouter initialEntries={['/review']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /review/i })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})
