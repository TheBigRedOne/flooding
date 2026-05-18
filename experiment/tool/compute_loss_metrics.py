#!/usr/bin/env python3
"""Compute unmet-Interest metrics from a consumer packet CSV."""

from __future__ import annotations

import argparse
import bisect
import os

import pandas as pd


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_default_metrics(metrics_output: str) -> None:
    """Write conservative default metrics when the input data is unusable."""
    _ensure_parent_dir(metrics_output)
    with open(metrics_output, "w", encoding="utf-8") as output_file:
        output_file.write("Handoff Window Ratio: 1.0\n")
        output_file.write("Steady State Ratio: 1.0\n")


def _write_metrics(
    metrics_output: str,
    handoff_ratio: float,
    steady_state_ratio: float,
    handoff_total: int,
    handoff_unmet: int,
    steady_total: int,
    steady_unmet: int,
    deadline: float,
) -> None:
    """Write the unmet-Interest metrics to the requested text output."""
    _ensure_parent_dir(metrics_output)
    with open(metrics_output, "w", encoding="utf-8") as output_file:
        output_file.write(f"Handoff Window Ratio: {handoff_ratio:.4f}\n")
        output_file.write(f"Steady State Ratio: {steady_state_ratio:.4f}\n")
        output_file.write(f"Handoff Requests: {handoff_total}\n")
        output_file.write(f"Handoff Unmet: {handoff_unmet}\n")
        output_file.write(f"Steady Requests: {steady_total}\n")
        output_file.write(f"Steady Unmet: {steady_unmet}\n")
        output_file.write(f"Deadline Seconds: {deadline:.2f}\n")


def _normalize_name(name: str) -> str:
    """Return the canonical data name before signer metadata."""
    return str(name).split(",", 1)[0].strip()


def _calculate_unmet_ratio(requests_df: pd.DataFrame) -> float:
    """Return the unmet-Interest ratio for request records containing `met`."""
    total = len(requests_df)
    if total == 0:
        return 0.0
    unmet = int((~requests_df["met"]).sum())
    return unmet / total


def _load_handoff_times_from_file(path: str) -> list[float]:
    """Read relative handoff times (seconds) from a handoffs.txt file.

    The file is the tab-separated artifact written by exp.py. Only the third
    column (rel_time) is consumed; the header row is skipped.
    """
    handoff_times: list[float] = []
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


def _resolve_handoff_times(args: argparse.Namespace) -> list[float]:
    """Resolve the handoff time list from either --handoff-file or --handoff-times."""
    if args.handoff_file and os.path.exists(args.handoff_file):
        return _load_handoff_times_from_file(args.handoff_file)
    return [float(token.strip()) for token in args.handoff_times.split(",") if token.strip()]


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV, optional handoff file, and output metrics path."""
    parser = argparse.ArgumentParser(description="Compute unmet-Interest metrics from NDN CSV.")
    parser.add_argument("input_csv", help="Input CSV file from tshark.")
    parser.add_argument(
        "handoff_file",
        nargs="?",
        default=None,
        help="Optional handoffs.txt; when present, its rel_time column overrides --handoff-times.",
    )
    parser.add_argument("metrics_output", help="Output unmet-Interest metrics text file.")
    parser.add_argument(
        "--handoff-times",
        default="120, 240",
        help="Comma-separated handoff times (fallback when no handoff_file is given).",
    )
    parser.add_argument("--window", type=float, default=10.0, help="Window length after each handoff.")
    parser.add_argument("--prefix", default="/example/LiveStream", help="Application prefix to include.")
    parser.add_argument(
        "--deadline",
        type=float,
        default=6.0,
        help="Deadline in seconds to consider an Interest satisfied by Data.",
    )
    return parser.parse_args()


def main() -> int:
    """Compute unmet-Interest ratios and write the metrics file."""
    args = _parse_args()

    try:
        df = pd.read_csv(args.input_csv)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input_csv} is empty or not found. No loss calculated.")
        _write_default_metrics(args.metrics_output)
        return 0

    df.rename(columns={"frame.time_epoch": "time", "ndn.type": "type", "ndn.name": "name"}, inplace=True)
    df = df.dropna(subset=["time", "type", "name"]).copy()
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])
    df = df[df["name"].astype(str).str.startswith(args.prefix)]
    df = df[~df["name"].astype(str).str.startswith("/localhost/")]
    df = df[~df["name"].astype(str).str.startswith("/localhop/ndn/nlsr/")]
    if df.empty:
        print(f"Warning: No packets under prefix {args.prefix}. No loss calculated.")
        _write_default_metrics(args.metrics_output)
        return 0

    df["type"] = df["type"].str.lower()
    df = df[df["type"].isin(["interest", "data"])].copy()
    if df.empty:
        print("Warning: No Interest/Data packets after filtering. No loss calculated.")
        _write_default_metrics(args.metrics_output)
        return 0
    df["base_name"] = df["name"].apply(_normalize_name)

    start_time = df["time"].min()
    handoffs = _resolve_handoff_times(args)
    interests = df[df["type"] == "interest"][["time", "base_name"]].sort_values("time")
    data = df[df["type"] == "data"][["time", "base_name"]].sort_values("time")
    if interests.empty:
        print("Warning: No Interests after filtering. No loss calculated.")
        _write_default_metrics(args.metrics_output)
        return 0

    first_requests = interests.groupby("base_name", as_index=False)["time"].min()
    data_times_by_name = {name: grp["time"].tolist() for name, grp in data.groupby("base_name")}

    records = []
    for _, row in first_requests.iterrows():
        name = row["base_name"]
        req_time = float(row["time"])
        data_times = data_times_by_name.get(name, [])
        idx = bisect.bisect_left(data_times, req_time)
        data_time = data_times[idx] if idx < len(data_times) else None
        met = data_time is not None and (data_time - req_time) <= args.deadline
        records.append(
            {
                "base_name": name,
                "request_time": req_time,
                "data_time": data_time,
                "met": met,
                "relative_time": req_time - start_time,
            }
        )
    requests_df = pd.DataFrame.from_records(records)

    handoff_mask = pd.Series(False, index=requests_df.index)
    for handoff in handoffs:
        handoff_mask |= (
            (requests_df["relative_time"] >= handoff)
            & (requests_df["relative_time"] < handoff + args.window)
        )

    handoff_df = requests_df[handoff_mask]
    steady_state_df = requests_df[~handoff_mask]
    handoff_total = len(handoff_df)
    steady_total = len(steady_state_df)
    handoff_unmet = int((~handoff_df["met"]).sum()) if handoff_total else 0
    steady_unmet = int((~steady_state_df["met"]).sum()) if steady_total else 0

    _write_metrics(
        args.metrics_output,
        _calculate_unmet_ratio(handoff_df),
        _calculate_unmet_ratio(steady_state_df),
        handoff_total,
        handoff_unmet,
        steady_total,
        steady_unmet,
        args.deadline,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
