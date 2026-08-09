/** Types mirroring the Helix FastAPI schema (see /docs on any node). */

export interface StorageStats {
  wal_bytes: number
  wal_entries: number
  memtable_entries: number
  memtable_limit: number
  memtable_fill_pct: number
  sstable_count: number
  sstables: { file: string; keys: number; bytes: number }[]
  live_keys: number
}

export interface NodeInfo {
  node_id: string
  address: string
  reachable: boolean
  key_count: number
  keys: string[]
  storage: StorageStats | null
  primary_for: number
  replica_for: number
  role: 'primary' | 'follower'
  alive: Record<string, boolean>
}

export interface ClusterNodes {
  asked: string
  replication: number
  members: Record<string, string>
  alive: Record<string, boolean>
  live_count: number
  nodes: NodeInfo[]
}

export interface RingVNode { pos: number; node: string }
export interface RingKey { key: string; pos: number; replicas: string[] }

export interface ClusterRing {
  vnodes: RingVNode[]
  vnodes_per_node: number
  arcs: { start: number; end: number; node: string }[]
  keys: RingKey[]
  alive: Record<string, boolean>
  replication: number
}

export interface LatencyStats {
  ops_per_sec: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  count: number
}

export interface ThroughputPoint {
  t: number
  read: number
  write: number
  delete: number
}

export interface ClusterMetrics {
  node: string
  uptime_seconds: number
  totals: Record<string, number>
  cluster_ops_per_sec: number
  latency: {
    read: LatencyStats
    write: LatencyStats
    delete: LatencyStats
    overall: LatencyStats
  }
  throughput_series: ThroughputPoint[]
  per_node: {
    node_id: string
    reachable: boolean
    key_count: number
    storage: StorageStats | null
    ops_per_sec: number
    read: LatencyStats | null
    write: LatencyStats | null
    totals: Record<string, number> | null
  }[]
}

export type EventType =
  | 'write' | 'delete' | 'read' | 'replicate_in'
  | 'node_up' | 'node_down' | 'node_killed' | 'node_started'

export interface ClusterEvent {
  seq: number
  ts: number
  type: EventType
  node: string
  key?: string
  peer?: string
  primary?: string
  source?: string
  replicas?: string[]
  acks?: string[]
  wal_ms?: number
  latency_ms?: number
  failover?: boolean
  delete?: boolean
  replication_lag_ms?: Record<string, number>
}

export interface KeyReadResult {
  key: string
  value: unknown
  served_by: string
  primary: string
  replicas: string[]
  served_from_replica: boolean
  latency_ms: number
  forwarded_by?: string
}

export interface KeyWriteResult {
  key: string
  primary: string
  acks: string[]
  replication_target: number
  wal_ms: number
  replication_lag_ms: Record<string, number>
  latency_ms: number
  forwarded_by?: string
}

export interface LocateResult {
  key: string
  hash_hex: string
  pos: number
  replicas: string[]
  replication: number
}
