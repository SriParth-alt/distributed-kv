"""Throughput + latency benchmark for Helix.

Fires a fixed number of operations from N concurrent clients, measures wall
time, and reports ops/sec with latency percentiles. Every number in the README
comes from this script, so results are reproducible:

    python launch_cluster.py --nodes 3          # terminal 1
    python bench.py --report                    # terminal 2

Routing modes
  entry   every request goes to node1, which forwards to the key's primary
          (the extra hop is the cost of a coordinator-style entry point)
  smart   the client hashes each key locally and calls the primary directly
          — the coordinator-free path the library client actually uses

Notes on interpreting results: all nodes run as processes on one machine, so
they share CPU; this measures the implementation, not a distributed
deployment's ceiling.
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from kvstore.hashring import HashRing
from launch_cluster import members_for


@dataclass
class Result:
    label: str
    ops: int                       # operations ATTEMPTED
    clients: int
    seconds: float
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    error_kinds: Counter = field(default_factory=Counter)

    @property
    def succeeded(self) -> int:
        return self.ops - self.errors

    @property
    def ops_per_sec(self) -> float:
        # only successful operations count — otherwise fast failures would
        # inflate throughput, which is the classic way to lie with a benchmark
        return self.succeeded / self.seconds if self.seconds else 0.0

    def pct(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        return s[min(int(len(s) * p), len(s) - 1)]

    def row(self) -> str:
        return (f"{self.label:<26} {self.clients:>3}  {self.succeeded:>6}  "
                f"{self.seconds:>7.2f}s  {self.ops_per_sec:>8.0f}  "
                f"{self.pct(.50):>7.1f}  {self.pct(.95):>7.1f}  "
                f"{self.pct(.99):>7.1f}  {self.errors:>4}")


class Bench:
    def __init__(self, members: dict[str, str], replication: int = 2,
                 mode: str = "smart", keyspace: int = 500):
        self.members = members
        self.ring = HashRing(list(members))
        self.replication = replication
        self.mode = mode
        self.keyspace = keyspace
        self.entry = f"http://{list(members.values())[0]}"

    def target(self, key: str) -> str:
        """Base URL for a key under the current routing mode."""
        if self.mode == "entry":
            return self.entry
        primary = self.ring.get_nodes(key, self.replication)[0]
        return f"http://{self.members[primary]}"

    # ------------------------------------------------------------------ ops
    def _write(self, s: requests.Session, key: str) -> float:
        t = time.perf_counter()
        r = s.put(f"{self.target(key)}/keys/{key}",
                  json={"value": {"k": key, "ts": time.time()}}, timeout=10)
        r.raise_for_status()
        return (time.perf_counter() - t) * 1000

    def _read(self, s: requests.Session, key: str) -> float:
        t = time.perf_counter()
        r = s.get(f"{self.target(key)}/keys/{key}", timeout=10)
        if r.status_code not in (200, 404):
            r.raise_for_status()
        return (time.perf_counter() - t) * 1000

    # ---------------------------------------------------------------- driver
    def run(self, label: str, ops: int, clients: int, read_ratio: float,
            seed: int = 1234) -> Result:
        per_client = ops // clients
        total = per_client * clients
        res = Result(label=label, ops=total, clients=clients, seconds=0.0)
        lock_free: list[list[float]] = [[] for _ in range(clients)]
        errors = [0] * clients
        kinds: list[Counter] = [Counter() for _ in range(clients)]

        def worker(idx: int) -> None:
            rng = random.Random(seed + idx)
            s = requests.Session()
            # one pooled connection per node per client, so the benchmark
            # measures the server rather than client-side connection churn
            s.mount("http://", requests.adapters.HTTPAdapter(
                pool_connections=len(self.members),
                pool_maxsize=len(self.members) * 2, max_retries=0))
            lats = lock_free[idx]
            for _ in range(per_client):
                key = f"bench:{rng.randrange(self.keyspace)}"
                try:
                    if rng.random() < read_ratio:
                        lats.append(self._read(s, key))
                    else:
                        lats.append(self._write(s, key))
                except Exception as e:
                    errors[idx] += 1
                    kinds[idx][type(e).__name__] += 1
            s.close()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=clients) as pool:
            list(pool.map(worker, range(clients)))
        res.seconds = time.perf_counter() - start
        for l in lock_free:
            res.latencies.extend(l)
        res.errors = sum(errors)
        for c in kinds:
            res.error_kinds.update(c)
        return res

    def prepopulate(self) -> None:
        s = requests.Session()
        for i in range(self.keyspace):
            s.put(f"{self.target(f'bench:{i}')}/keys/bench:{i}",
                  json={"value": {"seed": i}}, timeout=10)
        s.close()


HEADER = (f"{'workload':<26} {'cli':>3}  {'ops':>6}  {'wall':>8}  "
          f"{'ops/sec':>8}  {'p50ms':>7}  {'p95ms':>7}  {'p99ms':>7}  {'err':>4}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nodes", type=int, default=3)
    p.add_argument("--ops", type=int, default=2000)
    p.add_argument("--keyspace", type=int, default=500)
    p.add_argument("--clients", type=int, nargs="+", default=[1, 8, 32, 64])
    p.add_argument("--report", action="store_true",
                   help="run the full matrix used in the README")
    args = p.parse_args()

    members = members_for(args.nodes)
    print(f"Helix benchmark — {args.nodes} nodes, RF=2, "
          f"{platform.python_version()} on {platform.system()} "
          f"({platform.processor() or 'unknown cpu'})")
    print(f"keyspace={args.keyspace} ops/run={args.ops}\n")

    smart = Bench(members, mode="smart", keyspace=args.keyspace)
    print("pre-populating keyspace…")
    smart.prepopulate()

    results: list[Result] = []
    # warmup (not recorded)
    smart.run("warmup", 200, 8, 0.5)

    for clients in args.clients:
        results.append(smart.run("write 100% (smart)", args.ops, clients, 0.0))
    for clients in args.clients:
        results.append(smart.run("read 100% (smart)", args.ops, clients, 1.0))
    for clients in args.clients:
        results.append(smart.run("mixed 90r/10w (smart)", args.ops, clients, 0.9))

    if args.report:
        entry = Bench(members, mode="entry", keyspace=args.keyspace)
        for clients in (32,):
            results.append(entry.run("write 100% (entry hop)", args.ops, clients, 0.0))
            results.append(entry.run("read 100% (entry hop)", args.ops, clients, 1.0))

    print("\n" + HEADER)
    print("-" * len(HEADER))
    for r in results:
        print(r.row())

    failing = [r for r in results if r.errors]
    if failing:
        print("\nerrors (throughput counts successful ops only)")
        for r in failing:
            print(f"  {r.label} @ {r.clients} clients: "
                  f"{dict(r.error_kinds)}")

    best_w = max((r for r in results if r.label.startswith("write 100% (smart")),
                 key=lambda r: r.ops_per_sec)
    best_r = max((r for r in results if r.label.startswith("read 100% (smart")),
                 key=lambda r: r.ops_per_sec)
    best_m = max((r for r in results if r.label.startswith("mixed")),
                 key=lambda r: r.ops_per_sec)
    print("\npeak throughput")
    for r in (best_w, best_r, best_m):
        print(f"  {r.label:<26} {r.ops_per_sec:>8.0f} ops/s "
              f"@ {r.clients} clients (p50 {r.pct(.50):.1f} ms, "
              f"p99 {r.pct(.99):.1f} ms)")


if __name__ == "__main__":
    main()
