#!/usr/bin/env python3
"""Tukey box plots from canonical mobility-event rows."""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

if "matplotlib.pyplot" not in sys.modules:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.cbook import boxplot_stats

WHIS = 1.5
MEANPROPS = {
    "marker": "D",
    "markerfacecolor": "black",
    "markeredgecolor": "black",
    "markersize": 4.5,
    "linestyle": "none",
}


def load_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _numeric(text: str) -> Optional[float]:
    if text is None or text.strip() == "":
        return None
    return float(text)


def positive_log_bounds(samples: Sequence[float]) -> Tuple[float, float]:
    """Strictly positive log-axis limits. Zero is never a bound."""
    positive = [value for value in samples if value > 0.0]
    if not positive:
        raise SystemExit("logarithmic axis requires at least one positive value")
    low = min(positive)
    high = max(positive)
    if low == high:
        return low / 2.0, high * 2.0
    log_low = math.log10(low)
    log_high = math.log10(high)
    pad = max((log_high - log_low) * 0.08, 0.15)
    return 10.0 ** (log_low - pad), 10.0 ** (log_high + pad)


def groups_for(rows: Sequence[Dict[str, str]], labels: Sequence[str], field: str) -> Tuple[List[str], List[List[float]], List[str], List[int]]:
    """Return tick labels, numeric samples, notes, and total event counts."""
    data: List[List[float]] = []
    notes: List[str] = []
    kept: List[str] = []
    counts: List[int] = []
    for label in labels:
        selected = [row for row in rows if row["configuration"] == label]
        if len(selected) != 40:
            raise SystemExit(f"{label}: expected 40 event rows, found {len(selected)}")
        values: List[float] = []
        undefined = 0
        for row in selected:
            number = _numeric(row[field])
            if number is None:
                undefined += 1
            else:
                values.append(number)
        if undefined:
            notes.append(
                f"{label} {field}: undefined={undefined}; numeric={len(values)}; total_events={len(selected)}"
            )
        if not values:
            raise SystemExit(f"{label} {field}: no numeric observations")
        kept.append(label)
        data.append(values)
        counts.append(len(selected))
    return kept, data, notes, counts


# Baseline Figure 4 is included at 0.30\textwidth; the generic canvas is sized
# for 0.48\textwidth. Shrink only that canvas so Matplotlib point sizes keep
# approximately the same size on the page.
BASELINE_COMPACT_FIGSIZE = (6.2 * 0.30 / 0.48, 4.2 * 0.30 / 0.48)

# Section IV-D panels are included near 0.22\textwidth inside one column.
# The canvas shrinks by that ratio from the 0.48\textwidth / 6.2 in design
# so point sizes stay about the same size on the page.
COLUMN_PAIR_FIGSIZE = (6.2 * 0.22 / 0.48, 4.2 * 0.22 / 0.48)


def draw_boxes(
    path: str,
    labels: Sequence[str],
    data: Sequence[Sequence[float]],
    ylabel: str,
    log_y: bool,
    event_counts: Optional[Sequence[int]] = None,
    censor_marks: Optional[Sequence[Sequence[float]]] = None,
    censor_note: str = "right-censored",
    compact: bool = False,
    column_pair: bool = False,
) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if column_pair:
        figsize = COLUMN_PAIR_FIGSIZE
    elif compact:
        figsize = BASELINE_COMPACT_FIGSIZE
    else:
        figsize = (6.2, 4.2)
    fig, ax = plt.subplots(figsize=figsize)
    drawn = ax.boxplot(
        list(data),
        positions=list(range(len(labels))),
        whis=WHIS,
        showfliers=True,
        showmeans=True,
        meanline=False,
        patch_artist=True,
        meanprops=MEANPROPS,
    )
    if len(drawn["means"]) != len(labels):
        raise SystemExit("mean marker missing")
    ax.set_xticks(list(range(len(labels))))
    tick_labels = []
    visible: List[float] = []
    censor_labeled = False
    for index, (label, values) in enumerate(zip(labels, data)):
        total = event_counts[index] if event_counts is not None else len(values)
        # Compact panels keep the category only. The event count and the
        # right-censor explanation belong in the figure caption.
        text = label if compact else f"{label}\nn={total}"
        marks = list(censor_marks[index]) if censor_marks is not None else []
        if marks and not compact:
            text += f"\n{len(marks)} {censor_note}"
        if marks:
            ax.scatter(
                [index] * len(marks),
                marks,
                marker="v",
                s=36,
                color="crimson",
                zorder=5,
                label=None if censor_labeled else censor_note,
            )
            censor_labeled = True
            visible.extend(marks)
        visible.extend(values)
        tick_labels.append(text)
    ax.set_xticklabels(tick_labels)
    ax.set_ylabel(ylabel)
    if log_y:
        low, high = positive_log_bounds(visible)
        if low <= 0.0 or high <= 0.0:
            raise SystemExit(f"log axis bounds must be positive, got {low}, {high}")
        ax.set_yscale("log")
        ax.set_ylim(low, high)
    else:
        # Compact baseline SRT is the linear panel that carries a censor mark.
        # Include that mark; other linear panels keep the boxplot's own top.
        if compact and censor_labeled and visible:
            ax.set_ylim(0, max(visible) * 1.08)
        else:
            ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    if censor_labeled:
        ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    for index, (label, values) in enumerate(zip(labels, data)):
        total = event_counts[index] if event_counts is not None else len(values)
        stats = boxplot_stats(list(values), whis=WHIS)[0]
        censored = len(censor_marks[index]) if censor_marks is not None else 0
        print(
            f"{label} {ylabel}: total_events={total} numeric={len(values)} censored={censored} "
            f"median={float(stats['med']):.6g} mean={float(stats['mean']):.6g} "
            f"Q1={float(stats['q1']):.6g} Q3={float(stats['q3']):.6g}"
        )


