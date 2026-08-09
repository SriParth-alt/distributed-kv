/** KV Explorer — run operations and see exactly which node served them and why. */
import { useEffect, useState } from 'react'
import { api, ApiError, getApiKey, setApiKey } from '../api'
import { HashRing } from '../components/HashRing'
import { Badge, Panel } from '../components/ui'
import { useCluster } from '../store'
import type { KeyReadResult, KeyWriteResult, LocateResult } from '../types'

type Result =
  | { kind: 'read'; data: KeyReadResult }
  | { kind: 'write'; op: string; data: KeyWriteResult }
  | { kind: 'error'; message: string }

export function Explorer() {
  const { ring, refresh, colorOf } = useCluster()
  const [key, setKey] = useState('user:42')
  const [value, setValue] = useState('{"name": "parth", "score": 99}')
  const [result, setResult] = useState<Result | null>(null)
  const [locate, setLocate] = useState<LocateResult | null>(null)
  const [apiKey, setKeyState] = useState(getApiKey())
  const [busy, setBusy] = useState(false)

  // live hash→node preview as you type: makes consistent hashing tangible
  useEffect(() => {
    if (!key) { setLocate(null); return }
    const id = setTimeout(() => {
      api.locate(key).then(setLocate).catch(() => setLocate(null))
    }, 250)
    return () => clearTimeout(id)
  }, [key])

  const run = async (op: 'GET' | 'PUT' | 'DELETE') => {
    if (!key) return
    setBusy(true)
    try {
      if (op === 'GET') {
        setResult({ kind: 'read', data: await api.getKey(key) })
      } else if (op === 'PUT') {
        let parsed: unknown = value
        try { parsed = JSON.parse(value) } catch { /* plain string is fine */ }
        setResult({ kind: 'write', op, data: await api.putKey(key, parsed) })
      } else {
        setResult({ kind: 'write', op, data: await api.deleteKey(key) })
      }
      void refresh()
    } catch (e) {
      setResult({
        kind: 'error',
        message: e instanceof ApiError ? `${e.status} — ${e.message}` : String(e),
      })
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full rounded-lg border px-3 py-2 text-sm font-mono outline-none ' +
    'focus:border-[var(--color-accent)] transition-colors'
  const inputStyle = { background: 'var(--color-surface)', borderColor: 'var(--color-edge)' }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start">
      <div className="flex flex-col gap-4">
        <Panel title="Operation"
               subtitle="Writes go to the key's primary; reads fall back to replicas.">
          <div className="flex flex-col gap-3">
            <div>
              <label className="text-[11px] text-ink-3 uppercase tracking-wider">key</label>
              <input className={input} style={inputStyle} value={key}
                     onChange={(e) => setKey(e.target.value)} placeholder="user:42" />
            </div>
            <div>
              <label className="text-[11px] text-ink-3 uppercase tracking-wider">
                value <span className="normal-case">(JSON or plain text — PUT only)</span>
              </label>
              <input className={input} style={inputStyle} value={value}
                     onChange={(e) => setValue(e.target.value)} />
            </div>
            <div className="flex gap-2 flex-wrap">
              <button onClick={() => run('PUT')} disabled={busy}
                      className="px-4 py-1.5 rounded-lg text-sm font-medium text-white
                                 disabled:opacity-50 cursor-pointer"
                      style={{ background: 'var(--color-accent)' }}>PUT</button>
              <button onClick={() => run('GET')} disabled={busy}
                      className="px-4 py-1.5 rounded-lg text-sm border cursor-pointer
                                 disabled:opacity-50 hover:text-ink"
                      style={{ borderColor: 'var(--color-edge)' }}>GET</button>
              <button onClick={() => run('DELETE')} disabled={busy}
                      className="px-4 py-1.5 rounded-lg text-sm border cursor-pointer
                                 disabled:opacity-50 hover:text-[var(--color-bad)]"
                      style={{ borderColor: 'var(--color-edge)' }}>DELETE</button>
            </div>
          </div>
        </Panel>

        {locate && (
          <Panel title="Routing preview"
                 subtitle="Computed client-side of the write — the same math the smart client uses.">
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex gap-2 items-center flex-wrap">
                <span className="text-ink-3 text-xs">md5(key) =</span>
                <code className="text-xs text-ink-2 break-all">{locate.hash_hex}</code>
              </div>
              <div className="flex gap-2 items-center flex-wrap">
                <span className="text-ink-3 text-xs">ring position</span>
                <code className="text-xs text-ink-2">
                  {(locate.pos * 100).toFixed(4)}% around the ring
                </code>
              </div>
              <div className="flex gap-2 items-center flex-wrap mt-1">
                <span className="text-xs text-ink-3">walks clockwise to</span>
                {locate.replicas.map((r, i) => (
                  <span key={r} className="flex items-center gap-1.5 text-xs px-2 py-1
                                           rounded border"
                        style={{ borderColor: 'var(--color-edge)' }}>
                    <span className="h-2 w-2 rounded-sm" style={{ background: colorOf(r) }} />
                    {r}
                    <span className="text-ink-3">{i === 0 ? 'primary' : 'replica'}</span>
                  </span>
                ))}
              </div>
            </div>
          </Panel>
        )}

        {result && (
          <Panel title="Response">
            {result.kind === 'error' && (
              <div className="text-sm" style={{ color: 'var(--color-bad)' }}>
                {result.message}
              </div>
            )}

            {result.kind === 'read' && (
              <div className="flex flex-col gap-3">
                <pre className="rounded-lg border p-3 text-xs overflow-x-auto"
                     style={{ background: 'var(--color-surface)',
                              borderColor: 'var(--color-edge)' }}>
{JSON.stringify(result.data.value, null, 2)}</pre>
                <div className="flex gap-2 flex-wrap text-xs">
                  <Badge tone="accent">served by {result.data.served_by}</Badge>
                  <Badge>primary {result.data.primary}</Badge>
                  <Badge>{result.data.latency_ms} ms</Badge>
                  {result.data.served_from_replica && (
                    <Badge tone="bad">failover — primary unreachable</Badge>
                  )}
                  {result.data.forwarded_by && (
                    <Badge>forwarded by {result.data.forwarded_by}</Badge>
                  )}
                </div>
              </div>
            )}

            {result.kind === 'write' && (
              <div className="flex flex-col gap-3">
                <div className="text-sm">
                  <span style={{ color: 'var(--color-good)' }}>{result.op} ok</span>
                  <span className="text-ink-3"> — {result.data.key}</span>
                </div>
                <div className="flex gap-2 flex-wrap text-xs">
                  <Badge tone="accent">primary {result.data.primary}</Badge>
                  <Badge tone="good">
                    acks {result.data.acks.length}/{result.data.replication_target}
                  </Badge>
                  <Badge>wal fsync {result.data.wal_ms} ms</Badge>
                  <Badge>total {result.data.latency_ms} ms</Badge>
                </div>
                {Object.keys(result.data.replication_lag_ms).length > 0 && (
                  <div className="text-xs text-ink-2">
                    replication lag:{' '}
                    {Object.entries(result.data.replication_lag_ms)
                      .map(([n, ms]) => `${n} ${ms}ms`).join(' · ')}
                  </div>
                )}
              </div>
            )}
          </Panel>
        )}

        <Panel title="Auth"
               subtitle="Writes require an API key when the cluster sets HELIX_API_KEY.">
          <div className="flex gap-2">
            <input className={input} style={inputStyle} type="password"
                   placeholder="X-API-Key (blank in open demo mode)"
                   value={apiKey} onChange={(e) => setKeyState(e.target.value)} />
            <button onClick={() => setApiKey(apiKey)}
                    className="px-3 py-1.5 rounded-lg text-sm border shrink-0 cursor-pointer"
                    style={{ borderColor: 'var(--color-edge)' }}>save</button>
          </div>
        </Panel>
      </div>

      <Panel title="Where this key lives"
             subtitle="The selected key is highlighted with its replica set.">
        {ring
          ? <HashRing ring={ring} size={400} highlightKey={key} onSelectKey={setKey} />
          : <div className="text-ink-3 text-sm">loading ring…</div>}
        {ring && ring.keys.length > 0 && (
          <div className="mt-3 max-h-52 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="text-ink-3 text-[10px] uppercase tracking-wider">
                <tr><th className="text-left py-1">key</th>
                    <th className="text-left py-1">primary</th>
                    <th className="text-left py-1">replicas</th></tr>
              </thead>
              <tbody>
                {ring.keys.map((k) => (
                  <tr key={k.key} onClick={() => setKey(k.key)}
                      className="cursor-pointer border-t hover:opacity-80"
                      style={{ borderColor: 'var(--color-edge)' }}>
                    <td className="py-1 font-mono truncate max-w-[130px]">{k.key}</td>
                    <td className="py-1">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-sm"
                              style={{ background: colorOf(k.replicas[0]) }} />
                        {k.replicas[0]}
                      </span>
                    </td>
                    <td className="py-1 text-ink-3">{k.replicas.slice(1).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
