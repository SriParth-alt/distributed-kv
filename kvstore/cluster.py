"""Cluster membership + heartbeat-based failure detection.

Every node knows the full seed membership (node_id -> address). A background
thread pings peers every HEARTBEAT_INTERVAL seconds; a peer that hasn't
answered within DEAD_AFTER seconds is marked dead and removed from the live
hash ring. When it answers again it is marked alive and re-added.
"""
from __future__ import annotations

import threading
import time
from typing import Dict

import requests

from .hashring import HashRing

HEARTBEAT_INTERVAL = 1.0   # seconds between heartbeat rounds
DEAD_AFTER = 3.0           # seconds without response -> dead


class ClusterState:
    def __init__(self, node_id: str, members: Dict[str, str], replication: int = 2):
        """
        node_id : this node's id, e.g. "node1"
        members : all seed members {node_id: "host:port"}
        """
        self.node_id = node_id
        self.members = dict(members)
        self.replication = replication
        self.last_seen: Dict[str, float] = {n: time.time() for n in members}
        self.alive: Dict[str, bool] = {n: True for n in members}
        self._lock = threading.Lock()
        self.ring = HashRing(list(members.keys()))
        self._stop = threading.Event()

    # ------------------------------------------------------------------ views
    def address(self, node_id: str) -> str:
        return self.members[node_id]

    def live_nodes(self) -> list[str]:
        with self._lock:
            return [n for n, ok in self.alive.items() if ok]

    def replicas_for(self, key: str) -> list[str]:
        """Primary + replicas among currently-live nodes."""
        return self.ring.get_nodes(key, self.replication)

    def status(self) -> dict:
        with self._lock:
            return {
                "node_id": self.node_id,
                "alive": dict(self.alive),
                "members": dict(self.members),
                "replication": self.replication,
            }

    # ------------------------------------------------------------------ liveness
    def mark_alive(self, node_id: str) -> None:
        with self._lock:
            self.last_seen[node_id] = time.time()
            if not self.alive.get(node_id, False):
                self.alive[node_id] = True
                self.ring.add_node(node_id)

    def _mark_dead(self, node_id: str) -> None:
        with self._lock:
            if self.alive.get(node_id, False):
                self.alive[node_id] = False
                self.ring.remove_node(node_id)

    # ------------------------------------------------------------------ loop
    def start_heartbeats(self) -> None:
        t = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            for peer, addr in self.members.items():
                if peer == self.node_id:
                    continue
                try:
                    r = requests.post(
                        f"http://{addr}/internal/heartbeat",
                        json={"from": self.node_id},
                        timeout=0.8,
                    )
                    if r.ok:
                        self.mark_alive(peer)
                except requests.RequestException:
                    pass
                if time.time() - self.last_seen.get(peer, 0) > DEAD_AFTER:
                    self._mark_dead(peer)
            self._stop.wait(HEARTBEAT_INTERVAL)
