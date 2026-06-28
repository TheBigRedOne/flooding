#!/usr/bin/env python3
"""
Quantitative NLSR control-traffic analysis for the mobility baseline sweep.

Two inputs are compared:
  - results/   : local run (no recorded NLSR sync storm), full per-node CSVs available
  - results0/  : peer run (G3 sync storm recorded), summary text only

The tool produces:
  1. Cross-run Full-Run comparison (NLSR control packets/bytes, mean packet size, FCR)
     parsed from overhead_total.txt in both trees.
  2. Per-group decomposition of NLSR control bytes/packets into INFO (hello),
     sync (PSync IBF), and LSA (LSA retrieval) using results/ CSVs, replicating
     the relay-outbound + '/nlsr/' classification of plot_overhead.py.
  3. Mean packet size per control sub-type and the implied per-packet size of the
     results0 G3 storm excess (delta vs the local G3 run).
  4. Per-second control-rate peak per group/sub-type (storm detector).

Classification matches plot_overhead.py:
  - relay nodes: core,agg1,agg2,acc1..acc6
  - outbound: sll.pkttype == 4 (Linux cooked capture OUTGOING)
  - control: ndn.name contains '/nlsr/'
  - app start alignment: first '/LiveStream' (non-control, non-localhost) packet
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

RESULTS_LOCAL = r"d:\Cursor\flooding\results\baseline"
RESULTS_PEER = r"d:\Cursor\flooding\results0\baseline"
GROUPS = [
    "g0-h60-a10-r15",
    "g1-h54-a9-r14",
    "g2-h48-a8-r12",
    "g3-h42-a7-r10",
    "g4-h36-a6-r9",
]

RELAY_NODES = ["core", "agg1", "agg2", "acc1", "acc2", "acc3", "acc4", "acc5", "acc6"]
APP_PREFIX = "/LiveStream"
LOCALHOST_PREFIX = "/localhost/"
CSV_USECOLS = ["node", "frame.time_epoch", "frame.len", "sll.pkttype", "ndn.name"]


def _parse_full_run(path: str) -> Dict[str, Optional[float]]:
    """Parse the [Full Run] block of an overhead_total.txt file."""
    out: Dict[str, Optional[float]] = {"pkts": None, "bytes": None, "fcr": None}
    if not os.path.exists(path):
        return out
    section = None
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section != "Full Run" or ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            if key == "NLSR Control Packets":
                out["pkts"] = float(value)
            elif key == "NLSR Control Bytes":
                out["bytes"] = float(value)
            elif key == "Forwarding Cost Ratio":
                out["fcr"] = None if value.lower() == "n/a" else float(value)
    return out


def _classify_control(name: pd.Series) -> pd.Series:
    """Return control sub-type for each NLSR name: INFO / sync / LSA / other."""
    sub = pd.Series("other", index=name.index, dtype=object)
    sub[name.str.contains("/nlsr/INFO", regex=False)] = "INFO"
    sub[name.str.contains("/nlsr/sync", regex=False)] = "sync"
    sub[name.str.contains("/nlsr/LSA", regex=False)] = "LSA"
    return sub


def _load_relay_control(csv_path: str) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Load one network_overhead.csv and return relay-outbound NLSR control rows."""
    df = pd.read_csv(csv_path, usecols=CSV_USECOLS, dtype=str, low_memory=False)
    df = df.rename(columns={
        "frame.time_epoch": "time",
        "frame.len": "length",
        "sll.pkttype": "pkttype",
        "ndn.name": "name",
    })
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df["length"] = pd.to_numeric(df["length"], errors="coerce")
    df["pkttype"] = pd.to_numeric(df["pkttype"], errors="coerce")
    df = df.dropna(subset=["time", "length", "name"]).copy()
    df["name"] = df["name"].astype(str)
    df["node"] = df["node"].astype(str)

    # Attach classification as columns so masks stay index-aligned after filtering.
    df["is_control"] = df["name"].str.contains("/nlsr/", regex=False)
    df["is_localhost"] = df["name"].str.startswith(LOCALHOST_PREFIX)
    df["is_app"] = df["name"].str.startswith(APP_PREFIX) & ~df["is_control"] & ~df["is_localhost"]
    if not df["is_app"].any():
        raise ValueError(f"No app traffic in {csv_path}")

    start_time = float(df.loc[df["is_app"], "time"].min())
    df["rel"] = df["time"] - start_time
    df = df[df["rel"] >= 0].copy()

    df["is_outbound"] = df["pkttype"] == 4
    df["relay"] = df["node"].isin(RELAY_NODES)
    control = df[df["relay"] & df["is_outbound"] & df["is_control"]].copy()
    control["sub"] = _classify_control(control["name"])

    meta = {"app_start": start_time, "max_rel": float(df["rel"].max())}
    return control, meta


