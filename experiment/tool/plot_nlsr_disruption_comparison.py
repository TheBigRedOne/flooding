#!/usr/bin/env python3
"""
Plot per-handoff service-disruption box plots across baseline parameter sets.

Each box is the distribution of per-handoff disruption values read from that
profile's disruption_metrics.txt. Those values are the recorded observations
for the fixed mobility sequence, not run-to-run replicates.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.cbook import boxplot_stats
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
BOX_WIDTH = 0.55
BOX_FACECOLOR = "#7fb8e0"
BOX_EDGECOLOR = "#0072B2"
MEDIAN_COLOR = "#0b3d66"
MEDIAN_LINEWIDTH = 1.4
EXPECTED_PROFILE_COUNT = 5
EXPECTED_HANDOFF_COUNT = 16
WHIS = 1.5


class DisruptionMetricsError(Exception):
    """Raised when a profile's disruption_metrics.txt cannot be used for the paper figure."""


def parse_args() -> argparse.Namespace:
    """Parse the baseline result root, profile list, and output PDF path."""
    parser = argparse.ArgumentParser(
        description="Plot per-handoff disruption box plots across baseline parameter sets."
    )
    parser.add_argument("--root-dir", required=True, help="Root directory containing per-profile result folders.")
    parser.add_argument(
        "--profiles",
        required=True,
        help="Comma-separated profile directory names in the desired output order.",
    )
    parser.add_argument("--output", required=True, help="Output PDF path.")
    return parser.parse_args()


def _paper_figure_size():
    """Return the figure size in inches for one IEEE subfigure panel."""
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
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _profile_prefix(profile: str) -> str:
    """Return the compact profile prefix used as the plot label."""
    return profile.split("-", 1)[0].upper()


def _load_disruption_values(path: str, profile: str) -> List[float]:
    """Read per-handoff disruption values (ms) from one metrics text file.

    Every non-empty line must be a parseable disruption observation. Missing files,
    unparseable records, and counts other than EXPECTED_HANDOFF_COUNT are errors.
    """
    if not os.path.exists(path):
        raise DisruptionMetricsError(f"{profile}: missing {path}")

    values: List[float] = []
    with open(path, "r", encoding="utf-8") as metrics_file:
        for line_number, raw_line in enumerate(metrics_file, start=1):
            text = raw_line.strip()
            if not text:
                continue
            if "Disruption Time:" not in text:
                raise DisruptionMetricsError(
                    f"{profile}: line {line_number} is not a disruption observation: {text!r}"
                )
            token = text.split("Disruption Time:", 1)[1].strip().split()
            if not token:
                raise DisruptionMetricsError(
                    f"{profile}: line {line_number} has no disruption value: {text!r}"
                )
            try:
                values.append(float(token[0]))
            except ValueError as exc:
                raise DisruptionMetricsError(
                    f"{profile}: line {line_number} has an unparseable disruption value: {text!r}"
                ) from exc

    if len(values) != EXPECTED_HANDOFF_COUNT:
        raise DisruptionMetricsError(
            f"{profile}: n={len(values)} (expected {EXPECTED_HANDOFF_COUNT})"
        )
    return values


def _collect_profile_series(root_dir: str, profiles: Sequence[str]) -> List[Tuple[str, str, List[float]]]:
    """Load per-handoff observations for each profile, preserving profile order."""
    series: List[Tuple[str, str, List[float]]] = []
    errors: List[str] = []
    for profile in profiles:
        path = os.path.join(root_dir, profile, "disruption_metrics.txt")
        try:
            values = _load_disruption_values(path, profile)
        except DisruptionMetricsError as exc:
            errors.append(str(exc))
            continue
        series.append((profile, _profile_prefix(profile), values))
    if errors:
        raise DisruptionMetricsError(
            "baseline disruption comparison requires exactly "
            f"{EXPECTED_HANDOFF_COUNT} valid per-handoff observations "
            f"in each of {EXPECTED_PROFILE_COUNT} profiles:\n  " + "\n  ".join(errors)
        )
    return series


def _report_series(series: Sequence[Tuple[str, str, List[float]]]) -> None:
    """Print observation counts and Tukey 1.5-IQR outliers for the audit log."""
    for profile, label, values in series:
        stats = boxplot_stats(values, whis=WHIS)[0]
        fliers = [float(value) for value in stats["fliers"]]
        print(
            f"{label} ({profile}): n={len(values)} "
            f"median={float(stats['med']):.2f} "
            f"Q1={float(stats['q1']):.2f} Q3={float(stats['q3']):.2f} "
            f"whislo={float(stats['whislo']):.2f} whishi={float(stats['whishi']):.2f} "
            f"outliers={fliers}"
        )


def main() -> int:
    """Render the per-handoff disruption box-plot comparison figure."""
    args = parse_args()
    profiles = [profile.strip() for profile in re.split(r"[,\s]+", args.profiles) if profile.strip()]
    if len(profiles) != EXPECTED_PROFILE_COUNT:
        print(
            "baseline disruption comparison requires exactly "
            f"{EXPECTED_PROFILE_COUNT} profiles, got {len(profiles)}: {profiles}",
            file=sys.stderr,
        )
        return 1

    try:
        series = _collect_profile_series(args.root_dir, profiles)
    except DisruptionMetricsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _report_series(series)
    parent = os.path.dirname(args.output)
    if parent:
        os.makedirs(parent, exist_ok=True)

    labels = [label for _, label, _ in series]
    data = [values for _, _, values in series]
    x = np.arange(len(series))

    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    ax.boxplot(
        data,
        positions=x,
        widths=BOX_WIDTH,
        whis=WHIS,
        showfliers=True,
        showmeans=False,
        patch_artist=True,
        boxprops={
            "facecolor": BOX_FACECOLOR,
            "edgecolor": BOX_EDGECOLOR,
            "linewidth": 0.8,
        },
        medianprops={
            "color": MEDIAN_COLOR,
            "linewidth": MEDIAN_LINEWIDTH,
        },
        whiskerprops={
            "color": BOX_EDGECOLOR,
            "linewidth": 0.8,
        },
        capprops={
            "color": BOX_EDGECOLOR,
            "linewidth": 0.8,
        },
        flierprops={
            "marker": "o",
            "markerfacecolor": BOX_FACECOLOR,
            "markeredgecolor": BOX_EDGECOLOR,
            "markersize": 3.5,
        },
    )

    ax.set_xlabel("Baseline Parameter Group")
    ax.set_ylabel("Disruption Time (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", alpha=0.7)
    fig.tight_layout()
    plt.savefig(args.output)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
