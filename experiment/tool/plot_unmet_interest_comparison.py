#!/usr/bin/env python3
"""Plot unmet-Interest ratio comparison for baseline and OptoFlood."""

from __future__ import annotations

import argparse
import os
from typing import Dict

import matplotlib.pyplot as plt
import numpy as np


CM_TO_INCH = 1.0 / 2.54
FIGURE_WIDTH_CM = 8.0
FIGURE_HEIGHT_CM = 6.2
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 7
LEGEND_SIZE = 7
BASELINE_COLOR = "#0072B2"
SOLUTION_COLOR = "#D55E00"
VALUE_LABEL_OFFSET = 1.15


def _configure_style() -> None:
    """Configure plotting style for a compact grouped-bar figure."""
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


def _load_metrics(path: str) -> Dict[str, float]:
    """Read unmet-Interest ratios from a metrics text file."""
    values = {
        "Handoff Window Ratio": 1.0,
        "Steady State Ratio": 1.0,
    }
    with open(path, "r", encoding="utf-8") as metrics_file:
        for line in metrics_file:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key in values:
                values[key] = float(value.strip().split()[0])
    return values


def _annotate_bars(ax, bars) -> None:
    """Add compact numeric labels above bars."""
    for bar in bars:
        value = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            max(value * VALUE_LABEL_OFFSET, 1.2e-4),
            f"{value:.4f}",
            ha="center",
            va="bottom",
            fontsize=6,
            rotation=0,
        )


def _parse_args() -> argparse.Namespace:
    """Parse comparison inputs and output path."""
    parser = argparse.ArgumentParser(description="Plot unmet-Interest comparison.")
    parser.add_argument("baseline_metrics", help="Baseline loss metrics file.")
    parser.add_argument("solution_metrics", help="OptoFlood loss metrics file.")
    parser.add_argument("output_pdf", help="Output comparison PDF.")
    parser.add_argument(
        "--log-scale",
        action="store_true",
        help="Use logarithmic y-axis for large ratio differences.",
    )
    return parser.parse_args()


def main() -> int:
    """Generate the unmet-Interest comparison figure."""
    args = _parse_args()
    _configure_style()
    _ensure_parent_dir(args.output_pdf)

    baseline = _load_metrics(args.baseline_metrics)
    solution = _load_metrics(args.solution_metrics)
    categories = ["Handoff\nwindow", "Steady\nstate"]
    baseline_values = [baseline["Handoff Window Ratio"], baseline["Steady State Ratio"]]
    solution_values = [solution["Handoff Window Ratio"], solution["Steady State Ratio"]]

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    x = np.arange(len(categories))
    width = 0.34
    baseline_bars = ax.bar(x - width / 2, baseline_values, width, color=BASELINE_COLOR, label="Baseline")
    solution_bars = ax.bar(x + width / 2, solution_values, width, color=SOLUTION_COLOR, label="OptoFlood")

    if args.log_scale:
        ax.set_yscale("log")
        ax.set_ylim(bottom=1e-4, top=max(max(baseline_values), max(solution_values)) * 2.8)
        ax.set_ylabel("Unmet-Interest ratio")
    else:
        ax.set_ylim(bottom=0, top=max(max(baseline_values), max(solution_values)) * 1.25)
        ax.set_ylabel("Unmet-Interest ratio")

    ax.set_title("Delivery reliability across mobility phases", pad=18)
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.12), ncol=2, frameon=False)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.65)
    _annotate_bars(ax, baseline_bars)
    _annotate_bars(ax, solution_bars)

    fig.subplots_adjust(top=0.74, bottom=0.18, left=0.16, right=0.98)
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
