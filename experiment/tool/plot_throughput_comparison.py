#!/usr/bin/env python3
"""Plot consumer-throughput comparison for baseline and OptoFlood."""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, ScalarFormatter


CM_TO_INCH = 1.0 / 2.54
FIGURE_WIDTH_CM = 8.0
FIGURE_HEIGHT_CM = 6.0
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 7
LEGEND_SIZE = 7
BASELINE_COLOR = "#0072B2"
SOLUTION_COLOR = "#D55E00"
HANDOFF_SHADE_ALPHA = 0.14
APP_PREFIX = "/example/LiveStream"


def _configure_style() -> None:
    """Configure plotting style for the throughput comparison figure."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "font.size": FONT_SIZE,
            "axes.labelsize": AXIS_LABEL_SIZE,
            "axes.titlesize": AXIS_TITLE_SIZE,
            "xtick.labelsize": TICK_LABEL_SIZE,
            "ytick.labelsize": TICK_LABEL_SIZE,
            "legend.fontsize": LEGEND_SIZE,
        }
    )
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_packets(csv_path: str) -> List[Tuple[float, int]]:
    """Load application packet timestamps and frame lengths from a tshark CSV."""
    packets: List[Tuple[float, int]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            name = (row.get("ndn.name") or "").strip()
            if not name.startswith(APP_PREFIX):
                continue
            if name.startswith("/localhost/") or name.startswith("/localhop/ndn/nlsr/"):
                continue
            try:
                packets.append((float(row["frame.time_epoch"]), int(float(row["frame.len"]))))
            except (KeyError, ValueError):
                continue
    if not packets:
        raise ValueError(f"No application packets found in {csv_path}")
    return packets


def _aggregate_per_second(packets: Iterable[Tuple[float, int]]) -> Tuple[List[int], List[int]]:
    """Return relative seconds and bytes per second for a packet trace."""
    per_second: Dict[int, int] = defaultdict(int)
    for timestamp, frame_len in packets:
        per_second[int(timestamp)] += frame_len
    seconds = list(range(min(per_second), max(per_second) + 1))
    start = seconds[0]
    return [second - start for second in seconds], [per_second.get(second, 0) for second in seconds]


def _load_handoff_times_from_file(path: str) -> List[float]:
    """Read relative handoff times (seconds) from a handoffs.txt file."""
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


def _resolve_handoff_times(
    handoff_file: Optional[str],
    handoff_times_raw: str,
) -> List[float]:
    """Resolve a handoff time list, preferring the on-disk file when available."""
    if handoff_file and os.path.exists(handoff_file):
        return _load_handoff_times_from_file(handoff_file)
    return [float(token.strip()) for token in handoff_times_raw.split(",") if token.strip()]


def _parse_args() -> argparse.Namespace:
    """Parse throughput comparison inputs and output path."""
    parser = argparse.ArgumentParser(description="Plot consumer-throughput comparison.")
    parser.add_argument("baseline_csv", help="Baseline consumer CSV.")
    parser.add_argument("solution_csv", help="OptoFlood consumer CSV.")
    parser.add_argument("output_pdf", help="Output throughput comparison PDF.")
    parser.add_argument(
        "--handoff-times",
        default="120, 240",
        help="Comma-separated handoff times (fallback when no --*-handoff-file is provided).",
    )
    parser.add_argument(
        "--baseline-handoff-file",
        default=None,
        help="Path to the baseline handoffs.txt; its rel_time column shades baseline handoff windows.",
    )
    parser.add_argument(
        "--solution-handoff-file",
        default=None,
        help="Path to the solution handoffs.txt; its rel_time column shades solution handoff windows.",
    )
    parser.add_argument("--window", type=float, default=10.0, help="Handoff shading window in seconds.")
    return parser.parse_args()


def main() -> int:
    """Generate the consumer-throughput comparison figure."""
    args = _parse_args()
    _configure_style()
    _ensure_parent_dir(args.output_pdf)

    baseline_times, baseline_values = _aggregate_per_second(_load_packets(args.baseline_csv))
    solution_times, solution_values = _aggregate_per_second(_load_packets(args.solution_csv))

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    ax.plot(
        baseline_times,
        baseline_values,
        color=BASELINE_COLOR,
        linewidth=1.25,
        linestyle="-",
        label="Baseline",
    )
    ax.plot(
        solution_times,
        solution_values,
        color=SOLUTION_COLOR,
        linewidth=1.25,
        linestyle="--",
        label="OptoFlood",
    )
    baseline_handoffs = _resolve_handoff_times(args.baseline_handoff_file, args.handoff_times)
    solution_handoffs = _resolve_handoff_times(args.solution_handoff_file, args.handoff_times)
    union_handoffs = sorted(set(baseline_handoffs) | set(solution_handoffs))
    for index, handoff in enumerate(union_handoffs):
        ax.axvspan(
            handoff,
            handoff + args.window,
            color="orange",
            alpha=HANDOFF_SHADE_ALPHA,
            label="Handoff window" if index == 0 else None,
        )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Throughput (bytes/s)")
    ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=False))
    ax.ticklabel_format(style="plain", axis="y")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
