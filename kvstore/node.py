"""Helix node server — distributed KV core behind a REST + WebSocket API.

Public REST API (versioned surface consumed by the React dashboard):
    GET/PUT/DELETE /keys/{key}      key operations (writes require API key
                                    when HELIX_API_KEY is set)
    GET  /cluster/nodes             membership, health, per-node role & storage
    GET  /cluster/ring              consistent-hash ring state + key placement
    GET  /cluster/metrics           throughput, latency percentiles, LSM stats
    WS   /cluster/events            live cluster event stream (cluster-wide)

Legacy/compat:
    GET/PUT/DELETE /kv/{key}        original paths (still used by the CLI client)
    GET  /internal/status           cluster view (also used by the smart client)

Internal API (node <-> node):
    POST /internal/replicate        replica write (no further fan-out)
    POST /internal/heartbeat        liveness ping
    GET  /internal/events           event history, polled by the entry node so
                                    the WS feed covers the whole cluster
    POST /internal/die              crash this node (failover demo)

Ownership rule: a node handles a client write only if it is the key's primary;
otherwise it forwards to the primary (client normally hits the right node
directly, but forwarding makes every node a valid entry point).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import requests
import uvicorn
from fastapi import (Body, Depends, FastAPI, Header, HTTPException, WebSocket,
                     WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cluster import ClusterState
from .hashring import _hash
from .observability import EventBus, Metrics
from .storage import StorageEngine

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The event bus publishes from sync request handlers and the heartbeat
    # thread, so it needs the server's running loop to fan out to WebSockets.
    bus.bind_loop(asyncio.get_running_loop())
    bus.publish("node_started", node=state.node_id)
    yield


app = FastAPI(
    title="Helix API",
    description="Distributed key-value store: consistent hashing, "
                "leader-follower replication, WAL + LSM storage.",
    version="1.0.0",
    lifespan=lifespan,
)

state: ClusterState = None  # type: ignore
store: StorageEngine = None  # type: ignore
bus = EventBus()
metrics = Metrics()

RING_SPAN = 2 ** 128  # md5 hash space; ring positions normalized to [0,1)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
API_KEY = os.environ.get("HELIX_API_KEY", "")  # unset => open demo mode

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in
                   os.environ.get("HELIX_CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------- auth
def require_write_auth(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Writes require an API key when HELIX_API_KEY is configured.

    Accepts `X-API-Key: <key>` or `Authorization: Bearer <key>`. When the env
    var is unset the cluster runs open (public demo mode).
    """
    if not API_KEY:
        return
    supplied = x_api_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if supplied != API_KEY:
        metrics.bump("errors")
        raise HTTPException(status_code=401, detail="invalid or missing API key")


# ------------------------------------------------------------------ key ops
def _do_get(key: str):
    t0 = time.perf_counter()
    replicas = state.replicas_for(key)
    if state.node_id in replicas:
        value = store.get(key)
        elapsed = (time.perf_counter() - t0) * 1000
        metrics.record("read", elapsed, ok=value is not None)
        if value is None:
            raise HTTPException(status_code=404, detail="key not found")
        served_from_replica = replicas[0] != state.node_id
        bus.publish("read", key=key, node=state.node_id,
                    primary=replicas[0], failover=served_from_replica,
                    latency_ms=round(elapsed, 2))
        if served_from_replica:
            metrics.bump("failovers")
        return {"key": key, "value": value, "served_by": state.node_id,
                "primary": replicas[0], "replicas": replicas,
                "served_from_replica": served_from_replica,
                "latency_ms": round(elapsed, 2)}
    return _forward("GET", replicas[0], key)


def _do_put(key: str, body: dict):
    if "value" not in body:
        raise HTTPException(status_code=400, detail='body must be {"value": ...}')
    replicas = state.replicas_for(key)
    if not replicas:
        raise HTTPException(status_code=503, detail="no live nodes")
    if state.node_id == replicas[0]:
        return _primary_write(key, body["value"], replicas)
    return _forward("PUT", replicas[0], key, body)


def _do_delete(key: str):
    replicas = state.replicas_for(key)
    if not replicas:
        raise HTTPException(status_code=503, detail="no live nodes")
    if state.node_id == replicas[0]:
        return _primary_write(key, None, replicas, is_delete=True)
    return _forward("DELETE", replicas[0], key)


@app.get("/keys/{key}", tags=["keys"], summary="Read a key")
def api_get_key(key: str):
    return _do_get(key)


