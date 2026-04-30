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


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV and output metrics path."""
    parser = argparse.ArgumentParser(description="Compute service-disruption metrics from NDN CSV.")
    parser.add_argument("input_csv", help="Input CSV file from tshark.")
    parser.add_argument("metrics_output", help="Output disruption metrics text file.")
    parser.add_argument(
        "--handoff-times",
        default="120, 240",
        help="Comma-separated handoff times in seconds.",
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
    handoffs_absolute = [start_time + float(t.strip()) for t in args.handoff_times.split(",")]

    all_data_times = np.sort(df[df["type"] == "data"]["time"].unique())
    disruption_times: List[float] = []

    for handoff_time in handoffs_absolute:
        data_before_indices = np.where(all_data_times <= handoff_time)[0]
        if len(data_before_indices) == 0:
            continue
        last_data_time_before = all_data_times[data_before_indices[-1]]

        data_after_indices = np.where(all_data_times > handoff_time)[0]
        if len(data_after_indices) == 0:
            continue
        first_data_time_after = all_data_times[data_after_indices[0]]
        disruption_times.append((first_data_time_after - last_data_time_before) * 1000)

    if not disruption_times:
        print("Warning: Could not calculate any disruption times.")
        _write_empty_output(args.metrics_output)
        return 0

    _write_metrics(args.metrics_output, disruption_times)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
