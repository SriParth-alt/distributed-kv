"""Helix dashboard for Streamlit Community Cloud.

Boots the real 3-node cluster (separate uvicorn processes) inside the app's
container, then renders a live dashboard on top of it: node health, the
consistent-hash ring, key placement, KV operations, and crash-node failover.

Run locally:  streamlit run streamlit_app.py
"""
import json
import subprocess
import sys
import time

import requests
import streamlit as st

ENTRY = "http://127.0.0.1:8001"  # any node works; they forward internally

# node colors (validated categorical palette) + status colors
NODE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
GOOD, CRITICAL, MUTED, GRID = "#0ca30c", "#d03b3b", "#898781", "#b9b8b1"

st.set_page_config(page_title="Helix — Distributed KV Store", page_icon="🧩",
                   layout="wide")


# --------------------------------------------------------------------- cluster
@st.cache_resource
def start_cluster():
    """Spawn the cluster once per container; --revive heals crashed nodes."""
    proc = subprocess.Popen(
        [sys.executable, "launch_cluster.py", "--nodes", "3", "--revive", "10"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):  # wait for boot
        try:
            requests.get(f"{ENTRY}/internal/status", timeout=0.5)
            break
        except requests.RequestException:
            time.sleep(0.5)
    # seed demo data so the ring isn't empty for first-time visitors
    try:
        if requests.get(f"{ENTRY}/internal/status", timeout=2).json()["key_count"] == 0:
            for i in range(18):
                requests.put(f"{ENTRY}/kv/user:{i}",
                             json={"value": {"name": f"user_{i}", "score": i * 10}},
                             timeout=2)
    except requests.RequestException:
        pass
    return proc


def api(method: str, path: str, **kw):
    return requests.request(method, f"{ENTRY}{path}", timeout=3, **kw)


def color_of(members: dict) -> dict:
    return {nid: NODE_COLORS[i % len(NODE_COLORS)]
            for i, nid in enumerate(sorted(members))}


# ------------------------------------------------------------------- ring SVG
def ring_svg(ring: dict, colors: dict) -> str:
    cx = cy = 230
    r, tick, keyr = 168, 12, 198

    def pt(pos, rad):
        import math
        a = pos * 2 * math.pi - math.pi / 2
        return cx + rad * math.cos(a), cy + rad * math.sin(a)

    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
             f'stroke="{GRID}" stroke-width="1.5"/>']
    for v in ring["vnodes"]:
        (x1, y1), (x2, y2) = pt(v["pos"], r - tick / 2), pt(v["pos"], r + tick / 2)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{colors.get(v["node"], MUTED)}" stroke-width="2" '
                     f'stroke-linecap="round" opacity="0.85"/>')
    for k in ring["keys"]:
        x, y = pt(k["pos"], keyr)
        primary = k["replicas"][0] if k["replicas"] else "?"
        tip = f'{k["key"]} — primary {primary}, replicas {", ".join(k["replicas"][1:]) or "—"}'
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" '
                     f'fill="{colors.get(primary, MUTED)}" stroke="white" '
                     f'stroke-width="1.5"><title>{tip}</title></circle>')
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" fill="{MUTED}" '
                 f'font-size="15" font-weight="600" font-family="sans-serif">'
                 f'{len(ring["keys"])} keys</text>')
    parts.append(f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" fill="{MUTED}" '
                 f'font-size="10" font-family="sans-serif">ticks = vnodes · dots = keys</text>')
    return ('<svg viewBox="0 0 460 460" style="max-width:430px;display:block;margin:auto">'
            + "".join(parts) + "</svg>")


# ----------------------------------------------------------------------- page
start_cluster()

st.title("Helix — Distributed Key-Value Store")
st.caption("A real 3-node cluster running live in this container: consistent hashing · "
           "leader-follower replication (R=2) · WAL + LSM storage · heartbeat failure "
           "detection. [Source on GitHub](https://github.com/SriParth-alt/distributed-kv)")


