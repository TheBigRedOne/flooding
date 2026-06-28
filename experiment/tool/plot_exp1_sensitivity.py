#!/usr/bin/env python3
"""Aggregate the Exp 1 request-interval sweep (solution only) into figures.

For each request interval the script reads the consumer packet CSV and the
network-overhead CSV produced for that run, derives per-hand-off metrics, and
plots three sensitivity panels against the request interval:

  * exp1_disruption.pdf  per-hand-off service disruption (ms)
  * exp1_frameloss.pdf   deadline-missed frames per hand-off, one curve per deadline
  * exp1_flood.pdf       flooding load per hand-off (bytes), split into Interest and Data

The flooding load reuses the explicit-flood definition in plot_overhead so the
numbers are consistent with the main overhead figures.
"""

from __future__ import annotations

import argparse
import bisect
import os
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import plot_overhead

APP_PREFIX = "/LiveStream"

# Window parameters (seconds) for the per-hand-off metrics.
DISRUPTION_SEARCH_WINDOW = 60.0
DISRUPTION_PRE_MARGIN = 1.0
FRAMELOSS_WINDOW = 10.0
FLOOD_WINDOW = 10.0

FIGURE_HEIGHT_CM = 6.5
PRIMARY_LINE_WIDTH = 2.0
SECONDARY_LINE_WIDTH = 1.0


def _normalize_name(name: str) -> str:
    """Return the canonical data name before any signer metadata."""
    return str(name).split(",", 1)[0].strip()


def _load_consumer_csv(path: str) -> Optional[pd.DataFrame]:
    """Load and filter a consumer packet CSV to application Interest/Data rows."""
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return None
    df = df.rename(columns={"frame.time_epoch": "time", "ndn.type": "type", "ndn.name": "name"})
    df = df.dropna(subset=["time", "type", "name"]).copy()
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])
    df = df[df["name"].astype(str).str.startswith(APP_PREFIX)]
    df = df[~df["name"].astype(str).str.startswith("/localhost/")]
    df = df[~df["name"].astype(str).str.startswith("/localhop/ndn/nlsr/")]
    if df.empty:
        return None
    df["type"] = df["type"].astype(str).str.lower()
    df["base_name"] = df["name"].apply(_normalize_name)
    return df


def _load_handoff_times(run_dir: str) -> List[float]:
    """Return relative handoff times (seconds) for one run directory."""
    return plot_overhead.resolve_handoff_times(os.path.join(run_dir, "handoffs.txt"), None)


def _per_handoff_disruption(df: pd.DataFrame, handoff_times: List[float]) -> List[float]:
    """Return the maximum Data inter-arrival gap (ms) in each hand-off window."""
    data_times = np.sort(df[df["type"] == "data"]["time"].unique())
    if data_times.size < 2 or not handoff_times:
        return []
    start_time = float(df["time"].min())
    results: List[float] = []
    for rel in handoff_times:
        handoff = start_time + rel
        search_start = handoff - DISRUPTION_PRE_MARGIN
        search_end = handoff + DISRUPTION_SEARCH_WINDOW
        gaps: List[float] = []
        for prev_time, next_time in zip(data_times, data_times[1:]):
            if prev_time < search_start or prev_time > search_end:
                continue
            gaps.append(float(next_time - prev_time) * 1000.0)
        if gaps:
            results.append(max(gaps))
    return results


