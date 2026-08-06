#!/usr/bin/env python3
"""Aggregate the Exp 1 request-interval sweep (solution only) into figures.

For each request interval the script reads the consumer packet CSV and the
network-overhead CSV produced for that run, derives per-hand-off metrics, and
plots three sensitivity panels against the request interval:

  * exp1_disruption.pdf  per-hand-off service disruption (ms)
  * exp1_frameloss.pdf   share of frames arriving late per hand-off, one curve per
                         budget, plus the undelivered share as its own series
  * exp1_flood.pdf       flooding load per hand-off (bytes), split into Interest and Data

The flooding load reuses the explicit-flood definition in plot_overhead so the
numbers are consistent with the main overhead figures.
"""

from __future__ import annotations

import argparse
import bisect
import os
from typing import Dict, List, Optional, Tuple

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
    """Return absolute handoff times (Unix epoch seconds) for one run directory."""
    return plot_overhead.resolve_handoff_times(os.path.join(run_dir, "handoffs.txt"), None)


def _per_handoff_disruption(df: pd.DataFrame, handoff_times: List[float]) -> List[float]:
    """Return the maximum Data inter-arrival gap (ms) in each hand-off window."""
    data_times = np.sort(df[df["type"] == "data"]["time"].unique())
    if data_times.size < 2 or not handoff_times:
        return []
    start_time = float(df["time"].min())
    results: List[float] = []
    for rel in plot_overhead.normalize_handoff_times(handoff_times, start_time):
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
    budgets_s: List[float],
) -> Tuple[Dict[float, List[float]], List[float]]:
    """Return per-budget late shares and the undelivered share for each hand-off window.

    A frame counts as late when its delivery latency exceeds the run's median
    delivery latency by more than the budget. The median stands for the steady-state
    depth of the request pipeline: the consumer requests frames a fixed number ahead
    of the live edge, so every frame carries that look-ahead and it scales with the
    request interval. What remains above the median is the delay the hand-off adds.

    Frames that never arrive form their own series, so each budget curve describes
    delivered frames alone.

    Both results are shares of the frames in the window, which makes them comparable
    across request intervals that place different numbers of frames in a fixed
    window.
    """
    out: Dict[float, List[float]] = {budget: [] for budget in budgets_s}
    undelivered: List[float] = []
    if not handoff_times:
        return out, undelivered
    start_time = float(df["time"].min())
    interests = df[df["type"] == "interest"][["time", "base_name"]].sort_values("time")
    data = df[df["type"] == "data"][["time", "base_name"]].sort_values("time")
    if interests.empty:
        return out, undelivered

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

    delivered = [value for value in delivery_latency if value is not None]
    if not delivered:
        return out, undelivered
    steady_latency = float(np.median(delivered))

    rel_handoffs = plot_overhead.normalize_handoff_times(handoff_times, start_time)

    for rel_handoff in rel_handoffs:
        lo = rel_handoff
        hi = rel_handoff + FRAMELOSS_WINDOW
        in_window = [
            latency for rel_req, latency in zip(rel_request_times, delivery_latency)
            if lo <= rel_req < hi
        ]
        if not in_window:
            for budget in budgets_s:
                out[budget].append(float("nan"))
            undelivered.append(float("nan"))
            continue
        excess = [latency - steady_latency for latency in in_window if latency is not None]
        scale = 100.0 / len(in_window)
        for budget in budgets_s:
            out[budget].append(scale * sum(1 for value in excess if value > budget))
        undelivered.append(scale * sum(1 for latency in in_window if latency is None))
    return out, undelivered


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
        label="Measured gap",
    )
    # The metric is the largest interval between consecutive Data arrivals, so its
    # resolution equals one request interval. The floor line marks that resolution;
    # the distance between the curve and the line is the recovery time.
    ax.plot(
        intervals,
        intervals,
        linestyle="--",
        linewidth=SECONDARY_LINE_WIDTH,
        color="gray",
        label="Observation floor (one request interval)",
    )
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel("Per-hand-off disruption (ms)")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.legend(frameon=False, fontsize="small")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _save_frameloss_plot(
    output_path: str,
    intervals: List[int],
    series_by_budget: Dict[int, List[float]],
    undelivered: List[float],
    primary_budget_ms: int,
) -> None:
    """Write the late-frame-share-vs-interval panel, one curve per budget.

    The undelivered share is drawn as its own curve, so each budget curve carries
    the share of delivered frames that the hand-off delayed beyond that budget.
    """
    fig = plt.figure(figsize=plot_overhead._paper_figure_size(FIGURE_HEIGHT_CM))
    ax = fig.add_subplot(1, 1, 1)
    for budget_ms in sorted(series_by_budget):
        is_primary = budget_ms == primary_budget_ms
        ax.plot(
            intervals,
            series_by_budget[budget_ms],
            marker="o" if is_primary else "s",
            linewidth=PRIMARY_LINE_WIDTH if is_primary else SECONDARY_LINE_WIDTH,
            alpha=1.0 if is_primary else 0.6,
            label=f"Late by >{budget_ms} ms",
        )
    ax.plot(
        intervals,
        undelivered,
        marker="x",
        linestyle=":",
        linewidth=SECONDARY_LINE_WIDTH,
        color="black",
        label="Not delivered",
    )
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel("Frames per hand-off (% of window)")
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.legend(frameon=False, fontsize="small")
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
    parser.add_argument("--late-budgets", default="10,25,50",
                        help="Comma-separated budgets in ms for the late-frame panel. A frame "
                             "counts as late when its delivery is delayed by more than the "
                             "budget beyond the run's steady-state latency; values in the tens "
                             "of milliseconds bracket the delay a hand-off introduces.")
    parser.add_argument("--primary-budget", type=int, default=25,
                        help="Budget (ms) highlighted in the late-frame panel.")
    parser.add_argument("--out-dir", required=True, help="Directory for the output PDFs.")
    return parser.parse_args()


