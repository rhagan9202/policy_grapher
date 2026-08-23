import { NavLink, Route, Routes } from 'react-router-dom'
import Ask from './views/Ask'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'
import Ingest from './views/Ingest'
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
]

export default function App() {
  return (
    <>
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
      </Routes>
    </>
  )
}
