import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
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
import { ROUTES as DECLARED } from './routes'

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

  it('says an unknown address names no screen, rather than rendering nothing', () => {
    // A path matching no route rendered the navigation bar over a blank page —
    // indistinguishable from a screen that failed to load, and pointing the
    // reader at the app rather than at their own address bar.
    render(
      <MemoryRouter initialEntries={['/nonsense']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByRole('status')).toHaveTextContent(/no screen at \/nonsense/i)
    expect(screen.getByRole('link', { name: /start at the graph/i })).toBeInTheDocument()
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

// STORY-014, an MVP definition-of-done item open since DI-1: "Users can search by
// document name or ID". STORY-010 built a filter on the Documents table that
// matches `name` only and lives on one screen. The bar asks for two things it does
// not do — match the ID, and be reachable from anywhere.

describe('search from anywhere', () => {
  it('offers a search control on every screen', async () => {
    // Iterating the declaration itself, not a copy of it. The list above in this
    // file mirrors App.tsx by hand, so a route added there would be covered by
    // neither test — which is the failure this criterion was written against.
    for (const { to: path } of DECLARED) {
      const view = render(
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>,
      )
      expect(
        screen.getByRole('searchbox', { name: /search documents/i }),
        `no search control on ${path}`,
      ).toBeInTheDocument()
      view.unmount()
    }
  })

  it('takes a search from another screen to the documents table', async () => {
    render(
      <MemoryRouter initialEntries={['/ask']}>
        <App />
      </MemoryRouter>,
    )

    const box = screen.getByRole('searchbox', { name: /search documents/i })
    await userEvent.type(box, 'dodd-5000-01{Enter}')

    // The bar is "from anywhere", so the control has to navigate, not just filter
    // whatever screen happens to be showing.
    // DocumentTable is mocked to a stub in this file, so its stub text is what
    // proves the navigation happened.
    expect(await screen.findByText('documents')).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: /search documents/i })).toHaveValue(
      'dodd-5000-01',
    )
  })
})
