import { useEffect, useState } from 'react'
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom'
import { getHealth } from './api/client'
import Ask from './views/Ask'
import DocumentDetail from './views/DocumentDetail'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'
import Ingest from './views/Ingest'
import Reset from './views/Reset'
import Review from './views/Review'
import Triage from './views/Triage'

// DI-1 shipped two screens and no way to get from one to the other. Every route
// the app serves is named here, so a screen cannot exist without a way to reach
// it — App.test.tsx asserts one link per route.
const ROUTES = [
  { to: '/', label: 'Graph', element: <GraphExplorer /> },
  { to: '/documents', label: 'Documents', element: <DocumentTable /> },
  { to: '/ingest', label: 'Ingest', element: <Ingest /> },
  { to: '/triage', label: 'Triage', element: <Triage /> },
  { to: '/review', label: 'Review', element: <Review /> },
  { to: '/ask', label: 'Ask', element: <Ask /> },
  // Last in the navigation on purpose: it is the only destructive screen.
  { to: '/reset', label: 'Reset', element: <Reset /> },
]

/** The query parameter the Documents table reads its filter from. */
export const SEARCH_PARAM = 'q'

function SearchDocuments() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { pathname } = useLocation()
  // Controlled from the URL while on Documents, so a search survives a reload and
  // the box agrees with what the table is showing. Local elsewhere, because the
  // URL of another screen says nothing about a document search.
  const applied = pathname === '/documents' ? (params.get(SEARCH_PARAM) ?? '') : ''

  // Uncontrolled and keyed on the applied term rather than mirrored into state.
  // Changing the key remounts the input with the new default, which is React's
  // own answer to "reset this when that changes" — and avoids the effect-driven
  // state sync that causes cascading renders.
  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault()
        const field = new FormData(event.currentTarget).get(SEARCH_PARAM)
        const trimmed = String(field ?? '').trim()
        navigate(
          trimmed
            ? `/documents?${SEARCH_PARAM}=${encodeURIComponent(trimmed)}`
            : '/documents',
        )
      }}
    >
      <input
        key={applied}
        name={SEARCH_PARAM}
        type="search"
        aria-label="Search documents"
        placeholder="Name or ID, e.g. dodd-5000-01"
        defaultValue={applied}
      />
      <button type="submit">Search</button>
    </form>
  )
}

function NoSuchScreen() {
  const { pathname } = useLocation()
  return (
    <div role="status" style={{ padding: '1rem', maxWidth: '40rem' }}>
      <p>
        <strong>There is no screen at {pathname}.</strong>
      </p>
      <p>
        The app is running — this address does not name one of its screens. Pick one
        from the navigation above, or <Link to="/">start at the graph</Link>.
      </p>
    </div>
  )
}

export default function App() {
  // `getHealth` was the last client function with no caller. Every screen reported
  // its own fetch failure, so a backend that was down looked like five unrelated
  // broken screens rather than one cause — which is the class of thing ADR-019 says
  // the app must not misrepresent about its own state. Checked once at mount: this
  // answers "is anything there at all", not "is it there right now".
  const [reachable, setReachable] = useState(true)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then(() => {
        if (!cancelled) setReachable(true)
      })
      .catch(() => {
        if (!cancelled) setReachable(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      {!reachable && (
        <div role="alert" style={{ padding: '0.5rem 1rem' }}>
          The backend is not answering. Every screen below will fail to load until it
          does — this is one cause, not several. Check that the stack is up.
        </div>
      )}
      <nav aria-label="Main">
        <ul style={{ display: 'flex', gap: '1rem', listStyle: 'none', padding: '1rem' }}>
          {ROUTES.map((route) => (
            <li key={route.to}>
              {/* NavLink sets aria-current="page" on the active route itself. */}
              <NavLink to={route.to} end={route.to === '/'}>
                {route.label}
              </NavLink>
            </li>
          ))}
        </ul>
        {/* STORY-014, an MVP bar: "Users can search by document name or ID".
            Beside the navigation rather than on a screen, because the bar asks for
            reach from anywhere — and submitting to the Documents table rather than
            a results view of its own, because a separate view would duplicate the
            table's cap-and-say-so behaviour (STORY-070) and its row rendering to
            show the same rows. */}
        <SearchDocuments />
      </nav>

      <Routes>
        {ROUTES.map((route) => (
          <Route key={route.to} path={route.to} element={route.element} />
        ))}
        {/* Not in ROUTES: ROUTES is the navigation, and App.test.tsx asserts one
            link per entry. A document's detail page is reached from its row, not
            from a nav item that would need a document to point at. */}
        <Route path="/documents/:slug" element={<DocumentDetail />} />
        {/* Anything else. Without this, a mistyped or stale URL matched no route
            and React Router rendered nothing at all: the navigation bar over an
            empty page, which is the blank-that-reads-as-broken ADR-019 exists to
            forbid — and worse here, because the reader has no reason to suspect
            the address rather than the app. */}
        <Route path="*" element={<NoSuchScreen />} />
      </Routes>
    </>
  )
}
