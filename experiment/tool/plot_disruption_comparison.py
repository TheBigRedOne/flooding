#!/usr/bin/env python3
"""Plot per-handoff service-disruption comparison for baseline and OptoFlood."""

from __future__ import annotations

import argparse
import os
from typing import List

import matplotlib.pyplot as plt
import numpy as np


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


def _configure_style() -> None:
    """Configure plotting style for the disruption comparison figure."""
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
    """Parse disruption comparison inputs and output path."""
    parser = argparse.ArgumentParser(description="Plot service-disruption comparison.")
    parser.add_argument("baseline_disruption", help="Baseline disruption metrics file.")
    parser.add_argument("solution_disruption", help="OptoFlood disruption metrics file.")
    parser.add_argument("output_pdf", help="Output disruption comparison PDF.")
    return parser.parse_args()


def main() -> int:
    """Generate the service-disruption comparison figure."""
    args = _parse_args()
    _configure_style()
    _ensure_parent_dir(args.output_pdf)

    baseline_disruption = _load_disruption_metrics(args.baseline_disruption)
    solution_disruption = _load_disruption_metrics(args.solution_disruption)

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    count = min(len(baseline_disruption), len(solution_disruption))
    x = np.arange(count)
    width = 0.34
    baseline_bars = ax.bar(
        x - width / 2,
        baseline_disruption[:count],
        width,
        color=BASELINE_COLOR,
        label="Baseline",
    )
    solution_bars = ax.bar(
        x + width / 2,
        solution_disruption[:count],
        width,
        color=SOLUTION_COLOR,
        label="OptoFlood",
    )
    ax.set_yscale("log")
    ax.set_xlabel("Handoff")
    ax.set_ylabel("Disruption time (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels([str(i + 1) for i in range(count)])
    ax.set_ylim(bottom=max(1.0, min(solution_disruption[:count]) * 0.45))
    _annotate_bars(ax, baseline_bars)
    _annotate_bars(ax, solution_bars)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=2, frameon=False)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.6)
    fig.tight_layout()
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
