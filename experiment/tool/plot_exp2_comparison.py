#!/usr/bin/env python3
"""Preliminary Shared-versus-Distinct figures. Reads existing analysis CSVs only."""

from __future__ import annotations

import csv
import os
import statistics
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import matplotlib

if "matplotlib.pyplot" not in __import__("sys").modules:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

NOTE = "8 handoffs × 5 runs; handoffs within a run are not independent replicates"
CLUSTER_GAP = 1.7
RUNS = ("r1", "r2", "r3", "r4", "r5")
RUN_MARKERS = ("o", "s", "^", "D", "v")
CONFIGS: Tuple[Tuple[str, str, str, Optional[str]], ...] = (
    ("N=1 Solution", "N=1", "shared", None),
    ("N=2 Shared", "N=2", "shared", "shared"),
    ("N=2 Distinct", "N=2", "distinct", "distinct"),
    ("N=4 Shared", "N=4", "shared", "shared"),
    ("N=4 Distinct", "N=4", "distinct", "distinct"),
)
CLF_PANELS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("N=2 Shared", "shared", ("C1", "C2")),
    ("N=2 Distinct", "distinct", ("C1", "C2")),
    ("N=4 Shared", "shared", ("C1", "C2", "C3", "C4")),
    ("N=4 Distinct", "distinct", ("C1", "C2", "C3", "C4")),
)
STREAMS = {
    "N=2": {"C1": "/LiveStream/v0", "C2": "/LiveStream/v1"},
    "N=4": {
        "C1": "/LiveStream/v0",
        "C2": "/LiveStream/v1",
        "C3": "/LiveStream/v2",
        "C4": "/LiveStream/v3",
    },
}
NODES = {"N=1": "11", "N=2": "12", "N=4": "14"}
NETWORK_COUNTS = {"shared": {"N=1": 40, "N=2": 40, "N=4": 40}, "distinct": {"N=2": 40, "N=4": 40}}
CONSUMER_COUNTS = {
    "shared": {"N=1": 40, "N=2": 80, "N=4": 160},
    "distinct": {"N=2": 80, "N=4": 160},
}


class ComparisonDataError(ValueError):
    """Raised when an analysis table does not match the comparison contract."""


def _numeric(value: object) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value))


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _require_fields(rows: Sequence[Mapping[str, str]], fields: Sequence[str], label: str) -> None:
    if not rows:
        raise ComparisonDataError(f"{label} is empty")
    missing = [field for field in fields if field not in rows[0]]
    if missing:
        raise ComparisonDataError(f"{label} missing columns: {', '.join(missing)}")


def _unique(rows: Sequence[Mapping[str, str]], keys: Sequence[str], label: str) -> None:
    seen = [tuple(row[key] for key in keys) for row in rows]
    if len(seen) != len(set(seen)):
        raise ComparisonDataError(f"{label} has duplicate event keys")


def load_tables(root: Path) -> Dict[str, object]:
    base = root / "results" / "extended" / "exp2"
    return {
        "shared_network": _read(base / "analysis" / "network_handoffs.csv"),
        "shared_consumer": _read(base / "analysis" / "consumer_handoffs.csv"),
        "distinct_network": _read(base / "distinct" / "analysis" / "network_handoffs.csv"),
        "distinct_consumer": _read(base / "distinct" / "analysis" / "consumer_handoffs.csv"),
        "distinct_stream": _read(base / "distinct" / "analysis" / "stream_recovery_diagnostics.csv"),
        "distinct_audit": (base / "distinct" / "analysis" / "analysis_audit.txt").read_text(encoding="utf-8"),
        "shared_audit": (base / "analysis" / "analysis_audit.txt").read_text(encoding="utf-8"),
    }


def _check_runs(rows: Sequence[Mapping[str, str]], configuration: str, label: str) -> None:
    for run_id in RUNS:
        count = sum(1 for row in rows if row["configuration"] == configuration and row["run_id"] == run_id)
        if count != 8:
            raise ComparisonDataError(f"{label} {configuration} {run_id} has {count} handoffs; expected 8")


