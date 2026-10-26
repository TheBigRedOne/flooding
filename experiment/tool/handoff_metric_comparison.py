#!/usr/bin/env python3
"""Aggregate and plot per-handoff observations for baseline tuning and OptoFlood.

The observation is one handoff. A configuration is five runs (r1..r5) of eight
handoffs, so each plotted box contains 40 observations. Run identity is kept in
the observations CSV.

Service disruption is read from each run's disruption_metrics.txt.
Forwarding-cost ratio and NLSR control bytes are read from each run's
overhead_total.txt [Handoff N] sections. Those sections are the existing 10 s
post-handoff windows written by compute_overhead_metrics.py. The [Full Run]
section is ignored and cannot satisfy the per-handoff sample.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import matplotlib

if "matplotlib.pyplot" not in sys.modules:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.cbook import boxplot_stats


# Matches the unchanged default of compute_overhead_metrics.py / plot_overhead.py.
HANDOFF_WINDOW_SECONDS = 10.0
EXPECTED_RUN_IDS: Tuple[str, ...] = ("r1", "r2", "r3", "r4", "r5")
EXPECTED_HANDOFFS_PER_RUN = 8
EXPECTED_OBSERVATIONS = 40
EXPECTED_PROFILE_COUNT = 5
EXPECTED_SOLUTION_SERIES = 2
WHIS = 1.5
FULL_RUN_SECTION = "Full Run"

CM_TO_INCH = 1.0 / 2.54
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
MEAN_MARKER = "D"
MEANPROPS = {
    "marker": MEAN_MARKER,
    "markerfacecolor": "black",
    "markeredgecolor": "black",
    "markersize": 4.5,
    "linestyle": "none",
    "zorder": 4,
}

OBSERVATION_FIELDS = [
    "configuration",
    "source",
    "run_id",
    "handoff_index",
    "disruption_ms",
    "forwarding_cost_ratio",
    "nlsr_control_bytes",
]

_SECTION_RE = re.compile(r"^\[(.+)\]$")
_HANDOFF_SECTION_RE = re.compile(r"^Handoff (\d+)$")
_WINDOW_RE = re.compile(r"^Handoff Window Seconds:\s*([0-9]+(?:\.[0-9]+)?)\s*$")
_DISRUPTION_RE = re.compile(
    r"^Handoff (\d+) Disruption Time:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*ms\s*$"
)
_EXPECTED_HANDOFF_INDICES = list(range(1, EXPECTED_HANDOFFS_PER_RUN + 1))


class HandoffMetricError(Exception):
    """Raised when paper-grade aggregation cannot use a run or configuration."""


@dataclass(frozen=True)
class SeriesSpec:
    """One plotted configuration and the directory that contains r1..r5."""

    label: str
    source: str
    directory: str


@dataclass(frozen=True)
class HandoffObservation:
    """One per-handoff metric value with its run identity."""

    configuration: str
    source: str
    run_id: str
    handoff_index: int
    value: float


def parse_run_ids(text: str) -> Tuple[str, ...]:
    """Return the run list, refusing any list other than r1..r5."""
    runs = tuple(token.strip() for token in re.split(r"[,\s]+", text) if token.strip())
    if runs != EXPECTED_RUN_IDS:
        raise HandoffMetricError(
            f"expected runs {','.join(EXPECTED_RUN_IDS)}, got {','.join(runs) or '(empty)'}"
        )
    return runs


def _fmt(value: float) -> str:
    """Format an audit number without converting units."""
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _paper_figure_size() -> Tuple[float, float]:
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style() -> None:
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


def _require_indices(found: Sequence[int], label: str, run_id: str, kind: str) -> None:
    """Refuse a run whose handoff indices are not exactly 1..8."""
    if list(found) == _EXPECTED_HANDOFF_INDICES:
        return
    raise HandoffMetricError(
        f"{label}/{run_id}: {kind} handoffs {list(found)} "
        f"(expected {_EXPECTED_HANDOFF_INDICES}); "
        "refusing to aggregate a shorter or shifted run"
    )


def parse_disruption_file(path: str, spec: SeriesSpec, run_id: str) -> List[HandoffObservation]:
    """Read exactly eight disruption lines from one run."""
    if not os.path.isfile(path):
        raise HandoffMetricError(f"{spec.label}/{run_id}: missing {path}")

    values: Dict[int, float] = {}
    with open(path, "r", encoding="utf-8") as metrics_file:
        for line_number, raw_line in enumerate(metrics_file, start=1):
            text = raw_line.strip()
            if not text:
                continue
            match = _DISRUPTION_RE.match(text)
            if match is None:
                raise HandoffMetricError(
                    f"{spec.label}/{run_id}: {path}:{line_number} is not a disruption "
                    f"observation: {text!r}"
                )
            index = int(match.group(1))
            if index in values:
                raise HandoffMetricError(
                    f"{spec.label}/{run_id}: duplicate disruption handoff {index}"
                )
            values[index] = float(match.group(2))

    _require_indices(sorted(values), spec.label, run_id, "disruption")
    return [
        HandoffObservation(spec.label, spec.source, run_id, index, values[index])
        for index in _EXPECTED_HANDOFF_INDICES
    ]


def _require_number(
    fields: Mapping[str, str],
    key: str,
    spec: SeriesSpec,
    run_id: str,
    handoff_index: int,
) -> float:
    """Read one numeric per-handoff field. n/a is not dropped from the sample."""
    if key not in fields:
        raise HandoffMetricError(
            f"{spec.label}/{run_id}: Handoff {handoff_index} missing {key}"
        )
    text = fields[key].strip()
    if not text or text.lower() == "n/a":
        raise HandoffMetricError(
            f"{spec.label}/{run_id}: Handoff {handoff_index} {key} is not numeric ({text!r}); "
            "refusing to drop the handoff from the sample"
        )
    token = text.split()[0]
    try:
        return float(token)
    except ValueError as exc:
        raise HandoffMetricError(
            f"{spec.label}/{run_id}: Handoff {handoff_index} {key} is not numeric ({text!r})"
        ) from exc


def parse_overhead_file(
    path: str,
    spec: SeriesSpec,
    run_id: str,
) -> Tuple[List[HandoffObservation], List[HandoffObservation]]:
    """Read per-handoff FCR and NLSR control bytes from the 10 s windows.

    [Full Run] is skipped. It is not a fallback when a handoff section is absent.
    """
    if not os.path.isfile(path):
        raise HandoffMetricError(f"{spec.label}/{run_id}: missing {path}")

    window_values: List[float] = []
    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    with open(path, "r", encoding="utf-8") as metrics_file:
        for line_number, raw_line in enumerate(metrics_file, start=1):
            text = raw_line.strip()
            if not text:
                continue
            if current is None:
                window_match = _WINDOW_RE.match(text)
                if window_match is not None:
                    window_values.append(float(window_match.group(1)))
                    continue
            section_match = _SECTION_RE.match(text)
            if section_match is not None:
                name = section_match.group(1).strip()
                if name in sections:
                    raise HandoffMetricError(
                        f"{spec.label}/{run_id}: {path}:{line_number} duplicate section [{name}]"
                    )
                sections[name] = {}
                current = name
                continue
            if current is None or ":" not in text:
                continue
            key, value = text.split(":", 1)
            sections[current][key.strip()] = value.strip()

    if len(window_values) != 1:
        raise HandoffMetricError(
            f"{spec.label}/{run_id}: {path} has {len(window_values)} "
            "'Handoff Window Seconds' lines (expected 1)"
        )
    window_seconds = window_values[0]
    if abs(window_seconds - HANDOFF_WINDOW_SECONDS) > 1e-9:
        raise HandoffMetricError(
            f"{spec.label}/{run_id}: handoff window is {window_seconds} s "
            f"(expected {HANDOFF_WINDOW_SECONDS:.0f} s); "
            "refusing a different measurement window"
        )

    handoff_sections: Dict[int, Dict[str, str]] = {}
    for name, fields in sections.items():
        if name == FULL_RUN_SECTION:
            continue
        match = _HANDOFF_SECTION_RE.match(name)
        if match is None:
            raise HandoffMetricError(
                f"{spec.label}/{run_id}: unexpected overhead section [{name}]"
            )
        handoff_sections[int(match.group(1))] = fields

    _require_indices(sorted(handoff_sections), spec.label, run_id, "overhead")
    fcr_observations: List[HandoffObservation] = []
    control_observations: List[HandoffObservation] = []
    for index in _EXPECTED_HANDOFF_INDICES:
        fields = handoff_sections[index]
        fcr_observations.append(
            HandoffObservation(
                spec.label,
                spec.source,
                run_id,
                index,
                _require_number(fields, "Forwarding Cost Ratio", spec, run_id, index),
            )
        )
        control_observations.append(
            HandoffObservation(
                spec.label,
                spec.source,
                run_id,
                index,
                _require_number(fields, "NLSR Control Bytes", spec, run_id, index),
            )
        )
    return fcr_observations, control_observations


def _load_run_rows(spec: SeriesSpec, run_id: str) -> List[dict]:
    """Join one run's three metrics on handoff index. Both files are checked."""
    errors: List[str] = []
    disruption: List[HandoffObservation] = []
    fcr: List[HandoffObservation] = []
    control: List[HandoffObservation] = []
    try:
        disruption = parse_disruption_file(
            os.path.join(spec.directory, run_id, "disruption_metrics.txt"),
            spec,
            run_id,
        )
    except HandoffMetricError as exc:
        errors.append(str(exc))
    try:
        fcr, control = parse_overhead_file(
            os.path.join(spec.directory, run_id, "overhead_total.txt"),
            spec,
            run_id,
        )
    except HandoffMetricError as exc:
        errors.append(str(exc))
    if errors:
        raise HandoffMetricError("\n".join(errors))

    disruption_by_index = {item.handoff_index: item for item in disruption}
    fcr_by_index = {item.handoff_index: item for item in fcr}
    control_by_index = {item.handoff_index: item for item in control}
    rows: List[dict] = []
    for index in _EXPECTED_HANDOFF_INDICES:
        rows.append({
            "configuration": spec.label,
            "source": spec.source,
            "run_id": run_id,
            "handoff_index": index,
            "disruption_ms": disruption_by_index[index].value,
            "forwarding_cost_ratio": fcr_by_index[index].value,
            "nlsr_control_bytes": control_by_index[index].value,
        })
    return rows