def main() -> int:
    """Aggregate per-interval metrics and write the three sensitivity panels."""
    args = _parse_args()
    plot_overhead._configure_paper_style()

    intervals = [int(token.strip()) for token in args.intervals.split(",") if token.strip()]
    budgets_ms = [int(token.strip()) for token in args.late_budgets.split(",") if token.strip()]
    budgets_s = [budget / 1000.0 for budget in budgets_ms]

    os.makedirs(args.out_dir, exist_ok=True)
    disruption_path = os.path.join(args.out_dir, "exp1_disruption.pdf")
    frameloss_path = os.path.join(args.out_dir, "exp1_frameloss.pdf")
    flood_path = os.path.join(args.out_dir, "exp1_flood.pdf")

    disruption_mean: List[float] = []
    disruption_std: List[float] = []
    frameloss_mean: Dict[int, List[float]] = {budget: [] for budget in budgets_ms}
    undelivered_mean: List[float] = []
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
            for budget_ms in budgets_ms:
                frameloss_mean[budget_ms].append(float("nan"))
            undelivered_mean.append(float("nan"))
        else:
            disruption_values = _per_handoff_disruption(consumer_df, handoff_times)
            disruption_mean.append(_mean(disruption_values))
            disruption_std.append(_std(disruption_values))
            frameloss, undelivered = _per_handoff_frameloss(consumer_df, handoff_times, budgets_s)
            for budget_ms, budget_s in zip(budgets_ms, budgets_s):
                shares = [float(value) for value in frameloss[budget_s]]
                frameloss_mean[budget_ms].append(_mean(shares))
            undelivered_mean.append(_mean([float(value) for value in undelivered]))

        flood = _per_handoff_flood(os.path.join(run_dir, "network_overhead.csv"), handoff_times)
        flood_total_mean.append(_mean(flood["total"]))
        flood_interest_mean.append(_mean(flood["interest"]))
        flood_data_mean.append(_mean(flood["data"]))

    _save_disruption_plot(disruption_path, intervals, disruption_mean, disruption_std)
    _save_frameloss_plot(frameloss_path, intervals, frameloss_mean, undelivered_mean,
                         args.primary_budget)
    _save_flood_plot(flood_path, intervals, flood_total_mean, flood_interest_mean, flood_data_mean)
    print(f"Generated Exp 1 sensitivity panels in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
