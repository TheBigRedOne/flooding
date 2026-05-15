#!/usr/bin/env python3
"""Compute service-disruption metrics from a consumer packet CSV."""

from __future__ import annotations

import argparse
import os
from typing import List

import numpy as np
import pandas as pd


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_empty_output(metrics_output: str) -> None:
    """Create an empty metrics file when the input data is unusable."""
    _ensure_parent_dir(metrics_output)
    open(metrics_output, "w").close()


def _write_metrics(metrics_output: str, disruption_times: List[float]) -> None:
    """Write per-handoff disruption metrics to the requested text output."""
    _ensure_parent_dir(metrics_output)
    with open(metrics_output, "w", encoding="utf-8") as metrics_file:
        for index, disruption in enumerate(disruption_times, start=1):
            metrics_file.write(f"Handoff {index} Disruption Time: {disruption:.2f} ms\n")


def _load_handoff_times_from_file(path: str) -> List[float]:
    """Read relative handoff times (seconds) from a handoffs.txt file.

    The file is the tab-separated artifact written by exp.py. The first row is
    a header; each subsequent row carries `index abs_time rel_time from_node
    to_node interval_s`. Only the rel_time column is consumed here.
    """
    handoff_times: List[float] = []
    with open(path, "r", encoding="utf-8") as input_file:
        for raw_line in input_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.lower().startswith("index"):
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue
            try:
                handoff_times.append(float(tokens[2]))
            except ValueError:
                continue
    return handoff_times


def _resolve_handoff_times(args: argparse.Namespace) -> List[float]:
    """Resolve the handoff time list from either --handoff-file or --handoff-times."""
    if args.handoff_file and os.path.exists(args.handoff_file):
        return _load_handoff_times_from_file(args.handoff_file)
    return [float(token.strip()) for token in args.handoff_times.split(",") if token.strip()]


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV and output metrics path."""
    parser = argparse.ArgumentParser(description="Compute service-disruption metrics from NDN CSV.")
    parser.add_argument("input_csv", help="Input CSV file from tshark.")
    parser.add_argument("metrics_output", help="Output disruption metrics text file.")
    parser.add_argument(
        "--handoff-times",
        default="120, 240",
        help="Comma-separated handoff times in seconds (fallback when --handoff-file is absent).",
    )
    parser.add_argument(
        "--handoff-file",
        default=None,
        help="Path to handoffs.txt; when present, its rel_time column overrides --handoff-times.",
    )
    parser.add_argument(
        "--search-window",
        type=float,
        default=60.0,
        help="Seconds after each handoff in which to search for the disruption gap.",
    )
    parser.add_argument(
        "--pre-margin",
        type=float,
        default=1.0,
        help="Seconds before each handoff included to account for timestamp alignment.",
    )
    parser.add_argument("--prefix", default="/example/LiveStream", help="Application prefix to include.")
    return parser.parse_args()


def main() -> int:
    """Compute disruption times and write the metrics file."""
    args = _parse_args()

    try:
        df = pd.read_csv(args.input_csv)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input_csv} is empty or not found. Skipping analysis.")
        _write_empty_output(args.metrics_output)
        return 0

    df.rename(columns={"frame.time_epoch": "time", "ndn.type": "type", "ndn.name": "name"}, inplace=True)
    df = df.dropna().copy()
    df = df[df["name"].astype(str).str.startswith(args.prefix)]
    df = df[~df["name"].astype(str).str.startswith("/localhost/")]
    df = df[~df["name"].astype(str).str.startswith("/localhop/ndn/nlsr/")]

    if df.empty:
        print(f"Warning: No packets under prefix {args.prefix}. Skipping analysis.")
        _write_empty_output(args.metrics_output)
        return 0

    df["type"] = df["type"].str.lower()
    start_time = df["time"].min()
    handoff_relatives = _resolve_handoff_times(args)
    if not handoff_relatives:
        print("Warning: No handoff times available. Skipping analysis.")
        _write_empty_output(args.metrics_output)
        return 0
    handoffs_absolute = [start_time + value for value in handoff_relatives]

    all_data_times = np.sort(df[df["type"] == "data"]["time"].unique())
    disruption_times: List[float] = []

    for handoff_time in handoffs_absolute:
        search_start = handoff_time - args.pre_margin
        search_end = handoff_time + args.search_window
        candidate_gaps: List[float] = []

        for previous_time, next_time in zip(all_data_times, all_data_times[1:]):
            if previous_time < search_start or previous_time > search_end:
                continue
            candidate_gaps.append((next_time - previous_time) * 1000)

        if not candidate_gaps:
            continue
        disruption_times.append(max(candidate_gaps))

    if not disruption_times:
        print("Warning: Could not calculate any disruption times.")
        _write_empty_output(args.metrics_output)
        return 0

    _write_metrics(args.metrics_output, disruption_times)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