@app.put("/keys/{key}", tags=["keys"], summary="Write a key",
         dependencies=[Depends(require_write_auth)])
def api_put_key(key: str, body: dict = Body(...)):
    return _do_put(key, body)


@app.delete("/keys/{key}", tags=["keys"], summary="Delete a key",
            dependencies=[Depends(require_write_auth)])
def api_delete_key(key: str):
    return _do_delete(key)


# legacy paths kept working for the CLI client, demo script and tests
@app.get("/kv/{key}", include_in_schema=False)
def get_key(key: str):
    return _do_get(key)


@app.put("/kv/{key}", include_in_schema=False)
def put_key(key: str, body: dict = Body(...)):
    return _do_put(key, body)


@app.delete("/kv/{key}", include_in_schema=False)
def delete_key(key: str):
    return _do_delete(key)


# -------------------------------------------------------------------- cluster
def _key_placement() -> list[dict]:
    """Every known key with its ring position and current replica set."""
    seen: dict[str, dict] = {}
    for n in _gather_nodes():
        for k in n.get("keys", []):
            if k not in seen:
                seen[k] = {"key": k, "pos": _hash(k) / RING_SPAN,
                           "replicas": state.replicas_for(k)}
    return sorted(seen.values(), key=lambda x: x["pos"])


def _gather_nodes() -> list[dict]:
    """Status of every member, fetched server-side (no CORS/mixed-content)."""
    nodes = []
    for peer, addr in state.members.items():
        if peer == state.node_id:
            s = status()
            s["reachable"] = True
            nodes.append(s)
            continue
        try:
            s = requests.get(f"http://{addr}/internal/status", timeout=1.0).json()
            s["reachable"] = True
        except requests.RequestException:
            s = {"node_id": peer, "reachable": False, "key_count": 0, "keys": [],
                 "alive": {}, "storage": None}
        nodes.append(s)
    return nodes


@app.get("/cluster/nodes", tags=["cluster"], summary="Membership and health")
def cluster_nodes():
    nodes = _gather_nodes()
    placement = _key_placement()
    primary_counts: dict[str, int] = {}
    replica_counts: dict[str, int] = {}
    for k in placement:
        if k["replicas"]:
            primary_counts[k["replicas"][0]] = primary_counts.get(k["replicas"][0], 0) + 1
            for r in k["replicas"][1:]:
                replica_counts[r] = replica_counts.get(r, 0) + 1

    enriched = []
    for n in nodes:
        nid = n["node_id"]
        enriched.append({
            **n,
            "address": state.members.get(nid, ""),
            # leadership here is per-key-range, not cluster-wide: a node is
            # primary (leader) for the ranges it owns and follower for others
            "primary_for": primary_counts.get(nid, 0),
            "replica_for": replica_counts.get(nid, 0),
            "role": ("primary" if primary_counts.get(nid, 0) >= replica_counts.get(nid, 0)
                     else "follower"),
        })
    return {
        "asked": state.node_id,
        "replication": state.replication,
        "members": state.members,
        "alive": dict(state.alive),
        "live_count": sum(1 for v in state.alive.values() if v),
        "nodes": enriched,
    }


@app.get("/cluster/ring", tags=["cluster"], summary="Consistent-hash ring state")
def cluster_ring():
    vnodes = [{"pos": h / RING_SPAN, "node": n} for h, n in state.ring.positions()]
    # contiguous arcs each node owns, derived from consecutive vnode positions
    arcs = []
    for i, v in enumerate(vnodes):
        start = vnodes[i - 1]["pos"] if i else vnodes[-1]["pos"]
        arcs.append({"start": start, "end": v["pos"], "node": v["node"]})
    return {
        "vnodes": vnodes,
        "vnodes_per_node": state.ring.vnodes,
        "arcs": arcs,
        "keys": _key_placement(),
        "alive": dict(state.alive),
        "replication": state.replication,
    }


@app.get("/internal/metrics", include_in_schema=False)
def internal_metrics():
    return metrics.snapshot()


