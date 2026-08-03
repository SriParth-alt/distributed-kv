import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kvstore.hashring import HashRing
from kvstore.storage import StorageEngine

TMP = "/tmp/pykv_test_data"


# ---------------------------------------------------------------- hash ring
def test_ring_distribution_roughly_even():
    ring = HashRing(["a", "b", "c"])
    counts = {"a": 0, "b": 0, "c": 0}
    for i in range(3000):
        counts[ring.get_node(f"key{i}")] += 1
    for n, cnt in counts.items():
        assert 700 < cnt < 1300, f"{n} badly skewed: {cnt}"


def test_ring_minimal_remap_on_node_removal():
    ring = HashRing(["a", "b", "c"])
    before = {f"key{i}": ring.get_node(f"key{i}") for i in range(2000)}
    ring.remove_node("b")
    moved = 0
    for k, owner in before.items():
        new_owner = ring.get_node(k)
        if owner == "b":
            assert new_owner in ("a", "c")
        elif new_owner != owner:
            moved += 1
    assert moved == 0, "keys not owned by removed node must not move"


def test_ring_replicas_distinct():
    ring = HashRing(["a", "b", "c"])
    reps = ring.get_nodes("somekey", 2)
    assert len(reps) == 2 and len(set(reps)) == 2


# ---------------------------------------------------------------- storage
def _fresh_store(limit=128):
    shutil.rmtree(TMP, ignore_errors=True)
    return StorageEngine(TMP, memtable_limit=limit)


def test_put_get_delete():
    s = _fresh_store()
    s.put("k1", {"x": 1})
    assert s.get("k1") == {"x": 1}
    s.delete("k1")
    assert s.get("k1") is None


def test_wal_replay_restores_unflushed_writes():
    s = _fresh_store()
    s.put("crash_key", "survives")
    # simulate crash: new engine instance over same dir, memtable was never flushed
    s2 = StorageEngine(TMP)
    assert s2.get("crash_key") == "survives"


def test_sstable_flush_and_read():
    s = _fresh_store(limit=10)
    for i in range(25):                       # forces 2 flushes
        s.put(f"k{i:03d}", i)
    assert s.get("k003") == 3
    assert s.get("k024") == 24
    assert len(s._sstables) >= 2


def test_tombstone_masks_older_sstable_value():
    s = _fresh_store(limit=5)
    s.put("dead", "old")
    for i in range(6):                        # flush "dead" into an SSTable
        s.put(f"pad{i}", i)
    s.delete("dead")                          # tombstone in memtable
    assert s.get("dead") is None
    s.flush()                                 # tombstone now in newest SSTable
    assert s.get("dead") is None


def test_newest_sstable_wins():
    s = _fresh_store(limit=3)
    s.put("k", "v1")
    s.put("pad1", 1); s.put("pad2", 2)        # flush 1 (contains k=v1)
    s.put("k", "v2")
    s.put("pad3", 3); s.put("pad4", 4)        # flush 2 (contains k=v2)
    assert s.get("k") == "v2"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
