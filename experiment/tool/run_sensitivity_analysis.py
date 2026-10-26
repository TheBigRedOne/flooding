#!/usr/bin/env python3
"""Host-side OptoFlood parameter-sensitivity summaries.

SPRC Sync publication-delay sensitivity and EDRC verification-timeout
sensitivity. Each study calls the production mobility-event and routing
measure_run functions.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import mobility_event_metrics as metrics
import routing_convergence_metrics as routing
import run_mobility_event_analysis as mobility

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "extended" / "exp1"
EXPECTED_HANDOFFS = 8

SYNC_CELLS: Tuple[Tuple[str, str], ...] = (
    ("d0", "0"),
    ("d1", "1"),
    ("d2", "2"),
    ("d4", "4"),
)
TIMEOUT_CELLS: Tuple[Tuple[str, str], ...] = (
    ("t10", "10"),
    ("t25", "25"),
    ("t50", "50"),
    ("t100", "100"),
    ("t250", "250"),
)

STUDIES = {
    "sync-delay": SYNC_CELLS,
    "verification-timeout": TIMEOUT_CELLS,
}

PRIMARY_FIELDS = {
    "sync-delay": (
        ("service_path_lsa_lead_ms", "Service-path LSA lead (ms)"),
        ("service_path_fib_convergence_ms", "Service-path FIB convergence time (ms)"),
        ("network_fib_convergence_ms", "Network-wide FIB convergence time (ms)"),
    ),
    "verification-timeout": (
        ("topology_update_latency_ms", "Complete mobility-topology update latency (ms)"),
        ("service_path_fib_convergence_ms", "Service-path FIB convergence time (ms)"),
        ("network_fib_convergence_ms", "Network-wide FIB convergence time (ms)"),
    ),
}

PAPER_FIGURES = {
    "sync-delay": RESULTS / "exp1_sync_delay_sensitivity.pdf",
    "verification-timeout": RESULTS / "exp1_verification_timeout_sensitivity.pdf",
}

PAPER_XLABEL = {
    "sync-delay": "Sync publication delay (s)",
    "verification-timeout": "Verification timeout (ms)",
}

PAPER_PANELS = {
    "sync-delay": (
        ("service_path_lsa_lead_ms", "Service-Path LSA Lead"),
        ("service_path_fib_convergence_ms", "Service-Path FIB Convergence"),
        ("network_fib_convergence_ms", "Network-Wide FIB Convergence"),
    ),
    "verification-timeout": (
        ("topology_update_latency_ms", "Complete Mobility-Topology Update Latency"),
        ("service_path_fib_convergence_ms", "Service-Path FIB Convergence"),
        ("network_fib_convergence_ms", "Network-Wide FIB Convergence"),
    ),
}

VERIFICATION_FAILURE_NOTES = frozenset({
    "no mobility verification completion",
    "verification did not establish old UNREACHABLE and new REACHABLE",
    "no own Adj-LSA build at verification completion",
})

EVENT_FIELDS = (
    "study",
    "cell",
    "parameter_value",
    "handoff_index",
    "from_node",
    "to_node",
    "recovered",
    "service_recovery_time_ms",
    "nlsr_control_rate_bytes_per_s",
    "topology_update_latency_ms",
    "topology_note",
    "service_path_lsa_lead_ms",
    "service_path_fib_convergence_ms",
    "network_fib_converged",
    "network_fib_convergence_ms",
    "network_fib_censor_boundary_ms",
    "verification_start_ms",
    "verification_complete_ms",
    "old_adjacency_definitive_ms",
    "new_adjacency_definitive_ms",
    "verification_established",
    "old_poa_unreachable_ms",
    "new_poa_reachable_ms",
)


def verification_established(note: str, complete: str, old_ms: str, new_ms: str) -> bool:
    """True only when the existing accelerated check accepted both PoA facts."""
    return (
        complete != ""
        and old_ms != ""
        and new_ms != ""
        and note not in VERIFICATION_FAILURE_NOTES
    )


def cell_evidence(run_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Return required files and required directories. PCAP files stay explicit."""
    files = [
        run_dir / "params.txt",
        run_dir / "handoffs.txt",
    ]
    directories = [run_dir / "pcap_nodes"]
    for node in routing.NODES:
        files.append(run_dir / "minindn-logs" / node / "nlsr.log")
        files.append(run_dir / "pcap_nodes" / f"{node}.pcap")
    for node in routing.ROUTING_UNIVERSE:
        files.append(run_dir / "minindn-logs" / node / "nfd.log")
    return files, directories


