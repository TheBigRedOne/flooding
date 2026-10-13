#!/usr/bin/env python3
"""Exp2-A scalability figures. Handoffs within a run are not independent replicates."""

from __future__ import annotations

import csv
import os
import random
import statistics
from typing import List, Mapping, Optional, Sequence, Tuple

import matplotlib

if "matplotlib.pyplot" not in __import__("sys").modules:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

NOTE = "8 handoffs × 5 runs\nHandoffs within a run are not independent replicates"
CLF_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("N=1", ("C1",)),
    ("N=2", ("C1", "C2")),
    ("N=4", ("C1", "C2", "C3", "C4")),
)
_MEANPROPS = {
    "marker": "D",
    "markerfacecolor": "black",
    "markeredgecolor": "black",
    "markersize": 4.5,
    "linestyle": "none",
}


def _numeric(value: object) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value))


def _save(fig: plt.Figure, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def _box(
    ax: plt.Axes,
    data: Sequence[Sequence[float]],
    positions: Sequence[float],
    show_mean: bool,
) -> None:
    present = [(position, list(values)) for position, values in zip(positions, data) if values]
    if not present:
        return
    series = [values for _position, values in present]
    centers = [position for position, _values in present]
    if show_mean:
        drawn = ax.boxplot(
            series, positions=centers, widths=0.6, whis=1.5,
            showfliers=True, showmeans=True, patch_artist=True, meanprops=_MEANPROPS,
        )
    else:
        drawn = ax.boxplot(
            series, positions=centers, widths=0.6, whis=1.5,
            showfliers=True, showmeans=False, patch_artist=True,
        )
    if show_mean and len(drawn["means"]) != len(present):
        raise RuntimeError("mean marker missing")
    for patch in drawn["boxes"]:
        patch.set_facecolor("white")


def clf_series(rows: Sequence[Mapping[str, object]]) -> Tuple[List[float], List[List[float]], List[str], List[Tuple[float, str]]]:
    """Consumer groups in figure order, using every CLF value in the table."""
    positions: List[float] = []
    data: List[List[float]] = []
    tick_labels: List[str] = []
    group_centers: List[Tuple[float, str]] = []
    cursor = 0.0
    for configuration, identities in CLF_GROUPS:
        start = cursor
        for identity in identities:
            selected = [
                row for row in rows
                if row["configuration"] == configuration and row["consumer_identity"] == identity
            ]
            if len(selected) != 40:
                raise RuntimeError(f"{configuration} {identity}: expected 40 rows, found {len(selected)}")
            values: List[float] = []
            for row in selected:
                value = _numeric(row["content_loss_fraction"])
                if value is None:
                    raise RuntimeError(f"{configuration} {identity} h{row['handoff_index']}: CLF is blank")
                values.append(value)
            data.append(values)
            positions.append(cursor)
            tick_labels.append(identity)
            cursor += 1.0
        group_centers.append(((start + cursor - 1.0) / 2.0, configuration))
        cursor += 1.0
    return positions, data, tick_labels, group_centers


def group_medians(data: Sequence[Sequence[float]]) -> List[float]:
    """Median of every observation in the group, including values outside the low-range view."""
    return [float(statistics.median(values)) for values in data]


def _strip(ax: plt.Axes, data: Sequence[Sequence[float]], positions: Sequence[float]) -> None:
    """Jittered observations. The horizontal mark is the unfiltered group median."""
    rng = random.Random(0)
    for position, values, median in zip(positions, data, group_medians(data)):
        xs = [position + rng.uniform(-0.18, 0.18) for _value in values]
        ax.scatter(xs, list(values), s=8, c="black", alpha=0.7, linewidths=0, zorder=2)
        ax.plot(
            [position - 0.22, position + 0.22],
            [median, median],
            color="C1", linewidth=1.6, solid_capstyle="butt", zorder=3,
        )


def clf_axis_limits(data: Sequence[Sequence[float]]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Full range, then a magnified low range.

    The low range includes every N=1 observation and the negative value.
    Higher observations stay in the series and in the full-range panel.
    """
    flat = [value for values in data for value in values]
    low = min(flat)
    high = max(flat)
    span = high - low
    full = (low - 0.08 * span, high + 0.08 * span)
    n1_max = max(data[0])
    zoom_top = n1_max * 2.5
    zoom_bottom = min(0.0, low) - max(abs(low), zoom_top * 0.04)
    return full, (zoom_bottom, zoom_top)


def _style(ax: plt.Axes) -> None:
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=8)


def _population_panel(
    path: str,
    rows: Sequence[Mapping[str, object]],
    field: str,
    ylabel: str,
    tick_labels: Sequence[str],
    xlabel: str,
    footnote: str = "",
) -> plt.Figure:
    labels = ["N=1", "N=2", "N=4"]
    data: List[List[float]] = []
    for label in labels:
        selected = [row for row in rows if row["configuration"] == label]
        if len(selected) != 40:
            raise RuntimeError(f"{label} {field}: expected 40 network rows, found {len(selected)}")
        values: List[float] = []
        for row in selected:
            number = _numeric(row[field])
            if number is not None:
                values.append(number)
        if len(values) != 40:
            raise RuntimeError(f"{label} {field}: expected 40 numeric values, found {len(values)}")
        data.append(values)
    fig, ax = plt.subplots(figsize=(3.7, 3.5))
    _box(ax, data, [0, 1, 2], show_mean=True)
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(list(tick_labels), fontsize=8)
    ax.set_xlim(-0.6, 2.6)
    ax.set_xlabel(xlabel, fontsize=8)
    ax.set_ylabel(ylabel, fontsize=9)
    top = max(max(values) for values in data)
    ax.set_ylim(0.0, top * 1.12)
    _style(ax)
    bottom = 0.32 if footnote else 0.26
    fig.subplots_adjust(bottom=bottom, left=0.24, right=0.98, top=0.96)
    if footnote:
        fig.text(0.59, 0.02, footnote, ha="center", va="bottom", fontsize=7)
    if path:
        _save(fig, path)
    return fig


def _clf_figure(path: str, rows: Sequence[Mapping[str, object]]) -> plt.Figure:
    positions, data, tick_labels, group_centers = clf_series(rows)
    full, zoom = clf_axis_limits(data)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.8), sharex=True)
    _box(axes[0], data, positions, show_mean=False)
    _strip(axes[1], data, positions)
    for ax, title, limit in zip(axes, ("All observations", "Low-range view"), (full, zoom)):
        ax.set_xticks(positions)
        ax.set_xticklabels(tick_labels, fontsize=8)
        ax.set_xlim(-0.7, positions[-1] + 0.7)
        ax.set_ylim(*limit)
        ax.set_title(title, fontsize=9)
        _style(ax)
        for center, label in group_centers:
            ax.text(
                center, -0.22, label,
                transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=8, clip_on=False,
            )
    axes[0].set_ylabel("Content loss fraction", fontsize=9)
    fig.text(
        0.54, 0.02,
        "Nominal 20 ms frame opportunities; not confirmed Data loss.\n"
        "Right panel: low-range view. The left panel retains the complete distributions.\n"
        + NOTE,
        ha="center", va="bottom", fontsize=7,
    )
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.34, top=0.88, wspace=0.28)
    if path:
        _save(fig, path)
    return fig


def write_figures(
    output: str,
    network: Sequence[Mapping[str, object]],
    consumer: Sequence[Mapping[str, object]],
) -> None:
    directory = output
    _population_panel(
        os.path.join(directory, "srt_vs_population.pdf"),
        network,
        "service_recovery_time_ms",
        "Service recovery time (ms)",
        ["N=1", "N=2", "N=4"],
        "Configuration\n" + NOTE,
    )
    _clf_figure(os.path.join(directory, "clf_by_consumer.pdf"), consumer)
    _population_panel(
        os.path.join(directory, "rfv_vs_population.pdf"),
        network,
        "recovery_flood_bytes",
        "Recovery flooding volume\n(bytes per handoff)",
        ["N=1", "N=2", "N=4"],
        "Configuration\n" + NOTE,
        footnote="Marked Interest flooding bytes are 0; RFV is Data flooding.",
    )
    _population_panel(
        os.path.join(directory, "nlsr_rate_vs_population.pdf"),
        network,
        "nlsr_control_rate_bytes_per_s",
        "NLSR control rate (bytes/s)",
        ["N=1\n11 nodes", "N=2\n12 nodes", "N=4\n14 nodes"],
        NOTE,
    )


def main() -> int:
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "results", "extended", "exp2", "analysis",
    )
    with open(os.path.join(root, "network_handoffs.csv"), encoding="utf-8", newline="") as handle:
        network = list(csv.DictReader(handle))
    with open(os.path.join(root, "consumer_handoffs.csv"), encoding="utf-8", newline="") as handle:
        consumer = list(csv.DictReader(handle))
    write_figures(root, network, consumer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
