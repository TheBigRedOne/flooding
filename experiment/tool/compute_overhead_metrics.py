#!/usr/bin/env python3
"""Compute forwarding-overhead metrics from a network-overhead CSV."""

from __future__ import annotations

import argparse

import plot_overhead


def _parse_args() -> argparse.Namespace:
    """Parse the input CSV and output metrics path."""
    parser = argparse.ArgumentParser(description="Compute forwarding-overhead metrics.")
    parser.add_argument("input_csv", help="Input network-overhead CSV.")
    parser.add_argument("metrics_output", help="Output overhead metrics text file.")
    parser.add_argument(
        "--handoff-times",
        default="120, 240",
        help="Comma-separated handoff times (fallback when --handoff-file is absent).",
    )
    parser.add_argument(
        "--handoff-file",
        default=None,
        help="Path to handoffs.txt; when present, its rel_time column overrides --handoff-times.",
    )
    parser.add_argument("--window", type=float, default=10.0, help="Window length after each handoff.")
    parser.add_argument("--prefix", default="/example/LiveStream", help="Application prefix to include.")
    parser.add_argument(
        "--relay-nodes",
        default=",".join(plot_overhead.DEFAULT_RELAY_NODES),
        help="Comma-separated relay nodes counted in the forwarding-cost numerator.",
    )
    parser.add_argument("--consumer-node", default="consumer", help="Consumer node name.")
    return parser.parse_args()


def main() -> int:
    """Compute overhead summary metrics and write the metrics file."""
    args = _parse_args()
    handoff_times = plot_overhead.resolve_handoff_times(args.handoff_file, args.handoff_times)
    try:
        analysis = plot_overhead._load_analysis(
            args.input_csv,
            args.prefix,
            args.relay_nodes,
            args.consumer_node,
            handoff_times,
            args.window,
        )
    except ValueError as exc:
        print(f"Warning: {exc} Cannot generate overhead metrics.")
        plot_overhead._write_empty_outputs(None, None, args.metrics_output)
        return 0

    plot_overhead._ensure_parent_dir(args.metrics_output)
    plot_overhead._write_summary_file(
        args.metrics_output,
        analysis.relay_nodes,
        args.consumer_node,
        args.window,
        analysis.handoff_summaries,
        analysis.full_run_summary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