def missing_evidence(files: Sequence[Path], directories: Sequence[Path]) -> List[str]:
    """Directories use is_dir(); files use is_file()."""
    missing: List[str] = []
    for path in directories:
        if not path.is_dir():
            missing.append(f"required sensitivity evidence missing: {path}")
    for path in files:
        if not path.is_file():
            missing.append(f"required sensitivity evidence missing: {path}")
    return missing


def _require_evidence(run_dir: Path) -> None:
    missing = missing_evidence(*cell_evidence(run_dir))
    if missing:
        raise SystemExit("\n".join(missing))


def _measure_cell(study: str, cell: str, parameter: str) -> List[Dict[str, object]]:
    run_dir = RESULTS / study / cell
    _require_evidence(run_dir)
    packets_path = run_dir / "mobility_packets.csv"
    mobility.decode_run(run_dir, packets_path)
    _segments, frame_period_ms = metrics.load_run_config(str(run_dir / "params.txt"))
    handoffs = metrics.load_handoffs(str(run_dir / "handoffs.txt"))
    if len(handoffs) != EXPECTED_HANDOFFS:
        raise SystemExit(
            f"{run_dir}: expected {EXPECTED_HANDOFFS} handoffs, found {len(handoffs)}"
        )
    service_rows = metrics.measure_run(
        metrics.load_packets(str(packets_path)),
        handoffs,
        cell,
        study,
        cell,
        frame_period_ms=frame_period_ms,
    )
    routing_rows, leads, notes, _delays = routing.measure_run(run_dir, cell, study, cell, True)
    if len(service_rows) != EXPECTED_HANDOFFS or len(routing_rows) != EXPECTED_HANDOFFS:
        raise SystemExit(
            f"{run_dir}: measurement returned service={len(service_rows)} routing={len(routing_rows)}"
        )
    routing.apply_evidence_level(routing_rows, "NFD_CONFIRMED")
    lead_by_index = {
        int(row["handoff_index"]): row["median_lead_ms"]
        for row in routing.per_handoff_leads(leads)
    }
    routing_by_index = {int(row["handoff_index"]): row for row in routing_rows}
    combined: List[Dict[str, object]] = []
    for service in service_rows:
        index = int(str(service["handoff_index"]))
        route = routing_by_index[index]
        note = str(route.get("topology_note", ""))
        complete = str(route.get("verification_complete_ms", ""))
        old_ms = str(route.get("old_adjacency_definitive_ms", ""))
        new_ms = str(route.get("new_adjacency_definitive_ms", ""))
        established = verification_established(note, complete, old_ms, new_ms)
        combined.append({
            "study": study,
            "cell": cell,
            "parameter_value": parameter,
            "handoff_index": index,
            "from_node": service["from_node"],
            "to_node": service["to_node"],
            "recovered": service["recovered"],
            "service_recovery_time_ms": service["service_recovery_time_ms"],
            "nlsr_control_rate_bytes_per_s": service["nlsr_control_rate_bytes_per_s"],
            "topology_update_latency_ms": route.get("topology_update_latency_ms", ""),
            "topology_note": note,
            "service_path_lsa_lead_ms": lead_by_index.get(index, ""),
            "service_path_fib_convergence_ms": route.get("service_path_fib_convergence_ms", ""),
            "network_fib_converged": route.get("network_fib_converged", ""),
            "network_fib_convergence_ms": route.get("network_fib_convergence_ms", ""),
            "network_fib_censor_boundary_ms": route.get("network_fib_censor_boundary_ms", ""),
            "verification_start_ms": route.get("verification_start_ms", ""),
            "verification_complete_ms": complete,
            "old_adjacency_definitive_ms": old_ms,
            "new_adjacency_definitive_ms": new_ms,
            "verification_established": established,
            "old_poa_unreachable_ms": old_ms if established else "",
            "new_poa_reachable_ms": new_ms if established else "",
        })
        if note:
            notes.append(f"{cell} handoff {index}: {note}")
    for note in notes:
        print(note)
    return combined