def _check_recovery(rows: Sequence[Mapping[str, str]], label: str) -> None:
    for row in rows:
        recovered = row["recovered"] == "true"
        measured = _numeric(row["service_recovery_time_ms"])
        boundary = _numeric(row["srt_censor_boundary_ms"])
        if recovered and (measured is None or boundary is not None):
            raise ComparisonDataError(f"{label} recovered row has a blank SRT or a censor boundary")
        if not recovered and (measured is not None or boundary is None):
            raise ComparisonDataError(f"{label} censored row is missing its boundary or still has an SRT")


def validate(tables: Mapping[str, object]) -> None:
    """Check schemas, row counts, identities, and event-key uniqueness before plotting."""
    shared_network = tables["shared_network"]
    distinct_network = tables["distinct_network"]
    shared_consumer = tables["shared_consumer"]
    distinct_consumer = tables["distinct_consumer"]
    streams = tables["distinct_stream"]
    if not isinstance(shared_network, list) or not isinstance(distinct_network, list):
        raise ComparisonDataError("network tables must be row lists")
    if not isinstance(shared_consumer, list) or not isinstance(distinct_consumer, list) or not isinstance(streams, list):
        raise ComparisonDataError("consumer and stream tables must be row lists")
    network_fields = (
        "configuration", "run_id", "handoff_index", "recovered", "service_recovery_time_ms",
        "srt_censor_boundary_ms", "recovery_flood_bytes", "recovery_interest_flood_bytes",
        "recovery_data_flood_bytes", "nlsr_control_bytes", "nlsr_control_rate_bytes_per_s",
        "physical_capture_nodes",
    )
    _require_fields(shared_network, network_fields, "shared network")
    _require_fields(distinct_network, network_fields + ("demand_pattern", "recovery_stream_prefix"), "distinct network")
    _require_fields(
        shared_consumer,
        ("configuration", "run_id", "handoff_index", "consumer_identity", "content_loss_fraction"),
        "shared consumer",
    )
    _require_fields(
        distinct_consumer,
        (
            "demand_pattern", "configuration", "run_id", "handoff_index", "consumer_identity",
            "stream_prefix", "content_loss_fraction",
        ),
        "distinct consumer",
    )
    _require_fields(
        streams,
        (
            "demand_pattern", "configuration", "run_id", "handoff_index", "stream_prefix",
            "consumer_identity", "recovered", "service_recovery_time_ms", "srt_censor_boundary_ms",
            "diagnostic_not_network_srt",
        ),
        "stream diagnostics",
    )
    _unique(shared_network, ("configuration", "run_id", "handoff_index"), "shared network")
    _unique(distinct_network, ("configuration", "run_id", "handoff_index"), "distinct network")
    _unique(shared_consumer, ("configuration", "run_id", "handoff_index", "consumer_identity"), "shared consumer")
    _unique(distinct_consumer, ("configuration", "run_id", "handoff_index", "consumer_identity"), "distinct consumer")
    _unique(streams, ("configuration", "run_id", "handoff_index", "stream_prefix"), "stream diagnostics")
    if any(row["configuration"] == "N=1" for row in distinct_network):
        raise ComparisonDataError("Distinct tables must not contain an N=1 configuration")
    for source, rows, counts in (
        ("shared", shared_network, NETWORK_COUNTS["shared"]),
        ("distinct", distinct_network, NETWORK_COUNTS["distinct"]),
    ):
        for configuration, expected in counts.items():
            selected = [row for row in rows if row["configuration"] == configuration]
            if len(selected) != expected:
                raise ComparisonDataError(f"{source} {configuration} network rows {len(selected)} != {expected}")
            _check_runs(selected, configuration, source)
            nodes = {row["physical_capture_nodes"] for row in selected}
            if nodes != {NODES[configuration]}:
                raise ComparisonDataError(f"{source} {configuration} capture nodes {nodes}")
    for source, rows, counts in (
        ("shared", shared_consumer, CONSUMER_COUNTS["shared"]),
        ("distinct", distinct_consumer, CONSUMER_COUNTS["distinct"]),
    ):
        for configuration, expected in counts.items():
            selected = [row for row in rows if row["configuration"] == configuration]
            if len(selected) != expected:
                raise ComparisonDataError(f"{source} {configuration} consumer rows {len(selected)} != {expected}")
    for row in distinct_network:
        if row["demand_pattern"] != "distinct":
            raise ComparisonDataError("Distinct network demand_pattern must be distinct")
    for row in distinct_consumer:
        prefix = STREAMS[row["configuration"]][row["consumer_identity"]]
        if row["demand_pattern"] != "distinct" or row["stream_prefix"] != prefix:
            raise ComparisonDataError(
                f"stream mismatch {row['configuration']} {row['consumer_identity']} {row.get('stream_prefix')}"
            )
    for row in streams:
        if row["diagnostic_not_network_srt"] != "true" or row["demand_pattern"] != "distinct":
            raise ComparisonDataError("stream diagnostics must stay marked as non-network SRT")
        if row["stream_prefix"] != STREAMS[row["configuration"]][row["consumer_identity"]]:
            raise ComparisonDataError("stream diagnostic prefix does not match the consumer")
    _check_recovery(shared_network, "shared network")
    _check_recovery(distinct_network, "distinct network")
    _check_recovery(streams, "stream diagnostics")
    if len(streams) != 240:
        raise ComparisonDataError(f"stream diagnostics {len(streams)} != 240")