def load_series_rows(spec: SeriesSpec, run_ids: Sequence[str]) -> List[dict]:
    """Load five complete runs. A missing or short run fails the series."""
    errors: List[str] = []
    loaded: Dict[str, List[dict]] = {}
    for run_id in run_ids:
        try:
            loaded[run_id] = _load_run_rows(spec, run_id)
        except HandoffMetricError as exc:
            errors.append(str(exc))
    if errors:
        raise HandoffMetricError(
            "paper-grade aggregation failed; missing or short runs are not dropped:\n"
            + "\n".join(f"  {line}" for line in "\n".join(errors).splitlines())
        )
    if tuple(loaded) != tuple(run_ids):
        raise HandoffMetricError(
            f"{spec.label}: loaded runs {tuple(loaded)} (expected {tuple(run_ids)})"
        )
    rows: List[dict] = []
    for run_id in run_ids:
        run_rows = loaded[run_id]
        if len(run_rows) != EXPECTED_HANDOFFS_PER_RUN:
            raise HandoffMetricError(
                f"{spec.label}/{run_id}: n={len(run_rows)} "
                f"(expected {EXPECTED_HANDOFFS_PER_RUN} per run); "
                "refusing to aggregate a shorter run"
            )
        rows.extend(run_rows)
    if len(rows) != EXPECTED_OBSERVATIONS:
        raise HandoffMetricError(
            f"{spec.label}: n={len(rows)} (expected {EXPECTED_OBSERVATIONS}); "
            "refusing to aggregate a smaller sample"
        )
    return rows


