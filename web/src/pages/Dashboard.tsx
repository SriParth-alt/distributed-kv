/** Cluster Dashboard — ring visualization, node health, live event stream. */
import { useState } from 'react'
import { HashRing } from '../components/HashRing'
import { NodeCard } from '../components/NodeCard'
import { EventFeed } from '../components/EventFeed'
import { Panel, StatTile } from '../components/ui'
import { useCluster } from '../store'

export function Dashboard() {
  const { nodes, ring, metrics, colorOf } = useCluster()
  const [selected, setSelected] = useState<string | null>(null)

  if (!nodes || !ring) {
    return <div className="text-ink-3 text-sm py-10 text-center">connecting to cluster…</div>
  }

  const degraded = nodes.live_count < Object.keys(nodes.members).length

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <StatTile label="cluster status"
                  value={degraded ? 'degraded' : 'healthy'}
                  accent={degraded ? 'var(--color-warn)' : 'var(--color-good)'}
                  hint={`${nodes.live_count} of ${Object.keys(nodes.members).length} nodes alive`} />
        <StatTile label="keys" value={ring.keys.length}
                  hint={`replicated ×${ring.replication}`} />
        <StatTile label="throughput" value={metrics?.cluster_ops_per_sec ?? 0} unit="ops/s"
                  hint="cluster-wide, 120 s window" />
        <StatTile label="virtual nodes" value={ring.vnodes.length}
                  hint={`${ring.vnodes_per_node} per physical node`} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {nodes.nodes.map((n) => <NodeCard key={n.node_id} node={n} />)}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)] items-start">
        <Panel title="Consistent hash ring"
               subtitle="Ticks are virtual nodes; outer dots are keys at their hash position."
               right={
                 <div className="flex gap-3 text-[11px]">
                   {Object.keys(nodes.members).sort().map((id) => (
                     <span key={id} className="flex items-center gap-1.5"
                           style={{ opacity: nodes.alive[id] ? 1 : 0.4 }}>
                       <span className="h-2 w-2 rounded-sm"
                             style={{ background: colorOf(id) }} />
                       <span className={nodes.alive[id] ? 'text-ink-2' : 'line-through text-ink-3'}>
                         {id}
                       </span>
                     </span>
                   ))}
                 </div>
               }>
          <HashRing ring={ring} highlightKey={selected} onSelectKey={setSelected} />
        </Panel>

        <Panel title="Live cluster events"
               subtitle="Streamed over WebSocket from every node."
               className="h-[520px] flex flex-col">
          <EventFeed limit={80} />
        </Panel>
      </div>
    </div>
  )
}
