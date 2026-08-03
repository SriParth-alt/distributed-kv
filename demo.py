"""End-to-end demo: partitioning, replication, and failover.

Run AFTER `python launch_cluster.py --nodes 3` is up, in a second terminal:
    python demo.py
It will:
  1. write 30 keys and show how they distribute across nodes
  2. read them all back
  3. ask you to kill a node, then prove reads still succeed (failover)
"""
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter

import requests

from kvstore.client import KVClient
from launch_cluster import members_for

MEMBERS = members_for(3)


def line(msg=""):
    print(msg, flush=True)


def main():
    c = KVClient(MEMBERS)
    c.refresh_membership()

    line("=" * 60)
    line("1) WRITE 30 keys — watch consistent hashing spread them out")
    line("=" * 60)
    primaries = Counter()
    for i in range(30):
        res = c.put(f"user:{i}", {"name": f"user_{i}", "score": i * 10})
        primaries[res["primary"]] += 1
    for node, count in sorted(primaries.items()):
        line(f"   {node}: primary for {count} keys")

    line()
    line("=" * 60)
    line("2) READ all 30 back")
    line("=" * 60)
    ok = sum(1 for i in range(30) if c.get(f"user:{i}") is not None)
    line(f"   {ok}/30 reads succeeded")

    line()
    line("=" * 60)
    line("3) FAILOVER — killing node1, then re-reading everything")
    line("=" * 60)
    # kill node1 by the PID recorded by launch_cluster.py (cross-platform)
    with open("cluster.pids") as f:
        pid = json.load(f)["node1"]
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False,
                       capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)
    line("   node1 killed. waiting for failure detection (~4s)...")
    time.sleep(4.5)
    c.refresh_membership()
    ok = 0
    for i in range(30):
        v = c.get(f"user:{i}")
        if v is not None:
            ok += 1
    line(f"   {ok}/30 reads succeeded WITH node1 DEAD (served by replicas)")
    line()
    line("   why: every key was replicated to 2 nodes, and the smart client")
    line("   retries ring successors when the primary is unreachable.")


if __name__ == "__main__":
    main()