def aggregate_series(specs: Sequence[SeriesSpec], run_ids: Sequence[str]) -> List[dict]:
    """Aggregate every series, reporting all series errors together."""
    if tuple(run_ids) != EXPECTED_RUN_IDS:
        raise HandoffMetricError(
            f"expected runs {','.join(EXPECTED_RUN_IDS)}, got {','.join(run_ids)}"
        )
    errors: List[str] = []
    rows: List[dict] = []
    for spec in specs:
        try:
            rows.extend(load_series_rows(spec, run_ids))
        except HandoffMetricError as exc:
            errors.append(str(exc))
    if errors:
        raise HandoffMetricError("\n".join(errors))
    return rows


def baseline_specs(root_dir: str, profiles: Sequence[str]) -> List[SeriesSpec]:
    """Map the five baseline profile directories onto G0..G4."""
    if len(profiles) != EXPECTED_PROFILE_COUNT:
        raise HandoffMetricError(
            f"baseline comparison requires {EXPECTED_PROFILE_COUNT} profiles, "
            f"got {len(profiles)}: {list(profiles)}"
        )
    specs: List[SeriesSpec] = []
    for profile in profiles:
        specs.append(
            SeriesSpec(
                label=profile.split("-", 1)[0].upper(),
                source=profile,
                directory=os.path.join(root_dir, profile),
            )
        )
    return specs


