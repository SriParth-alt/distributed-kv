/** Live cluster event feed, streamed over the WebSocket. */
import { useCluster } from '../store'
import type { ClusterEvent, EventType } from '../types'

const LABEL: Record<EventType, string> = {
  write: 'WRITE', delete: 'DELETE', read: 'READ', replicate_in: 'REPLICATE',
  node_up: 'NODE UP', node_down: 'NODE DOWN', node_killed: 'KILLED',
  node_started: 'STARTED',
}

const TONE: Record<EventType, string> = {
  write: 'var(--color-accent)', delete: 'var(--color-warn)',
  read: 'var(--color-ink-3)', replicate_in: 'var(--color-good)',
  node_up: 'var(--color-good)', node_down: 'var(--color-bad)',
  node_killed: 'var(--color-bad)', node_started: 'var(--color-ink-3)',
}

function describe(e: ClusterEvent): string {
  switch (e.type) {
    case 'write':
    case 'delete':
      return `${e.key} → acks [${(e.acks ?? []).join(', ')}] · wal ${e.wal_ms}ms · ${e.latency_ms}ms`
    case 'replicate_in':
      return `${e.key} ← from ${e.source} · ${e.latency_ms}ms`
    case 'read':
      return `${e.key}${e.failover ? ' (served by replica — failover)' : ''} · ${e.latency_ms}ms`
    case 'node_up':
      return `${e.peer} rejoined the ring`
    case 'node_down':
      return `${e.peer} missed heartbeats — evicted from ring`
    case 'node_killed':
      return 'crashed on request'
    default:
      return 'online'
  }
}

export function EventFeed({ limit = 60, types }: { limit?: number; types?: EventType[] }) {
  const events = useCluster((s) => s.events)
  const connected = useCluster((s) => s.connected)
  const colorOf = useCluster((s) => s.colorOf)
  const shown = (types ? events.filter((e) => types.includes(e.type)) : events).slice(0, limit)

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 mb-2 text-xs text-ink-3">
        <span className="h-1.5 w-1.5 rounded-full"
              style={{ background: connected ? 'var(--color-good)' : 'var(--color-bad)' }} />
        {connected ? 'websocket connected' : 'reconnecting…'}
        <span className="ml-auto tabular-nums">{shown.length} events</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto font-mono text-[11px] leading-relaxed
                      rounded-lg border p-2.5"
           style={{ background: 'var(--color-surface)', borderColor: 'var(--color-edge)' }}>
        {shown.length === 0 && (
          <div className="text-ink-3 p-2">waiting for cluster activity…</div>
        )}
        {shown.map((e) => (
          <div key={`${e.node}-${e.seq}`} className="flex gap-2 py-0.5">
            <span className="text-ink-3 shrink-0">
              {new Date(e.ts * 1000).toLocaleTimeString()}
            </span>
            <span className="shrink-0 w-[68px] font-semibold" style={{ color: TONE[e.type] }}>
              {LABEL[e.type]}
            </span>
            <span className="shrink-0 w-[52px]" style={{ color: colorOf(e.node) }}>
              {e.node}
            </span>
            <span className="text-ink-2 truncate">{describe(e)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
