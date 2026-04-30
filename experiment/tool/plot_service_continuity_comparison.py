#!/usr/bin/env python3
"""Plot throughput and disruption comparison for baseline and OptoFlood."""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator, ScalarFormatter


CM_TO_INCH = 1.0 / 2.54
FIGURE_WIDTH_CM = 17.6
FIGURE_HEIGHT_CM = 8.2
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 7
LEGEND_SIZE = 7
BASELINE_COLOR = "dimgray"
SOLUTION_COLOR = "seagreen"
HANDOFF_SHADE_ALPHA = 0.14
APP_PREFIX = "/example/LiveStream"


def _configure_style() -> None:
    """Configure plotting style for a dense two-panel paper figure."""
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


def _load_disruption_metrics(metrics_path: str) -> List[float]:
    """Read per-handoff disruption values in milliseconds."""
    values: List[float] = []
    with open(metrics_path, "r", encoding="utf-8") as metrics_file:
        for line in metrics_file:
            if "Disruption Time:" not in line:
                continue
            values.append(float(line.split("Disruption Time:", 1)[1].strip().split()[0]))
    if not values:
        raise ValueError(f"No disruption metrics found in {metrics_path}")
    return values


def _annotate_bars(ax, bars) -> None:
    """Annotate grouped bars with compact duration labels."""
    for bar in bars:
        value = bar.get_height()
        label = f"{value / 1000:.1f}s" if value >= 1000 else f"{value:.0f}ms"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.12,
            label,
            ha="center",
            va="bottom",
            fontsize=6,
            rotation=0,
        )


def _parse_args() -> argparse.Namespace:
    """Parse comparison inputs and output path."""
    parser = argparse.ArgumentParser(description="Plot service-continuity comparison.")
    parser.add_argument("baseline_csv", help="Baseline consumer CSV.")
    parser.add_argument("solution_csv", help="OptoFlood consumer CSV.")
    parser.add_argument("baseline_disruption", help="Baseline disruption metrics file.")
    parser.add_argument("solution_disruption", help="OptoFlood disruption metrics file.")
    parser.add_argument("output_pdf", help="Output composite PDF.")
    parser.add_argument("--handoff-times", default="120, 240", help="Comma-separated handoff times.")
    parser.add_argument("--window", type=float, default=10.0, help="Handoff shading window in seconds.")
    return parser.parse_args()


def main() -> int:
    """Generate the service-continuity comparison figure."""
    args = _parse_args()
    _configure_style()
    _ensure_parent_dir(args.output_pdf)

    baseline_times, baseline_values = _aggregate_per_second(_load_packets(args.baseline_csv))
    solution_times, solution_values = _aggregate_per_second(_load_packets(args.solution_csv))
    baseline_disruption = _load_disruption_metrics(args.baseline_disruption)
    solution_disruption = _load_disruption_metrics(args.solution_disruption)

    fig, (ax_throughput, ax_disruption) = plt.subplots(
        1,
        2,
        figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH),
        gridspec_kw={"width_ratios": [1.45, 1.0], "wspace": 0.32},
    )

    ax_throughput.plot(
        baseline_times,
        baseline_values,
        color=BASELINE_COLOR,
        linewidth=1.0,
        label="Baseline",
    )
    ax_throughput.plot(
        solution_times,
        solution_values,
        color=SOLUTION_COLOR,
        linewidth=1.0,
        label="OptoFlood",
    )
    for index, handoff in enumerate(float(t.strip()) for t in args.handoff_times.split(",") if t.strip()):
        ax_throughput.axvspan(
            handoff,
            handoff + args.window,
            color="orange",
            alpha=HANDOFF_SHADE_ALPHA,
            label="Handoff window" if index == 0 else None,
        )
    ax_throughput.set_title("(a) Consumer throughput")
    ax_throughput.set_xlabel("Time (s)")
    ax_throughput.set_ylabel("Throughput (bytes/s)")
    ax_throughput.yaxis.set_major_formatter(ScalarFormatter(useMathText=False))
    ax_throughput.ticklabel_format(style="plain", axis="y")
    ax_throughput.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
    ax_throughput.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax_throughput.legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=3, frameon=False)

    count = min(len(baseline_disruption), len(solution_disruption))
    x = np.arange(count)
    width = 0.34
    baseline_bars = ax_disruption.bar(
        x - width / 2,
        baseline_disruption[:count],
        width,
        color=BASELINE_COLOR,
        label="Baseline",
    )
    solution_bars = ax_disruption.bar(
        x + width / 2,
        solution_disruption[:count],
        width,
        color=SOLUTION_COLOR,
        label="OptoFlood",
    )
    ax_disruption.set_yscale("log")
    ax_disruption.set_title("(b) Service disruption")
    ax_disruption.set_xlabel("Handoff")
    ax_disruption.set_ylabel("Disruption time (ms, log scale)")
    ax_disruption.set_xticks(x)
    ax_disruption.set_xticklabels([str(i + 1) for i in range(count)])
    ax_disruption.set_ylim(bottom=max(1.0, min(solution_disruption[:count]) * 0.45))
    _annotate_bars(ax_disruption, baseline_bars)
    _annotate_bars(ax_disruption, solution_bars)
    ax_disruption.legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=2, frameon=False)
    ax_disruption.grid(True, axis="y", which="both", linestyle="--", alpha=0.6)

    fig.subplots_adjust(top=0.78, bottom=0.18, left=0.07, right=0.98)
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
