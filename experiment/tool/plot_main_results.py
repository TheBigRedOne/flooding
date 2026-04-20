#!/usr/bin/env python3
"""Run the full baseline-default versus solution plotting pipeline.

Purpose:
    Generate the four primary metrics for the default baseline result set and
    the solution result set while preserving a shared overhead y-axis.

Interface:
    python3 experiment/tool/plot_main_results.py
        --baseline-dir <dir> --solution-dir <dir>
        --plot-driver <path>
        --overhead-ymax-script <path>
        --latency-script <path> --loss-script <path>
        --throughput-script <path> --overhead-script <path>
        --handoff-times <times> [--window <seconds>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the main plotting pipeline."""
    parser = argparse.ArgumentParser(
        description="Plot the full metric set for baseline(default) and solution."
    )
    parser.add_argument("--baseline-dir", required=True, help="Default baseline result directory.")
    parser.add_argument("--solution-dir", required=True, help="Solution result directory.")
    parser.add_argument("--plot-driver", required=True, help="Path to plot_result_metrics.py.")
    parser.add_argument(
        "--overhead-ymax-script",
        required=True,
        help="Path to compute_overhead_ymax.py.",
    )
    parser.add_argument("--latency-script", required=True, help="Path to plot_latency.py.")
    parser.add_argument("--loss-script", required=True, help="Path to plot_loss.py.")
    parser.add_argument("--throughput-script", required=True, help="Path to plot_throughput.py.")
    parser.add_argument("--overhead-script", required=True, help="Path to plot_overhead.py.")
    parser.add_argument("--handoff-times", required=True, help="Comma-separated handoff times.")
    parser.add_argument("--window", type=float, default=10.0, help="Window length after a handoff.")
    parser.add_argument(
        "--prefix",
        default="/example/LiveStream",
        help="Application prefix passed to the plotting scripts.",
    )
    parser.add_argument(
        "--relay-nodes",
        default="core,agg1,agg2,acc1,acc2,acc3,acc4,acc5,acc6",
        help="Comma-separated relay nodes passed to plot_overhead.py.",
    )
    parser.add_argument(
        "--consumer-node",
        default="consumer",
        help="Consumer node name passed to plot_overhead.py.",
    )
    return parser.parse_args()


def run_command(command: Iterable[str]) -> subprocess.CompletedProcess[str]:
    """Execute one subprocess command and return its completed process."""
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=True,
    )


def compute_shared_overhead_limits(args: argparse.Namespace) -> Tuple[float, float]:
    """Compute one overhead y-axis pair shared by baseline(default) and solution."""
    result = run_command(
        [
            sys.executable,
            args.overhead_ymax_script,
            "--inputs",
            str(Path(args.baseline_dir) / "network_overhead.csv"),
            str(Path(args.solution_dir) / "network_overhead.csv"),
            "--handoff-times",
            args.handoff_times,
        ]
    )
    values = result.stdout.strip().split()
    if len(values) != 2:
        raise ValueError(
            "compute_overhead_ymax.py did not return the expected two numeric values."
        )
    return float(values[0]), float(values[1])


def run_full_metric_set(
    result_dir: Path,
    args: argparse.Namespace,
    timeseries_y_max: float,
    summary_y_max: float,
) -> None:
    """Generate the four main metrics for one result directory."""
    command: List[str] = [
        sys.executable,
        args.plot_driver,
        "--result-dir",
        str(result_dir),
        "--metric-set",
        "full",
        "--latency-script",
        args.latency_script,
        "--loss-script",
        args.loss_script,
        "--throughput-script",
        args.throughput_script,
        "--overhead-script",
        args.overhead_script,
        "--handoff-times",
        args.handoff_times,
        "--window",
        str(args.window),
        "--prefix",
        args.prefix,
        "--relay-nodes",
        args.relay_nodes,
        "--consumer-node",
        args.consumer_node,
        "--timeseries-y-max",
        str(timeseries_y_max),
        "--summary-y-max",
        str(summary_y_max),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    """Plot the baseline(default) and solution result sets with shared overhead axes."""
    args = parse_args()
    timeseries_y_max, summary_y_max = compute_shared_overhead_limits(args)
    run_full_metric_set(Path(args.baseline_dir), args, timeseries_y_max, summary_y_max)
    run_full_metric_set(Path(args.solution_dir), args, timeseries_y_max, summary_y_max)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
