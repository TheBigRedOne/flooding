#!/usr/bin/env python3
"""Host-side OptoFlood parameter-sensitivity summaries.

Calls the production mobility-event and routing measure_run functions.
It does not start a VM and does not change those metric definitions.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

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


def _require_files(paths: Sequence[Path]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        detail = "\n".join(f"required sensitivity evidence missing: {path}" for path in missing)
        raise SystemExit(detail)


def _cell_evidence(run_dir: Path) -> List[Path]:
    required = [
        run_dir / "params.txt",
        run_dir / "handoffs.txt",
        run_dir / "pcap_nodes",
    ]
    for node in routing.NODES:
        required.append(run_dir / "minindn-logs" / node / "nlsr.log")
    for node in routing.ROUTING_UNIVERSE:
        required.append(run_dir / "minindn-logs" / node / "nfd.log")
    pcap_dir = run_dir / "pcap_nodes"
    if pcap_dir.is_dir():
        for node in routing.NODES:
            required.append(pcap_dir / f"{node}.pcap")
    return required


def _measure_cell(study: str, cell: str, parameter: str) -> List[Dict[str, object]]:
    run_dir = RESULTS / study / cell
    _require_files(_cell_evidence(run_dir))
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


def _summary_lines(study: str, rows: Sequence[Dict[str, object]], cells: Sequence[Tuple[str, str]]) -> List[str]:
    lines = [
        f"study={study}",
        "Blank numeric endpoints stay out of medians. The handoff row is retained.",
        "FIB times use the production NFD_CONFIRMED endpoint. A missing install is not replaced by an NLSR registration time.",
        "verification_established requires the accelerated check to accept old UNREACHABLE and new REACHABLE.",
    ]
    for cell, _parameter in cells:
        selected = [row for row in rows if row["cell"] == cell]
        censored = sum(1 for row in selected if str(row.get("network_fib_converged")) == "false")
        established = sum(1 for row in selected if row.get("verification_established") is True)
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


def _plot(path: Path, rows: Sequence[Dict[str, object]], cells: Sequence[Tuple[str, str]], field: str, ylabel: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(6.2, 4.2))
    for position, (cell, _parameter) in enumerate(cells):
        values = routing.numeric([row for row in rows if row["cell"] == cell], field)
        axis.scatter([position] * len(values), values, s=28, color="C0", alpha=0.65, linewidths=0, zorder=3)
        if not values:
            continue
        _q1, median, _q3 = routing.quantiles(values)
        axis.plot([position - 0.18, position + 0.18], [median, median], color="black", linewidth=1.4, zorder=4)
        if len(values) >= 2:
            q1, _median, q3 = routing.quantiles(values)
            axis.plot([position + 0.22, position + 0.22], [q1, q3], color="black", linewidth=1.0, zorder=2)
    axis.set_xticks(list(range(len(cells))))
    axis.set_xticklabels([cell for cell, _parameter in cells])
    axis.set_ylabel(ylabel)
    axis.grid(True, axis="y", linestyle="--", alpha=0.6)
    axis.set_axisbelow(True)
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
        _plot(destination / f"{field}.pdf", rows, cells, field, ylabel)
    print("\n".join(summary))


def main(argv: Sequence[str] | None = None) -> int:
    study = (argv[0] if argv else sys.argv[1]) if (argv or len(sys.argv) > 1) else ""
    if study not in STUDIES:
        raise SystemExit(f"usage: run_sensitivity_analysis.py {'|'.join(STUDIES)}")
    analyze(study)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