def _fmt(n: Optional[float]) -> str:
    return "n/a" if n is None else f"{n:,.0f}"


def _persecond_report(label: str, control: pd.DataFrame) -> None:
    """Print sub-type split and per-second rate distribution over the full run."""
    control = control.copy()
    control["sec"] = control["rel"].astype(int)
    max_sec = int(control["sec"].max())
    per_sec = control.groupby("sec")["length"].sum().reindex(range(max_sec + 1), fill_value=0)
    total_b = int(control["length"].sum())
    total_p = int(len(control))
    comp = control.groupby("sub")["length"].sum()

    def pct(sub: str) -> float:
        return 100.0 * int(comp.get(sub, 0)) / total_b if total_b else 0.0

    print(f"\n[{label}] control {total_p:,} pkt / {total_b:,} B "
          f"({total_b / total_p:.0f} B/pkt)  run={max_sec}s")
    print(f"    split:  INFO {pct('INFO'):.0f}%  sync {pct('sync'):.0f}%  "
          f"LSA {pct('LSA'):.0f}%  other {pct('other'):.0f}%")
    q = per_sec.quantile([0.5, 0.9, 0.99])
    nonzero = 100.0 * (per_sec > 0).mean()
    print(f"    per-sec B/s: mean={per_sec.mean():.0f}  p50={q[0.5]:.0f}  p90={q[0.9]:.0f}  "
          f"p99={q[0.99]:.0f}  max={per_sec.max():.0f}  peak/mean={per_sec.max() / per_sec.mean():.1f}x  "
          f"active={nonzero:.0f}%")
    peak_sec = int(per_sec.idxmax())
    win = control[(control["sec"] >= peak_sec - 3) & (control["sec"] <= peak_sec + 3)]
    wb = int(win["length"].sum())
    wc = win.groupby("sub")["length"].sum()
    print(f"    busiest [{peak_sec - 3},{peak_sec + 3}]s = {wb:,} B  "
          f"INFO {100 * int(wc.get('INFO', 0)) / wb:.0f}%  sync {100 * int(wc.get('sync', 0)) / wb:.0f}%  "
          f"LSA {100 * int(wc.get('LSA', 0)) / wb:.0f}%")


