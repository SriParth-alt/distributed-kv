/** Internals — WAL / LSM storage state and replication behaviour per node. */
import { EventFeed } from '../components/EventFeed'
import { Panel } from '../components/ui'
import { useCluster } from '../store'
import type { StorageStats } from '../types'

const fmtBytes = (b: number) =>
  b < 1024 ? `${b} B` : b < 1024 ** 2 ? `${(b / 1024).toFixed(1)} KB`
    : `${(b / 1024 ** 2).toFixed(2)} MB`

function LsmColumn({ nodeId, storage, color }: {
  nodeId: string; storage: StorageStats; color: string
}) {
  const fill = Math.min(storage.memtable_fill_pct, 100)
  return (
    <div className="rounded-xl border p-3 flex flex-col gap-3"
         style={{ background: 'var(--color-panel)', borderColor: 'var(--color-edge)' }}>
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
        {nodeId}
        <span className="ml-auto text-xs text-ink-3 tabular-nums">
          {storage.live_keys} live keys
        </span>
      </div>

      {/* WAL */}
      <div>
        <div className="flex justify-between text-[11px] text-ink-3">
          <span>write-ahead log</span>
          <span className="tabular-nums">
            {storage.wal_entries} entries · {fmtBytes(storage.wal_bytes)}
          </span>
        </div>
        <div className="mt-1 h-6 rounded-md border flex items-center px-2 text-[10px]
                        font-mono overflow-hidden"
             style={{ background: 'var(--color-surface)', borderColor: 'var(--color-edge)' }}>
          <span className="text-ink-3 truncate">
            {storage.wal_entries > 0
              ? `${storage.wal_entries} un-flushed records — fsync'd before ACK`
              : 'empty — flushed to SSTable'}
          </span>
        </div>
      </div>

      {/* memtable */}
      <div>
        <div className="flex justify-between text-[11px] text-ink-3">
          <span>memtable (sorted, in-memory)</span>
          <span className="tabular-nums">
            {storage.memtable_entries}/{storage.memtable_limit}
          </span>
        </div>
        <div className="mt-1 h-2 rounded-full overflow-hidden"
             style={{ background: 'var(--color-panel-2)' }}>
          <div className="h-full transition-all rounded-full"
               style={{ width: `${fill}%`, background: color }} />
        </div>
        <div className="text-[10px] text-ink-3 mt-1">
          flushes to an immutable SSTable at {storage.memtable_limit}
        </div>
      </div>

      {/* sstables */}
      <div className="flex-1">
        <div className="flex justify-between text-[11px] text-ink-3 mb-1">
          <span>SSTables (immutable, sorted)</span>
          <span className="tabular-nums">{storage.sstable_count}</span>
        </div>
        <div className="flex flex-col gap-1">
          {storage.sstables.length === 0 && (
            <div className="text-[10px] text-ink-3 italic">
              none yet — all data still in WAL + memtable
            </div>
          )}
          {storage.sstables.map((s, i) => (
            <div key={s.file}
                 className="rounded border px-2 py-1 text-[10px] font-mono flex gap-2"
                 style={{
                   background: 'var(--color-surface)',
                   borderColor: 'var(--color-edge)',
                   marginLeft: `${i * 6}px`,
                 }}>
              <span className="truncate">L{i} · {s.file}</span>
              <span className="ml-auto text-ink-3 shrink-0">
                {s.keys}k · {fmtBytes(s.bytes)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function Internals() {
  const { metrics, colorOf, events } = useCluster()

  const replEvents = events.filter((e) => e.type === 'replicate_in')
  const avgReplLag = replEvents.length
    ? (replEvents.reduce((a, e) => a + (e.latency_ms ?? 0), 0) / replEvents.length).toFixed(2)
    : '—'

  const writeEvents = events.filter((e) => e.type === 'write' || e.type === 'delete')
  const avgWal = writeEvents.length
    ? (writeEvents.reduce((a, e) => a + (e.wal_ms ?? 0), 0) / writeEvents.length).toFixed(2)
    : '—'

  return (
    <div className="flex flex-col gap-4">
      <Panel title="LSM storage engine per node"
             subtitle="Write path: WAL fsync → sorted memtable → immutable SSTables. Reads check memtable first, then SSTables newest → oldest.">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {metrics?.per_node.map((n) =>
            n.storage
              ? <LsmColumn key={n.node_id} nodeId={n.node_id} storage={n.storage}
                           color={colorOf(n.node_id)} />
              : (
                <div key={n.node_id}
                     className="rounded-xl border p-3 text-xs text-ink-3"
                     style={{ borderColor: 'var(--color-bad)' }}>
                  {n.node_id} unreachable
                </div>
              ),
          )}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start">
        <Panel title="Replication stream"
               subtitle="Every write fans out synchronously from the primary to its successors."
               className="h-[420px] flex flex-col">
          <EventFeed limit={80} types={['write', 'delete', 'replicate_in']} />
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel title="Durability & replication">
            <dl className="text-sm flex flex-col gap-2">
              <div className="flex justify-between">
                <dt className="text-ink-3">avg WAL fsync</dt>
                <dd className="tabular-nums">{avgWal} ms</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">avg replication ack</dt>
                <dd className="tabular-nums">{avgReplLag} ms</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">replications sent</dt>
                <dd className="tabular-nums">{metrics?.totals.replications_sent ?? 0}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">replications failed</dt>
                <dd className="tabular-nums"
                    style={{ color: (metrics?.totals.replications_failed ?? 0) > 0
                      ? 'var(--color-bad)' : undefined }}>
                  {metrics?.totals.replications_failed ?? 0}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-3">reads served by replica</dt>
                <dd className="tabular-nums">{metrics?.totals.failovers ?? 0}</dd>
              </div>
            </dl>
          </Panel>

          <Panel title="How a write lands">
            <ol className="text-xs text-ink-2 flex flex-col gap-2 list-decimal list-inside">
              <li>Key hashed (MD5) → position on the ring</li>
              <li>Walk clockwise → primary + {metrics ? '' : ''}successor replicas</li>
              <li>Primary appends to WAL and <b>fsyncs</b> — the durability contract</li>
              <li>Record inserted into the sorted memtable</li>
              <li>Synchronous fan-out to replicas; acks collected</li>
              <li>Memtable full → flushed to an immutable SSTable, WAL truncated</li>
            </ol>
          </Panel>
        </div>
      </div>
    </div>
  )
}
