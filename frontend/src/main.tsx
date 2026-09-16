import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import './styles.css'

// Two boundaries, at different depths, because they catch different failures.
//
// The one inside App wraps the routed screen only, so the navigation survives a
// screen that throws and the reader can leave it. That is the common case and
// the useful one. But it cannot catch a throw in the navigation itself, in the
// search box beside it, or in App's own body — and those would still blank the
// page, which is the failure the inner boundary was added to end.
//
// This one is the backstop for that remainder. It has nothing to offer but a
// message, since by the time it catches there is no chrome left to navigate
// with; `resetKey` is constant because there is no navigation to reset on.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary resetKey="root" hasNavigation={false}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
)
