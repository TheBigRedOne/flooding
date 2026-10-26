#!/usr/bin/env python3
"""Host-side Exp3 figures. Reads analysis CSVs and does not start a VM.

Formal comparison, only after a complete campaign manifest:
    python3 experiment/tool/plot_exp3.py

P=4 pilot diagnostics, labelled as a pilot rather than formal r1:
    python3 experiment/tool/plot_exp3.py --pilot
"""

from __future__ import annotations

import csv
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import matplotlib

if "matplotlib.pyplot" not in sys.modules:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

import exp3_config as config
import exp3_metrics as exp3

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_ROOT = ROOT / "results" / "extended" / "exp3" / "analysis"
POPULATIONS = exp3.POPULATIONS
RUNS = exp3.FORMAL_RUNS
RUN_MARKERS = ("o", "s", "^", "D", "v")
CONSUMERS = ("consumer1", "consumer2", "consumer3", "consumer4")


class PlotDataError(ValueError):
    """Raised when a figure would not represent measured Exp3 analysis."""


def _read(path: Path) -> List[Dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PlotDataError(f"missing measured table: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise PlotDataError(f"measured table has no rows: {path}")
    return rows


def _manifest_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values.get("complete") == "true" and values.get("pilot_included") == "false"


def _numeric(row: Mapping[str, str], key: str) -> Optional[float]:
    text = (row.get(key) or "").strip()
    if not text:
        return None
    return float(text)


def _require(rows: Sequence[Mapping[str, str]], fields: Sequence[str], label: str) -> None:
    missing = [field for field in fields if field not in rows[0]]
    if missing:
        raise PlotDataError(f"{label} missing columns: {', '.join(missing)}")


def assert_formal_campaign(analysis_root: Path) -> None:
    status = analysis_root / "campaign" / "campaign_status.txt"
    if not _manifest_complete(status):
        raise PlotDataError(
            f"{status} is not a complete formal campaign; no comparison figure was written"
        )
    comparison = _read(analysis_root / "campaign" / "population_comparison.csv")
    _require(comparison, ("population", "run_id", "source_kind", "network_rfv_bytes"), "population comparison")
    keys = {(row["population"], row["run_id"]) for row in comparison}
    expected = set(exp3.formal_run_keys())
    if keys != expected or any(row["source_kind"] != "formal" or row["run_id"] == "pilot" for row in comparison):
        raise PlotDataError("population comparison is not the fifteen formal runs")


def _save(figure: plt.Figure, path: Path, *, bottom: Optional[float] = None, top: Optional[float] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    adjust = {}
    if bottom is not None:
        adjust["bottom"] = bottom
    if top is not None:
        adjust["top"] = top
    if adjust:
        figure.subplots_adjust(**adjust)
    figure.savefig(path)
    plt.close(figure)


def _point_jitter(row: Mapping[str, str], scale: float = 0.12) -> float:
    """Stable horizontal offset so repeated handoff values remain visible."""
    token = "|".join((row["population"], row["run_id"], row["producer"], row["handoff_index"]))
    slot = zlib.crc32(token.encode("utf-8")) % 1000
    return ((slot / 999.0) - 0.5) * 2.0 * scale


def _box_with_runs(
    ax: plt.Axes,
    rows: Sequence[Mapping[str, str]],
    value_key: str,
    position_of,
    *,
    jitter: bool = False,
    label_runs: bool = True,
    widths: float = 0.55,
) -> None:
    grouped: Dict[float, List[float]] = {}
    for row in rows:
        value = _numeric(row, value_key)
        position = position_of(row)
        if value is None or position is None:
            continue
        grouped.setdefault(position, []).append(value)
    if not grouped:
        raise PlotDataError(f"no measured values for {value_key}")
    positions = sorted(grouped)
    ax.boxplot(
        [grouped[position] for position in positions],
        positions=positions,
        widths=widths,
        showfliers=False,
    )
    labelled = set()
    for row in rows:
        value = _numeric(row, value_key)
        position = position_of(row)
        if value is None or position is None or row["run_id"] not in RUNS:
            continue
        run_index = RUNS.index(row["run_id"])
        label = None
        if label_runs and row["run_id"] not in labelled:
            label = row["run_id"]
            labelled.add(row["run_id"])
        horizontal = position + (_point_jitter(row) if jitter else 0.0)
        ax.scatter(
            horizontal, value, marker=RUN_MARKERS[run_index], s=18, zorder=3,
            color="black", label=label,
        )


def _population_position(row: Mapping[str, str]) -> Optional[float]:
    if row["population"] not in POPULATIONS:
        return None
    return float(POPULATIONS.index(row["population"]))


def _style_populations(ax: plt.Axes, ylabel: str, title: str) -> None:
    ax.set_xticks(range(len(POPULATIONS)))
    ax.set_xticklabels(("P=1", "P=2", "P=4"))
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=8)


def draw_formal(analysis_root: Path, figure_dir: Path) -> List[Path]:
    """Draw formal comparisons from a complete campaign. Incomplete input produces no PDF."""
    assert_formal_campaign(analysis_root)
    events = _read(analysis_root / "campaign" / "events.csv")
    comparison = _read(analysis_root / "campaign" / "population_comparison.csv")
    _require(events, ("service_recovery_time_ms", "content_loss_fraction", "recovery_status", "consumer"), "events")
    written = []
    recovered = [row for row in events if row["recovery_status"] == "recovered"]
    if not recovered:
        raise PlotDataError("formal campaign has no successful recovery to plot; censored SRT was not drawn as zero")
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    _box_with_runs(axis, recovered, "service_recovery_time_ms", _population_position)
    censored = sum(1 for row in events if row["recovery_status"] == "right-censored")
    _style_populations(
        axis,
        "SRT (ms), conditional on recovery",
        f"Exp3 SRT by producer population ({censored} right-censored events excluded)",
    )
    path = figure_dir / "srt_conditional_by_population.pdf"
    _save(figure, path)
    written.append(path)

    figure, axes = plt.subplots(1, 3, figsize=(10.5, 4.2), sharey=True)
    for axis, population in zip(axes, POPULATIONS):
        subset = [row for row in events if row["population"] == population]
        consumers = [name for name in CONSUMERS if any(row["consumer"] == name for row in subset)]
        values = [
            [float(row["content_loss_fraction"]) for row in subset if row["consumer"] == name]
            for name in consumers
        ]
        axis.boxplot(values, showfliers=True)
        axis.set_xticks(range(1, len(consumers) + 1))
        axis.set_xticklabels(consumers)
        axis.set_title(population)
        axis.tick_params(axis="x", labelrotation=30)
    axes[0].set_ylabel("CLF (fraction per handoff)")
    figure.suptitle("Exp3 content loss fraction, unweighted handoffs, by paired consumer")
    path = figure_dir / "clf_by_population.pdf"
    _save(figure, path)
    written.append(path)

    prefix_rows = _read(analysis_root / "campaign" / "prefix_rfv.csv")
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    _box_with_runs(axis, prefix_rows, "prefix_rfv_bytes", _population_position)
    _style_populations(
        axis,
        "Prefix RFV (bytes per handoff)",
        "Exp3 prefix-attributed recovery flooding; not the network-wide total",
    )
    path = figure_dir / "prefix_rfv_by_population.pdf"
    _save(figure, path)
    written.append(path)

    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    _box_with_runs(axis, comparison, "network_rfv_bytes", _population_position)
    _style_populations(
        axis,
        "Network-wide RFV (bytes per run)",
        "Exp3 network RFV, one observation per run, not multiplied by P",
    )
    path = figure_dir / "network_rfv_by_population.pdf"
    _save(figure, path)
    written.append(path)

    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    _box_with_runs(axis, comparison, "nlsr_control_rate_bytes_per_s", _population_position)
    _style_populations(
        axis,
        "NLSR control rate (bytes/s)",
        "Exp3 network-wide NLSR control rate over the common observation interval",
    )
    path = figure_dir / "nlsr_control_rate_by_population.pdf"
    _save(figure, path)
    written.append(path)

    notes = [
        "Formal Exp3 figures use the complete r1-r5 campaign.",
        "The replication unit is the run. Points are repeated handoffs or one run-level overhead.",
        "SRT is milliseconds and is conditional on successful recovery. Censored events are excluded, not plotted as zero.",
        "CLF is an unweighted fraction per paired-consumer handoff.",
        "Prefix RFV is bytes per producer handoff and is not the network-wide total.",
        "Network RFV is bytes per run and is not multiplied by P. NLSR rate is bytes/s per run.",
        "Differences across P are descriptive. Node population and offered prefixes also change.",
    ]
    if any(int(row["n_censored"]) > 0 for row in comparison):
        figure, axis = plt.subplots(figsize=(7.2, 4.4))
        _box_with_runs(axis, comparison, "recovery_success_fraction", _population_position)
        _style_populations(
            axis,
            "Recovery success fraction (per run)",
            "Exp3 recovery success; censored handoffs remain in the denominator",
        )
        path = figure_dir / "recovery_success_by_population.pdf"
        _save(figure, path)
        written.append(path)
        notes.append("Recovery success is recovered handoffs divided by all handoffs in the run.")
    else:
        notes.append("No censored recoveries were present, so no recovery-success figure was written.")
    units = figure_dir / "figure_units.txt"
    units.write_text("\n".join(notes) + "\n", encoding="utf-8", newline="\n")
    written.append(units)
    return written


def draw_pilot(analysis_root: Path, figure_dir: Path) -> List[Path]:
    """Pilot diagnostics. The figure text does not call this result formal r1."""
    pilot = analysis_root / "p4" / "pilot"
    events = _read(pilot / "events.csv")
    prefix_rows = _read(pilot / "prefix_rfv.csv")
    network = _read(pilot / "network_overhead.csv")
    if any(row["source_kind"] != "pilot" or row["run_id"] != "pilot" for row in events + prefix_rows + network):
        raise PlotDataError("pilot figures require source_kind=pilot and run_id=pilot")
    if any(row["population"] != "p4" for row in events):
        raise PlotDataError("the Exp3 pilot plot is P=4 only")
    disclaimer = "P=4 pilot diagnostic; not a formal r1 replicate"
    written = []
    recovered = [row for row in events if row["recovery_status"] == "recovered" and _numeric(row, "service_recovery_time_ms") is not None]
    notes = [
        disclaimer,
        "These figures are one P=4 pilot run. They are not the formal five-run campaign.",
        "A matching schedule seed does not make this directory formal r1.",
    ]
    if recovered:
        figure, axis = plt.subplots(figsize=(7.2, 4.4))
        values = [float(row["service_recovery_time_ms"]) for row in recovered]
        labels = [f"{row['producer']}:{row['handoff_index']}" for row in recovered]
        axis.scatter(range(len(values)), values, color="black", s=18)
        axis.set_xticks(range(len(labels)))
        axis.set_xticklabels(labels, rotation=90, fontsize=7)
        axis.set_ylabel("SRT (ms), conditional on recovery")
        axis.set_title(disclaimer)
        path = figure_dir / "pilot_srt_conditional.pdf"
        _save(figure, path)
        written.append(path)
        notes.append(f"Conditional SRT is shown for {len(recovered)} recovered handoffs.")
    else:
        notes.append("No successful recovery was measured, so no SRT figure was written and no zero SRT was invented.")
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    for consumer in CONSUMERS:
        subset = [row for row in events if row["consumer"] == consumer]
        axis.scatter(
            [int(row["handoff_index"]) for row in subset],
            [float(row["content_loss_fraction"]) for row in subset],
            s=18,
            label=consumer,
        )
    axis.set_xlabel("Handoff index")
    axis.set_ylabel("CLF (fraction per handoff)")
    axis.set_title(disclaimer)
    axis.legend(frameon=False, fontsize=8)
    path = figure_dir / "pilot_clf.pdf"
    _save(figure, path)
    written.append(path)
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    axis.scatter(
        range(len(prefix_rows)),
        [int(row["prefix_rfv_bytes"]) for row in prefix_rows],
        color="black",
        s=18,
    )
    axis.set_ylabel("Prefix RFV (bytes per handoff)")
    axis.set_title(disclaimer + "; not network-wide")
    path = figure_dir / "pilot_prefix_rfv.pdf"
    _save(figure, path)
    written.append(path)
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 4.0))
    axes[0].bar(("network RFV",), (float(network[0]["network_rfv_bytes"]),), color="0.3")
    axes[0].set_ylabel("bytes per run")
    axes[1].bar(("NLSR control",), (float(network[0]["nlsr_control_rate_bytes_per_s"]),), color="0.3")
    axes[1].set_ylabel("bytes/s")
    figure.suptitle(disclaimer + "; one run, not multiplied by P")
    path = figure_dir / "pilot_network_overhead.pdf"
    _save(figure, path)
    written.append(path)
    units = figure_dir / "pilot_figure_units.txt"
    units.write_text("\n".join(notes) + "\n", encoding="utf-8", newline="\n")
    written.append(units)
    return written


