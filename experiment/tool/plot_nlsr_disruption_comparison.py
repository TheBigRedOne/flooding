#!/usr/bin/env python3
"""
Plot per-handoff disruption comparison from the summary CSV.
"""

from __future__ import annotations

import argparse
import csv
import os
from typing import List

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
BAR_WIDTH = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot per-handoff disruption comparison across NLSR sensitivity profiles."
    )
    parser.add_argument("--input", required=True, help="Input summary CSV.")
    parser.add_argument("--output", required=True, help="Output PDF path.")
    return parser.parse_args()


def _paper_figure_size():
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
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
    with open(path, "r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def _safe_empty_output(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _configure_paper_style()
    fig, _ = plt.subplots(figsize=_paper_figure_size())
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    if not os.path.exists(args.input):
        _safe_empty_output(args.output)
        return 0

    rows = _read_rows(args.input)
    if not rows:
        _safe_empty_output(args.output)
        return 0

    labels = [row["profile_label"] for row in rows]
    handoff_1_values = [float(row["handoff_1_disruption_ms"]) for row in rows]
    handoff_2_values = [float(row["handoff_2_disruption_ms"]) for row in rows]
    x = np.arange(len(rows))

    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    ax.bar(x - BAR_WIDTH / 2, handoff_1_values, BAR_WIDTH, label="Handoff 1", color="steelblue")
    ax.bar(x + BAR_WIDTH / 2, handoff_2_values, BAR_WIDTH, label="Handoff 2", color="darkorange")
    ax.set_xlabel("NLSR Parameter Set (hello / adj-lsa / route-calc)")
    ax.set_ylabel("Disruption Time (ms)")
    ax.set_title("Per-Handoff Disruption Under Baseline NLSR Tuning")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(bottom=0)
    ax.legend()
    ax.grid(True, axis="y", linestyle="--", alpha=0.7)
    fig.tight_layout()
    plt.savefig(args.output)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