def network_rows(tables: Mapping[str, Sequence[Mapping[str, str]]], source: str, configuration: str) -> List[Mapping[str, str]]:
    key = "shared_network" if source == "shared" else "distinct_network"
    return [row for row in tables[key] if row["configuration"] == configuration]


def measured_srt(rows: Sequence[Mapping[str, str]]) -> Tuple[List[float], List[float]]:
    """Return observed SRT values and, separately, right-censor boundaries."""
    observed: List[float] = []
    censored: List[float] = []
    for row in rows:
        if row["recovered"] == "true":
            value = _numeric(row["service_recovery_time_ms"])
            if value is None:
                raise ComparisonDataError("recovered SRT is blank")
            observed.append(value)
        else:
            boundary = _numeric(row["srt_censor_boundary_ms"])
            if boundary is None:
                raise ComparisonDataError("censored SRT has no boundary")
            censored.append(boundary)
    return observed, censored


def _values(rows: Sequence[Mapping[str, str]], field: str) -> List[float]:
    parsed = []
    for row in rows:
        value = _numeric(row[field])
        if value is None:
            raise ComparisonDataError(f"blank {field}")
        parsed.append(value)
    return parsed


def run_medians(rows: Sequence[Mapping[str, str]], field: str, recovered_only: bool = False) -> List[float]:
    medians = []
    for run_id in RUNS:
        selected = [row for row in rows if row["run_id"] == run_id]
        if recovered_only:
            selected = [row for row in selected if row["recovered"] == "true"]
        if not selected:
            continue
        medians.append(statistics.median(_values(selected, field)))
    return medians


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _style(ax: plt.Axes) -> None:
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=8)


def _boxes(ax: plt.Axes, series: Sequence[Sequence[float]], positions: Sequence[float]) -> None:
    drawn = ax.boxplot(
        list(series), positions=list(positions), widths=0.55, whis=1.5,
        showfliers=True, showmeans=False, patch_artist=True,
    )
    for patch in drawn["boxes"]:
        patch.set_facecolor("white")
        patch.set_zorder(1)


def _run_markers(ax: plt.Axes, rows_by_config: Sequence[Sequence[Mapping[str, str]]], field: str, recovered_only: bool) -> None:
    """Draw one marker per run above the box. Offsets stay inside the box width."""
    for position, rows in enumerate(rows_by_config):
        for run_number, run_id in enumerate(RUNS):
            selected = [row for row in rows if row["run_id"] == run_id]
            if recovered_only:
                selected = [row for row in selected if row["recovered"] == "true"]
            if not selected:
                continue
            plotted = ax.plot(
                position + (run_number - 2) * 0.11,
                statistics.median(_values(selected, field)),
                marker=RUN_MARKERS[run_number],
                markerfacecolor="black",
                markeredgecolor="white",
                markeredgewidth=0.6,
                markersize=6.5,
                linestyle="None",
                zorder=6,
                clip_on=True,
            )
            plotted[0].set_gid(f"run-median-{run_id}")