EVENT_KEY = ("population", "run_id", "producer", "handoff_index")
ATTACHMENT_CATEGORIES = ("same-access", "same-aggregation", "opposite-aggregation")
ATTACHMENT_LABELS = {
    "same-access": "Same access",
    "same-aggregation": "Same aggregation,\ndifferent access",
    "opposite-aggregation": "Opposite aggregation",
}
EXTENDED_FIGURES = ("srt_by_producer.pdf", "prefix_rfv_by_attachment.pdf")
_ATTACHMENT_GROUP = 4.0
_ATTACHMENT_SLOT = 0.9


def _access_aggregation() -> Dict[str, str]:
    """Map each access router to its aggregation parent from the Exp3 backbone."""
    mapping: Dict[str, str] = {}
    for left, right, _bandwidth, _delay in config.BACKBONE_LINKS:
        if left in config.SHARED_FORWARDERS and right.startswith("acc"):
            mapping[right] = left
        elif right in config.SHARED_FORWARDERS and left.startswith("acc"):
            mapping[left] = right
    return mapping


def attachment_category(to_node: str, consumer: str) -> str:
    """Classify the producer's new attachment against its paired consumer.

    The category is the new access router. It is not whether this hop crossed
    the aggregation boundary.
    """
    if consumer not in config.CONSUMER_ATTACHMENT:
        raise PlotDataError(f"unknown paired consumer: {consumer}")
    aggregation = _access_aggregation()
    consumer_access = config.CONSUMER_ATTACHMENT[consumer]
    if to_node not in aggregation or consumer_access not in aggregation:
        raise PlotDataError(
            f"attachment {to_node} for {consumer} is outside the Exp3 access topology"
        )
    if to_node == consumer_access:
        return "same-access"
    if aggregation[to_node] == aggregation[consumer_access]:
        return "same-aggregation"
    return "opposite-aggregation"


