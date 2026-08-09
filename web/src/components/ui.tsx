/** Small shared primitives used across pages. */
import type { ReactNode } from 'react'

export function Panel({ title, subtitle, right, children, className = '' }: {
  title?: string
  subtitle?: string
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border p-4 ${className}`}
             style={{ background: 'var(--color-panel)', borderColor: 'var(--color-edge)' }}>
      {(title || right) && (
        <header className="flex items-center gap-3 mb-3">
          <div>
            {title && (
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                {title}
              </h2>
            )}
            {subtitle && <p className="text-xs text-ink-2 mt-0.5">{subtitle}</p>}
          </div>
          {right && <div className="ml-auto">{right}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function StatTile({ label, value, unit, hint, accent }: {
  label: string
  value: ReactNode
  unit?: string
  hint?: string
  accent?: string
}) {
  return (
    <div className="rounded-xl border p-4"
         style={{ background: 'var(--color-panel)', borderColor: 'var(--color-edge)' }}>
      <div className="text-[11px] uppercase tracking-wider text-ink-3">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <span className="text-2xl font-semibold tabular-nums"
              style={accent ? { color: accent } : undefined}>{value}</span>
        {unit && <span className="text-xs text-ink-3">{unit}</span>}
      </div>
      {hint && <div className="text-[11px] text-ink-3 mt-1">{hint}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'neutral' }: {
  children: ReactNode
  tone?: 'neutral' | 'good' | 'bad' | 'accent'
}) {
  const color = {
    neutral: 'var(--color-ink-3)', good: 'var(--color-good)',
    bad: 'var(--color-bad)', accent: 'var(--color-accent)',
  }[tone]
  return (
    <span className="px-1.5 py-0.5 rounded text-[11px] border"
          style={{ color, borderColor: 'var(--color-edge)' }}>
      {children}
    </span>
  )
}