def solution_specs(baseline_dir: str, solution_dir: str, baseline_label: str, solution_label: str) -> List[SeriesSpec]:
    """G0 and OptoFlood, each read from its own r1..r5 directory."""
    specs = [
        SeriesSpec(baseline_label, os.path.basename(baseline_dir), baseline_dir),
        SeriesSpec(solution_label, "solution", solution_dir),
    ]
    if len(specs) != EXPECTED_SOLUTION_SERIES:
        raise HandoffMetricError(
            f"solution comparison requires {EXPECTED_SOLUTION_SERIES} series, got {len(specs)}"
        )
    return specs


def metric_groups(rows: Sequence[dict], labels: Sequence[str], field: str) -> List[Tuple[str, List[float]]]:
    """Return plotted groups in label order, each with 40 observations."""
    groups: List[Tuple[str, List[float]]] = []
    for label in labels:
        values = [float(row[field]) for row in rows if row["configuration"] == label]
        if len(values) != EXPECTED_OBSERVATIONS:
            raise HandoffMetricError(
                f"{label} {field}: n={len(values)} (expected {EXPECTED_OBSERVATIONS}); "
                "refusing to plot a smaller sample"
            )
        groups.append((label, values))
    return groups


def summarise_values(values: Sequence[float]) -> dict:
    """Tukey 1.5-IQR summary. Whisker ends are not the sample min and max."""
    stats = boxplot_stats(list(values), whis=WHIS)[0]
    return {
        "n": len(values),
        "min": float(min(values)),
        "q1": float(stats["q1"]),
        "median": float(stats["med"]),
        "mean": float(stats["mean"]),
        "q3": float(stats["q3"]),
        "max": float(max(values)),
        "whislo": float(stats["whislo"]),
        "whishi": float(stats["whishi"]),
        "tukey_outliers": [float(value) for value in stats["fliers"]],
    }


def format_audit(metric_name: str, groups: Sequence[Tuple[str, Sequence[float]]]) -> str:
    """One audit line per box: n, min, Q1, median, mean, Q3, max, Tukey outliers."""
    lines: List[str] = []
    for label, values in groups:
        summary = summarise_values(values)
        outliers = [_fmt(value) for value in summary["tukey_outliers"]]
        lines.append(
            f"{metric_name} {label}: "
            f"n={summary['n']} "
            f"min={_fmt(summary['min'])} "
            f"Q1={_fmt(summary['q1'])} "
            f"median={_fmt(summary['median'])} "
            f"mean={_fmt(summary['mean'])} "
            f"Q3={_fmt(summary['q3'])} "
            f"max={_fmt(summary['max'])} "
            f"tukey_outliers={outliers}"
        )
    return "\n".join(lines) + "\n"


def draw_handoff_boxes(ax, groups: Sequence[Tuple[str, Sequence[float]]]) -> dict:
    """Draw Tukey boxes with a mean marker. Each group must contain 40 values."""
    if not groups:
        raise HandoffMetricError("no groups to plot")
    data: List[Sequence[float]] = []
    for label, values in groups:
        if len(values) != EXPECTED_OBSERVATIONS:
            raise HandoffMetricError(
                f"{label}: n={len(values)} (expected {EXPECTED_OBSERVATIONS}); "
                "refusing to plot a smaller sample"
            )
        data.append(values)

    positions = list(range(len(groups)))
    boxplot = ax.boxplot(
        data,
        positions=positions,
        widths=BOX_WIDTH,
        whis=WHIS,
        showfliers=True,
        showmeans=True,
        meanline=False,
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
        meanprops=MEANPROPS,
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
    if len(boxplot["means"]) != len(groups):
        raise HandoffMetricError("box plot did not create a mean marker for every group")
    for mean_artist in boxplot["means"]:
        if mean_artist.get_marker() != MEAN_MARKER:
            raise HandoffMetricError("box plot mean marker is missing")
    ax.set_xticks(positions)
    ax.set_xticklabels([label for label, _ in groups])
    return boxplot


def render_metric_pdf(
    path: str,
    groups: Sequence[Tuple[str, Sequence[float]]],
    xlabel: str,
    ylabel: str,
    plain_y: bool,
) -> None:
    """Write one comparison box-plot PDF."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    draw_handoff_boxes(ax, groups)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", alpha=0.7)
    if plain_y:
        ax.ticklabel_format(style="plain", axis="y", useOffset=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_observations(path: str, rows: Sequence[dict]) -> None:
    """Write the long-form sample, including run_id and handoff_index."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OBSERVATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "configuration": row["configuration"],
                "source": row["source"],
                "run_id": row["run_id"],
                "handoff_index": row["handoff_index"],
                "disruption_ms": row["disruption_ms"],
                "forwarding_cost_ratio": row["forwarding_cost_ratio"],
                "nlsr_control_bytes": row["nlsr_control_bytes"],
            })