def _legend(fig: plt.Figure) -> None:
    handles = [
        Line2D([0], [0], marker=marker, color="black", linestyle="None", markersize=5, label=run_id)
        for run_id, marker in zip(RUNS, RUN_MARKERS)
    ]
    fig.legend(handles, list(RUNS), title="Run median", fontsize=7, title_fontsize=7, loc="center right", frameon=False)


def _metric_figure(
    path: str,
    series: Sequence[Sequence[float]],
    censored: Sequence[Sequence[float]],
    rows_by_config: Sequence[Sequence[Mapping[str, str]]],
    field: str,
    recovered_only: bool,
    ylabel: str,
    caption: str,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(7.2, 3.45))
    _boxes(ax, series, list(range(len(series))))
    _run_markers(ax, rows_by_config, field, recovered_only)
    for position, boundaries in enumerate(censored):
        if not boundaries:
            continue
        ax.scatter(
            [position] * len(boundaries), boundaries,
            marker="x", c="0.35", s=18, zorder=5, label=None,
        )
    labels = [label for label, _configuration, _source, _pattern in CONFIGS]
    ax.set_xticks(list(range(len(labels))))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.set_ylabel(ylabel, fontsize=9)
    highest = max(max(values) for values in series if values)
    if any(censored):
        highest = max(highest, max(max(values) for values in censored if values))
    ax.set_ylim(0.0, highest * 1.12)
    _style(ax)
    fig.text(0.46, 0.015, caption, ha="center", va="bottom", fontsize=7)
    _legend(fig)
    fig.subplots_adjust(left=0.12, right=0.84, bottom=0.22, top=0.97)
    if path:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)
    return fig


def clf_groups(tables: Mapping[str, Sequence[Mapping[str, str]]]) -> Tuple[List[str], List[List[float]], List[Tuple[float, str]]]:
    labels: List[str] = []
    series: List[List[float]] = []
    centers: List[Tuple[float, str]] = []
    cursor = 0.0
    for title, source, identities in CLF_PANELS:
        configuration = title.split()[0]
        rows = tables["shared_consumer" if source == "shared" else "distinct_consumer"]
        start = cursor
        for identity in identities:
            selected = [
                row for row in rows
                if row["configuration"] == configuration and row["consumer_identity"] == identity
            ]
            if len(selected) != 40:
                raise ComparisonDataError(f"{title} {identity} has {len(selected)} CLF rows; expected 40")
            series.append(_values(selected, "content_loss_fraction"))
            labels.append(identity)
            cursor += 1.0
        centers.append(((start + cursor - 1.0) / 2.0, title))
        cursor += CLUSTER_GAP
    return labels, series, centers