@app.get("/cluster/metrics", tags=["cluster"], summary="Throughput, latency, LSM stats")
def cluster_metrics():
    """Cluster-wide metrics: each node counts the operations it serves as
    primary, so totals and throughput are summed across the whole cluster
    while latency percentiles stay per-node (averaging percentiles is not
    statistically meaningful)."""
    own = metrics.snapshot()
    per_node, snapshots = [], {state.node_id: own}

    for n in _gather_nodes():
        nid = n["node_id"]
        if nid != state.node_id and n.get("reachable"):
            try:
                snapshots[nid] = requests.get(
                    f"http://{state.members[nid]}/internal/metrics", timeout=1.0).json()
            except (requests.RequestException, ValueError):
                pass
        snap = snapshots.get(nid)
        per_node.append({
            "node_id": nid,
            "reachable": n.get("reachable", False),
            "key_count": n.get("key_count", 0),
            "storage": n.get("storage"),
            "ops_per_sec": snap["overall"]["ops_per_sec"] if snap else 0,
            "read": snap["read"] if snap else None,
            "write": snap["write"] if snap else None,
            "totals": snap["totals"] if snap else None,
        })

    totals: dict[str, int] = {}
    for snap in snapshots.values():
        for k, v in snap["totals"].items():
            totals[k] = totals.get(k, 0) + v

    series: dict[int, dict] = {}
    for snap in snapshots.values():
        for point in snap["throughput_series"]:
            acc = series.setdefault(point["t"], {"t": point["t"], "read": 0,
                                                 "write": 0, "delete": 0})
            for op in ("read", "write", "delete"):
                acc[op] += point[op]
    merged_series = [series[t] for t in sorted(series)]

    return {
        "node": state.node_id,
        "uptime_seconds": own["uptime_seconds"],
        "totals": totals,
        "cluster_ops_per_sec": round(
            sum(s["overall"]["ops_per_sec"] for s in snapshots.values()), 2),
        "latency": {"read": own["read"], "write": own["write"],
                    "delete": own["delete"], "overall": own["overall"]},
        "throughput_series": merged_series,
        "per_node": per_node,
    }


@app.get("/cluster/locate/{key}", tags=["cluster"],
         summary="Which nodes own a key, and where it lands on the ring")
def locate(key: str):
    return {"key": key, "hash_hex": f"{_hash(key):032x}",
            "pos": _hash(key) / RING_SPAN,
            "replicas": state.replicas_for(key),
            "replication": state.replication}


@app.post("/cluster/nodes/{node_id}/kill", tags=["cluster"],
          summary="Crash a node (failover demo)",
          dependencies=[Depends(require_write_auth)])
def kill_peer(node_id: str):
    if node_id == state.node_id:
        return die()
    addr = state.members.get(node_id)
    if not addr:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id}")
    try:
        return requests.post(f"http://{addr}/internal/die", timeout=1.5).json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"could not reach {node_id}: {e}")


