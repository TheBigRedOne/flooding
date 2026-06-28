import argparse
from typing import List, Optional

import plot_overhead


def _parse_args() -> argparse.Namespace:
    """Parse inputs, optional handoff files, and the output path."""
    parser = argparse.ArgumentParser(
        description="Compute shared y-axis limits for paired overhead plots."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional positional input CSV files followed by the output path.",
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        help="Input network-overhead CSV files that should share axis limits.",
    )
    parser.add_argument(
        "--handoff-files",
        nargs="+",
        default=None,
        help="Per-input handoff files (one per --inputs entry, same order).",
    )
    parser.add_argument(
        "--handoff-times",
        type=str,
        default="120, 240",
        help="Comma-separated handoff times used when no --handoff-files is provided.",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=10.0,
        help="Time window in seconds after a handoff for summary metrics.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="/LiveStream",
        help="Application prefix to include.",
    )
    parser.add_argument(
        "--relay-nodes",
        type=str,
        default=",".join(plot_overhead.DEFAULT_RELAY_NODES),
        help="Comma-separated relay nodes counted in the forwarding-cost numerator.",
    )
    parser.add_argument(
        "--consumer-node",
        type=str,
        default="consumer",
        help="Consumer node name used for delivered-data reference.",
    )
    parser.add_argument(
        "--output",
        help="Optional file that receives the computed time-series and summary y-axis limits.",
    )
    return parser.parse_args()


def _resolve_inputs_and_output(args: argparse.Namespace) -> tuple[List[str], Optional[str]]:
    """Reconcile the positional and explicit input/output specifications."""
    inputs = list(args.inputs) if args.inputs else []
    output = args.output
    if args.paths:
        if len(args.paths) < 2:
            raise ValueError(
                "positional mode requires at least one input CSV and an output path"
            )
        if not inputs:
            inputs = list(args.paths[:-1])
        if not output:
            output = args.paths[-1]
    if not inputs:
        raise ValueError("at least one input CSV is required")
    return inputs, output


def _per_input_handoff_times(
    inputs: List[str],
    handoff_files: Optional[List[str]],
    handoff_times_raw: str,
) -> List[List[float]]:
    """Return one resolved handoff-time list per input CSV.

    When --handoff-files is provided, its length must match --inputs; the
    rel_time column from each file is used. Otherwise --handoff-times applies
    uniformly to every input.
    """
    if handoff_files:
        if len(handoff_files) != len(inputs):
            raise ValueError(
                f"--handoff-files has {len(handoff_files)} entries but --inputs has {len(inputs)}"
            )
        return [
            plot_overhead.resolve_handoff_times(file_path, handoff_times_raw)
            for file_path in handoff_files
        ]
    shared = plot_overhead.resolve_handoff_times(None, handoff_times_raw)
    return [shared for _ in inputs]


def main() -> None:
    """Compute and emit the shared y-axis upper bounds for overhead plots."""
    args = _parse_args()
    inputs, output = _resolve_inputs_and_output(args)
    per_input_times = _per_input_handoff_times(inputs, args.handoff_files, args.handoff_times)

    timeseries_y_max = 0.0
    summary_y_max = 0.0
    for input_path, handoff_times in zip(inputs, per_input_times):
        analysis = plot_overhead._load_analysis(
            input_path,
            args.prefix,
            args.relay_nodes,
            args.consumer_node,
            handoff_times,
            args.window,
        )
        timeseries_y_max = max(timeseries_y_max, plot_overhead._compute_timeseries_y_max(analysis))
        summary_y_max = max(summary_y_max, plot_overhead._compute_summary_y_max(analysis))

    output_text = f"{timeseries_y_max:.6f} {summary_y_max:.6f}\n"
    if output:
        with open(output, "w", encoding="utf-8") as output_file:
            output_file.write(output_text)
    print(output_text, end="")


if __name__ == "__main__":
    main()
