# Helix — Distributed Key-Value Store

**A fault-tolerant, horizontally scalable key-value store built from scratch in Python**

---

## 1. Project Description

Helix is a distributed key-value storage system that partitions data across multiple
nodes using **consistent hashing**, replicates every key to **N replicas** for fault
tolerance, and survives node failures through **heartbeat-based failure detection**
with automatic request re-routing.

Unlike a single-server cache or a wrapper around Redis, Helix implements the core
distributed-systems machinery itself:

- **Data partitioning** — keys are distributed across nodes via a consistent hash
  ring with virtual nodes, so adding/removing a node only remaps ~1/N of the keys
  (vs. nearly all keys with naive `hash(key) % N` partitioning).
- **Replication** — every write is stored on a primary node and synchronously
  replicated to the next R-1 successors on the ring (leader-follower model).
  Reads can be served by any replica.
- **Durability** — each node persists writes to a **Write-Ahead Log (WAL)** before
  acknowledging, and maintains an in-memory **memtable** (sorted dict) that is
  periodically flushed to immutable **SSTable** files on disk — a simplified
  LSM-tree storage engine, the same design used by Cassandra, RocksDB, and LevelDB.
- **Failure detection** — nodes gossip heartbeats; when a node misses its heartbeat
  window, peers mark it dead, remove it from the ring, and route requests to the
  remaining replicas. Reads/writes keep succeeding as long as ≥1 replica is alive.
- **Smart client** — the client library maintains its own view of the ring, hashes
  keys locally, and talks directly to the correct primary — no central coordinator
  or single point of failure.

### Why this project matters (interview framing)

This directly mirrors the Amazon SDE JD line *"Build distributed storage, index,
and query systems that are scalable, fault-tolerant, low cost, and easy to
manage/use."* It demonstrates:

| JD requirement | Where Helix shows it |
|---|---|
| Distributed, multi-tiered systems | Multi-node cluster, smart client tier, storage tier |
| Algorithms & data structures | Consistent hashing, sorted memtable, binary-searched SSTables, WAL replay |
| Fault tolerance | Replication + heartbeat failure detection + automatic failover |
| Scalability | Virtual-node hash ring → minimal data movement on scale-out |
| Complexity analysis | O(log V) key lookup on ring, O(log n) memtable ops, O(log n) SSTable search |

---

## 2. Tech Stack — and what each part does

| Technology | Role in the project | Why chosen |
|---|---|---|
| **Python 3.12** | Implementation language for all components | Your strongest language; readable for interview walkthroughs |
| **FastAPI** | HTTP server framework running on every node — exposes `/kv/{key}` (client API) and `/internal/*` (replication, heartbeats) | Async-capable, minimal boilerplate, auto-generated OpenAPI docs |
| **Uvicorn** | ASGI server that runs each FastAPI node process | Production-grade async server, one command per node |
| **httpx / requests** | Inter-node HTTP calls (replication fan-out, heartbeats) and client → node calls | Simple, dependency-light RPC via REST |
| **hashlib (MD5)** | Hash function for the consistent hash ring | Uniform distribution, deterministic across processes |
| **bisect (stdlib)** | Binary search over the sorted ring and SSTable indexes | O(log n) lookups — the "algorithms" story in the project |
| **JSON-lines WAL files** | Write-ahead log: every mutation appended to disk before ack | Crash durability; replayed on restart to rebuild the memtable |
| **SSTable files (JSON, sorted)** | Immutable on-disk sorted files flushed from the memtable | Simplified LSM-tree — same lineage as LevelDB/Cassandra |
| **threading (stdlib)** | Background heartbeat loop + memtable flush lock | Concurrency-safety story for interviews |
| **pytest** | Unit tests for hash ring, storage engine, and cluster behavior | Shows engineering rigor |

### No external database, no Redis, no Kafka — by design.
The entire point is that the distributed machinery is **implemented, not imported**.

---

## 3. Architecture

```
                        ┌─────────────┐
                        │ Smart Client│  hashes key locally,
                        │  (client.py)│  picks primary from ring
                        └──────┬──────┘
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
      ┌────────────┐    ┌────────────┐    ┌────────────┐
      │  Node A    │◄──►│  Node B    │◄──►│  Node C    │   heartbeats +
      │ :8001      │    │ :8002      │    │ :8003      │   replication
      ├────────────┤    ├────────────┤    ├────────────┤
      │ HashRing   │    │ HashRing   │    │ HashRing   │  (each node has
      │ Memtable   │    │ Memtable   │    │ Memtable   │   full ring view)
      │ WAL        │    │ WAL        │    │ WAL        │
      │ SSTables   │    │ SSTables   │    │ SSTables   │
      └────────────┘    └────────────┘    └────────────┘
```