def clf_limits(series: Sequence[Sequence[float]]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    flat = [value for values in series for value in values]
    low = min(flat)
    high = max(flat)
    span = high - low
    full = (low - 0.08 * span, high + 0.08 * span)
    medians = [statistics.median(values) for values in series]
    zoom_top = max(medians) * 4.0
    zoom_bottom = min(0.0, low) - max(abs(low), zoom_top * 0.04)
    return full, (zoom_bottom, zoom_top)


def _clf_figure(path: str, labels: Sequence[str], series: Sequence[Sequence[float]], centers: Sequence[Tuple[float, str]]) -> plt.Figure:
    full, zoom = clf_limits(series)
    positions = []
    cursor = 0.0
    for _title, _source, identities in CLF_PANELS:
        for _identity in identities:
            positions.append(cursor)
            cursor += 1.0
        cursor += CLUSTER_GAP
    fig, axes = plt.subplots(1, 2, figsize=(7.8, 4.3), sharex=True)
    _boxes(axes[0], series, positions)
    axes[0].set_ylim(*full)
    rng_positions = []
    for position, values in zip(positions, series):
        median = statistics.median(values)
        span = max(len(values) - 1, 1)
        xs = [position + (index - (len(values) - 1) / 2.0) / span * 0.36 for index in range(len(values))]
        axes[1].scatter(xs, values, s=8, c="black", alpha=0.65, linewidths=0, zorder=2)
        axes[1].plot([position - 0.22, position + 0.22], [median, median], color="C1", linewidth=1.5, zorder=3)
        rng_positions.append(xs)
    axes[1].set_ylim(*zoom)
    for ax, title in zip(axes, ("All observations", "Low-range view")):
        ax.set_xticks(positions)
        ax.set_xticklabels(list(labels), fontsize=7)
        ax.set_xlim(-0.7, positions[-1] + 0.7)
        ax.set_title(title, fontsize=9)
        _style(ax)
        for center, label in centers:
            ax.text(
                center, -0.22, label.replace(" ", "\n"),
                transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=7, clip_on=False,
            )
    axes[0].set_ylabel("Content loss fraction", fontsize=9)
    fig.text(
        0.50, 0.01,
        "Nominal 20 ms frame opportunities; not confirmed Data loss.\n"
        "Right panel: low-range view of the same observations. The left panel retains every value, including negatives.\n"
        + NOTE,
        ha="center", va="bottom", fontsize=7,
    )
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.34, top=0.90, wspace=0.24)
    if path:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)
    return fig


def _fmt(value: float) -> str:
    return format(value, ".8g")


def _event_line(metric: str, label: str, values: Sequence[float], recovered: int, censored: int) -> str:
    return (
        f"event {label} {metric} n={len(values)} median={_fmt(statistics.median(values))} "
        f"min={_fmt(min(values))} max={_fmt(max(values))} recovered={recovered} censored={censored}"
    )