def _event_identity(row: Mapping[str, str]) -> Tuple[str, str, str, str]:
    return (row["population"], row["run_id"], row["producer"], row["handoff_index"])


def _refuse_extended_output(figure_dir: Path) -> None:
    """Keep supplementary figures out of the formal analysis tree and paper figures."""
    target = figure_dir.resolve()
    protected = (
        ANALYSIS_ROOT.resolve(),
        (ROOT / "paper" / "figures").resolve(),
    )
    for forbidden in protected:
        if target == forbidden or forbidden in target.parents:
            raise PlotDataError(f"extended figures cannot be written to {figure_dir}")


def load_extended_handoffs(analysis_root: Path) -> List[Dict[str, str]]:
    """Join campaign events and prefix RFV one-to-one, including packet counts."""
    if not _manifest_complete(analysis_root / "campaign" / "campaign_status.txt"):
        raise PlotDataError(
            f"{analysis_root} is not a complete formal campaign; no extended figure was written"
        )
    events = _read(analysis_root / "campaign" / "events.csv")
    prefix_rows = _read(analysis_root / "campaign" / "prefix_rfv.csv")
    _require(
        events,
        EVENT_KEY + ("consumer", "to_node", "recovery_status", "service_recovery_time_ms"),
        "events",
    )
    _require(
        prefix_rows,
        EVENT_KEY + ("consumer", "prefix_rfv_bytes", "prefix_rfv_packets"),
        "prefix_rfv",
    )
    event_map: Dict[Tuple[str, str, str, str], Mapping[str, str]] = {}
    for row in events:
        key = _event_identity(row)
        if key in event_map:
            raise PlotDataError(f"duplicate event key {key}")
        event_map[key] = row
    prefix_map: Dict[Tuple[str, str, str, str], Mapping[str, str]] = {}
    for row in prefix_rows:
        key = _event_identity(row)
        if key in prefix_map:
            raise PlotDataError(f"duplicate prefix RFV key {key}")
        if key not in event_map:
            raise PlotDataError(f"prefix RFV row without an event: {key}")
        if row["consumer"] != event_map[key]["consumer"]:
            raise PlotDataError(f"consumer mismatch for {key}")
        prefix_map[key] = row
    missing = set(event_map) - set(prefix_map)
    if missing:
        raise PlotDataError(f"event without a prefix RFV row: {sorted(missing)[0]}")
    joined: List[Dict[str, str]] = []
    for key in sorted(event_map):
        event = event_map[key]
        flood = prefix_map[key]
        if event["recovery_status"] == "recovered" and _numeric(event, "service_recovery_time_ms") is None:
            raise PlotDataError(f"recovered handoff missing SRT: {key}")
        if _numeric(flood, "prefix_rfv_bytes") is None or _numeric(flood, "prefix_rfv_packets") is None:
            raise PlotDataError(f"prefix RFV row missing bytes or packet count: {key}")
        category = attachment_category(event["to_node"], event["consumer"])
        joined.append({
            **event,
            "prefix_rfv_bytes": flood["prefix_rfv_bytes"],
            "prefix_rfv_packets": flood["prefix_rfv_packets"],
            "attachment_category": category,
        })
    return joined


