"""Mini-LSM storage engine: Write-Ahead Log -> sorted memtable -> SSTables.

Write path : append to WAL (durability) -> insert into memtable -> ACK.
Flush      : when memtable exceeds threshold, write a sorted immutable SSTable
             and truncate the WAL.
Read path  : memtable first, then SSTables newest -> oldest (first hit wins).
Deletes    : tombstone records (value=None) so deletes mask older SSTable data.
Recovery   : on startup, replay WAL into memtable to restore un-flushed writes.
"""
from __future__ import annotations

import json
import os
import threading
from bisect import bisect_left
from typing import Any, Dict, List, Optional, Tuple

_TOMBSTONE = "__PYKV_TOMBSTONE__"


class SSTable:
    """Immutable sorted key-value file with an in-memory sparse-free index
    (all keys held in memory here for simplicity; binary search on read)."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "r", encoding="utf-8") as f:
            data: List[Tuple[str, Any]] = json.load(f)
        self._keys = [k for k, _ in data]           # sorted
        self._values = [v for _, v in data]

    @staticmethod
    def write(path: str, items: Dict[str, Any]) -> "SSTable":
        rows = sorted(items.items())
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, path)  # atomic rename
        return SSTable(path)

    def get(self, key: str) -> Tuple[bool, Optional[Any]]:
        """Returns (found, value). value may be tombstone sentinel."""
        i = bisect_left(self._keys, key)
        if i < len(self._keys) and self._keys[i] == key:
            return True, self._values[i]
        return False, None


class StorageEngine:
    def __init__(self, data_dir: str, memtable_limit: int = 128):
        self.data_dir = data_dir
        self.memtable_limit = memtable_limit
        os.makedirs(data_dir, exist_ok=True)
        self.wal_path = os.path.join(data_dir, "wal.log")
        self._memtable: Dict[str, Any] = {}
        self._sstables: List[SSTable] = []          # oldest -> newest
        self._lock = threading.RLock()
        self._load_sstables()
        self._replay_wal()

    # ------------------------------------------------------------------ startup
    def _load_sstables(self) -> None:
        files = sorted(
            f for f in os.listdir(self.data_dir)
            if f.startswith("sstable_") and f.endswith(".json")
        )
        self._sstables = [SSTable(os.path.join(self.data_dir, f)) for f in files]

    def _replay_wal(self) -> None:
        if not os.path.exists(self.wal_path):
            return
        with open(self.wal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._memtable[rec["k"]] = rec["v"]

    # ------------------------------------------------------------------ ops
    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._wal_append(key, value)
            self._memtable[key] = value
            if len(self._memtable) >= self.memtable_limit:
                self._flush()

    def delete(self, key: str) -> None:
        # Tombstone, not removal: must mask copies in older SSTables.
        self.put(key, _TOMBSTONE)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._memtable:
                v = self._memtable[key]
                return None if v == _TOMBSTONE else v
            for sst in reversed(self._sstables):     # newest first
                found, v = sst.get(key)
                if found:
                    return None if v == _TOMBSTONE else v
        return None

    def keys(self) -> List[str]:
        with self._lock:
            live: Dict[str, Any] = {}
            for sst in self._sstables:               # oldest -> newest overwrites
                for k, v in zip(sst._keys, sst._values):
                    live[k] = v
            live.update(self._memtable)
            return sorted(k for k, v in live.items() if v != _TOMBSTONE)

    def stats(self) -> Dict[str, Any]:
        """Storage-engine internals for the dashboard's LSM view."""
        with self._lock:
            wal_bytes = (os.path.getsize(self.wal_path)
                         if os.path.exists(self.wal_path) else 0)
            wal_entries = 0
            if wal_bytes:
                with open(self.wal_path, "r", encoding="utf-8") as f:
                    wal_entries = sum(1 for line in f if line.strip())
            return {
                "wal_bytes": wal_bytes,
                "wal_entries": wal_entries,
                "memtable_entries": len(self._memtable),
                "memtable_limit": self.memtable_limit,
                "memtable_fill_pct": round(
                    len(self._memtable) / self.memtable_limit * 100, 1),
                "sstable_count": len(self._sstables),
                "sstables": [
                    {"file": os.path.basename(s.path),
                     "keys": len(s._keys),
                     "bytes": os.path.getsize(s.path) if os.path.exists(s.path) else 0}
                    for s in self._sstables
                ],
                "live_keys": len(self.keys()),
            }

    # ------------------------------------------------------------------ internals
    def _wal_append(self, key: str, value: Any) -> None:
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k": key, "v": value}) + "\n")
            f.flush()
            os.fsync(f.fileno())                     # the durability contract

    def _flush(self) -> None:
        seq = len(self._sstables)
        path = os.path.join(self.data_dir, f"sstable_{seq:06d}.json")
        self._sstables.append(SSTable.write(path, self._memtable))
        self._memtable = {}
        open(self.wal_path, "w").close()             # truncate WAL after flush

    def flush(self) -> None:
        with self._lock:
            if self._memtable:
                self._flush()
