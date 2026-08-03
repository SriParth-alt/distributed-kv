# PyKV — Distributed Key-Value Store

Fault-tolerant, horizontally scalable KV store built from scratch in Python.
Consistent hashing · leader-follower replication · WAL + LSM storage · heartbeat
failure detection · coordinator-free smart client.

> Full architecture, tech stack, design decisions, and resume bullets: **[DESIGN.md](DESIGN.md)**

## Quick Start

```bash
pip install fastapi uvicorn requests pytest

# terminal 1 — start a 3-node cluster (replication factor 2)
python launch_cluster.py --nodes 3

# terminal 2 — run the demo (write/distribute/failover)
python demo.py
```

Expected demo output:
```
1) WRITE 30 keys — consistent hashing spreads them: node1:13 node2:10 node3:7
2) READ all 30 back — 30/30 succeeded
3) FAILOVER — node1 killed → 30/30 reads STILL succeed (served by replicas)
```

## Dashboard

Every node serves a live dashboard at its root URL — open **http://127.0.0.1:8001**
while the cluster is running. It shows the consistent hash ring (vnode ticks +
key positions), per-node health and key counts, and lets you PUT/GET/DELETE keys
and crash nodes to watch failover happen in real time.

## Deploy to AWS

One t3.micro EC2 instance runs the whole 3-node cluster + dashboard (port 8001):

```powershell
# prereqs: AWS CLI configured, repo pushed to GitHub
.\deploy\deploy_ec2.ps1 -RepoUrl https://github.com/<you>/distributed-kv.git
```

The script picks the latest Amazon Linux 2023 AMI, opens port 8001, and boots
the cluster under systemd (`--revive 15` auto-restarts crashed nodes so the
public failover demo is self-healing). It prints the dashboard URL and the
teardown command when done.

## Use it directly

```bash
# CLI
M='{"node1":"127.0.0.1:8001","node2":"127.0.0.1:8002","node3":"127.0.0.1:8003"}'
python -m kvstore.client --members "$M" put user:42 "parth"
python -m kvstore.client --members "$M" get user:42

# or curl any node — nodes forward to the right owner
curl -X PUT http://127.0.0.1:8002/kv/hello -H 'Content-Type: application/json' -d '{"value":"world"}'
curl http://127.0.0.1:8001/kv/hello
curl http://127.0.0.1:8001/internal/status
```

## Tests

```bash
python -m pytest tests/ -v     # 8 tests: ring distribution, minimal remapping,
                               # WAL replay, SSTable reads, tombstones
```

## Project layout

```
kvstore/hashring.py   consistent hash ring, 150 vnodes/node, O(log V) lookup
kvstore/storage.py    WAL -> memtable -> SSTables (mini-LSM), crash recovery
kvstore/cluster.py    membership + heartbeat failure detection (1s beat / 3s dead)
kvstore/node.py       FastAPI node: public /kv API + internal replicate/heartbeat
kvstore/client.py     smart client: local hashing, replica retry, no coordinator
launch_cluster.py     spawn N local nodes
demo.py               distribution + replication + kill-node failover demo
tests/test_kv.py      unit tests
```