def main() -> int:
    # ---- Section 1: cross-run Full-Run comparison -------------------------------
    print("=" * 96)
    print("SECTION 1  Full-Run NLSR control: local (results) vs peer (results0)")
    print("=" * 96)
    header = (f"{'group':<16}{'local_pkts':>11}{'local_bytes':>14}{'local_B/pkt':>12}"
              f"{'peer_pkts':>11}{'peer_bytes':>14}{'peer_B/pkt':>12}{'bytes_x':>8}")
    print(header)
    storm_delta: Dict[str, Tuple[float, float]] = {}
    for g in GROUPS:
        loc = _parse_full_run(os.path.join(RESULTS_LOCAL, g, "overhead_total.txt"))
        peer = _parse_full_run(os.path.join(RESULTS_PEER, g, "overhead_total.txt"))
        lbp = (loc["bytes"] / loc["pkts"]) if loc["pkts"] else None
        pbp = (peer["bytes"] / peer["pkts"]) if peer["pkts"] else None
        ratio = (peer["bytes"] / loc["bytes"]) if (loc["bytes"] and peer["bytes"]) else None
        print(f"{g:<16}{_fmt(loc['pkts']):>11}{_fmt(loc['bytes']):>14}"
              f"{(f'{lbp:.0f}' if lbp else 'n/a'):>12}"
              f"{_fmt(peer['pkts']):>11}{_fmt(peer['bytes']):>14}"
              f"{(f'{pbp:.0f}' if pbp else 'n/a'):>12}"
              f"{(f'{ratio:.2f}' if ratio else 'n/a'):>8}")
        if loc["bytes"] and peer["bytes"]:
            storm_delta[g] = (peer["bytes"] - loc["bytes"], peer["pkts"] - loc["pkts"])

    # ---- Section 2/3: per-group control decomposition (local CSVs) --------------
    print()
    print("=" * 96)
    print("SECTION 2  NLSR control decomposition in local run (results/, no storm)")
    print("=" * 96)
    for g in GROUPS:
        csv_path = os.path.join(RESULTS_LOCAL, g, "network_overhead.csv")
        if not os.path.exists(csv_path):
            print(f"{g}: CSV missing")
            continue
        control, meta = _load_relay_control(csv_path)
        total_b = int(control["length"].sum())
        total_p = int(len(control))
        print(f"\n[{g}]  total relay-outbound NLSR control: "
              f"{total_p:,} pkts / {total_b:,} bytes "
              f"({total_b / total_p:.0f} B/pkt)  run={meta['max_rel']:.0f}s")
        grp = control.groupby("sub")["length"].agg(["count", "sum"])
        for sub in ["INFO", "sync", "LSA", "other"]:
            if sub in grp.index:
                c = int(grp.loc[sub, "count"])
                b = int(grp.loc[sub, "sum"])
                print(f"    {sub:<6} {c:>8,} pkts  {b:>12,} bytes  "
                      f"{b / c:>6.0f} B/pkt  {100 * b / total_b:5.1f}% bytes  "
                      f"{100 * c / total_p:5.1f}% pkts")
        # sample names for validation
        samples = (control[control["sub"] == "other"]["name"].head(3).tolist())
        if samples:
            print(f"    other-sample: {samples}")

    # ---- Section 3: storm excess per-packet size -------------------------------
    print()
    print("=" * 96)
    print("SECTION 3  results0 storm excess (peer - local) implied packet size")
    print("=" * 96)
    for g, (db, dp) in storm_delta.items():
        size = (db / dp) if dp else float("nan")
        print(f"{g:<16} delta_bytes={db:>12,.0f}  delta_pkts={dp:>8,.0f}  "
              f"excess_B/pkt={size:>7.0f}")

    # ---- Section 4: per-second control rate peak + burst composition -----------
    print()
    print("=" * 96)
    print("SECTION 4  Per-second relay control rate and burst composition (local CSV)")
    print("=" * 96)
    for g in GROUPS:
        csv_path = os.path.join(RESULTS_LOCAL, g, "network_overhead.csv")
        if not os.path.exists(csv_path):
            continue
        control, _ = _load_relay_control(csv_path)
        control["sec"] = control["rel"].astype(int)
        per_sec = control.groupby("sec")["length"].sum()
        mean_rate = per_sec.mean()
        peak_rate = per_sec.max()
        peak_sec = int(per_sec.idxmax())
        # bytes share concentrated in the 10 busiest seconds
        top10_share = per_sec.sort_values(ascending=False).head(10).sum() / per_sec.sum()
        print(f"\n[{g}] mean={mean_rate:.0f} B/s  peak={peak_rate:.0f} B/s @ t={peak_sec}s  "
              f"peak/mean={peak_rate / mean_rate:.1f}x  top10s_byte_share={100 * top10_share:.1f}%")
        # decompose the busiest window (peak +/- 3s) by sub-type
        win = control[(control["sec"] >= peak_sec - 3) & (control["sec"] <= peak_sec + 3)]
        wb = int(win["length"].sum())
        comp = win.groupby("sub")["length"].sum()
        parts = "  ".join(
            f"{s}={int(comp.get(s, 0)):,}B({100 * comp.get(s, 0) / wb:.0f}%)"
            for s in ["INFO", "sync", "LSA", "other"]
        )
        print(f"    busiest window t=[{peak_sec - 3},{peak_sec + 3}]s total={wb:,}B  {parts}")

    # ---- Section 5: baseline vs solution (local CSVs with sub-type + spikiness) -
    print()
    print("=" * 96)
    print("SECTION 5  Baseline g0 vs Solution: composition and per-second spikiness")
    print("=" * 96)
    pairs = [
        ("baseline g0", os.path.join(RESULTS_LOCAL, "g0-h60-a10-r15", "network_overhead.csv")),
        ("solution", os.path.join(os.path.dirname(RESULTS_LOCAL), "solution", "network_overhead.csv")),
    ]
    for label, path in pairs:
        if not os.path.exists(path):
            print(f"{label}: CSV missing ({path})")
            continue
        control, _ = _load_relay_control(path)
        _persecond_report(label, control)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