def summary_rows(tables: Mapping[str, object]) -> Tuple[List[str], List[Dict[str, str]]]:
    """Event-level and run-level summaries. Forty handoffs are not independent replicates."""
    lines = [
        "Shared versus Distinct preliminary summary.",
        "Event-level statistics pool eight correlated handoffs from each of five runs.",
        "The five run medians are the independent-run summaries.",
        "No significance test is reported.",
        "N=1 is the completed Solution reference. It is not split into Shared and Distinct.",
        "SRT endpoint: Producer ingress of the first qualifying post-handoff content Interest.",
        "For more than one Consumer, network SRT is the earliest such Interest, not each Consumer's recovery time.",
        "Per-stream rows are Distinct diagnostics and are not a replacement network SRT.",
        "P95 uses linear interpolation between sorted recovered observations.",
    ]
    records: List[Dict[str, str]] = []
    network = tables["shared_network"]
    distinct_network = tables["distinct_network"]
    if not isinstance(network, list) or not isinstance(distinct_network, list):
        raise ComparisonDataError("network tables must be row lists")
    for label, configuration, source, _pattern in CONFIGS:
        rows = network_rows({"shared_network": network, "distinct_network": distinct_network}, source, configuration)
        observed, censored = measured_srt(rows)
        for metric, values, recovered_only in (
            ("recovery_flood_bytes", _values(rows, "recovery_flood_bytes"), False),
            ("service_recovery_time_ms", observed, True),
            ("nlsr_control_rate_bytes_per_s", _values(rows, "nlsr_control_rate_bytes_per_s"), False),
        ):
            lines.append(_event_line(metric, label, values, len(observed) if metric.startswith("service") else len(rows), len(censored) if metric.startswith("service") else 0))
            records.append({
                "record_type": "event",
                "configuration": label,
                "metric": metric,
                "run_id": "",
                "consumer_identity": "",
                "stream_prefix": "",
                "n": str(len(values)),
                "median": _fmt(statistics.median(values)),
                "minimum": _fmt(min(values)),
                "maximum": _fmt(max(values)),
                "p95": "",
                "recovered": str(len(observed) if metric.startswith("service") else len(rows)),
                "censored": str(len(censored) if metric.startswith("service") else 0),
                "interest_flood_bytes": "",
                "data_flood_bytes": "",
                "note": "",
            })
            for run_id, median in zip(RUNS, run_medians(rows, "service_recovery_time_ms" if recovered_only else metric, recovered_only)):
                lines.append(f"run {label} {metric} {run_id} median={_fmt(median)}")
                records.append({
                    "record_type": "run_median",
                    "configuration": label,
                    "metric": metric,
                    "run_id": run_id,
                    "consumer_identity": "",
                    "stream_prefix": "",
                    "n": "8",
                    "median": _fmt(median),
                    "minimum": "",
                    "maximum": "",
                    "p95": "",
                    "recovered": "",
                    "censored": "",
                    "interest_flood_bytes": "",
                    "data_flood_bytes": "",
                    "note": "median of the eight handoffs in this run",
                })
        interest = sum(int(row["recovery_interest_flood_bytes"]) for row in rows)
        data = sum(int(row["recovery_data_flood_bytes"]) for row in rows)
        lines.append(f"flood {label} interest_bytes={interest} data_bytes={data}")
        records.append({
            "record_type": "flood_bytes",
            "configuration": label,
            "metric": "recovery_flood_components",
            "run_id": "",
            "consumer_identity": "",
            "stream_prefix": "",
            "n": str(len(rows)),
            "median": "",
            "minimum": "",
            "maximum": "",
            "p95": "",
            "recovered": str(len(observed)),
            "censored": str(len(censored)),
            "interest_flood_bytes": str(interest),
            "data_flood_bytes": str(data),
            "note": "sums of event-level sender-egress bytes; not divided by Consumer count",
        })
    shared_consumer = tables["shared_consumer"]
    distinct_consumer = tables["distinct_consumer"]
    if not isinstance(shared_consumer, list) or not isinstance(distinct_consumer, list):
        raise ComparisonDataError("consumer tables must be row lists")
    lines.append("Per-consumer CLF uses each consumer's own observations. Consumers are not pooled.")
    for label, configuration, source, _pattern in CONFIGS:
        rows = shared_consumer if source == "shared" else distinct_consumer
        identities = ("C1",) if configuration == "N=1" else STREAMS[configuration].keys()
        for identity in identities:
            selected = [row for row in rows if row["configuration"] == configuration and row["consumer_identity"] == identity]
            values = _values(selected, "content_loss_fraction")
            lines.append(
                f"clf {label} {identity} n={len(values)} median={_fmt(statistics.median(values))} max={_fmt(max(values))}"
            )
            records.append({
                "record_type": "consumer_clf",
                "configuration": label,
                "metric": "content_loss_fraction",
                "run_id": "",
                "consumer_identity": identity,
                "stream_prefix": "" if source == "shared" else selected[0]["stream_prefix"],
                "n": str(len(values)),
                "median": _fmt(statistics.median(values)),
                "minimum": _fmt(min(values)),
                "maximum": _fmt(max(values)),
                "p95": "",
                "recovered": "",
                "censored": "",
                "interest_flood_bytes": "",
                "data_flood_bytes": "",
                "note": "",
            })
    stream_rows = tables["distinct_stream"]
    if not isinstance(stream_rows, list):
        raise ComparisonDataError("stream table must be a row list")
    lines.append("Distinct per-stream recovery diagnostics. These medians are not the network SRT.")
    seen_prefixes: List[Tuple[str, str]] = []
    seen = set()
    for row in stream_rows:
        key = (row["configuration"], row["stream_prefix"])
        if key not in seen:
            seen.add(key)
            seen_prefixes.append(key)
    for configuration, prefix in seen_prefixes:
        selected = [row for row in stream_rows if row["configuration"] == configuration and row["stream_prefix"] == prefix]
        observed, censored = measured_srt(selected)
        lines.append(
            f"stream {configuration} {prefix} n={len(observed)} median={_fmt(statistics.median(observed))} "
            f"p95={_fmt(_percentile(observed, 0.95))} max={_fmt(max(observed))} "
            f"recovered={len(observed)} censored={len(censored)}"
        )
        records.append({
            "record_type": "stream_recovery",
            "configuration": configuration,
            "metric": "service_recovery_time_ms",
            "run_id": "",
            "consumer_identity": selected[0]["consumer_identity"],
            "stream_prefix": prefix,
            "n": str(len(observed)),
            "median": _fmt(statistics.median(observed)),
            "minimum": _fmt(min(observed)),
            "maximum": _fmt(max(observed)),
            "p95": _fmt(_percentile(observed, 0.95)),
            "recovered": str(len(observed)),
            "censored": str(len(censored)),
            "interest_flood_bytes": "",
            "data_flood_bytes": "",
            "note": "diagnostic; not the network-level SRT",
        })
    lines.append("Final-observation shortfall warnings copied from the existing audits.")
    shared_audit = str(tables["shared_audit"])
    distinct_audit = str(tables["distinct_audit"])
    shared_warnings = [line for line in shared_audit.splitlines() if line.startswith("SHORTFALL ")]
    distinct_warnings = [line for line in distinct_audit.splitlines() if line.startswith("SHORTFALL ")]
    if not shared_warnings:
        lines.append("Shared/Solution audit records no SHORTFALL warnings.")
    for line in shared_warnings + distinct_warnings:
        lines.append(line)
        records.append({
            "record_type": "shortfall",
            "configuration": "",
            "metric": "",
            "run_id": "",
            "consumer_identity": "",
            "stream_prefix": "",
            "n": "",
            "median": "",
            "minimum": "",
            "maximum": "",
            "p95": "",
            "recovered": "",
            "censored": "",
            "interest_flood_bytes": "",
            "data_flood_bytes": "",
            "note": line,
        })
    return lines, records