def _attachment_position(category: str, population: str) -> float:
    return ATTACHMENT_CATEGORIES.index(category) * _ATTACHMENT_GROUP + POPULATIONS.index(population) * _ATTACHMENT_SLOT


def _producer_label(producer: str) -> str:
    if not producer.startswith("producer") or not producer.removeprefix("producer").isdigit():
        raise PlotDataError(f"unknown producer: {producer}")
    return f"Producer {producer.removeprefix('producer')}"


def conditional_srt_limits(values: Sequence[float]) -> Tuple[float, float]:
    """Pad the observed recovered SRT range so extreme markers stay inside the axes.

    Box plots with hidden fliers otherwise lock the view to the whiskers.
    """
    if not values:
        raise PlotDataError("no recovered SRT values")
    low = min(values)
    high = max(values)
    span = high - low
    pad = 1.0 if span <= 0 else max(span * 0.08, 2.0)
    return low - pad, high + pad


def draw_srt_by_producer(handoffs: Sequence[Mapping[str, str]], figure_dir: Path) -> Path:
    """Per-producer conditional SRT. Censored handoffs stay out of the boxes."""
    censored = sum(1 for row in handoffs if row["recovery_status"] == "right-censored")
    recovered = [row for row in handoffs if row["recovery_status"] == "recovered"]
    if not recovered:
        raise PlotDataError("no successful recovery to plot; censored SRT was not drawn as zero")
    observed = []
    for row in recovered:
        value = _numeric(row, "service_recovery_time_ms")
        if value is None:
            raise PlotDataError("recovered handoff missing SRT")
        observed.append(value)
    lower, upper = conditional_srt_limits(observed)
    figure, axes = plt.subplots(
        1, 3, figsize=(7.2, 4.15), sharey=True,
        gridspec_kw={"width_ratios": (1.2, 1.8, 3.0)},
    )
    legend_axis = None
    for axis, population in zip(axes, POPULATIONS):
        producers = [pair.producer for pair in config.pairs_for(config.parse_population(population))]
        subset = [row for row in recovered if row["population"] == population]

        def position(row: Mapping[str, str], names: Sequence[str] = tuple(producers)) -> Optional[float]:
            if row["producer"] not in names:
                return None
            return float(names.index(row["producer"]))

        _box_with_runs(
            axis, subset, "service_recovery_time_ms", position,
            jitter=True, label_runs=legend_axis is None,
        )
        legend_axis = legend_axis or axis
        axis.set_xticks(range(len(producers)))
        axis.set_xticklabels([_producer_label(name) for name in producers], fontsize=8)
        axis.set_title({"p1": "P=1", "p2": "P=2", "p4": "P=4"}[population], pad=4)
        axis.set_ylim(lower, upper)
    axes[0].set_ylabel("SRT (ms), conditional on recovery")
    figure.suptitle(f"SRT by producer ({censored} right-censored)", y=0.98)
    if legend_axis is not None and legend_axis.get_legend_handles_labels()[0]:
        handles, labels = legend_axis.get_legend_handles_labels()
        figure.legend(
            handles, labels, loc="lower center", ncol=5, frameon=False,
            bbox_to_anchor=(0.5, 0.88), fontsize=8,
        )
    path = figure_dir / "srt_by_producer.pdf"
    _save(figure, path, bottom=0.18, top=0.76)
    return path


