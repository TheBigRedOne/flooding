#!/usr/bin/env python3
"""
Plot one baseline parameter-set network-cost panel from the summary CSV.

The script emits a single PDF for either full-run FCR or NLSR control traffic,
using the same summary fields and conversions as the former combined figure.
"""

from __future__ import annotations

import argparse
import csv
import os
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np


CM_TO_INCH = 1.0 / 2.54
# Sized for one panel in a full-width IEEE three-subfigure figure.
PAPER_FIGURE_WIDTH_CM = 6.0
PAPER_FIGURE_HEIGHT_CM = 5.0
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
FIGURE_TITLE_SIZE = 8
FCR_BAR_COLOR = "crimson"
CONTROL_BAR_COLOR = "slateblue"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot one of FCR or NLSR control cost across baseline parameter sets."
    )
    parser.add_argument("--input", required=True, help="Input summary CSV.")
    parser.add_argument("--output", required=True, help="Output PDF path.")
    parser.add_argument(
        "--metric",
        required=True,
        choices=("fcr", "control"),
        help="Which single-panel figure to emit.",
    )
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
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _read_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


def _to_optional_float(raw: str | None) -> float | None:
    """Convert a CSV field to float, returning None for 'n/a' or empty values."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.lower() == "n/a":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _safe_empty_output(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _configure_paper_style()
    fig, _ = plt.subplots(figsize=_paper_figure_size())
    fig.savefig(path)
    plt.close(fig)


def _collect_valid_rows(rows: Sequence[dict]) -> List[Tuple[str, float, float]]:
    """Return rows where both FCR and control bytes are numeric, preserving CSV order."""
    valid_rows: List[Tuple[str, float, float]] = []
    for row in rows:
        fcr = _to_optional_float(row.get("full_run_fcr"))
        control = _to_optional_float(row.get("full_run_control_bytes"))
        if fcr is None or control is None:
            continue
        valid_rows.append((row["profile_label"], fcr, control))
    return valid_rows


def _draw_bar_panel(labels: Sequence[str], values: Sequence[float], color: str, ylabel: str, output: str, plain_y: bool) -> None:
    """Render one labelled bar panel and write it to output."""
    x = np.arange(len(labels))
    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    ax.bar(x, values, color=color)
    ax.set_xlabel("Baseline Parameter Group")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", alpha=0.7)
    if plain_y:
        ax.ticklabel_format(style="plain", axis="y", useOffset=False)
    fig.tight_layout()
    plt.savefig(output)
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

    valid_rows = _collect_valid_rows(rows)
    if not valid_rows:
        _safe_empty_output(args.output)
        return 0

    labels = [label for label, _, _ in valid_rows]
    if args.metric == "fcr":
        values = [fcr for _, fcr, _ in valid_rows]
        _draw_bar_panel(labels, values, FCR_BAR_COLOR, "Full-run FCR", args.output, False)
        return 0

    # Display control bytes in MB to suppress matplotlib's 1e6 offset annotation
    # and to keep tick labels readable.
    control_values_mb = [control / 1_000_000.0 for _, _, control in valid_rows]
    _draw_bar_panel(
        labels,
        control_values_mb,
        CONTROL_BAR_COLOR,
        "NLSR Control Bytes (MB)",
        args.output,
        True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