def write_outputs(directory: Path, tables: Mapping[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shared_network = tables["shared_network"]
    distinct_network = tables["distinct_network"]
    if not isinstance(shared_network, list) or not isinstance(distinct_network, list):
        raise ComparisonDataError("network tables must be row lists")
    grouped = [
        network_rows({"shared_network": shared_network, "distinct_network": distinct_network}, source, configuration)
        for _label, configuration, source, _pattern in CONFIGS
    ]
    rfv = [_values(rows, "recovery_flood_bytes") for rows in grouped]
    srt = []
    censored = []
    for rows in grouped:
        observed, boundaries = measured_srt(rows)
        srt.append(observed)
        censored.append(boundaries)
    censored_count = sum(len(values) for values in censored)
    _metric_figure(
        str(directory / "rfv_shared_vs_distinct.pdf"),
        rfv,
        [[] for _rows in grouped],
        grouped,
        "recovery_flood_bytes",
        False,
        "Recovery flooding volume\n(bytes per handoff)",
        "Network-wide sender-egress bytes per handoff; not divided by Consumer count.\n"
        "Markers: per-run median of eight handoffs. Handoffs within a run are not independent replicates.",
    )
    _metric_figure(
        str(directory / "srt_shared_vs_distinct.pdf"),
        srt,
        censored,
        grouped,
        "service_recovery_time_ms",
        True,
        "Service recovery time (ms)",
        "Endpoint: Producer ingress of the first qualifying post-handoff content Interest.\n"
        "N>1 uses the earliest Interest from any active Consumer. "
        f"Right-censored handoffs: {censored_count}.\n"
        "Boxes contain measured recoveries only. Handoffs within a run are not independent replicates.",
    )
    if not isinstance(tables["shared_consumer"], list) or not isinstance(tables["distinct_consumer"], list):
        raise ComparisonDataError("consumer tables must be row lists")
    labels, series, centers = clf_groups({
        "shared_consumer": tables["shared_consumer"],
        "distinct_consumer": tables["distinct_consumer"],
    })
    _clf_figure(str(directory / "clf_shared_vs_distinct.pdf"), labels, series, centers)
    lines, records = summary_rows(tables)
    (directory / "comparison_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    fields = (
        "record_type", "configuration", "metric", "run_id", "consumer_identity", "stream_prefix",
        "n", "median", "minimum", "maximum", "p95", "recovered", "censored",
        "interest_flood_bytes", "data_flood_bytes", "note",
    )
    with (directory / "comparison_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    tables = load_tables(root)
    validate(tables)
    write_outputs(root / "results" / "extended" / "exp2" / "comparison", tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
