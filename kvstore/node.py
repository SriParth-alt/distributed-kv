"""Node server. Run one process per node.

Public API (clients):
    GET    /kv/{key}       read a value
    PUT    /kv/{key}       write {"value": ...}
    DELETE /kv/{key}       delete
    GET    /internal/status   cluster view (also used by smart client)

Internal API (node <-> node):
    POST /internal/replicate  replica write (no further fan-out)
    POST /internal/heartbeat  liveness ping

Ownership rule: a node handles a client write only if it is the key's primary;
otherwise it forwards to the primary (client normally hits the right node
directly, but forwarding makes every node a valid entry point).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from typing import Any

import requests
import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .cluster import ClusterState
from .hashring import _hash
from .storage import StorageEngine

app = FastAPI(title="PyKV Node")
state: ClusterState = None  # type: ignore
store: StorageEngine = None  # type: ignore

RING_SPAN = 2 ** 128  # md5 hash space; used to normalize ring positions to [0,1)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ------------------------------------------------------------------- dashboard
@app.get("/")
def dashboard():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/internal/cluster")
def cluster_view():
    """Aggregated view of every member, fetched server-side (no CORS needed)."""
    nodes = []
    for peer, addr in state.members.items():
        if peer == state.node_id:
            s = status()
            s["reachable"] = True
            nodes.append(s)
            continue
        try:
            r = requests.get(f"http://{addr}/internal/status", timeout=1.0)
            s = r.json()
            s["reachable"] = True
        except requests.RequestException:
            s = {"node_id": peer, "reachable": False, "key_count": 0, "keys": []}
        nodes.append(s)
    return {"asked": state.node_id, "replication": state.replication,
            "members": state.members, "alive": dict(state.alive), "nodes": nodes}


@app.get("/internal/ring")
def ring_view():
    """Vnode positions + key positions (normalized 0-1) for the ring visual."""
    vnodes = [{"pos": h / RING_SPAN, "node": n} for h, n in state.ring.positions()]
    seen: dict[str, dict] = {}
    for n in cluster_view()["nodes"]:
        for k in n.get("keys", []):
            if k not in seen:
                seen[k] = {"key": k, "pos": _hash(k) / RING_SPAN,
                           "replicas": state.replicas_for(k)}
    return {"vnodes": vnodes, "keys": sorted(seen.values(), key=lambda x: x["pos"]),
            "alive": dict(state.alive)}


@app.get("/internal/locate/{key}")
def locate(key: str):
    return {"key": key, "pos": _hash(key) / RING_SPAN,
            "replicas": state.replicas_for(key)}


@app.post("/internal/die")
def die():
    """Crash this node on purpose (failover demo button in the dashboard)."""
    threading.Timer(0.3, lambda: os._exit(1)).start()
    return {"ok": True, "dying": state.node_id}


@app.post("/internal/kill/{node_id}")
def kill_peer(node_id: str):
    """Dashboard helper: forward a crash request to any member node."""
    if node_id == state.node_id:
        return die()
    addr = state.members.get(node_id)
    if not addr:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id}")
    try:
        return requests.post(f"http://{addr}/internal/die", timeout=1.5).json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"could not reach {node_id}: {e}")


# ---------------------------------------------------------------------- public
@app.get("/kv/{key}")
def get_key(key: str):
    replicas = state.replicas_for(key)
    if state.node_id in replicas:
        value = store.get(key)
        if value is None:
            raise HTTPException(status_code=404, detail="key not found")
        return {"key": key, "value": value, "served_by": state.node_id}
    return _forward("GET", replicas[0], key)


@app.put("/kv/{key}")
def put_key(key: str, body: dict = Body(...)):
    if "value" not in body:
        raise HTTPException(status_code=400, detail='body must be {"value": ...}')
    replicas = state.replicas_for(key)
    if not replicas:
        raise HTTPException(status_code=503, detail="no live nodes")
    if state.node_id == replicas[0]:
        return _primary_write(key, body["value"], replicas)
    return _forward("PUT", replicas[0], key, body)


@app.delete("/kv/{key}")
def delete_key(key: str):
    replicas = state.replicas_for(key)
    if not replicas:
        raise HTTPException(status_code=503, detail="no live nodes")
    if state.node_id == replicas[0]:
        return _primary_write(key, None, replicas, is_delete=True)
    return _forward("DELETE", replicas[0], key)


@app.get("/internal/status")
def status():
    s = state.status()
    s["key_count"] = len(store.keys())
    s["keys"] = store.keys()[:50]
    return s


# -------------------------------------------------------------------- internal
@app.post("/internal/replicate")
def replicate(body: dict = Body(...)):
    key, value, is_delete = body["key"], body.get("value"), body.get("delete", False)
    if is_delete:
        store.delete(key)
    else:
        store.put(key, value)
    return {"ok": True, "replica": state.node_id}


@app.post("/internal/heartbeat")
def heartbeat(body: dict = Body(...)):
    state.mark_alive(body["from"])
    return {"ok": True, "from": state.node_id}


# --------------------------------------------------------------------- helpers
def _primary_write(key: str, value: Any, replicas: list[str], is_delete: bool = False):
    # 1. local durable write
    if is_delete:
        store.delete(key)
    else:
        store.put(key, value)
    # 2. synchronous fan-out to replica successors
    acks = [state.node_id]
    for peer in replicas[1:]:
        try:
            r = requests.post(
                f"http://{state.address(peer)}/internal/replicate",
                json={"key": key, "value": value, "delete": is_delete},
                timeout=1.5,
            )
            if r.ok:
                acks.append(peer)
        except requests.RequestException:
            pass  # replica down; heartbeat loop will mark it dead
    return {"key": key, "primary": state.node_id, "acks": acks,
            "replication_target": len(replicas)}


def _forward(method: str, target: str, key: str, body: dict | None = None):
    try:
        r = requests.request(
            method, f"http://{state.address(target)}/kv/{key}",
            json=body, timeout=2.0,
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="key not found")
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"forward to {target} failed: {e}")


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
    state = ClusterState(args.id, members, replication=args.replication)
    store = StorageEngine(data_dir)
    state.start_heartbeats()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