**Write path:** client hashes key → sends PUT to primary → primary appends to WAL
→ updates memtable → synchronously replicates to R-1 successors → ACKs client.

**Read path:** client hashes key → GET from primary → if primary is down, client
retries against replicas in ring order.

**Failure path:** Node B dies → A and C miss its heartbeats → mark B dead →
remove from live ring → keys owned by B are served by their replicas on A/C.

---

## 4. Component Map (file by file)

| File | Component | What it does |
|---|---|---|
| `kvstore/hashring.py` | **Consistent Hash Ring** | Maps keys → nodes with virtual nodes (default 150/node). `get_nodes(key, n)` returns primary + replica successors via binary search on the sorted ring. |
| `kvstore/storage.py` | **Storage Engine (mini-LSM)** | WAL append → memtable insert → flush to sorted SSTable when memtable exceeds threshold. Reads check memtable first, then SSTables newest-to-oldest. Tombstones handle deletes. WAL replay on startup restores un-flushed state. |
| `kvstore/cluster.py` | **Cluster Membership + Failure Detector** | Static seed membership; background thread sends heartbeats to peers every 1s; marks peers dead after 3 missed windows; rebuilds the live ring on membership change. |
| `kvstore/node.py` | **Node Server (FastAPI)** | Public API: `GET/PUT/DELETE /kv/{key}`. Internal API: `/internal/replicate`, `/internal/heartbeat`, `/internal/status`. Enforces "am I the right owner?" and forwards misdirected requests. |
| `kvstore/client.py` | **Smart Client** | Library + CLI. Keeps a ring replica, hashes locally, retries across replicas on failure, refreshes membership from any live node. |
| `launch_cluster.py` | **Cluster Launcher** | Spawns an N-node cluster locally (separate processes, separate data dirs). |
| `demo.py` | **Demo Script** | Seeds data, shows distribution across nodes, kills a node, proves reads still succeed — the exact demo to run in an interview. |
| `tests/test_kv.py` | **Tests** | Ring distribution/remapping, storage durability (WAL replay), SSTable reads, tombstone deletes. |

---

## 5. Key Design Decisions (talking points)

1. **Consistent hashing with virtual nodes** — plain modulo hashing remaps ~100%
   of keys when a node joins/leaves; consistent hashing remaps ~K/N. Virtual
   nodes fix the uneven-distribution problem of raw consistent hashing.
2. **Synchronous replication (R=2 default)** — chosen for read-your-writes
   simplicity over async replication's lower latency. Tradeoff is explicitly
   documented — interviewers love hearing you *chose*, not stumbled.
3. **WAL before memtable** — the durability contract: a write is only ACKed after
   it's on disk. Crash between ACK and flush? WAL replay recovers it.
4. **LSM-style storage over B-tree** — append-only writes are sequential I/O
   (fast); reads pay a small cost checking multiple SSTables. Write-optimized,
   like Cassandra.
5. **Smart client over central router** — a router/coordinator is a single point
   of failure and a bandwidth bottleneck; client-side routing scales linearly.

## 6. Known Limitations (be upfront in interviews)

- No consensus protocol (Raft/Paxos) — membership is heartbeat-based, so network
  partitions can cause split-brain. Fine for a portfolio scope; name-drop Raft as
  the next step.
- Synchronous replication blocks on slowest replica.
- No SSTable compaction (files accumulate; compaction is a documented TODO).
- No re-replication after permanent node loss (replica count degrades).

Each limitation is a *feature* in interviews: it shows you know where the edges are.

## 7. Resume Bullet (ready to paste)

> **Helix — Distributed Key-Value Store** | Python · FastAPI · Consistent Hashing · LSM Storage
> - Built a fault-tolerant distributed KV store from scratch: consistent-hash partitioning (150 virtual nodes/node), leader-follower replication (R=2), and heartbeat failure detection with automatic failover across a multi-node cluster.
> - Implemented an LSM-tree-style storage engine with write-ahead logging, in-memory sorted memtable, and immutable SSTables — achieving crash durability with O(log n) reads verified by WAL-replay tests.
> - Designed a coordinator-free smart client that hashes keys locally and retries across replicas, keeping reads available through single-node failures (demonstrated via automated kill-node demo).
