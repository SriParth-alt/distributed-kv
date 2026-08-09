/** Per-node status card: health, role, key ownership, storage fill, crash button. */
import { useState } from 'react'
import { api } from '../api'
import { useCluster } from '../store'
import type { NodeInfo } from '../types'

export function NodeCard({ node }: { node: NodeInfo }) {
  const colorOf = useCluster((s) => s.colorOf)
  const refresh = useCluster((s) => s.refresh)
  const [busy, setBusy] = useState(false)
  const color = colorOf(node.node_id)

  const kill = async () => {
    setBusy(true)
    try {
      await api.killNode(node.node_id)
    } catch {
      /* the node dies mid-response; that is the expected path */
    } finally {
      setTimeout(() => { void refresh(); setBusy(false) }, 600)
    }
  }

  const fill = node.storage?.memtable_fill_pct ?? 0

  return (
    <div className="rounded-xl border p-4 flex flex-col gap-3"
         style={{
           background: 'var(--color-panel)',
           borderColor: node.reachable ? 'var(--color-edge)' : 'var(--color-bad)',
         }}>
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: color }} />
        <span className="font-semibold">{node.node_id}</span>
        <span className="ml-auto text-xs font-medium"
              style={{ color: node.reachable ? 'var(--color-good)' : 'var(--color-bad)' }}>
          {node.reachable ? '● alive' : '✕ dead'}
        </span>
      </div>

      <div className="text-xs text-ink-3 font-mono">{node.address}</div>

      {node.reachable ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">{node.key_count}</span>
            <span className="text-xs text-ink-3">keys stored</span>
          </div>

          <div className="flex gap-1.5 flex-wrap text-[11px]">
            <span className="px-1.5 py-0.5 rounded border border-edge text-ink-2">
              primary for <b className="text-ink">{node.primary_for}</b>
            </span>
            <span className="px-1.5 py-0.5 rounded border border-edge text-ink-2">
              replica for <b className="text-ink">{node.replica_for}</b>
            </span>
          </div>

          {node.storage && (
            <div>
              <div className="flex justify-between text-[11px] text-ink-3 mb-1">
                <span>memtable</span>
                <span className="tabular-nums">
                  {node.storage.memtable_entries}/{node.storage.memtable_limit}
                  {node.storage.sstable_count > 0 &&
                    ` · ${node.storage.sstable_count} sstables`}
                </span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden"
                   style={{ background: 'var(--color-panel-2)' }}>
                <div className="h-full rounded-full transition-all"
                     style={{ width: `${Math.min(fill, 100)}%`, background: color }} />
              </div>
            </div>
          )}

          <button
            onClick={kill} disabled={busy}
            className="mt-auto self-start text-xs px-2.5 py-1 rounded border
                       border-edge text-ink-2 hover:text-[var(--color-bad)]
                       hover:border-[var(--color-bad)] transition-colors
                       disabled:opacity-40 cursor-pointer">
            {busy ? 'crashing…' : '💥 crash node'}
          </button>
        </>
      ) : (
        <div className="text-xs text-ink-3 py-2">
          unreachable — keys served by replicas
          <div className="mt-1">auto-restarts in ~10 s</div>
        </div>
      )}
    </div>
  )
}
