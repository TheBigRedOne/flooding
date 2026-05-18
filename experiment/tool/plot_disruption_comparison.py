#!/usr/bin/env python3
"""Plot aggregated service-disruption comparison for baseline and OptoFlood."""

from __future__ import annotations

import argparse
import os
from typing import List, Tuple

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
BASELINE_FILL = "#9ec8e6"
BASELINE_EDGE = "#0072B2"
SOLUTION_FILL = "#f1b27e"
SOLUTION_EDGE = "#D55E00"
MEAN_COLOR = "#1a1a1a"
MEAN_LINE_WIDTH = 1.4
RANGE_BAR_WIDTH = 0.5


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


def _load_disruption_values(metrics_path: str) -> List[float]:
    """Read all per-handoff disruption values from a metrics text file."""
    values: List[float] = []
    if not os.path.exists(metrics_path):
        return values
    with open(metrics_path, "r", encoding="utf-8") as metrics_file:
        for line in metrics_file:
            if "Disruption Time:" not in line:
                continue
            token = line.split("Disruption Time:", 1)[1].strip().split()
            if not token:
                continue
            try:
                values.append(float(token[0]))
            except ValueError:
                continue
    return values


def _summarise(values: List[float]) -> Tuple[float, float, float]:
    """Return (min, max, mean) of a non-empty value list."""
    return min(values), max(values), sum(values) / len(values)


def _draw_range_bar(
    ax,
    x_position: float,
    values: List[float],
    fill_color: str,
    edge_color: str,
    label: str,
) -> None:
    """Draw one min-max range bar with a horizontal mean indicator."""
    if not values:
        return
    lo, hi, mean_value = _summarise(values)
    ax.bar(
        [x_position],
        [hi - lo],
        width=RANGE_BAR_WIDTH,
        bottom=[lo],
        color=fill_color,
        edgecolor=edge_color,
        linewidth=0.9,
        label=label,
    )
    half = RANGE_BAR_WIDTH / 2.0
    ax.hlines(
        [mean_value],
        [x_position - half],
        [x_position + half],
        color=MEAN_COLOR,
        linewidth=MEAN_LINE_WIDTH,
    )


def _parse_args() -> argparse.Namespace:
    """Parse disruption comparison inputs and output path."""
    parser = argparse.ArgumentParser(description="Plot service-disruption comparison.")
    parser.add_argument("baseline_disruption", help="Baseline disruption metrics file.")
    parser.add_argument("solution_disruption", help="OptoFlood disruption metrics file.")
    parser.add_argument("output_pdf", help="Output disruption comparison PDF.")
    return parser.parse_args()


def main() -> int:
    """Generate the aggregated service-disruption comparison figure."""
    args = _parse_args()
    _configure_style()
    _ensure_parent_dir(args.output_pdf)

    baseline_values = _load_disruption_values(args.baseline_disruption)
    solution_values = _load_disruption_values(args.solution_disruption)
    if not baseline_values and not solution_values:
        fig, _ = plt.subplots(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
        fig.savefig(args.output_pdf)
        plt.close(fig)
        return 0

    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_CM * CM_TO_INCH, FIGURE_HEIGHT_CM * CM_TO_INCH))
    positions = np.array([0.0, 1.0])
    baseline_label = f"Baseline (n={len(baseline_values)})"
    solution_label = f"OptoFlood (n={len(solution_values)})"

    _draw_range_bar(ax, positions[0], baseline_values, BASELINE_FILL, BASELINE_EDGE, "Min–max range")
    _draw_range_bar(ax, positions[1], solution_values, SOLUTION_FILL, SOLUTION_EDGE, "Min–max range")

    handles, plot_labels = ax.get_legend_handles_labels()
    # Deduplicate the shared "Min-max range" entry while preserving the mean indicator.
    seen: set[str] = set()
    unique_handles = []
    for handle, plot_label in zip(handles, plot_labels):
        if plot_label in seen:
            continue
        seen.add(plot_label)
        unique_handles.append(handle)
    mean_handle = plt.Line2D([0], [0], color=MEAN_COLOR, linewidth=MEAN_LINE_WIDTH, label="Mean")
    if unique_handles:
        ax.legend(handles=[*unique_handles, mean_handle], loc="upper right", frameon=False)

    ax.set_yscale("log")
    bottom_values = [value for value in (baseline_values + solution_values) if value > 0]
    ax.set_ylim(bottom=max(1.0, min(bottom_values) * 0.45) if bottom_values else 1.0)
    ax.set_xticks(positions)
    ax.set_xticklabels([baseline_label, solution_label])
    ax.set_ylabel("Disruption time per handoff (ms)")
    ax.set_title("Aggregated per-handoff service disruption")
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.6)
    fig.tight_layout()
    fig.savefig(args.output_pdf, bbox_inches="tight")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
