"""Coordinator-free smart client.

The client holds its own copy of the hash ring, hashes keys locally, and talks
directly to the primary. On failure it retries against replica successors, so
reads survive node crashes without any central router.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from .hashring import HashRing


class KVClient:
    def __init__(self, members: Dict[str, str], replication: int = 2):
        self.members = dict(members)
        self.replication = replication
        self.ring = HashRing(list(members.keys()))

    # ------------------------------------------------------------------ api
    def put(self, key: str, value: Any) -> dict:
        return self._try_each("PUT", key, {"value": value})

    def get(self, key: str) -> Optional[Any]:
        try:
            return self._try_each("GET", key)["value"]
        except KeyError:
            return None

    def delete(self, key: str) -> dict:
        return self._try_each("DELETE", key)

    def refresh_membership(self) -> None:
        """Ask any live node for the cluster view; drop dead nodes from ring."""
        for node, addr in self.members.items():
            try:
                s = requests.get(f"http://{addr}/internal/status", timeout=1.0).json()
                live = HashRing([n for n, ok in s["alive"].items() if ok])
                self.ring = live
                return
            except requests.RequestException:
                continue

    # ------------------------------------------------------------------ core
    def _try_each(self, method: str, key: str, body: dict | None = None) -> dict:
        """Try primary, then replica successors, then any live node."""
        targets = self.ring.get_nodes(key, self.replication)
        # fall back to every known node as last resort (they can forward)
        for n in self.ring.nodes:
            if n not in targets:
                targets.append(n)
        last_err: Exception | None = None
        for node in targets:
            addr = self.members[node]
            try:
                r = requests.request(
                    method, f"http://{addr}/kv/{key}", json=body, timeout=2.0
                )
                if r.status_code == 404:
                    raise KeyError(key)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                last_err = e
                continue
        raise ConnectionError(f"all nodes unreachable for {method} {key}: {last_err}")


# ---------------------------------------------------------------------- CLI
def main():
    import argparse

    p = argparse.ArgumentParser(description="Helix client CLI")
    p.add_argument("--members", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get"); g.add_argument("key")
    s = sub.add_parser("put"); s.add_argument("key"); s.add_argument("value")
    d = sub.add_parser("del"); d.add_argument("key")
    args = p.parse_args()

    c = KVClient(json.loads(args.members))
    c.refresh_membership()
    if args.cmd == "get":
        print(json.dumps(c.get(args.key)))
    elif args.cmd == "put":
        print(json.dumps(c.put(args.key, args.value)))
    else:
        print(json.dumps(c.delete(args.key)))


if __name__ == "__main__":
    main()
