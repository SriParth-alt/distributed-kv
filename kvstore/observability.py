"""Event bus + metrics collection for the live dashboard.

EventBus fans out cluster events (writes, replication, heartbeats, node
join/leave) to any number of WebSocket subscribers, and keeps a bounded
history so a page that connects late still has context.

Metrics tracks throughput and latency percentiles in a rolling window, plus
cumulative counters — enough to drive real charts without a metrics backend.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

HISTORY = 200          # events retained for late subscribers
WINDOW_SECONDS = 120   # rolling window for throughput/latency


class EventBus:
    """Thread-safe publish (from sync request handlers) → async fan-out (WS)."""

    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._history: Deque[dict] = deque(maxlen=HISTORY)
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seq = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once the server's event loop exists, so sync code can
        schedule fan-out onto it thread-safely."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def history(self) -> List[dict]:
        with self._lock:
            return list(self._history)

    def publish(self, type_: str, **fields: Any) -> None:
        """Safe to call from any thread (request handlers, heartbeat loop)."""
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "ts": time.time(), "type": type_, **fields}
            self._history.append(event)
            subs = list(self._subscribers)
        if self._loop is None:
            return
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except (RuntimeError, asyncio.QueueFull):
                pass  # slow or closed consumer; it will catch up from history


class Metrics:
    """Rolling-window throughput + latency percentiles, plus totals."""

    def __init__(self) -> None:
        self._samples: Deque[tuple] = deque()  # (ts, op, latency_ms, ok)
        self._lock = threading.Lock()
        self.totals: Dict[str, int] = {
            "reads": 0, "writes": 0, "deletes": 0,
            "replications_sent": 0, "replications_failed": 0,
            "failovers": 0, "errors": 0,
        }
        self.started = time.time()

    def record(self, op: str, latency_ms: float, ok: bool = True) -> None:
        now = time.time()
        with self._lock:
            self._samples.append((now, op, latency_ms, ok))
            cutoff = now - WINDOW_SECONDS
            while self._samples and self._samples[0][0] < cutoff:
                self._samples.popleft()
            key = {"read": "reads", "write": "writes", "delete": "deletes"}.get(op)
            if key:
                self.totals[key] += 1
            if not ok:
                self.totals["errors"] += 1

    def bump(self, counter: str, n: int = 1) -> None:
        with self._lock:
            self.totals[counter] = self.totals.get(counter, 0) + n

    @staticmethod
    def _pct(values: List[float], p: float) -> float:
        if not values:
            return 0.0
        values = sorted(values)
        i = min(int(len(values) * p), len(values) - 1)
        return round(values[i], 2)

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            samples = list(self._samples)
            totals = dict(self.totals)
        window = [s for s in samples if s[0] >= now - WINDOW_SECONDS]
        span = max(min(WINDOW_SECONDS, now - self.started), 1e-6)

        def stats_for(op: Optional[str]) -> dict:
            sel = [s for s in window if op is None or s[1] == op]
            lat = [s[2] for s in sel]
            return {
                "ops_per_sec": round(len(sel) / span, 2),
                "p50_ms": self._pct(lat, 0.50),
                "p95_ms": self._pct(lat, 0.95),
                "p99_ms": self._pct(lat, 0.99),
                "count": len(sel),
            }

        # per-second buckets for the throughput chart (last 60s)
        buckets: Dict[int, Dict[str, int]] = {}
        for ts, op, _lat, _ok in window:
            b = int(now - ts)
            if b < 60:
                buckets.setdefault(b, {"read": 0, "write": 0, "delete": 0})
                if op in buckets[b]:
                    buckets[b][op] += 1
        series = [
            {"t": -b, "read": buckets.get(b, {}).get("read", 0),
             "write": buckets.get(b, {}).get("write", 0),
             "delete": buckets.get(b, {}).get("delete", 0)}
            for b in range(59, -1, -1)
        ]

        return {
            "uptime_seconds": round(now - self.started, 1),
            "totals": totals,
            "overall": stats_for(None),
            "read": stats_for("read"),
            "write": stats_for("write"),
            "delete": stats_for("delete"),
            "throughput_series": series,
        }
