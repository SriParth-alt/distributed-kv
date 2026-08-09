/** Consistent-hash ring visualization.
 *
 * Ticks are virtual nodes (150 per physical node); the outer dots are keys at
 * their hash position, colored by current primary owner. Hovering a key shows
 * its replica set; a highlighted key is emphasized and its replicas traced.
 */
import { useMemo, useState } from 'react'
import { useCluster } from '../store'
import type { ClusterRing } from '../types'

interface Props {
  ring: ClusterRing
  size?: number
  highlightKey?: string | null
  onSelectKey?: (key: string) => void
}

const polar = (pos: number, radius: number, c: number) => {
  const a = pos * 2 * Math.PI - Math.PI / 2
  return [c + radius * Math.cos(a), c + radius * Math.sin(a)] as const
}

export function HashRing({ ring, size = 460, highlightKey, onSelectKey }: Props) {
  const colorOf = useCluster((s) => s.colorOf)
  const [hover, setHover] = useState<{ x: number; y: number; key: string } | null>(null)
  const c = size / 2
  const R = size * 0.36
  const TICK = size * 0.028
  const KEY_R = R + size * 0.065

  const highlighted = useMemo(
    () => ring.keys.find((k) => k.key === highlightKey),
    [ring.keys, highlightKey],
  )
  const active = hover ? ring.keys.find((k) => k.key === hover.key) : highlighted

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[460px] mx-auto block">
        <circle cx={c} cy={c} r={R} fill="none" stroke="var(--color-edge)" strokeWidth={1.5} />

        {/* virtual nodes */}
        {ring.vnodes.map((v, i) => {
          const [x1, y1] = polar(v.pos, R - TICK / 2, c)
          const [x2, y2] = polar(v.pos, R + TICK / 2, c)
          const dim = active && !active.replicas.includes(v.node)
          return (
            <line
              key={i} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={colorOf(v.node)} strokeWidth={1.8} strokeLinecap="round"
              opacity={dim ? 0.18 : 0.85}
            />
          )
        })}

        {/* keys */}
        {ring.keys.map((k) => {
          const [x, y] = polar(k.pos, KEY_R, c)
          const isActive = active?.key === k.key
          return (
            <g key={k.key}>
              {isActive && (
                <circle cx={x} cy={y} r={11} fill="none"
                        stroke={colorOf(k.replicas[0])} strokeWidth={1.5} opacity={0.6} />
              )}
              <circle
                cx={x} cy={y} r={isActive ? 6.5 : 4.5}
                fill={colorOf(k.replicas[0])}
                stroke="var(--color-surface)" strokeWidth={1.5}
                className="cursor-pointer transition-all"
                opacity={active && !isActive ? 0.3 : 1}
                onMouseEnter={() => setHover({ x, y, key: k.key })}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelectKey?.(k.key)}
              />
            </g>
          )
        })}

        <text x={c} y={c - 6} textAnchor="middle" className="fill-[var(--color-ink)]"
              fontSize={size * 0.055} fontWeight={600}>
          {ring.keys.length}
        </text>
        <text x={c} y={c + 14} textAnchor="middle" className="fill-[var(--color-ink-3)]"
              fontSize={size * 0.028}>
          keys on ring
        </text>
        <text x={c} y={c + 34} textAnchor="middle" className="fill-[var(--color-ink-3)]"
              fontSize={size * 0.026}>
          {ring.vnodes.length} vnodes · RF={ring.replication}
        </text>
      </svg>

      {active && (
        <div className="absolute left-1/2 -translate-x-1/2 bottom-0 bg-panel-2 border
                        border-edge rounded-lg px-3 py-2 text-xs shadow-lg pointer-events-none"
             style={{ borderColor: 'var(--color-edge)' }}>
          <div className="font-mono text-ink">{active.key}</div>
          <div className="text-ink-2 mt-0.5">
            primary <span style={{ color: colorOf(active.replicas[0]) }}>
              {active.replicas[0]}</span>
            {active.replicas.length > 1 && (
              <> · replica <span style={{ color: colorOf(active.replicas[1]) }}>
                {active.replicas.slice(1).join(', ')}</span></>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
