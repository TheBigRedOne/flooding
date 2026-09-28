#!/usr/bin/env python3
"""Mobility-event analysis from raw per-node packet captures.

Decodes PCAPs with the Python decoder, measures one run, and aggregates the
baseline, solution, and Exp1 event tables and figures. This program does not
start a virtual machine.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import extract_overhead_csv as extractor
import mobility_event_metrics as metrics
import plot_mobility_event_metrics as plots

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
PROFILES = [
    "g0-h60-a10-r15-s60",
    "g1-h54-a9-r14-s54",
    "g2-h48-a8-r12-s48",
    "g3-h42-a7-r10-s42",
    "g4-h36-a6-r9-s36",
]
RUNS = ["r1", "r2", "r3", "r4", "r5"]
EXP1_INTERVALS = [10, 20, 30, 40, 50]
NODE_PCAPS = (
    "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
    "producer", "consumer",
)
PACKET_HEADER = [
    "node", "frame.number", "frame.time_epoch", "frame.len", "sll.pkttype", "sll.ifindex",
    "ndn.type", "ndn.name", "ndn.flood_id", "ndn.new_face_seq",
    "ndn.lp.hoplimit", "ndn.lp.mobility_flag", "ndn.hoplimit",
]


def _packet_name_and_type(ndn_payload: bytes) -> tuple[str, str, dict]:
    custom = extractor._decode_custom_fields(ndn_payload)
    try:
        tlv_type, tlv_value, _ = extractor._read_tlv(ndn_payload, 0)
    except ValueError:
        return "", "", custom
    inner_type, inner_value = tlv_type, tlv_value
    if tlv_type == extractor._LP_PACKET_TLV:
        fragment = None
        offset = 0
        try:
            while offset < len(tlv_value):
                sub_type, sub_value, offset = extractor._read_tlv(tlv_value, offset)
                if sub_type == extractor._LP_FRAGMENT_TLV:
                    fragment = sub_value
        except ValueError:
            return "", "", custom
        if fragment is None:
            return "", "", custom
        try:
            inner_type, inner_value, _ = extractor._read_tlv(fragment, 0)
        except ValueError:
            return "", "", custom
    if inner_type == extractor._NDN_INTEREST_TLV:
        ptype = "Interest"
    elif inner_type == extractor._NDN_DATA_TLV:
        ptype = "Data"
    else:
        return "", "", custom
    try:
        name_type, name_value, _ = extractor._read_tlv(inner_value, 0)
    except ValueError:
        return "", ptype, custom
    if name_type != 7:
        return "", ptype, custom
    parts = []
    offset = 0
    try:
        while offset < len(name_value):
            component_type, component_value, offset = extractor._read_tlv(name_value, offset)
            parts.append((component_type, component_value))
    except ValueError:
        return "", ptype, custom
    return metrics.render_components(parts), ptype, custom


def decode_run(run_dir: Path, output: Path) -> None:
    """Write one decoded packet table for a run. Raw PCAPs are not modified."""
    pcap_dir = run_dir / "pcap_nodes"
    pcaps = sorted(pcap_dir.glob("*.pcap")) if pcap_dir.is_dir() else []
    if not pcaps:
        raise metrics.MobilityMetricError(f"missing packet captures in {pcap_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(PACKET_HEADER)
        for pcap in pcaps:
            print(f"decode {pcap}", flush=True)
            for frame_no, (timestamp, frame, linktype) in enumerate(extractor._iter_pcap_frames(pcap), start=1):
                parsed = extractor._parse_link_header(frame, linktype)
                if parsed is None:
                    continue
                pkttype, ifindex, protocol, payload = parsed
                ndn_payload = extractor._extract_ndn_payload(protocol, payload)
                if ndn_payload is None:
                    continue
                name, ptype, custom = _packet_name_and_type(ndn_payload)
                if not name:
                    continue
                writer.writerow([
                    pcap.stem, frame_no, f"{timestamp:.9f}", len(frame),
                    "" if pkttype is None else pkttype,
                    "" if ifindex is None else ifindex,
                    ptype, name,
                    custom.get("ndn.flood_id", ""),
                    custom.get("ndn.new_face_seq", ""),
                    custom.get("ndn.lp.hoplimit", ""),
                    custom.get("ndn.lp.mobility_flag", ""),
                    custom.get("ndn.hoplimit", ""),
                ])


def _identity(run_dir: Path) -> tuple[str, str, str]:
    parts = [part.lower() for part in run_dir.parts]
    if "baseline" in parts:
        profile = run_dir.parent.name
        return profile.split("-", 1)[0].upper(), profile, run_dir.name
    if run_dir.parent.name == "solution":
        return "OptoFlood", "solution", run_dir.name
    if "exp1" in parts:
        _segments, interval = metrics.load_run_config(str(run_dir / "params.txt"))
        return str(interval), f"i{interval}", "exp1"
    raise metrics.MobilityMetricError(f"unrecognised run directory {run_dir}")


def measure_run(run_dir: Path, packets_path: Path, output: Path) -> None:
    configuration, profile, run_id = _identity(run_dir)
    _segments, interval = metrics.load_run_config(str(run_dir / "params.txt"))
    rows = metrics.measure_run(
        metrics.load_packets(str(packets_path)),
        metrics.load_handoffs(str(run_dir / "handoffs.txt")),
        configuration,
        profile,
        run_id,
        frame_period_ms=interval,
    )
    metrics.write_csv(str(output), rows)


def _read_events(paths: Sequence[Path]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(dict(row))
    return rows


def _write_rows(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metrics.EVENT_FIELDS), lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _audit(path: Path, rows: Sequence[Dict[str, object]], extra: str = "") -> None:
    text = metrics.srt_observation_summary(rows) + "\n" + metrics.format_audit(rows) + extra
    path.write_text(text, encoding="utf-8")


def _boxes(source: Path, field: str, ylabel: str, labels: str, output: Path, log_y: bool) -> None:
    argv = ["boxes", "--input", str(source), "--field", field, "--ylabel", ylabel, "--labels", labels, "--output", str(output)]
    if log_y:
        argv.append("--log-y")
    plots.main(argv)


def require_raw(paths: Sequence[Path]) -> None:
    """Fail before any decode when experiment evidence is absent.

    Analysis does not ask Make to rebuild a missing capture.
    """
    missing = [path for path in paths if not path.is_file()]
    if missing:
        detail = "\n".join(f"required raw capture missing: {path}" for path in missing)
        raise metrics.MobilityMetricError(detail)


def run_raw_files(run_dir: Path) -> List[Path]:
    files = [run_dir / "params.txt", run_dir / "handoffs.txt", run_dir / "consumer_capture.pcap"]
    files.extend(run_dir / "pcap_nodes" / f"{node}.pcap" for node in NODE_PCAPS)
    return files


def _analyze_runs(run_dirs: Sequence[Path]) -> None:
    require_raw([path for run_dir in run_dirs for path in run_raw_files(run_dir)])
    for run_dir in run_dirs:
        packets = run_dir / "mobility_packets.csv"
        decode_run(run_dir, packets)
        measure_run(run_dir, packets, run_dir / "mobility_events.csv")


def analyze_baseline() -> None:
    _analyze_runs([RESULTS / "baseline" / profile / run_id for profile in PROFILES for run_id in RUNS])
    aggregate_baseline()


def analyze_solution() -> None:
    _analyze_runs([RESULTS / "baseline" / PROFILES[0] / run_id for run_id in RUNS])
    _analyze_runs([RESULTS / "solution" / run_id for run_id in RUNS])
    aggregate_solution()


def _write_timeline(deadline_ms: float) -> None:
    run_dir = RESULTS / "extended" / "exp1" / "i20"
    capture = run_dir / "consumer_capture.pcap"
    handoffs = run_dir / "handoffs.txt"
    require_raw([capture, handoffs])
    derived = run_dir / "consumer_capture.csv"
    with derived.open("w", encoding="utf-8", newline="") as handle:
        subprocess.run(
            [
                "tshark", "-X", "lua_script:experiment/tool/ndn.lua", "-r", str(capture),
                "-T", "fields", "-e", "frame.time_epoch", "-e", "frame.len", "-e", "ndn.type", "-e", "ndn.name",
                "-E", "separator=,", "-E", "header=y", "-E", "quote=d",
            ],
            check=True,
            stdout=handle,
        )
    output = RESULTS / "extended" / "exp1" / "exp1_delivery_timeline.pdf"
    subprocess.run(
        [
            sys.executable, str(ROOT / "experiment" / "tool" / "plot_delivery_timeline.py"),
            str(derived), str(handoffs), str(output), "--deadline", str(deadline_ms),
        ],
        check=True,
    )


def analyze_exp1(diagnostic: bool = False, deadline_ms: float = 200.0) -> None:
    _analyze_runs([RESULTS / "extended" / "exp1" / f"i{interval}" for interval in EXP1_INTERVALS])
    aggregate_exp1(diagnostic=diagnostic)
    _write_timeline(deadline_ms)


def aggregate_baseline() -> None:
    paths = [RESULTS / "baseline" / profile / run_id / "mobility_events.csv" for profile in PROFILES for run_id in RUNS]
    rows = _read_events(paths)
    for profile in PROFILES:
        label = profile.split("-", 1)[0].upper()
        metrics.require_complete([row for row in rows if row["configuration"] == label], label, RUNS, 8)
    destination = RESULTS / "baseline" / "mobility_events.csv"
    _write_rows(destination, rows)
    _audit(RESULTS / "baseline" / "mobility_event_audit.txt", rows)
    _boxes(destination, "service_recovery_time_ms", "Service recovery time (ms)", "G0,G1,G2,G3,G4", RESULTS / "baseline_service_recovery_time.pdf", False)
    _boxes(destination, "content_loss_fraction", "Content loss fraction", "G0,G1,G2,G3,G4", RESULTS / "baseline_content_loss_fraction.pdf", False)
    _boxes(destination, "forwarding_cost_ratio", "Forwarding cost ratio", "G0,G1,G2,G3,G4", RESULTS / "baseline_forwarding_cost_ratio.pdf", True)
    _boxes(destination, "nlsr_control_rate_bytes_per_s", "NLSR control rate (bytes/s)", "G0,G1,G2,G3,G4", RESULTS / "baseline_nlsr_control_rate.pdf", True)


def aggregate_solution() -> None:
    g0 = [RESULTS / "baseline" / PROFILES[0] / run_id / "mobility_events.csv" for run_id in RUNS]
    solution = [RESULTS / "solution" / run_id / "mobility_events.csv" for run_id in RUNS]
    rows = _read_events(g0 + solution)
    metrics.require_complete([row for row in rows if row["configuration"] == "G0"], "G0", RUNS, 8)
    metrics.require_complete([row for row in rows if row["configuration"] == "OptoFlood"], "OptoFlood", RUNS, 8)
    destination = RESULTS / "solution" / "mobility_events.csv"
    _write_rows(destination, rows)
    _audit(RESULTS / "solution" / "mobility_event_audit.txt", rows)
    _boxes(destination, "service_recovery_time_ms", "Service recovery time (ms)", "G0,OptoFlood", RESULTS / "solution_service_recovery_time.pdf", True)
    _boxes(destination, "content_loss_fraction", "Content loss fraction", "G0,OptoFlood", RESULTS / "solution_content_loss_fraction.pdf", False)
    _boxes(destination, "forwarding_cost_ratio", "Forwarding cost ratio", "G0,OptoFlood", RESULTS / "solution_forwarding_cost_ratio.pdf", False)
    _boxes(destination, "nlsr_control_rate_bytes_per_s", "NLSR control rate (bytes/s)", "G0,OptoFlood", RESULTS / "solution_nlsr_control_rate.pdf", False)


def aggregate_exp1(diagnostic: bool = False) -> None:
    paths = [RESULTS / "extended" / "exp1" / f"i{interval}" / "mobility_events.csv" for interval in EXP1_INTERVALS]
    rows = _read_events(paths)
    for interval in EXP1_INTERVALS:
        selected = [row for row in rows if row["configuration"] == str(interval)]
        if len(selected) != 16:
            raise metrics.MobilityMetricError(f"exp1 {interval}: expected 16 events, found {len(selected)}")
    destination = RESULTS / "extended" / "exp1" / "mobility_events.csv"
    _write_rows(destination, rows)
    _audit(RESULTS / "extended" / "exp1" / "mobility_event_audit.txt", rows)
    out = RESULTS / "extended" / "exp1"
    plots.main(["exp1", "--input", str(destination), "--field", "service_recovery_time_ms", "--ylabel", "Service recovery time (ms)", "--output", str(out / "exp1_service_recovery_time.pdf")])
    plots.main(["exp1", "--input", str(destination), "--field", "content_loss_fraction", "--ylabel", "Content loss fraction", "--output", str(out / "exp1_content_loss_fraction.pdf")])
    plots.main(["exp1", "--input", str(destination), "--field", "explicit_flood_rate_bytes_per_s", "--ylabel", "Explicit flood rate (bytes/s)", "--series", "explicit_flood_rate_bytes_per_s,interest_flood_rate_bytes_per_s,data_flood_rate_bytes_per_s", "--output", str(out / "exp1_explicit_flood_rate.pdf")])
    if diagnostic:
        plots.main(["exp1", "--input", str(destination), "--field", "service_recovery_time_ms", "--ylabel", "Time (ms)", "--series", "first_post_handoff_producer_data_arrival_ms,service_recovery_time_ms", "--output", str(out / "exp1_recovery_decomposition.pdf")])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure mobility events from raw captures.")
    sub = parser.add_subparsers(dest="command", required=True)
    decode = sub.add_parser("decode")
    decode.add_argument("--run-dir", required=True)
    decode.add_argument("--output", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--run-dir", required=True)
    measure.add_argument("--packets", required=True)
    measure.add_argument("--output", required=True)
    sub.add_parser("aggregate-baseline")
    sub.add_parser("aggregate-solution")
    exp1 = sub.add_parser("aggregate-exp1")
    exp1.add_argument("--diagnostic", action="store_true")
    sub.add_parser("analyze-baseline")
    sub.add_parser("analyze-solution")
    analyze_exp = sub.add_parser("analyze-exp1")
    analyze_exp.add_argument("--diagnostic", action="store_true")
    analyze_exp.add_argument("--deadline", type=float, default=200.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "decode":
            decode_run(Path(args.run_dir), Path(args.output))
        elif args.command == "measure":
            measure_run(Path(args.run_dir), Path(args.packets), Path(args.output))
        elif args.command == "aggregate-baseline":
            aggregate_baseline()
        elif args.command == "aggregate-solution":
            aggregate_solution()
        elif args.command == "aggregate-exp1":
            aggregate_exp1(diagnostic=args.diagnostic)
        elif args.command == "analyze-baseline":
            analyze_baseline()
        elif args.command == "analyze-solution":
            analyze_solution()
        else:
            analyze_exp1(diagnostic=args.diagnostic, deadline_ms=args.deadline)
    except metrics.MobilityMetricError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