# ------------------------------------------------------------------ websocket
@app.websocket("/cluster/events")
async def cluster_events(ws: WebSocket):
    """Live cluster-wide event stream.

    Merges this node's local event bus with events polled from peers, so a
    browser connected to any single node sees writes, replication, failover
    and membership changes happening anywhere in the cluster.
    """
    await ws.accept()
    bus.bind_loop(asyncio.get_running_loop())
    q = bus.subscribe()
    seen_peer_seq: dict[str, int] = {}

    async def poll_peers():
        while True:
            for peer, addr in state.members.items():
                if peer == state.node_id:
                    continue
                since = seen_peer_seq.get(peer, 0)
                try:
                    r = await asyncio.to_thread(
                        requests.get,
                        f"http://{addr}/internal/events?since={since}", timeout=1.0)
                    for ev in r.json().get("events", []):
                        seen_peer_seq[peer] = max(seen_peer_seq.get(peer, 0), ev["seq"])
                        await ws.send_json({**ev, "node": ev.get("node", peer)})
                except (requests.RequestException, ValueError, KeyError):
                    pass
            await asyncio.sleep(1.0)

    poller = asyncio.create_task(poll_peers())
    try:
        for ev in bus.history()[-40:]:
            await ws.send_json({**ev, "node": ev.get("node", state.node_id)})
        while True:
            ev = await q.get()
            await ws.send_json({**ev, "node": ev.get("node", state.node_id)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        poller.cancel()
        bus.unsubscribe(q)


@app.get("/internal/events", include_in_schema=False)
def internal_events(since: int = 0):
    events = [e for e in bus.history() if e["seq"] > since]
    return {"node": state.node_id, "events": events}


# -------------------------------------------------------------------- status
@app.get("/internal/status", include_in_schema=False)
def status():
    s = state.status()
    keys = store.keys()
    s["key_count"] = len(keys)
    s["keys"] = keys[:200]
    s["storage"] = store.stats()
    return s


# legacy aggregate endpoints used by the bundled HTML dashboard
@app.get("/internal/cluster", include_in_schema=False)
def cluster_view():
    return {"asked": state.node_id, "replication": state.replication,
            "members": state.members, "alive": dict(state.alive),
            "nodes": _gather_nodes()}


@app.get("/internal/ring", include_in_schema=False)
def ring_view():
    return cluster_ring()


@app.post("/internal/kill/{node_id}", include_in_schema=False)
def kill_peer_legacy(node_id: str):
    return kill_peer(node_id)


# -------------------------------------------------------------------- internal
@app.post("/internal/replicate", include_in_schema=False)
def replicate(body: dict = Body(...)):
    key, value, is_delete = body["key"], body.get("value"), body.get("delete", False)
    t0 = time.perf_counter()
    if is_delete:
        store.delete(key)
    else:
        store.put(key, value)
    bus.publish("replicate_in", key=key, node=state.node_id,
                source=body.get("from"), delete=is_delete,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2))
    return {"ok": True, "replica": state.node_id}


@app.post("/internal/heartbeat", include_in_schema=False)
def heartbeat(body: dict = Body(...)):
    state.mark_alive(body["from"])
    return {"ok": True, "from": state.node_id}


@app.post("/internal/die", include_in_schema=False)
def die():
    """Crash this node on purpose (failover demo button in the dashboard)."""
    bus.publish("node_killed", node=state.node_id)
    threading.Timer(0.3, lambda: os._exit(1)).start()
    return {"ok": True, "dying": state.node_id}


# --------------------------------------------------------------------- helpers
def _primary_write(key: str, value: Any, replicas: list[str], is_delete: bool = False):
    t0 = time.perf_counter()
    # 1. local durable write (WAL fsync -> memtable)
    if is_delete:
        store.delete(key)
    else:
        store.put(key, value)
    local_ms = (time.perf_counter() - t0) * 1000

    # 2. synchronous fan-out to replica successors
    acks = [state.node_id]
    lags = {}
    for peer in replicas[1:]:
        t1 = time.perf_counter()
        try:
            r = requests.post(
                f"http://{state.address(peer)}/internal/replicate",
                json={"key": key, "value": value, "delete": is_delete,
                      "from": state.node_id},
                timeout=1.5,
            )
            if r.ok:
                acks.append(peer)
                lags[peer] = round((time.perf_counter() - t1) * 1000, 2)
                metrics.bump("replications_sent")
        except requests.RequestException:
            metrics.bump("replications_failed")  # replica down; heartbeat marks it

    total_ms = (time.perf_counter() - t0) * 1000
    op = "delete" if is_delete else "write"
    metrics.record(op, total_ms)
    bus.publish(op, key=key, node=state.node_id, primary=state.node_id,
                replicas=replicas, acks=acks, wal_ms=round(local_ms, 2),
                replication_lag_ms=lags, latency_ms=round(total_ms, 2))
    return {"key": key, "primary": state.node_id, "acks": acks,
            "replication_target": len(replicas),
            "wal_ms": round(local_ms, 2),
            "replication_lag_ms": lags,
            "latency_ms": round(total_ms, 2)}


def _forward(method: str, target: str, key: str, body: dict | None = None):
    try:
        r = requests.request(
            method, f"http://{state.address(target)}/kv/{key}",
            json=body, timeout=2.0,
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="key not found")
        r.raise_for_status()
        out = r.json()
        out["forwarded_by"] = state.node_id
        return out
    except requests.RequestException as e:
        metrics.bump("errors")
        raise HTTPException(status_code=502, detail=f"forward to {target} failed: {e}")


# ------------------------------------------------------------------ dashboard
@app.get("/legacy", include_in_schema=False)
def legacy_dashboard():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Serve the built React app at / when present (single-origin deployment);
# falls back to the bundled HTML dashboard otherwise.
if os.path.isdir(WEB_DIST):
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    def root_dashboard():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ------------------------------------------------------------------------ main
def main():
    global state, store
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--members", required=True,
                   help='JSON: {"node1":"127.0.0.1:8001",...}')
    p.add_argument("--data-dir", default=None)
    p.add_argument("--replication", type=int, default=2)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (0.0.0.0 to expose, e.g. on a server)")
    args = p.parse_args()

    members = json.loads(args.members)
    data_dir = args.data_dir or os.path.join("data", args.id)

    def on_membership_change(peer: str, alive: bool) -> None:
        bus.publish("node_up" if alive else "node_down",
                    node=args.id, peer=peer)

    state = ClusterState(args.id, members, replication=args.replication,
                         on_change=on_membership_change)
    store = StorageEngine(data_dir)
    state.start_heartbeats()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
