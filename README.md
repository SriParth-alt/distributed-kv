# Helix — Distributed Key-Value Store

A fault-tolerant, horizontally scalable key-value store built from scratch in
Python, with a **React + TypeScript** dashboard for live cluster visualisation.

Consistent hashing · leader-follower replication · WAL + LSM storage · heartbeat
failure detection · REST + WebSocket API · coordinator-free smart client.

> Architecture, design decisions, and trade-offs: **[DESIGN.md](DESIGN.md)**

## Architecture

```
   ┌──────────────────────────────────────────────────────────┐
   │  React + TypeScript dashboard (Vite, Tailwind, Zustand)  │
   │  ring viz · KV explorer · LSM internals · metrics        │
   └───────────────┬──────────────────────┬───────────────────┘
        REST (typed client)        WebSocket (live events)
   ┌───────────────▼──────────────────────▼───────────────────┐
   │  FastAPI layer  /keys · /cluster/* · WS /cluster/events  │
   │  API-key auth on writes · CORS · OpenAPI schema          │
   └───────────────┬──────────────────────────────────────────┘
   ┌───────────────▼──────────────────────────────────────────┐
   │  Helix core                                              │
   │  HashRing (150 vnodes/node)  ClusterState (heartbeats)   │
   │  StorageEngine: WAL → memtable → SSTables                │
   └──────────────────────────────────────────────────────────┘
             node1 ◄──── replication + heartbeats ────► node2 ◄──► node3
```

## Quick start

```bash
pip install -r requirements.txt

# terminal 1 — 3-node cluster (replication factor 2)
python launch_cluster.py --nodes 3 --revive 10

# terminal 2 — React dashboard on http://localhost:5173
cd web && npm install && npm run dev
```

Or run the whole thing in Docker (one container per node, DNS discovery, the
dashboard built in):

```bash
docker compose up -d --build
```

Dashboard at **http://localhost:8001** — any node's port serves it.

## The dashboard

| Page | What it shows |
|---|---|
| **Cluster** (`/`) | Hash-ring visualisation (vnode ticks + key placement), node health cards with live key counts and memtable fill, and a WebSocket event feed covering the whole cluster. Crash any node and watch failover. |
| **KV Explorer** (`/explore`) | PUT/GET/DELETE against the live cluster. Shows the key's MD5, its ring position, the clockwise walk to primary + replicas, and per-write WAL fsync and replication-lag timings. |
| **Internals** (`/internals`) | Per-node LSM state: WAL entries/bytes, memtable fill, SSTable levels — plus the live replication stream. |
| **Metrics** (`/metrics`) | Cluster throughput over time, latency percentiles, per-node load distribution (Recharts). |

## API

Interactive OpenAPI docs on any node: **http://localhost:8001/docs**

```bash
# keys
curl -X PUT localhost:8001/keys/user:42 -H 'Content-Type: application/json' \
     -d '{"value": {"name": "parth"}}'
curl localhost:8001/keys/user:42

# cluster
curl localhost:8001/cluster/nodes      # membership, health, roles
curl localhost:8001/cluster/ring       # ring state + key placement
curl localhost:8001/cluster/metrics    # throughput, latency, LSM stats
curl localhost:8001/cluster/locate/user:42
```

**Auth:** set `HELIX_API_KEY` on the nodes and writes require
`X-API-Key: <key>` (or `Authorization: Bearer <key>`); reads stay open. Unset =
open demo mode. **CORS:** set `HELIX_CORS_ORIGINS` to your frontend origin.

## Deployment

- **Backend + dashboard, one URL** — [`render.yaml`](render.yaml) runs the full
  cluster behind a single port on Render's free tier. The image picks its mode
  from its arguments, so Blueprint and plain Docker web-service deploys both
  work: with `--id` it runs one node (Compose), with no arguments it runs the
  whole cluster on `$PORT`.
- **Frontend on Vercel** — deploy `web/` with root directory `web`; set
  `VITE_API_BASE` to your backend URL, and `HELIX_CORS_ORIGINS` to the Vercel
  origin on the backend.