@dataclass
class RecoveryFloodLayout:
    labels: List[str]
    x: List[float]
    y_kb: List[float]
    median_bytes: float
    mean_bytes: float


def recovery_flood_layout(rows: Sequence[Dict[str, str]]) -> RecoveryFloodLayout:
    """OptoFlood raw recovery-flood bytes, plotted in kB. Baseline rows are omitted.

    Every observation in one run shares that run's category centre. Horizontal
    position inside a run is not a variable.
    """
    selected = [row for row in rows if row["configuration"] == "OptoFlood"]
    if len(selected) != 40:
        raise SystemExit(f"OptoFlood recovery flooding volume: expected 40 events, found {len(selected)}")
    points: List[Tuple[str, int, float]] = []
    for row in selected:
        run_id = row["run_id"].strip()
        handoff = int(row["handoff_index"])
        value = _numeric(row["recovery_flood_bytes"])
        if value is None:
            raise SystemExit(f"{run_id} handoff {handoff}: recovery_flood_bytes is blank")
        points.append((run_id, handoff, value))
    runs = ("r1", "r2", "r3", "r4", "r5")
    if {run for run, _handoff, _value in points} != set(runs):
        raise SystemExit("OptoFlood recovery flooding volume: expected runs r1-r5")
    ordered = sorted(value for _run, _handoff, value in points)
    median = (ordered[19] + ordered[20]) / 2.0
    mean = sum(ordered) / 40.0
    xs: List[float] = []
    ys: List[float] = []
    for position, run_id in enumerate(runs, start=1):
        values = [value for run, _handoff, value in points if run == run_id]
        if len(values) != 8:
            raise SystemExit(f"{run_id}: expected 8 handoffs, found {len(values)}")
        xs.extend([float(position)] * 8)
        ys.extend(value / 1000.0 for value in values)
    if set(xs) != {1.0, 2.0, 3.0, 4.0, 5.0}:
        raise SystemExit(f"recovery flooding volume figure: unexpected x coordinates {set(xs)}")
    return RecoveryFloodLayout(list(runs), xs, ys, median, mean)


