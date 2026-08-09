import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'

// Route-level code splitting: the chart-heavy pages (Recharts) are fetched on
// demand, keeping the initial dashboard bundle small.
const Explorer = lazy(() => import('./pages/Explorer').then((m) => ({ default: m.Explorer })))
const Internals = lazy(() => import('./pages/Internals').then((m) => ({ default: m.Internals })))
const Metrics = lazy(() => import('./pages/Metrics').then((m) => ({ default: m.Metrics })))

const Loading = () => (
  <div className="text-ink-3 text-sm py-10 text-center">loading…</div>
)

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="explore"
                 element={<Suspense fallback={<Loading />}><Explorer /></Suspense>} />
          <Route path="internals"
                 element={<Suspense fallback={<Loading />}><Internals /></Suspense>} />
          <Route path="metrics"
                 element={<Suspense fallback={<Loading />}><Metrics /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
