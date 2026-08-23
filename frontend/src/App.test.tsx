import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./views/GraphExplorer', () => ({ default: () => <div>graph</div> }))
vi.mock('./views/DocumentTable', () => ({ default: () => <div>documents</div> }))
vi.mock('./views/Triage', () => ({ default: () => <div>triage</div> }))
vi.mock('./views/Review', () => ({ default: () => <div>review</div> }))
vi.mock('./views/Ask', () => ({ default: () => <div>ask</div> }))
vi.mock('./views/Ingest', () => ({ default: () => <div>ingest</div> }))
vi.mock('./views/Reset', () => ({ default: () => <div>reset</div> }))
vi.mock('./views/DocumentDetail', () => ({ default: () => <div>detail</div> }))

const getHealth = vi.fn()
vi.mock('./api/client', () => ({
  getHealth: () => getHealth(),
  ApiError: class extends Error {},
}))

import App from './App'

const ROUTES = [
  [/graph/i, '/'],
  [/documents/i, '/documents'],
  [/ingest/i, '/ingest'],
  [/triage/i, '/triage'],
  [/review/i, '/review'],
  [/ask/i, '/ask'],
  [/reset/i, '/reset'],
] as const

beforeEach(() => getHealth.mockResolvedValue({ status: 'ok' }))
afterEach(() => getHealth.mockReset())

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

// `getHealth` was the last client function with no caller. Every screen reported its
// own failure, so a backend that was down looked like five unrelated broken screens
// — the state ADR-019 exists to stop the app misrepresenting.
describe('App — backend reachability', () => {
  it('says nothing while the backend answers', async () => {
    getHealth.mockResolvedValue({ status: 'ok' })
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    await screen.findByText('graph')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says so once when the backend cannot be reached', async () => {
    getHealth.mockRejectedValue(new Error('Failed to fetch'))
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend/i)
  })
})
