"""Spawn a local N-node PyKV cluster (one process per node).

Usage:  python launch_cluster.py --nodes 3
Ctrl+C stops all nodes.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

BASE_PORT = 8001
PID_FILE = "cluster.pids"


def members_for(n: int) -> dict:
    return {f"node{i+1}": f"127.0.0.1:{BASE_PORT + i}" for i in range(n)}


def kill_stale_nodes():
    """Kill nodes left over from a previous launch (recorded in PID_FILE)."""
    try:
        with open(PID_FILE) as f:
            stale = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for node_id, pid in stale.items():
        if pid == os.getpid():
            continue
        try:
            if sys.platform == "win32":
                r = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   check=False, capture_output=True)
                if r.returncode == 0:
                    print(f"killed stale {node_id} (pid {pid})")
            else:
                os.kill(pid, signal.SIGTERM)
                print(f"killed stale {node_id} (pid {pid})")
        except (OSError, ProcessLookupError):
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nodes", type=int, default=3)
    p.add_argument("--replication", type=int, default=2)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address for nodes (0.0.0.0 to expose, e.g. on a server)")
    p.add_argument("--revive", type=float, default=0,
                   help="seconds after which a dead node is restarted (0 = never)")
    args = p.parse_args()

    kill_stale_nodes()
    members = members_for(args.nodes)
    members_json = json.dumps(members)
    node_ids = list(members)
    cmds = []
    for node_id, addr in members.items():
        port = addr.split(":")[1]
        cmds.append([
            sys.executable, "-m", "kvstore.node",
            "--id", node_id, "--port", port,
            "--members", members_json,
            "--replication", str(args.replication),
            "--host", args.host,
        ])
    procs = [subprocess.Popen(cmd) for cmd in cmds]
    for node_id, addr in members.items():
        print(f"started {node_id} on {addr}")

    def write_pidfile():
        pids = {nid: pr.pid for nid, pr in zip(node_ids, procs)}
        pids["_launcher"] = os.getpid()
        with open(PID_FILE, "w") as f:
            json.dump(pids, f)

    write_pidfile()

    print(f"\ncluster up: {args.nodes} nodes, replication={args.replication}")
    print(f"members: {members_json}")
    print("Ctrl+C to stop\n")

    def shutdown(*_):
        for pr in procs:
            pr.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    died_at: dict[int, float] = {}
    while True:
        time.sleep(1)
        now = time.time()
        for i, pr in enumerate(procs):
            if pr.poll() is None:
                continue
            died_at.setdefault(i, now)
            if args.revive and now - died_at[i] >= args.revive:
                procs[i] = subprocess.Popen(cmds[i])
                died_at.pop(i)
                print(f"revived {node_ids[i]}")
                write_pidfile()
        if not args.revive and all(pr.poll() is not None for pr in procs):
            print("all nodes have exited — shutting down launcher")
            sys.exit(1)


if __name__ == "__main__":
    main()
