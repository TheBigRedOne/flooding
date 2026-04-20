#!/usr/bin/env python3
"""Run the selected metric plotting pipeline for one result directory.

Purpose:
    Provide one reusable host-side entry point that maps a scenario-specific
    metric set onto the existing single-metric plotting scripts.

Interface:
    python3 experiment/tool/plot_result_metrics.py --result-dir <dir>
        --metric-set <baseline-profile|full>
        --latency-script <path> --overhead-script <path>
        [--loss-script <path>] [--throughput-script <path>]
        --handoff-times <times> [--window <seconds>]
        [--prefix <name-prefix>] [--relay-nodes <nodes>]
        [--consumer-node <node>] [--timeseries-y-max <value>]
        [--summary-y-max <value>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


RAW_RESULT_FILES = ("consumer_capture.csv", "network_overhead.csv")
METRIC_SET_BASELINE_PROFILE = "baseline-profile"
METRIC_SET_FULL = "full"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for scenario-specific plotting."""
    parser = argparse.ArgumentParser(
        description="Run the selected metric plotting pipeline for one result directory."
    )
    parser.add_argument("--result-dir", required=True, help="Directory containing one result set.")
    parser.add_argument(
        "--metric-set",
        required=True,
        choices=(METRIC_SET_BASELINE_PROFILE, METRIC_SET_FULL),
        help="Named metric set that selects which plotting scripts are executed.",
    )
    parser.add_argument("--latency-script", required=True, help="Path to plot_latency.py.")
    parser.add_argument("--overhead-script", required=True, help="Path to plot_overhead.py.")
    parser.add_argument("--loss-script", help="Path to plot_loss.py.")
    parser.add_argument("--throughput-script", help="Path to plot_throughput.py.")
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
    parser.add_argument(
        "--timeseries-y-max",
        type=float,
        help="Shared y-axis upper bound for the overhead time-series figure.",
    )
    parser.add_argument(
        "--summary-y-max",
        type=float,
        help="Shared y-axis upper bound for the overhead summary figure.",
    )
    return parser.parse_args()


def require_raw_inputs(result_dir: Path) -> None:
    """Ensure that the common raw files exist before plotting begins."""
    missing = [name for name in RAW_RESULT_FILES if not (result_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing required raw files in {result_dir}: {', '.join(missing)}"
        )


def run_command(command: Iterable[str]) -> None:
    """Execute one plotting command and stop on the first failure."""
    subprocess.run(list(command), check=True)


def run_latency_plot(args: argparse.Namespace, result_dir: Path) -> None:
    """Generate the disruption plot and summary text for one result set."""
    run_command(
        [
            sys.executable,
            args.latency_script,
            "--input",
            str(result_dir / "consumer_capture.csv"),
            "--output-dir",
            str(result_dir),
            "--handoff-times",
            args.handoff_times,
            "--prefix",
            args.prefix,
        ]
    )


def run_loss_plot(args: argparse.Namespace, result_dir: Path) -> None:
    """Generate the unmet-interest plot and summary text for one result set."""
    if not args.loss_script:
        raise ValueError("loss-script is required for the full metric set.")
    run_command(
        [
            sys.executable,
            args.loss_script,
            "--input",
            str(result_dir / "consumer_capture.csv"),
            "--output-dir",
            str(result_dir),
            "--handoff-times",
            args.handoff_times,
            "--window",
            str(args.window),
            "--prefix",
            args.prefix,
        ]
    )


def run_throughput_plot(args: argparse.Namespace, result_dir: Path) -> None:
    """Generate the throughput plot and summary text for one result set."""
    if not args.throughput_script:
        raise ValueError("throughput-script is required for the full metric set.")
    run_command(
        [
            sys.executable,
            args.throughput_script,
            "--input",
            str(result_dir / "consumer_capture.csv"),
            "--output-dir",
            str(result_dir),
            "--handoff-times",
            args.handoff_times,
            "--window",
            str(int(args.window)),
        ]
    )


def run_overhead_plot(args: argparse.Namespace, result_dir: Path) -> None:
    """Generate the overhead plots and summary text for one result set."""
    command: List[str] = [
        sys.executable,
        args.overhead_script,
        "--input",
        str(result_dir / "network_overhead.csv"),
        "--output-dir",
        str(result_dir),
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
    ]
    if args.timeseries_y_max is not None:
        command.extend(["--timeseries-y-max", str(args.timeseries_y_max)])
    if args.summary_y_max is not None:
        command.extend(["--summary-y-max", str(args.summary_y_max)])
    run_command(command)


def main() -> int:
    """Execute the configured metric set for the target result directory."""
    args = parse_args()
    result_dir = Path(args.result_dir)
    require_raw_inputs(result_dir)

    run_latency_plot(args, result_dir)
    if args.metric_set == METRIC_SET_FULL:
        run_loss_plot(args, result_dir)
        run_throughput_plot(args, result_dir)
    run_overhead_plot(args, result_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