- **Docker Compose** — `docker compose up -d --build` for the true
  one-container-per-node topology.
- **AWS EC2** — [`deploy/deploy_ec2.ps1`](deploy/deploy_ec2.ps1) if you want it
  on your own instance.

## Benchmarks

Reproduce with [`bench.py`](bench.py) — N concurrent clients fire a fixed
number of operations, wall time is measured, and **only successful operations
count toward throughput**:

```bash
python launch_cluster.py --nodes 3     # terminal 1
python bench.py --report               # terminal 2
```

**Conditions:** 3 nodes, replication factor 2, 500-key keyspace, 3,000 ops per
run. All three nodes run as separate processes on one machine (Intel i7-13700HX,
24 logical cores, NVMe SSD, Windows) — so this measures the implementation, not
a multi-machine deployment's ceiling. Clients hash keys locally and call the
primary directly (the coordinator-free path). Run-to-run variance < 2%.

| Workload | Clients | Throughput | p50 | p95 | p99 |
|---|--:|--:|--:|--:|--:|
| Read 100% | 8 | **1,840 ops/s** | 4.2 ms | 6.4 ms | 7.5 ms |
| Read 100% | 32 | 1,825 ops/s | 16.2 ms | 26.9 ms | 32.5 ms |
| Write 100% (durable + replicated) | 32 | **1,180 ops/s** | 29.0 ms | 40.2 ms | 49.1 ms |
| Write 100% | 8 | 1,035 ops/s | 7.1 ms | 12.9 ms | 18.7 ms |
| Mixed 90R/10W | 8 | **1,780 ops/s** | 4.1 ms | 7.6 ms | 9.9 ms |
| Single client (read / write) | 1 | 1,120 / 320 ops/s | 0.8 / 2.9 ms | — | — |

Every write is fsync'd to the WAL **and** synchronously replicated before it is
acknowledged, so write throughput is bounded by disk durability plus a replica
round-trip — that is the intended trade-off, not a bottleneck.

**Smart client vs. entry-node routing** — the same 100%-write load at 32
clients, routed two ways:

| Routing | Throughput | p50 |
|---|--:|--:|
| Smart client (hash locally → primary) | 1,180 ops/s | 29 ms |
| Entry node (all requests to node1, forwarded) | 730 ops/s | 38 ms |

Client-side routing is ~1.6× faster because it removes an extra network hop per
misdirected request — the reason the client library owns a copy of the ring.

> Load testing surfaced a real bottleneck: inter-node calls (replication,
> forwarding, heartbeats) each opened a **new TCP connection**, which exhausted
> ephemeral ports under sustained load — ~1,000 failed requests per run at 32
> clients. Pooling those connections eliminated the errors and took forwarded
> writes from 215 → 730 ops/s (3.4×).

## Tests

```bash
python -m pytest tests/ -v     # ring distribution, minimal remapping, WAL
                               # replay, SSTable reads, tombstones
cd web && npm run build        # typechecks the frontend (tsc) + builds
```

## Layout

```
kvstore/hashring.py       consistent hash ring, 150 vnodes/node, O(log V) lookup
kvstore/storage.py        WAL → memtable → SSTables (mini-LSM), crash recovery
kvstore/cluster.py        membership + heartbeat failure detection (1s/3s)
kvstore/observability.py  event bus (WebSocket fan-out) + metrics collection
kvstore/node.py           FastAPI node: REST + WS API, serves the built UI
kvstore/client.py         smart client: local hashing, replica retry
web/src/api.ts            typed API client
web/src/store.ts          Zustand cluster store
web/src/hooks/            useClusterEvents (WebSocket), useClusterPolling
web/src/components/       HashRing, NodeCard, EventFeed, MetricChart
web/src/pages/            Dashboard, Explorer, Internals, Metrics
launch_cluster.py         spawn N local nodes (--revive auto-restarts)
demo.py                   distribution + replication + kill-node failover demo
```
