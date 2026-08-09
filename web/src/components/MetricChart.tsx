/** Recharts wrappers styled for the dashboard: throughput area + latency bars. */
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import type { LatencyStats, ThroughputPoint } from '../types'

const axis = { stroke: 'var(--color-ink-3)', fontSize: 11 }
const tooltipStyle = {
  background: 'var(--color-panel-2)',
  border: '1px solid var(--color-edge)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--color-ink)',
}

export function ThroughputChart({ data }: { data: ThroughputPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
        <defs>
          {[['w', 'var(--color-accent)'], ['r', 'var(--color-good)'],
            ['d', 'var(--color-warn)']].map(([id, color]) => (
            <linearGradient key={id} id={`g-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.45} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="var(--color-edge)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="t" tick={axis} tickLine={false} axisLine={false}
               tickFormatter={(t: number) => (t === 0 ? 'now' : `${t}s`)} />
        <YAxis tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle}
                 labelFormatter={(t) => (t === 0 ? 'now' : `${t}s ago`)} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--color-ink-2)' }} />
        <Area type="monotone" dataKey="write" stackId="1" name="writes"
              stroke="var(--color-accent)" fill="url(#g-w)" strokeWidth={2} />
        <Area type="monotone" dataKey="read" stackId="1" name="reads"
              stroke="var(--color-good)" fill="url(#g-r)" strokeWidth={2} />
        <Area type="monotone" dataKey="delete" stackId="1" name="deletes"
              stroke="var(--color-warn)" fill="url(#g-d)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export function LatencyChart({ read, write }: { read: LatencyStats; write: LatencyStats }) {
  const data = [
    { pct: 'p50', read: read.p50_ms, write: write.p50_ms },
    { pct: 'p95', read: read.p95_ms, write: write.p95_ms },
    { pct: 'p99', read: read.p99_ms, write: write.p99_ms },
  ]
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
        <CartesianGrid stroke="var(--color-edge)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="pct" tick={axis} tickLine={false} axisLine={false} />
        <YAxis tick={axis} tickLine={false} axisLine={false}
               tickFormatter={(v: number) => `${v}ms`} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v} ms`}
                 cursor={{ fill: 'var(--color-panel-2)' }} />
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--color-ink-2)' }} />
        <Bar dataKey="read" name="reads" fill="var(--color-good)" radius={[4, 4, 0, 0]}
             maxBarSize={38} />
        <Bar dataKey="write" name="writes (durable + replicated)"
             fill="var(--color-accent)" radius={[4, 4, 0, 0]} maxBarSize={38} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function NodeOpsChart({ data, colors }: {
  data: { node_id: string; ops_per_sec: number }[]
  colors: (id: string) => string
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
        <CartesianGrid stroke="var(--color-edge)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="node_id" tick={axis} tickLine={false} axisLine={false} />
        <YAxis tick={axis} tickLine={false} axisLine={false} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v} ops/s`}
                 cursor={{ fill: 'var(--color-panel-2)' }} />
        <Bar dataKey="ops_per_sec" radius={[4, 4, 0, 0]} maxBarSize={54}>
          {data.map((d) => <Cell key={d.node_id} fill={colors(d.node_id)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
