import Ask from './views/Ask'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'
import Ingest from './views/Ingest'
import Reset from './views/Reset'
import Review from './views/Review'
import Triage from './views/Triage'

// DI-1 shipped two screens and no way to get from one to the other. Every route
// the app serves is named here, so a screen cannot exist without a way to reach
// it — App.test.tsx asserts one link per route.
export const ROUTES = [
  { to: '/', label: 'Graph', element: <GraphExplorer /> },
  { to: '/documents', label: 'Documents', element: <DocumentTable /> },
  { to: '/ingest', label: 'Ingest', element: <Ingest /> },
  { to: '/triage', label: 'Triage', element: <Triage /> },
  { to: '/review', label: 'Review', element: <Review /> },
  { to: '/ask', label: 'Ask', element: <Ask /> },
  // Last in the navigation on purpose: it is the only destructive screen.
  { to: '/reset', label: 'Reset', element: <Reset /> },
]