def draw_prefix_rfv_by_attachment(handoffs: Sequence[Mapping[str, str]], figure_dir: Path) -> Path:
    """Bytes and sender-egress transmissions for the same handoffs, by new attachment."""
    figure, axes = plt.subplots(2, 1, figsize=(8.0, 7.2), sharex=True)
    panels = (
        (axes[0], "prefix_rfv_bytes", "Prefix RFV\n(bytes per handoff)", True),
        (axes[1], "prefix_rfv_packets", "Sender-egress transmissions\nper handoff", False),
    )
    legend_axis = None
    for axis, value_key, ylabel, label_runs in panels:
        def position(row: Mapping[str, str]) -> Optional[float]:
            category = row.get("attachment_category")
            if category not in ATTACHMENT_CATEGORIES or row["population"] not in POPULATIONS:
                return None
            return _attachment_position(category, row["population"])

        _box_with_runs(axis, handoffs, value_key, position, jitter=True, label_runs=label_runs, widths=0.62)
        axis.relim()
        axis.autoscale_view()
        legend_axis = legend_axis or axis
        axis.set_ylabel(ylabel)
    positions = [
        _attachment_position(category, population)
        for category in ATTACHMENT_CATEGORIES
        for population in POPULATIONS
    ]
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(["P=1", "P=2", "P=4"] * len(ATTACHMENT_CATEGORIES))
    for category in ATTACHMENT_CATEGORIES:
        axes[1].annotate(
            ATTACHMENT_LABELS[category],
            xy=(_attachment_position(category, "p2"), 0.0),
            xycoords=("data", "axes fraction"),
            xytext=(0, -36),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8,
            annotation_clip=False,
        )
    figure.suptitle(
        "Prefix recovery flooding by new attachment relative to the paired consumer\n"
        "Bytes and transmissions describe the same handoffs."
    )
    if legend_axis is not None and legend_axis.get_legend_handles_labels()[0]:
        handles, labels = legend_axis.get_legend_handles_labels()
        figure.legend(handles, labels, loc="upper center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.90))
    path = figure_dir / "prefix_rfv_by_attachment.pdf"
    _save(figure, path, bottom=0.22, top=0.84)
    return path


def draw_extended(analysis_root: Path, figure_dir: Path) -> List[Path]:
    """Write the two supplementary figures. Does not draw the formal figure set."""
    _refuse_extended_output(figure_dir)
    handoffs = load_extended_handoffs(analysis_root)
    written = [
        draw_srt_by_producer(handoffs, figure_dir),
        draw_prefix_rfv_by_attachment(handoffs, figure_dir),
    ]
    return written


def _parse_extended(arguments: Sequence[str]) -> Optional[Tuple[Path, Path]]:
    if not arguments or arguments[0] != "--extended":
        return None
    values: Dict[str, str] = {}
    rest = list(arguments[1:])
    if len(rest) % 2 != 0:
        raise PlotDataError(
            "usage: plot_exp3.py --extended --analysis-root DIR --figure-dir DIR"
        )
    for flag, value in zip(rest[0::2], rest[1::2]):
        if flag in values or flag not in {"--analysis-root", "--figure-dir"}:
            raise PlotDataError(
                "usage: plot_exp3.py --extended --analysis-root DIR --figure-dir DIR"
            )
        values[flag] = value
    if set(values) != {"--analysis-root", "--figure-dir"}:
        raise PlotDataError(
            "usage: plot_exp3.py --extended --analysis-root DIR --figure-dir DIR"
        )
    return Path(values["--analysis-root"]), Path(values["--figure-dir"])


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["--pilot"]:
            written = draw_pilot(ANALYSIS_ROOT, ANALYSIS_ROOT / "figures" / "pilot")
        elif not arguments:
            written = draw_formal(ANALYSIS_ROOT, ANALYSIS_ROOT / "figures")
        elif arguments and arguments[0] == "--extended":
            parsed = _parse_extended(arguments)
            if parsed is None:
                print(
                    "usage: plot_exp3.py --extended --analysis-root DIR --figure-dir DIR",
                    file=sys.stderr,
                )
                return 2
            analysis_root, figure_dir = parsed
            written = draw_extended(analysis_root, figure_dir)
        else:
            print("usage: plot_exp3.py [--pilot | --extended --analysis-root DIR --figure-dir DIR]", file=sys.stderr)
            return 2
    except PlotDataError as error:
        print(f"Exp3 plotting refused: {error}", file=sys.stderr)
        return 2
    for path in written:
        print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
