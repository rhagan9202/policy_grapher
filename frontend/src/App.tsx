import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
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
      </nav>

      <Routes>
        {ROUTES.map((route) => (
          <Route key={route.to} path={route.to} element={route.element} />
        ))}
        {/* Not in ROUTES: ROUTES is the navigation, and App.test.tsx asserts one
            link per entry. A document's detail page is reached from its row, not
            from a nav item that would need a document to point at. */}
        <Route path="/documents/:slug" element={<DocumentDetail />} />
      </Routes>
    </>
  )
}