def _write_rows(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _as_dicts(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def timeout_cell_status(cell: str, rows: Sequence[Mapping[str, Any]]) -> str:
    """Counts for one verification-timeout cell. Failed events stay in the total."""
    established = sum(
        1 for row in rows
        if row.get("verification_established") is True or str(row.get("verification_established")) == "True"
    )
    censored = sum(1 for row in rows if str(row.get("network_fib_converged")) == "false")
    counted = _as_dicts(rows)
    return (
        f"{cell}: events={len(rows)} "
        f"verification_established={established} "
        f"topology_numeric={len(routing.numeric(counted, 'topology_update_latency_ms'))} "
        f"service_fib_numeric={len(routing.numeric(counted, 'service_path_fib_convergence_ms'))} "
        f"network_fib_numeric={len(routing.numeric(counted, 'network_fib_convergence_ms'))} "
        f"network_right_censored={censored} "
        f"verification_not_established={len(rows) - established}"
    )


CROSS_CHECK_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("topology_update_latency_ms", "Complete Mobility-Topology Update Latency", "routing"),
    ("service_path_fib_convergence_ms", "Service-Path FIB Convergence", "routing"),
    ("network_fib_convergence_ms", "Network-Wide FIB Convergence", "routing"),
    ("service_recovery_time_ms", "SRT", "mobility"),
)


def _median_text(values: Sequence[float]) -> str:
    if not values:
        return ""
    _q1, median, _q3 = routing.quantiles(values)
    return f"{median:.6g}"


def _main_distribution_text(values: Sequence[float]) -> str:
    if not values:
        return "main_n=0 main_median= main_Q1= main_Q3= main_min= main_max="
    ordered = sorted(values)
    q1, median, q3 = routing.quantiles(ordered)
    return (
        f"main_n={len(ordered)} main_median={median:.6g} main_Q1={q1:.6g} "
        f"main_Q3={q3:.6g} main_min={ordered[0]:.6g} main_max={ordered[-1]:.6g}"
    )


def default_cross_check_lines(
    main_mobility: Sequence[Mapping[str, Any]],
    main_routing: Sequence[Mapping[str, Any]],
    d1_rows: Sequence[Mapping[str, Any]],
    t50_rows: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Describe d1 and t50 against the stored main OptoFlood distributions."""
    lines = [
        "Default-configuration cross-check.",
        "d1 and t50 are independent runs of the production OptoFlood parameter point.",
        "Main statistics are read from existing production CSVs. This comparison is descriptive and has no pass/fail threshold.",
    ]
    opto_mobility = [row for row in main_mobility if row.get("configuration") == "OptoFlood"]
    opto_routing = [row for row in main_routing if row.get("configuration") == "OptoFlood"]
    for field, title, source in CROSS_CHECK_FIELDS:
        main_rows = opto_routing if source == "routing" else opto_mobility
        main_values = routing.numeric(_as_dicts(main_rows), field)
        d1_values = routing.numeric(_as_dicts([row for row in d1_rows if str(row.get("cell")) == "d1"]), field)
        t50_values = routing.numeric(_as_dicts([row for row in t50_rows if str(row.get("cell")) == "t50"]), field)
        lines.append(
            f"{title}: {_main_distribution_text(main_values)} "
            f"d1_median={_median_text(d1_values)} t50_median={_median_text(t50_values)}"
        )
    return lines


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_default_cross_check(repo: Path) -> List[str]:
    """Read the stored production and sensitivity CSVs and compare their recorded values."""
    paths = {
        "mobility": repo / "results" / "solution" / "mobility_events.csv",
        "routing": repo / "results" / "routing" / "routing_events.csv",
        "d1": repo / "results" / "extended" / "exp1" / "sync-delay" / "sensitivity_events.csv",
        "t50": repo / "results" / "extended" / "exp1" / "verification-timeout" / "sensitivity_events.csv",
    }
    missing = [path for path in paths.values() if not path.is_file()]
    if missing:
        detail = "\n".join(f"required cross-check CSV missing: {path}" for path in missing)
        raise SystemExit(detail)
    lines = default_cross_check_lines(
        _read_csv(paths["mobility"]),
        _read_csv(paths["routing"]),
        _read_csv(paths["d1"]),
        _read_csv(paths["t50"]),
    )
    destination = repo / "results" / "extended" / "exp1" / "default_cross_check.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def _summary_lines(study: str, rows: Sequence[Dict[str, object]], cells: Sequence[Tuple[str, str]]) -> List[str]:
    lines = [
        f"study={study}",
        "Blank numeric endpoints stay out of medians. The handoff row is retained.",
        "FIB times use the production NFD_CONFIRMED endpoint. A missing install is not replaced by an NLSR registration time.",
        "verification_established requires the accelerated check to accept old UNREACHABLE and new REACHABLE.",
    ]
    for cell, _parameter in cells:
        selected = [row for row in rows if row["cell"] == cell]
        if study == "verification-timeout":
            lines.append(timeout_cell_status(cell, selected))
        else:
            censored = sum(1 for row in selected if str(row.get("network_fib_converged")) == "false")
            established = sum(
                1 for row in selected
                if row.get("verification_established") is True or str(row.get("verification_established")) == "True"
            )
            lines.append(
                f"{cell}: events={len(selected)} "
                f"srt_numeric={len(routing.numeric(selected, 'service_recovery_time_ms'))} "
                f"topology_numeric={len(routing.numeric(selected, 'topology_update_latency_ms'))} "
                f"lsa_lead_numeric={len(routing.numeric(selected, 'service_path_lsa_lead_ms'))} "
                f"service_fib_numeric={len(routing.numeric(selected, 'service_path_fib_convergence_ms'))} "
                f"network_fib_numeric={len(routing.numeric(selected, 'network_fib_convergence_ms'))} "
                f"network_censored={censored} "
                f"verification_established={established}"
            )
        for field, label in (
            ("service_recovery_time_ms", "SRT"),
            ("nlsr_control_rate_bytes_per_s", "NLSR control rate"),
            ("topology_update_latency_ms", "topology update"),
            ("service_path_lsa_lead_ms", "service-path LSA lead"),
            ("service_path_fib_convergence_ms", "service-path FIB"),
            ("network_fib_convergence_ms", "network-wide FIB"),
            ("verification_start_ms", "verification start"),
            ("verification_complete_ms", "verification complete"),
            ("old_poa_unreachable_ms", "old PoA UNREACHABLE"),
            ("new_poa_reachable_ms", "new PoA REACHABLE"),
        ):
            lines.append(routing.summarise(f"{cell} {label}", routing.numeric(selected, field)))
    return lines


# Median bar and IQR caps are centred on the group. Widths are fractions of the unit spacing.
_MEDIAN_HALF_WIDTH = 0.18
_IQR_CAP_HALF_WIDTH = 0.08


def group_positions(cells: Sequence[Tuple[str, str]]) -> List[float]:
    """Equally spaced positions, one per tested cell."""
    return [float(index) for index in range(len(cells))]


def group_tick_labels(cells: Sequence[Tuple[str, str]]) -> List[str]:
    """Parameter value shown under each experimental level."""
    return [parameter for _cell, parameter in cells]


def _draw_parameter_panel(axis: Any, rows: Sequence[Mapping[str, object]], cells: Sequence[Tuple[str, str]], field: str, title: str, xlabel: str) -> None:
    """Eight handoff observations at one experimental level, plus median and IQR."""
    # Sensitivity cells are displayed as equally spaced experimental levels.
    positions = group_positions(cells)
    for x, (cell, _parameter) in zip(positions, cells):
        values = routing.numeric(_as_dicts([row for row in rows if str(row["cell"]) == cell]), field)
        axis.scatter([x] * len(values), values, s=22, color="C0", alpha=0.65, linewidths=0, zorder=3)
        if not values:
            continue
        q1, median, q3 = routing.quantiles(values)
        axis.plot([x - _MEDIAN_HALF_WIDTH, x + _MEDIAN_HALF_WIDTH], [median, median], color="black", linewidth=1.4, zorder=4)
        if len(values) >= 2:
            axis.plot([x, x], [q1, q3], color="black", linewidth=1.0, zorder=4)
            axis.plot([x - _IQR_CAP_HALF_WIDTH, x + _IQR_CAP_HALF_WIDTH], [q1, q1], color="black", linewidth=1.0, zorder=4)
            axis.plot([x - _IQR_CAP_HALF_WIDTH, x + _IQR_CAP_HALF_WIDTH], [q3, q3], color="black", linewidth=1.0, zorder=4)
    axis.set_xticks(positions)
    axis.set_xticklabels(group_tick_labels(cells))
    axis.set_xlim(-0.55, len(cells) - 0.45)
    axis.set_title(title, loc="left", fontsize=9)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("Time (ms)")
    axis.grid(True, axis="y", linestyle="--", alpha=0.6)
    axis.set_axisbelow(True)


def _plot(path: Path, rows: Sequence[Mapping[str, object]], cells: Sequence[Tuple[str, str]], field: str, ylabel: str, xlabel: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(6.2, 4.2))
    _draw_parameter_panel(axis, rows, cells, field, ylabel, xlabel)
    axis.set_title("")
    axis.set_ylabel(ylabel)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_production_figure(path: Path, study: str, rows: Sequence[Mapping[str, object]]) -> None:
    """Three-panel figure of the eight handoffs from one sensitivity run."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(9.6, 3.4))
    letters = "abc"
    for axis, letter, (field, title) in zip(axes, letters, PAPER_PANELS[study]):
        _draw_parameter_panel(axis, rows, STUDIES[study], field, f"({letter}) {title}", PAPER_XLABEL[study])
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def analyze(study: str) -> None:
    cells = STUDIES[study]
    rows: List[Dict[str, object]] = []
    for cell, parameter in cells:
        rows.extend(_measure_cell(study, cell, parameter))
    destination = RESULTS / study
    _write_rows(destination / "sensitivity_events.csv", rows)
    summary = _summary_lines(study, rows, cells)
    (destination / "sensitivity_summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    for field, ylabel in PRIMARY_FIELDS[study]:
        _plot(destination / f"{field}.pdf", rows, cells, field, ylabel, PAPER_XLABEL[study])
    plot_production_figure(PAPER_FIGURES[study], study, rows)
    print("\n".join(summary))


def main(argv: Sequence[str] | None = None) -> int:
    study = (argv[0] if argv else sys.argv[1]) if (argv or len(sys.argv) > 1) else ""
    if study == "cross-check":
        print("\n".join(write_default_cross_check(ROOT)))
        return 0
    if study not in STUDIES:
        names = "|".join((*STUDIES, "cross-check"))
        raise SystemExit(f"usage: run_sensitivity_analysis.py {names}")
    analyze(study)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
