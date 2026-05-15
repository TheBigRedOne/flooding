#!/usr/bin/env python3
"""
Plot disruption-time min/max/mean comparison across baseline parameter sets.
"""

from __future__ import annotations

import argparse
import csv
import os
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np


CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.0
PAPER_FIGURE_HEIGHT_CM = 6.0
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
LEGEND_SIZE = 8
FIGURE_TITLE_SIZE = 8
RANGE_BAR_WIDTH = 0.55
RANGE_BAR_COLOR = "#7fb8e0"
RANGE_BAR_EDGECOLOR = "#0072B2"
MEAN_LINE_COLOR = "#0b3d66"
MEAN_LINE_WIDTH = 1.4


def parse_args() -> argparse.Namespace:
    """Parse the summary CSV input and the output PDF path."""
    parser = argparse.ArgumentParser(
        description="Plot min/max/mean disruption across baseline parameter sets."
    )
    parser.add_argument("--input", required=True, help="Input summary CSV.")
    parser.add_argument("--output", required=True, help="Output PDF path.")
    return parser.parse_args()


def _paper_figure_size():
    """Return the figure size in inches for a single-column paper figure."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Configure paper figure style consistent with other plots."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({
        "font.size": FONT_SIZE,
        "axes.labelsize": AXIS_LABEL_SIZE,
        "axes.titlesize": AXIS_TITLE_SIZE,
        "xtick.labelsize": TICK_LABEL_SIZE,
        "ytick.labelsize": TICK_LABEL_SIZE,
        "legend.fontsize": LEGEND_SIZE,
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _read_rows(path: str) -> List[dict]:
    """Read the summary CSV into a list of row dictionaries."""
    with open(path, "r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def _to_optional_float(raw: str) -> Optional[float]:
    """Convert a CSV field to float, returning None for 'n/a'/empty."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.lower() == "n/a":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _safe_empty_output(path: str) -> None:
    """Write a valid empty PDF placeholder when input data is unusable."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _configure_paper_style()
    fig, _ = plt.subplots(figsize=_paper_figure_size())
    fig.savefig(path)
    plt.close(fig)


def _collect_valid_rows(rows: List[dict]) -> List[Tuple[str, float, float, float]]:
    """Return rows where min/max/mean are all numeric, preserving CSV order."""
    valid: List[Tuple[str, float, float, float]] = []
    for row in rows:
        label = row.get("profile_label", "").strip() or row.get("profile", "").strip()
        dis_min = _to_optional_float(row.get("disruption_min_ms", ""))
        dis_max = _to_optional_float(row.get("disruption_max_ms", ""))
        dis_mean = _to_optional_float(row.get("disruption_mean_ms", ""))
        if dis_min is None or dis_max is None or dis_mean is None:
            continue
        valid.append((label, dis_min, dis_max, dis_mean))
    return valid


def main() -> int:
    """Render the disruption-range comparison figure."""
    args = parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    if not os.path.exists(args.input):
        _safe_empty_output(args.output)
        return 0

    rows = _read_rows(args.input)
    valid_rows = _collect_valid_rows(rows)
    if not valid_rows:
        _safe_empty_output(args.output)
        return 0

    labels = [item[0] for item in valid_rows]
    mins = [item[1] for item in valid_rows]
    maxs = [item[2] for item in valid_rows]
    means = [item[3] for item in valid_rows]
    x = np.arange(len(valid_rows))

    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())

    heights = [hi - lo for lo, hi in zip(mins, maxs)]
    ax.bar(
        x,
        heights,
        width=RANGE_BAR_WIDTH,
        bottom=mins,
        color=RANGE_BAR_COLOR,
        edgecolor=RANGE_BAR_EDGECOLOR,
        linewidth=0.8,
        label="Min-max range",
    )

    half_width = RANGE_BAR_WIDTH / 2.0
    ax.hlines(
        means,
        x - half_width,
        x + half_width,
        color=MEAN_LINE_COLOR,
        linewidth=MEAN_LINE_WIDTH,
        label="Mean",
    )

    ax.set_xlabel("Baseline Parameter Group")
    ax.set_ylabel("Disruption Time (ms)")
    ax.set_title("Per-Group Disruption Range and Mean")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper right", frameon=False)
    ax.grid(True, axis="y", linestyle="--", alpha=0.7)
    fig.tight_layout()
    plt.savefig(args.output)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