def _per_handoff_frameloss(
    df: pd.DataFrame,
    handoff_times: List[float],
    deadlines_s: List[float],
) -> Dict[float, List[int]]:
    """Return, per deadline, the deadline-missed frame count in each hand-off window."""
    out: Dict[float, List[int]] = {deadline: [] for deadline in deadlines_s}
    if not handoff_times:
        return out
    start_time = float(df["time"].min())
    interests = df[df["type"] == "interest"][["time", "base_name"]].sort_values("time")
    data = df[df["type"] == "data"][["time", "base_name"]].sort_values("time")
    if interests.empty:
        return out

    first_requests = interests.groupby("base_name", as_index=False)["time"].min()
    data_times_by_name = {name: grp["time"].tolist() for name, grp in data.groupby("base_name")}

    rel_request_times: List[float] = []
    delivery_latency: List[Optional[float]] = []
    for _, row in first_requests.iterrows():
        name = row["base_name"]
        req_time = float(row["time"])
        times = data_times_by_name.get(name, [])
        idx = bisect.bisect_left(times, req_time)
        data_time = times[idx] if idx < len(times) else None
        rel_request_times.append(req_time - start_time)
        delivery_latency.append(None if data_time is None else float(data_time) - req_time)

    for deadline in deadlines_s:
        for rel_handoff in handoff_times:
            lo = rel_handoff
            hi = rel_handoff + FRAMELOSS_WINDOW
            missed = 0
            for rel_req, latency in zip(rel_request_times, delivery_latency):
                if rel_req < lo or rel_req >= hi:
                    continue
                if latency is None or latency > deadline:
                    missed += 1
            out[deadline].append(missed)
    return out


def _per_handoff_flood(overhead_csv: str, handoff_times: List[float]) -> Dict[str, List[float]]:
    """Return per-hand-off flood bytes (total/interest/data) via plot_overhead."""
    empty: Dict[str, List[float]] = {"total": [], "interest": [], "data": []}
    try:
        analysis = plot_overhead._load_analysis(
            overhead_csv,
            APP_PREFIX,
            ",".join(plot_overhead.DEFAULT_RELAY_NODES),
            "consumer",
            handoff_times,
            FLOOD_WINDOW,
        )
    except ValueError:
        return empty
    return {
        "total": [float(s.flood_bytes) for s in analysis.handoff_summaries],
        "interest": [float(s.interest_flood_bytes) for s in analysis.handoff_summaries],
        "data": [float(s.data_flood_bytes) for s in analysis.handoff_summaries],
    }


def _mean(values: List[float]) -> float:
    """Return the mean of a non-empty list, or NaN when empty."""
    return float(np.mean(values)) if values else float("nan")


def _std(values: List[float]) -> float:
    """Return the population standard deviation, or 0 when fewer than two samples."""
    return float(np.std(values)) if len(values) > 1 else 0.0


def _save_disruption_plot(
    output_path: str,
    intervals: List[int],
    means: List[float],
    stds: List[float],
) -> None:
    """Write the disruption-vs-interval panel."""
    fig = plt.figure(figsize=plot_overhead._paper_figure_size(FIGURE_HEIGHT_CM))
    ax = fig.add_subplot(1, 1, 1)
    ax.errorbar(
        intervals,
        means,
        yerr=stds,
        marker="o",
        linewidth=PRIMARY_LINE_WIDTH,
        capsize=3,
        color="crimson",
    )
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel("Per-hand-off disruption (ms)")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.7)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _save_frameloss_plot(
    output_path: str,
    intervals: List[int],
    series_by_deadline: Dict[int, List[float]],
    primary_deadline_ms: int,
) -> None:
    """Write the deadline-missed-frames-vs-interval panel, one curve per deadline."""
    fig = plt.figure(figsize=plot_overhead._paper_figure_size(FIGURE_HEIGHT_CM))
    ax = fig.add_subplot(1, 1, 1)
    for deadline_ms in sorted(series_by_deadline):
        is_primary = deadline_ms == primary_deadline_ms
        ax.plot(
            intervals,
            series_by_deadline[deadline_ms],
            marker="o" if is_primary else "s",
            linewidth=PRIMARY_LINE_WIDTH if is_primary else SECONDARY_LINE_WIDTH,
            alpha=1.0 if is_primary else 0.6,
            label=f"deadline {deadline_ms} ms",
        )
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel("Deadline-missed frames per hand-off")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _save_flood_plot(
    output_path: str,
    intervals: List[int],
    total_means: List[float],
    interest_means: List[float],
    data_means: List[float],
) -> None:
    """Write the flood-load-vs-interval panel."""
    fig = plt.figure(figsize=plot_overhead._paper_figure_size(FIGURE_HEIGHT_CM))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(intervals, total_means, marker="o", linewidth=PRIMARY_LINE_WIDTH,
            color="darkorange", label="Total flood")
    ax.plot(intervals, interest_means, marker="s", linewidth=SECONDARY_LINE_WIDTH,
            color="royalblue", label="Interest flood")
    ax.plot(intervals, data_means, marker="^", linewidth=SECONDARY_LINE_WIDTH,
            color="firebrick", label="Data flood")
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel("Flood load per hand-off (bytes)")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _parse_args() -> argparse.Namespace:
    """Parse the sweep root, interval list, deadlines, and output directory."""
    parser = argparse.ArgumentParser(description="Plot Exp 1 request-interval sensitivity.")
    parser.add_argument("--root", required=True, help="Sweep root (contains i<interval> directories).")
    parser.add_argument("--intervals", required=True, help="Comma-separated request intervals in ms.")
    parser.add_argument("--deadlines", default="100,200,500,1000",
                        help="Comma-separated playout deadlines in ms for the frame-loss panel.")
    parser.add_argument("--primary-deadline", type=int, default=200,
                        help="Deadline (ms) highlighted in the frame-loss panel.")
    parser.add_argument("--out-dir", required=True, help="Directory for the output PDFs.")
    return parser.parse_args()


