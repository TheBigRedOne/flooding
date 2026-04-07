#!/usr/bin/env python3
"""
Plot NLSR sensitivity network cost comparison from the summary CSV.
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
PAPER_FIGURE_HEIGHT_CM = 8.0
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
FIGURE_TITLE_SIZE = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot FCR and all observed NLSR control cost across sensitivity profiles."
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
    fcr_values = [float(row["full_run_fcr"]) for row in rows]
    control_values = [float(row["full_run_control_bytes"]) for row in rows]
    x = np.arange(len(rows))

    _configure_paper_style()
    fig, (ax_fcr, ax_control) = plt.subplots(
        2,
        1,
        figsize=_paper_figure_size(),
        gridspec_kw={"height_ratios": [1.0, 1.2]},
    )

    ax_fcr.bar(x, fcr_values, color="crimson")
    ax_fcr.set_ylabel("Full-run FCR")
    ax_fcr.set_title("Baseline NLSR Tuning Network Cost")
    ax_fcr.set_xticks(x)
    ax_fcr.set_xticklabels(labels)
    ax_fcr.set_ylim(bottom=0)
    ax_fcr.grid(True, axis="y", linestyle="--", alpha=0.7)

    ax_control.bar(x, control_values, color="slateblue")
    ax_control.set_xlabel("NLSR Parameter Set (hello / adj-lsa / route-calc)")
    ax_control.set_ylabel("All NLSR Control Bytes")
    ax_control.set_xticks(x)
    ax_control.set_xticklabels(labels)
    ax_control.set_ylim(bottom=0)
    ax_control.grid(True, axis="y", linestyle="--", alpha=0.7)

    fig.tight_layout()
    plt.savefig(args.output)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
