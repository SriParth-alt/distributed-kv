/** Global cluster state (Zustand) — shared by every page, no prop drilling.
 *
 * A single poller keeps nodes/ring/metrics fresh; the WebSocket hook pushes
 * live events into the same store so views stay in sync.
 */
import { create } from 'zustand'
import { api } from './api'
import type { ClusterEvent, ClusterMetrics, ClusterNodes, ClusterRing } from './types'

const EVENT_LIMIT = 250

/** Stable per-node colors (validated categorical palette). */
const PALETTE = ['#3987e5', '#eb6834', '#1baf7a', '#eda100',
                 '#e87ba4', '#12a150', '#9085e9', '#e66767']

interface ClusterStore {
  nodes: ClusterNodes | null
  ring: ClusterRing | null
  metrics: ClusterMetrics | null
  events: ClusterEvent[]
  connected: boolean
  error: string | null
  lastUpdated: number | null

  colorOf: (nodeId: string) => string
  refresh: () => Promise<void>
  pushEvent: (e: ClusterEvent) => void
  setConnected: (c: boolean) => void
}

export const useCluster = create<ClusterStore>((set, get) => ({
  nodes: null,
  ring: null,
  metrics: null,
  events: [],
  connected: false,
  error: null,
  lastUpdated: null,

  colorOf: (nodeId) => {
    const ids = Object.keys(get().nodes?.members ?? {}).sort()
    const i = ids.indexOf(nodeId)
    return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]
  },

  refresh: async () => {
    try {
      const [nodes, ring, metrics] = await Promise.all([
        api.nodes(), api.ring(), api.metrics(),
      ])
      set({ nodes, ring, metrics, error: null, lastUpdated: Date.now() })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'cluster unreachable' })
    }
  },

  pushEvent: (e) =>
    set((s) => {
      // de-dupe: peers are polled and may resend an event already streamed
      if (s.events.some((x) => x.seq === e.seq && x.node === e.node)) return s
      return { events: [e, ...s.events].slice(0, EVENT_LIMIT) }
    }),

  setConnected: (connected) => set({ connected }),
}))
