/** WebSocket hook for the live cluster event stream.
 *
 * Streams writes, replication, reads served from replicas, and membership
 * changes from anywhere in the cluster. Reconnects with backoff, and drives
 * a store refresh on structural events so views update without polling fast.
 */
import { useEffect, useRef } from 'react'
import { wsUrl } from '../api'
import { useCluster } from '../store'
import type { ClusterEvent } from '../types'

const STRUCTURAL: ClusterEvent['type'][] =
  ['node_up', 'node_down', 'node_killed', 'node_started']

export function useClusterEvents() {
  const pushEvent = useCluster((s) => s.pushEvent)
  const setConnected = useCluster((s) => s.setConnected)
  const refresh = useCluster((s) => s.refresh)
  const retry = useRef(0)

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout>
    let closed = false

    const connect = () => {
      if (closed) return
      ws = new WebSocket(wsUrl())

      ws.onopen = () => {
        retry.current = 0
        setConnected(true)
      }

      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as ClusterEvent
          pushEvent(event)
          if (STRUCTURAL.includes(event.type)) void refresh()
        } catch {
          /* ignore malformed frame */
        }
      }

      ws.onclose = () => {
        setConnected(false)
        if (closed) return
        const delay = Math.min(1000 * 2 ** retry.current++, 10000)
        timer = setTimeout(connect, delay)
      }

      ws.onerror = () => ws?.close()
    }

    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [pushEvent, setConnected, refresh])
}

/** Single shared poller for REST snapshots (nodes / ring / metrics). */
export function useClusterPolling(intervalMs = 2000) {
  const refresh = useCluster((s) => s.refresh)
  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(id)
  }, [refresh, intervalMs])
}