def draw_recovery_flooding_volume(rows: Sequence[Dict[str, str]], path: str, column_pair: bool = False) -> None:
    """Raw OptoFlood recovery-flood observations with the global median and mean."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    layout = recovery_flood_layout(rows)
    median_kb = layout.median_bytes / 1000.0
    mean_kb = layout.mean_bytes / 1000.0
    fig, ax = plt.subplots(figsize=COLUMN_PAIR_FIGSIZE if column_pair else (6.2, 4.2))
    ax.scatter(layout.x, layout.y_kb, s=28, color="C0", alpha=0.65, zorder=3, linewidths=0)
    ax.axhline(median_kb, color="black", linestyle="-", linewidth=1.0, zorder=2, label=f"Median: {median_kb:.3f} kB")
    ax.axhline(mean_kb, color="black", linestyle="--", linewidth=1.0, zorder=2, label=f"Mean: {mean_kb:.3f} kB")
    centers = list(range(1, len(layout.labels) + 1))
    ax.set_xticks(centers)
    ax.set_xticklabels(layout.labels)
    ax.set_xlim(0.5, len(layout.labels) + 0.5)
    ax.set_ylim(5.5, 11.0)
    # The full ylabel is longer than the column canvas. The subcaption names
    # the metric; the axis keeps the unit. The legend sits below the axes.
    if column_pair:
        ax.set_ylabel("kB per hand-off")
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.34),
            ncol=1,
            frameon=False,
            fontsize=8,
        )
        fig.subplots_adjust(left=0.24, right=0.98, bottom=0.40, top=0.97)
    else:
        ax.set_ylabel("Recovery flooding volume (kB per handoff)")
        ax.legend(loc="center", bbox_to_anchor=(0.5, 0.70), ncol=2, frameon=True, fontsize=8)
        fig.tight_layout()
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax.set_axisbelow(True)
    fig.savefig(path)
    plt.close(fig)
    print(
        f"recovery flooding volume: n=40 "
        f"median_bytes={layout.median_bytes:.3f} mean_bytes={layout.mean_bytes:.3f}"
    )


def plot_exp1(path: str, rows: Sequence[Dict[str, str]], field: str, ylabel: str, series: Sequence[str]) -> None:
    """Median and IQR versus request interval, with faint per-handoff points."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    intervals = []
    for row in rows:
        interval = int(row["configuration"])
        if interval not in intervals:
            intervals.append(interval)
    intervals.sort()
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for offset, name in enumerate(series):
        centers = []
        medians = []
        lows = []
        highs = []
        for interval in intervals:
            selected = [row for row in rows if int(row["configuration"]) == interval]
            if len(selected) != 16:
                raise SystemExit(f"exp1 interval {interval}: expected 16 events, found {len(selected)}")
            values = [_numeric(row[name]) for row in selected]
            numeric = [value for value in values if value is not None]
            if len(numeric) != 16:
                print(f"exp1 interval {interval} {name}: plotted {len(numeric)} of 16; undefined={16 - len(numeric)}")
            if not numeric:
                continue
            stats = boxplot_stats(numeric, whis=WHIS)[0]
            center = interval + (offset - (len(series) - 1) / 2.0) * 1.2
            centers.append(center)
            medians.append(float(stats["med"]))
            lows.append(float(stats["med"]) - float(stats["q1"]))
            highs.append(float(stats["q3"]) - float(stats["med"]))
            ax.scatter([center] * len(numeric), numeric, s=12, alpha=0.35)
        if centers:
            ax.errorbar(centers, medians, yerr=[lows, highs], fmt="o", capsize=3, label=name)
    ax.set_xlabel("Request interval (ms)")
    ax.set_ylabel(ylabel)
    ax.set_xticks(intervals)
    if len(series) > 1:
        ax.legend()
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Plot prototype mobility-event figures.")
    sub = parser.add_subparsers(dest="command", required=True)
    boxes = sub.add_parser("boxes")
    boxes.add_argument("--input", required=True)
    boxes.add_argument("--field", required=True)
    boxes.add_argument("--ylabel", required=True)
    boxes.add_argument("--labels", required=True)
    boxes.add_argument("--output", required=True)
    boxes.add_argument("--log-y", action="store_true")
    boxes.add_argument("--compact", action="store_true")
    boxes.add_argument("--column-pair", action="store_true")
    exp1 = sub.add_parser("exp1")
    exp1.add_argument("--input", required=True)
    exp1.add_argument("--field", required=True)
    exp1.add_argument("--ylabel", required=True)
    exp1.add_argument("--output", required=True)
    exp1.add_argument("--series", default="")
    args = parser.parse_args(argv)
    rows = load_rows(args.input)
    if args.command == "boxes":
        labels = [item.strip() for item in args.labels.split(",") if item.strip()]
        kept, data, notes, counts = groups_for(rows, labels, args.field)
        for note in notes:
            print(note)
        censors = None
        if args.field == "service_recovery_time_ms":
            censors = []
            for label in kept:
                marks = []
                for row in rows:
                    if row["configuration"] != label:
                        continue
                    if _numeric(row["service_recovery_time_ms"]) is not None:
                        continue
                    duration = _numeric(row["event_duration_s"])
                    if duration is not None and duration > 0 and str(row.get("recovered", "")).lower() != "true":
                        marks.append(duration * 1000.0)
                censors.append(marks)
        draw_boxes(
            args.output,
            kept,
            data,
            args.ylabel,
            args.log_y,
            event_counts=counts,
            censor_marks=censors,
            compact=args.compact,
            column_pair=args.column_pair,
        )
        return 0
    series = [item.strip() for item in args.series.split(",") if item.strip()] or [args.field]
    plot_exp1(args.output, rows, args.field, args.ylabel, series)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
