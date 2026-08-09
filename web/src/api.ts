/** Typed Helix API client.
 *
 * Base URL is same-origin by default (the node serves the built app), or
 * VITE_API_BASE when the frontend is deployed separately (e.g. Vercel).
 * An optional API key is sent on writes when the cluster requires auth.
 */
import type {
  ClusterMetrics, ClusterNodes, ClusterRing, KeyReadResult, KeyWriteResult,
  LocateResult,
} from './types'

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

const KEY_STORAGE = 'helix.apiKey'
export const getApiKey = () => localStorage.getItem(KEY_STORAGE) ?? ''
export const setApiKey = (k: string) =>
  k ? localStorage.setItem(KEY_STORAGE, k) : localStorage.removeItem(KEY_STORAGE)

export function wsUrl(path = '/cluster/events'): string {
  const base = API_BASE || window.location.origin
  return base.replace(/^http/, 'ws') + path
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const isWrite = init.method && init.method !== 'GET'
  if (isWrite) {
    headers.set('Content-Type', 'application/json')
    const key = getApiKey()
    if (key) headers.set('X-API-Key', key)
  }
  const res = await fetch(API_BASE + path, { ...init, headers })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(res.status, (body as { detail?: string }).detail ?? res.statusText)
  }
  return body as T
}

export const api = {
  getKey: (key: string) =>
    request<KeyReadResult>(`/keys/${encodeURIComponent(key)}`),

  putKey: (key: string, value: unknown) =>
    request<KeyWriteResult>(`/keys/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),

  deleteKey: (key: string) =>
    request<KeyWriteResult>(`/keys/${encodeURIComponent(key)}`, { method: 'DELETE' }),

  locate: (key: string) =>
    request<LocateResult>(`/cluster/locate/${encodeURIComponent(key)}`),

  nodes: () => request<ClusterNodes>('/cluster/nodes'),
  ring: () => request<ClusterRing>('/cluster/ring'),
  metrics: () => request<ClusterMetrics>('/cluster/metrics'),

  killNode: (nodeId: string) =>
    request<{ ok: boolean; dying: string }>(`/cluster/nodes/${nodeId}/kill`, {
      method: 'POST',
    }),
}
