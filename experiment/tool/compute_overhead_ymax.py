import argparse

import plot_overhead


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute shared y-axis limits for paired overhead plots."
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Input network-overhead CSV files that should share axis limits.",
    )
    parser.add_argument(
        "--handoff-times",
        type=str,
        help="Comma-separated list of handoff event times in seconds.",
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
        default="/example/LiveStream",
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
    args = parser.parse_args()

    timeseries_y_max = 0.0
    summary_y_max = 0.0
    for input_path in args.inputs:
        analysis = plot_overhead._load_analysis(
            input_path,
            args.prefix,
            args.relay_nodes,
            args.consumer_node,
            args.handoff_times,
            args.window,
        )
        timeseries_y_max = max(timeseries_y_max, plot_overhead._compute_timeseries_y_max(analysis))
        summary_y_max = max(summary_y_max, plot_overhead._compute_summary_y_max(analysis))

    print(f"{timeseries_y_max:.6f} {summary_y_max:.6f}")


if __name__ == "__main__":
    main()
