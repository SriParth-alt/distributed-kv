/** Metrics — throughput over time, latency percentiles, per-node load. */
import { LatencyChart, NodeOpsChart, ThroughputChart } from '../components/MetricChart'
import { Panel, StatTile } from '../components/ui'
import { useCluster } from '../store'

export function Metrics() {
  const { metrics, colorOf } = useCluster()

  if (!metrics) {
    return <div className="text-ink-3 text-sm py-10 text-center">loading metrics…</div>
  }

  const t = metrics.totals
  const uptime = metrics.uptime_seconds
  const uptimeLabel = uptime > 3600 ? `${(uptime / 3600).toFixed(1)} h`
    : uptime > 60 ? `${(uptime / 60).toFixed(1)} min` : `${uptime.toFixed(0)} s`

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <StatTile label="cluster throughput" value={metrics.cluster_ops_per_sec} unit="ops/s"
                  accent="var(--color-accent)" hint="summed across all nodes" />
        <StatTile label="read p50" value={metrics.latency.read.p50_ms} unit="ms"
                  accent="var(--color-good)"
                  hint={`p99 ${metrics.latency.read.p99_ms} ms`} />
        <StatTile label="write p50" value={metrics.latency.write.p50_ms} unit="ms"
                  hint="includes WAL fsync + replica ack" />
        <StatTile label="uptime" value={uptimeLabel}
                  hint={`${t.errors ?? 0} errors`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Throughput" subtitle="Operations per second, last 60 seconds (cluster-wide).">
          <ThroughputChart data={metrics.throughput_series} />
        </Panel>

        <Panel title="Latency percentiles"
               subtitle={`Measured on ${metrics.node} — averaging percentiles across nodes would not be meaningful.`}>
          <LatencyChart read={metrics.latency.read} write={metrics.latency.write} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-start">
        <Panel title="Load distribution"
               subtitle="Consistent hashing spreads work across nodes.">
          <NodeOpsChart
            data={metrics.per_node.map((n) => ({
              node_id: n.node_id, ops_per_sec: n.ops_per_sec,
            }))}
            colors={colorOf} />
        </Panel>

        <Panel title="Per-node detail">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-ink-3 text-[10px] uppercase tracking-wider">
                <tr>
                  {['node', 'status', 'keys', 'ops/s', 'read p50', 'write p50', 'wal', 'sstables']
                    .map((h) => <th key={h} className="text-left py-1.5 pr-3">{h}</th>)}
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {metrics.per_node.map((n) => (
                  <tr key={n.node_id} className="border-t"
                      style={{ borderColor: 'var(--color-edge)' }}>
                    <td className="py-1.5 pr-3">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-sm"
                              style={{ background: colorOf(n.node_id) }} />
                        {n.node_id}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3"
                        style={{ color: n.reachable ? 'var(--color-good)' : 'var(--color-bad)' }}>
                      {n.reachable ? 'alive' : 'dead'}
                    </td>
                    <td className="py-1.5 pr-3">{n.key_count}</td>
                    <td className="py-1.5 pr-3">{n.ops_per_sec}</td>
                    <td className="py-1.5 pr-3">{n.read?.p50_ms ?? '—'}</td>
                    <td className="py-1.5 pr-3">{n.write?.p50_ms ?? '—'}</td>
                    <td className="py-1.5 pr-3">{n.storage?.wal_entries ?? '—'}</td>
                    <td className="py-1.5 pr-3">{n.storage?.sstable_count ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="Cumulative counters" subtitle="Since cluster start.">
        <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 text-sm">
          {[
            ['reads', t.reads], ['writes', t.writes], ['deletes', t.deletes],
            ['replications', t.replications_sent], ['repl. failed', t.replications_failed],
            ['replica reads', t.failovers],
          ].map(([label, value]) => (
            <div key={label as string}>
              <div className="text-[11px] uppercase tracking-wider text-ink-3">{label}</div>
              <div className="text-lg font-semibold tabular-nums">{value ?? 0}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