def write_audit(path: str, text: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
        output_file.write(text)


def _emit_comparison(
    rows: Sequence[dict],
    labels: Sequence[str],
    xlabel: str,
    observations_path: str,
    audit_path: str,
    disruption_pdf: str,
    fcr_pdf: str,
    control_pdf: str,
) -> None:
    """Write the CSV, audit, and three box plots after aggregation has succeeded."""
    disruption = metric_groups(rows, labels, "disruption_ms")
    fcr = metric_groups(rows, labels, "forwarding_cost_ratio")
    control = metric_groups(rows, labels, "nlsr_control_bytes")
    audit = (
        format_audit("disruption", disruption)
        + format_audit("fcr", fcr)
        + format_audit("nlsr_control_bytes", control)
    )
    print(audit, end="")
    write_observations(observations_path, rows)
    write_audit(audit_path, audit)
    render_metric_pdf(disruption_pdf, disruption, xlabel, "Disruption Time (ms)", False)
    render_metric_pdf(fcr_pdf, fcr, xlabel, "Forwarding Cost Ratio", False)
    render_metric_pdf(control_pdf, control, xlabel, "NLSR Control Bytes", True)


def _parse_profiles(text: str) -> List[str]:
    return [token.strip() for token in re.split(r"[,\s]+", text) if token.strip()]


def run_baseline(args: argparse.Namespace) -> None:
    run_ids = parse_run_ids(args.runs)
    profiles = _parse_profiles(args.profiles)
    specs = baseline_specs(args.root_dir, profiles)
    rows = aggregate_series(specs, run_ids)
    _emit_comparison(
        rows,
        [spec.label for spec in specs],
        "Baseline Parameter Group",
        args.observations,
        args.audit,
        args.disruption_pdf,
        args.fcr_pdf,
        args.control_pdf,
    )


def run_solution(args: argparse.Namespace) -> None:
    run_ids = parse_run_ids(args.runs)
    specs = solution_specs(
        args.baseline_dir,
        args.solution_dir,
        args.baseline_label,
        args.solution_label,
    )
    rows = aggregate_series(specs, run_ids)
    _emit_comparison(
        rows,
        [spec.label for spec in specs],
        "Configuration",
        args.observations,
        args.audit,
        args.disruption_pdf,
        args.fcr_pdf,
        args.control_pdf,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot per-handoff disruption, FCR, and NLSR control box plots."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline = subparsers.add_parser("baseline", help="G0..G4 baseline tuning figures.")
    baseline.add_argument("--root-dir", required=True)
    baseline.add_argument("--profiles", required=True)
    baseline.add_argument("--runs", default=",".join(EXPECTED_RUN_IDS))
    baseline.add_argument("--observations", required=True)
    baseline.add_argument("--audit", required=True)
    baseline.add_argument("--disruption-pdf", required=True)
    baseline.add_argument("--fcr-pdf", required=True)
    baseline.add_argument("--control-pdf", required=True)
    baseline.set_defaults(handler=run_baseline)

    solution = subparsers.add_parser("solution", help="G0 versus OptoFlood figures.")
    solution.add_argument("--baseline-dir", required=True)
    solution.add_argument("--solution-dir", required=True)
    solution.add_argument("--baseline-label", default="G0")
    solution.add_argument("--solution-label", default="OptoFlood")
    solution.add_argument("--runs", default=",".join(EXPECTED_RUN_IDS))
    solution.add_argument("--observations", required=True)
    solution.add_argument("--audit", required=True)
    solution.add_argument("--disruption-pdf", required=True)
    solution.add_argument("--fcr-pdf", required=True)
    solution.add_argument("--control-pdf", required=True)
    solution.set_defaults(handler=run_solution)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        args.handler(args)
    except HandoffMetricError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
