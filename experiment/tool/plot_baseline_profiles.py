#!/usr/bin/env python3
"""Run baseline-profile plotting and comparison summarization.

Purpose:
    Plot the per-profile baseline metrics that are required for parameter-set
    comparison, then aggregate those outputs into summary and comparison plots.

Interface:
    python3 experiment/tool/plot_baseline_profiles.py --root-dir <dir>
        --profile-config <json>
        --plot-driver <path>
        --summary-script <path>
        --disruption-comparison-script <path>
        --cost-comparison-script <path>
        --latency-script <path>
        --overhead-script <path>
        --handoff-times <times> [--window <seconds>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from baseline_profiles import get_default_profile, get_result_dir, load_profiles


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for baseline profile plotting."""
    parser = argparse.ArgumentParser(
        description="Plot baseline profile metrics and aggregate comparison outputs."
    )
    parser.add_argument("--root-dir", required=True, help="Baseline results root directory.")
    parser.add_argument(
        "--profile-config",
        required=True,
        help="Baseline profile JSON configuration path.",
    )
    parser.add_argument("--plot-driver", required=True, help="Path to plot_result_metrics.py.")
    parser.add_argument("--summary-script", required=True, help="Path to the summary script.")
    parser.add_argument(
        "--disruption-comparison-script",
        required=True,
        help="Path to the baseline disruption comparison plotting script.",
    )
    parser.add_argument(
        "--cost-comparison-script",
        required=True,
        help="Path to the baseline overhead comparison plotting script.",
    )
    parser.add_argument("--latency-script", required=True, help="Path to plot_latency.py.")
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


def run_command(command: Iterable[str]) -> None:
    """Execute one subprocess command and stop on the first failure."""
    subprocess.run(list(command), check=True)


def main() -> int:
    """Generate per-profile baseline plots and aggregated comparison outputs."""
    args = parse_args()
    root_dir = Path(args.root_dir)
    profiles = load_profiles(args.profile_config)
    profile_names = [profile.directory_name for profile in profiles]
    default_profile = get_default_profile(profiles)

    for profile in profiles:
        result_dir = get_result_dir(args.root_dir, profile)
        run_command(
            [
                sys.executable,
                args.plot_driver,
                "--result-dir",
                str(result_dir),
                "--metric-set",
                "baseline-profile",
                "--latency-script",
                args.latency_script,
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
            ]
        )

    summary_csv = root_dir / "summary.csv"
    run_command(
        [
            sys.executable,
            args.summary_script,
            "--root-dir",
            str(root_dir),
            "--profiles",
            ",".join(profile_names),
            "--default-profile",
            default_profile.directory_name,
            "--output",
            str(summary_csv),
        ]
    )
    run_command(
        [
            sys.executable,
            args.disruption_comparison_script,
            "--input",
            str(summary_csv),
            "--output",
            str(root_dir / "disruption_comparison.pdf"),
        ]
    )
    run_command(
        [
            sys.executable,
            args.cost_comparison_script,
            "--input",
            str(summary_csv),
            "--output",
            str(root_dir / "network_cost_comparison.pdf"),
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