@st.fragment(run_every="2s")
def live_view():
    try:
        cluster = api("GET", "/internal/cluster").json()
        ring = api("GET", "/internal/ring").json()
    except requests.RequestException:
        st.warning("Cluster booting or unreachable — retrying…")
        return
    colors = color_of(cluster["members"])

    cols = st.columns(len(cluster["nodes"]))
    for col, n in zip(cols, cluster["nodes"]):
        nid = n["node_id"]
        with col, st.container(border=True):
            dot = colors[nid]
            if n["reachable"]:
                st.markdown(f'<span style="color:{dot}">●</span> **{nid}** '
                            f'&nbsp;<span style="color:{GOOD};font-size:0.85em">'
                            f'alive</span>', unsafe_allow_html=True)
                st.metric("keys stored", n["key_count"], label_visibility="collapsed")
                if st.button("💥 crash", key=f"kill-{nid}",
                             help="Kill this node — reads keep working via replicas; "
                                  "it auto-restarts in ~10 s"):
                    try:
                        api("POST", f"/internal/kill/{nid}")
                    except requests.RequestException:
                        pass
                    st.toast(f"{nid} killed — watch its keys fail over, "
                             f"then the node revive", icon="💥")
            else:
                st.markdown(f'<span style="color:{dot}">●</span> **{nid}** '
                            f'&nbsp;<span style="color:{CRITICAL};font-size:0.85em">'
                            f'✕ dead (reviving…)</span>', unsafe_allow_html=True)
                st.metric("keys stored", "–", label_visibility="collapsed")

    left, right = st.columns([5, 4], gap="large")
    with left:
        st.subheader("Consistent hash ring", divider="gray")
        st.markdown(ring_svg(ring, colors), unsafe_allow_html=True)
        legend = " &nbsp; ".join(
            f'<span style="color:{c}">■</span> {n}' for n, c in colors.items())
        st.markdown(f'<div style="text-align:center;color:{MUTED};font-size:0.85em">'
                    f'{legend}</div>', unsafe_allow_html=True)
    with right:
        st.subheader(f'Keys ({len(ring["keys"])})', divider="gray")
        if ring["keys"]:
            st.dataframe(
                [{"key": k["key"],
                  "primary": k["replicas"][0] if k["replicas"] else "?",
                  "replicas": ", ".join(k["replicas"][1:]) or "—"}
                 for k in ring["keys"]],
                use_container_width=True, height=330, hide_index=True)
        else:
            st.caption("no keys yet — PUT one below")


live_view()

# ------------------------------------------------------------------ operations
st.subheader("Operations", divider="gray")
c1, c2, c3 = st.columns([3, 3, 2])
key = c1.text_input("key", placeholder="user:42")
raw = c2.text_input("value", placeholder='{"name": "parth"}  (PUT only)')
op = c3.radio("operation", ["PUT", "GET", "DELETE"], horizontal=True)

if st.button("run", type="primary") and key:
    try:
        if op == "PUT":
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            r = api("PUT", f"/kv/{key}", json={"value": value})
        elif op == "GET":
            r = api("GET", f"/kv/{key}")
        else:
            r = api("DELETE", f"/kv/{key}")
        (st.success if r.ok else st.error)(f"{op} {key} → {r.json()}")
    except requests.RequestException as e:
        st.error(f"{op} {key} failed: {e}")

with st.expander("what am I looking at?"):
    st.markdown("""
- **Ring ticks** are virtual nodes (150 per physical node) on the consistent-hash
  ring; **dots** are keys, colored by their primary owner (hover for replicas).
- Every write goes to a **write-ahead log** before being acknowledged, then to an
  in-memory memtable flushed to **SSTables** — a mini LSM tree, as in Cassandra.
- Each key is **replicated to 2 nodes**. Click 💥 on a node: reads keep succeeding
  from replicas, heartbeats mark it dead within ~3 s, and the launcher revives it
  ~10 s later — watch the ring re-shard in real time.
""")
