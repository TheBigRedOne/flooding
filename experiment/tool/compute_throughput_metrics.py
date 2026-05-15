#!/usr/bin/env python3
"""Compute throughput metrics from a consumer packet CSV."""

from __future__ import annotations

import argparse
import csv
import os
from typing import Dict, Iterable, List, Tuple


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_packets(csv_path: str) -> List[Tuple[float, int]]:
    """Load packet timestamps and frame lengths from a tshark CSV file."""
    packets: List[Tuple[float, int]] = []
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            try:
                timestamp = float(row.get("frame.time_epoch", ""))
                frame_len = int(float(row.get("frame.len", "")))
            except (TypeError, ValueError):
                continue
            packets.append((timestamp, frame_len))
    return packets


def _aggregate_per_second(packets: Iterable[Tuple[float, int]]) -> Dict[int, int]:
    """Aggregate packet bytes by integer second."""
    per_second: Dict[int, int] = {}
    for timestamp, frame_len in packets:
        second = int(timestamp)
        per_second[second] = per_second.get(second, 0) + frame_len
    return per_second


def _fill_missing_seconds(per_second: Dict[int, int]) -> Tuple[List[int], List[int]]:
    """Return continuous seconds and byte values for the observed interval."""
    if not per_second:
        return [], []
    seconds = list(range(min(per_second), max(per_second) + 1))
    return seconds, [per_second.get(second, 0) for second in seconds]


def _percentile(values: List[int], percentile: float) -> float:
    """Compute a percentile using linear interpolation."""
    if not values:
        return 0.0
    if percentile <= 0:
        return float(min(values))
    if percentile >= 100:
        return float(max(values))

    sorted_vals = sorted(values)
    rank = (percentile / 100) * (len(sorted_vals) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_vals) - 1)
    fraction = rank - lower
    return sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction


def _write_metrics(metrics_output: str, values: List[int], seconds: List[int]) -> None:
    """Write throughput metrics to the requested text output."""
    avg: float
    peak: float
    p95: float
    total_bytes: int
    duration: int
    if not values or not seconds:
        avg = peak = p95 = 0.0
        total_bytes = 0
        duration = 0
    else:
        total_bytes = sum(values)
        duration = max(seconds[-1] - seconds[0] + 1, 1)
        avg = total_bytes / duration
        peak = float(max(values))
        p95 = _percentile(values, 95)

    _ensure_parent_dir(metrics_output)
    with open(metrics_output, "w", encoding="utf-8") as metrics_file:
        metrics_file.write(f"Average: {avg:.2f} bytes/s\n")
        metrics_file.write(f"Peak: {peak:.2f} bytes/s\n")
        metrics_file.write(f"P95: {p95:.2f} bytes/s\n")
        metrics_file.write(f"TotalBytes: {int(total_bytes)}\n")
        metrics_file.write(f"Duration: {duration:.2f} s\n")


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV and output metrics path."""
    parser = argparse.ArgumentParser(description="Compute throughput metrics from tshark CSV.")
    parser.add_argument("input_csv", help="Input CSV file from tshark.")
    parser.add_argument("metrics_output", help="Output throughput metrics text file.")
    return parser.parse_args()


def main() -> int:
    """Compute throughput metrics and write the metrics file."""
    args = _parse_args()
    if not os.path.exists(args.input_csv):
        _write_metrics(args.metrics_output, [], [])
        return 0

    try:
        packets = _load_packets(args.input_csv)
    except Exception:
        _write_metrics(args.metrics_output, [], [])
        return 0

    seconds, values = _fill_missing_seconds(_aggregate_per_second(packets))
    _write_metrics(args.metrics_output, values, seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
