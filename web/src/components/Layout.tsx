/** App shell: nav, live connection indicator, cluster summary. */
import { NavLink, Outlet } from 'react-router-dom'
import { useCluster } from '../store'
import { useClusterEvents, useClusterPolling } from '../hooks/useClusterEvents'

const TABS = [
  { to: '/', label: 'Cluster', end: true },
  { to: '/explore', label: 'KV Explorer' },
  { to: '/internals', label: 'Internals' },
  { to: '/metrics', label: 'Metrics' },
]

export function Layout() {
  useClusterEvents()
  useClusterPolling(2000)

  const nodes = useCluster((s) => s.nodes)
  const connected = useCluster((s) => s.connected)
  const error = useCluster((s) => s.error)

  const live = nodes?.live_count ?? 0
  const total = Object.keys(nodes?.members ?? {}).length

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b sticky top-0 z-10 backdrop-blur"
              style={{ borderColor: 'var(--color-edge)',
                       background: 'color-mix(in srgb, var(--color-surface) 88%, transparent)' }}>
        <div className="max-w-[1240px] mx-auto px-5 py-3 flex items-center gap-5 flex-wrap">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tracking-tight">Helix</span>
            <span className="text-xs text-ink-3 hidden sm:inline">
              distributed key-value store
            </span>
          </div>

          <nav className="flex gap-1">
            {TABS.map((t) => (
              <NavLink key={t.to} to={t.to} end={t.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm transition-colors ${
                    isActive ? 'text-ink' : 'text-ink-3 hover:text-ink-2'}`}
                style={({ isActive }) =>
                  isActive ? { background: 'var(--color-panel-2)' } : undefined}>
                {t.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-xs">
            {total > 0 && (
              <span className="text-ink-2 tabular-nums">
                {live}/{total} nodes · RF={nodes?.replication}
              </span>
            )}
            <span className="flex items-center gap-1.5 text-ink-3">
              <span className="h-1.5 w-1.5 rounded-full"
                    style={{ background: connected ? 'var(--color-good)' : 'var(--color-bad)' }} />
              {connected ? 'live' : 'offline'}
            </span>
          </div>
        </div>
      </header>

      {error && (
        <div className="max-w-[1240px] mx-auto w-full px-5 pt-4">
          <div className="rounded-lg border px-3 py-2 text-xs"
               style={{ borderColor: 'var(--color-bad)', color: 'var(--color-bad)' }}>
            {error} — is a Helix node running on :8001?
          </div>
        </div>
      )}

      <main className="flex-1 max-w-[1240px] mx-auto w-full px-5 py-5">
        <Outlet />
      </main>

      <footer className="border-t" style={{ borderColor: 'var(--color-edge)' }}>
        <div className="max-w-[1240px] mx-auto px-5 py-3 text-[11px] text-ink-3
                        flex gap-4 flex-wrap">
          <span>React · TypeScript · Vite · Tailwind — talking to FastAPI + WebSockets</span>
          <a className="ml-auto hover:text-ink-2"
             href="https://github.com/SriParth-alt/distributed-kv"
             target="_blank" rel="noreferrer">source →</a>
        </div>
      </footer>
    </div>
  )
}