def main() -> int:
    """Aggregate per-interval metrics and write the three sensitivity panels."""
    args = _parse_args()
    plot_overhead._configure_paper_style()

    intervals = [int(token.strip()) for token in args.intervals.split(",") if token.strip()]
    deadlines_ms = [int(token.strip()) for token in args.deadlines.split(",") if token.strip()]
    deadlines_s = [deadline / 1000.0 for deadline in deadlines_ms]

    os.makedirs(args.out_dir, exist_ok=True)
    disruption_path = os.path.join(args.out_dir, "exp1_disruption.pdf")
    frameloss_path = os.path.join(args.out_dir, "exp1_frameloss.pdf")
    flood_path = os.path.join(args.out_dir, "exp1_flood.pdf")

    disruption_mean: List[float] = []
    disruption_std: List[float] = []
    frameloss_mean: Dict[int, List[float]] = {deadline: [] for deadline in deadlines_ms}
    flood_total_mean: List[float] = []
    flood_interest_mean: List[float] = []
    flood_data_mean: List[float] = []

    for interval in intervals:
        run_dir = os.path.join(args.root, f"i{interval}")
        handoff_times = _load_handoff_times(run_dir)
        consumer_df = _load_consumer_csv(os.path.join(run_dir, "consumer_capture.csv"))

        if consumer_df is None:
            disruption_mean.append(float("nan"))
            disruption_std.append(0.0)
            for deadline_ms in deadlines_ms:
                frameloss_mean[deadline_ms].append(float("nan"))
        else:
            disruption_values = _per_handoff_disruption(consumer_df, handoff_times)
            disruption_mean.append(_mean(disruption_values))
            disruption_std.append(_std(disruption_values))
            frameloss = _per_handoff_frameloss(consumer_df, handoff_times, deadlines_s)
            for deadline_ms, deadline_s in zip(deadlines_ms, deadlines_s):
                counts = [float(value) for value in frameloss[deadline_s]]
                frameloss_mean[deadline_ms].append(_mean(counts))

        flood = _per_handoff_flood(os.path.join(run_dir, "network_overhead.csv"), handoff_times)
        flood_total_mean.append(_mean(flood["total"]))
        flood_interest_mean.append(_mean(flood["interest"]))
        flood_data_mean.append(_mean(flood["data"]))

    _save_disruption_plot(disruption_path, intervals, disruption_mean, disruption_std)
    _save_frameloss_plot(frameloss_path, intervals, frameloss_mean, args.primary_deadline)
    _save_flood_plot(flood_path, intervals, flood_total_mean, flood_interest_mean, flood_data_mean)
    print(f"Generated Exp 1 sensitivity panels in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
