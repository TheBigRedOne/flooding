#!/usr/bin/env python3
"""Plot the per-frame delivery-latency timeline for one run.

X axis: first-request time (seconds, relative to the run start).
Y axis: delivery latency (ms) = Data arrival - first request, per frame.
A horizontal line marks the playout deadline; vertical lines mark hand-offs.
Frames whose Data never arrives are drawn as losses at the top of the axis.
"""

from __future__ import annotations

import argparse
import bisect
import os
from typing import List, Tuple

import matplotlib.pyplot as plt
import pandas as pd

APP_PREFIX = "/example/LiveStream"
CM_TO_INCH = 1.0 / 2.54
FIGURE_WIDTH_CM = 8.0
FIGURE_HEIGHT_CM = 6.0


def _normalize_name(name: str) -> str:
    """Return the canonical data name before any signer metadata."""
    return str(name).split(",", 1)[0].strip()


def _load_handoff_times(path: str) -> List[float]:
    """Read relative handoff times (seconds) from a handoffs.txt file."""
    times: List[float] = []
    if not os.path.exists(path):
        return times
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.lower().startswith("index"):
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue
            try:
                times.append(float(tokens[2]))
            except ValueError:
                continue
    return times


def _per_frame_latency(df: pd.DataFrame) -> Tuple[List[float], List[float], List[float]]:
    """Return (delivered_rel_req, delivered_latency_ms, lost_rel_req) per frame."""
    start_time = float(df["time"].min())
    interests = df[df["type"] == "interest"][["time", "base_name"]].sort_values("time")
    data = df[df["type"] == "data"][["time", "base_name"]].sort_values("time")
    first_requests = interests.groupby("base_name", as_index=False)["time"].min()
    data_times_by_name = {name: grp["time"].tolist() for name, grp in data.groupby("base_name")}

    delivered_req: List[float] = []
    delivered_latency: List[float] = []
    lost_req: List[float] = []
    for _, row in first_requests.iterrows():
        name = row["base_name"]
        req_time = float(row["time"])
        times = data_times_by_name.get(name, [])
        idx = bisect.bisect_left(times, req_time)
        data_time = times[idx] if idx < len(times) else None
        rel_req = req_time - start_time
        if data_time is None:
            lost_req.append(rel_req)
        else:
            delivered_req.append(rel_req)
            delivered_latency.append((float(data_time) - req_time) * 1000.0)
    return delivered_req, delivered_latency, lost_req


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV, handoff file, output path, and deadline."""
    parser = argparse.ArgumentParser(description="Plot per-frame delivery-latency timeline.")
    parser.add_argument("input_csv", help="Consumer packet CSV.")
    parser.add_argument("handoff_file", help="handoffs.txt with relative handoff times.")
    parser.add_argument("output_pdf", help="Output PDF path.")
    parser.add_argument("--deadline", type=float, default=200.0, help="Playout deadline in ms.")
    return parser.parse_args()


def _save_empty(path: str) -> None:
    """Write a valid empty PDF placeholder."""
    fig = plt.figure(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    """Compute per-frame delivery latency and write the timeline figure."""
    args = _parse_args()
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({"font.size": 8, "font.family": "serif"})
    plt.rcParams["pdf.use14corefonts"] = True

    try:
        df = pd.read_csv(args.input_csv)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: {args.input_csv} empty or missing. Writing empty timeline.")
        _save_empty(args.output_pdf)
        return 0

    df = df.rename(columns={"frame.time_epoch": "time", "ndn.type": "type", "ndn.name": "name"})
    df = df.dropna(subset=["time", "type", "name"]).copy()
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])
    df = df[df["name"].astype(str).str.startswith(APP_PREFIX)]
    df = df[~df["name"].astype(str).str.startswith("/localhost/")]
    df = df[~df["name"].astype(str).str.startswith("/localhop/ndn/nlsr/")]
    if df.empty:
        print(f"Warning: no app packets in {args.input_csv}. Writing empty timeline.")
        _save_empty(args.output_pdf)
        return 0
    df["type"] = df["type"].astype(str).str.lower()
    df["base_name"] = df["name"].apply(_normalize_name)

    delivered_req, delivered_latency, lost_req = _per_frame_latency(df)
    handoff_times = _load_handoff_times(args.handoff_file)

    fig = plt.figure(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    ax = fig.add_subplot(1, 1, 1)

    if delivered_req:
        ax.scatter(delivered_req, delivered_latency, s=4, color="steelblue",
                   alpha=0.6, label="Delivered")

    if delivered_latency:
        top_level = max(max(delivered_latency), args.deadline) * 1.1
    else:
        top_level = args.deadline * 1.5
    if lost_req:
        ax.scatter(lost_req, [top_level] * len(lost_req), s=8, marker="x",
                   color="firebrick", label="Lost")

    ax.axhline(args.deadline, color="black", linestyle="--", linewidth=1.0,
               label=f"Deadline {args.deadline:.0f} ms")
    for index, handoff in enumerate(handoff_times):
        ax.axvline(handoff, color="orange", linestyle=":", linewidth=0.8,
                   label="Hand-off" if index == 0 else None)

    ax.set_xlabel("Request time (s)")
    ax.set_ylabel("Delivery latency (ms)")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend(frameon=False, loc="upper right", fontsize=7)
    fig.tight_layout()
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"Generated delivery timeline {args.output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
