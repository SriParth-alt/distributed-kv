"""Consistent hash ring with virtual nodes.

Maps keys to nodes such that adding/removing a node only remaps ~K/N keys.
Virtual nodes (default 150 per physical node) smooth out distribution.
"""
from __future__ import annotations

import bisect
import hashlib
from typing import Dict, List


def _hash(value: str) -> int:
    """Deterministic 128-bit hash -> int. MD5 is fine here (not security-sensitive)."""
    return int(hashlib.md5(value.encode("utf-8")).hexdigest(), 16)


class HashRing:
    def __init__(self, nodes: List[str] | None = None, vnodes: int = 150):
        self.vnodes = vnodes
        self._ring: Dict[int, str] = {}          # hash position -> node id
        self._sorted_hashes: List[int] = []      # sorted positions for bisect
        self._nodes: set[str] = set()
        for n in nodes or []:
            self.add_node(n)

    # ------------------------------------------------------------------ members
    @property
    def nodes(self) -> List[str]:
        return sorted(self._nodes)

    def add_node(self, node_id: str) -> None:
        if node_id in self._nodes:
            return
        self._nodes.add(node_id)
        for i in range(self.vnodes):
            h = _hash(f"{node_id}#vn{i}")
            self._ring[h] = node_id
            bisect.insort(self._sorted_hashes, h)

    def remove_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return
        self._nodes.discard(node_id)
        for i in range(self.vnodes):
            h = _hash(f"{node_id}#vn{i}")
            if self._ring.pop(h, None) is not None:
                idx = bisect.bisect_left(self._sorted_hashes, h)
                if idx < len(self._sorted_hashes) and self._sorted_hashes[idx] == h:
                    self._sorted_hashes.pop(idx)

    def positions(self) -> List[tuple[int, str]]:
        """All (hash, node) vnode positions, sorted — for ring visualization."""
        return [(h, self._ring[h]) for h in self._sorted_hashes]

    # ------------------------------------------------------------------ lookup
    def get_node(self, key: str) -> str | None:
        """Primary owner of a key: first vnode clockwise from hash(key)."""
        owners = self.get_nodes(key, 1)
        return owners[0] if owners else None

    def get_nodes(self, key: str, n: int) -> List[str]:
        """Primary + successor replicas: the next n *distinct* physical nodes
        walking clockwise around the ring. O(log V) to find the start point."""
        if not self._sorted_hashes:
            return []
        n = min(n, len(self._nodes))
        h = _hash(key)
        idx = bisect.bisect_right(self._sorted_hashes, h) % len(self._sorted_hashes)
        found: List[str] = []
        seen: set[str] = set()
        for step in range(len(self._sorted_hashes)):
            pos = self._sorted_hashes[(idx + step) % len(self._sorted_hashes)]
            node = self._ring[pos]
            if node not in seen:
                seen.add(node)
                found.append(node)
                if len(found) == n:
                    break
        return found
