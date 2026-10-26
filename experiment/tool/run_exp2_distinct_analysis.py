#!/usr/bin/env python3
"""Distinct Streams measurement. Does not start a VM or modify Exp2(a) outputs.

One run:
    python3 experiment/tool/run_exp2_distinct_analysis.py n2 r1
    python3 experiment/tool/run_exp2_distinct_analysis.py n4 r1

All ten full runs:
    python3 experiment/tool/run_exp2_distinct_analysis.py --all
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import exp2_distinct_metrics as distinct
import exp2_shared_config as config
import mobility_event_metrics as metrics
import run_mobility_event_analysis as decoder

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results" / "extended" / "exp2" / "distinct"
OUTPUT = SOURCE / "analysis"
RUNS = config.FULL_RUN_IDS
POPULATIONS = ("n2", "n4")


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _capture_identity(run_dir: Path, population: str, run_id: str) -> str:
    lines = [
        f"campaign={config.DISTINCT_CAMPAIGN_ID}",
        f"population={population}",
        f"run_id={run_id}",
        f"source={run_dir.resolve()}",
    ]
    pcap_dir = run_dir / "pcap_nodes"
    pcaps = sorted(pcap_dir.glob("*.pcap")) if pcap_dir.is_dir() else []
    lines.append(f"pcap_count={len(pcaps)}")
    for pcap in pcaps:
        lines.append(f"{pcap.name}:{pcap.stat().st_size}")
    return "\n".join(lines) + "\n"


def _load_packets(run_dir: Path, population: str, run_id: str) -> Tuple[List[metrics.Packet], List[metrics.Handoff], int]:
    identity = _capture_identity(run_dir, population, run_id)
    decoded = OUTPUT / "packets" / population / run_id / "mobility_packets.csv"
    identity_path = decoded.with_suffix(".identity")
    reusable = (
        decoded.is_file()
        and decoded.stat().st_size > 0
        and identity_path.is_file()
        and identity_path.read_text(encoding="utf-8") == identity
    )
    if reusable:
        print(f"reuse decoded packets {decoded}", flush=True)
    else:
        if decoded.exists() or identity_path.exists():
            print(f"decoded packets do not match this run; decoding again: {run_dir}", flush=True)
        decoder.decode_run(run_dir, decoded)
        identity_path.write_text(identity, encoding="utf-8")
    packets = metrics.load_packets(str(decoded))
    handoffs = metrics.load_handoffs(str(run_dir / "handoffs.txt"))
    return packets, handoffs, len(list((run_dir / "pcap_nodes").glob("*.pcap")))


def _final_shortfall(last_handoff: float, final_observation_s: float, capture_end: float) -> float:
    return (last_handoff + final_observation_s) - capture_end


def measure_run(
    population: str,
    run_id: str,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], List[str], List[str]]:
    if population not in POPULATIONS or run_id not in RUNS:
        raise metrics.MobilityMetricError(f"Distinct analysis accepts n2/n4 and r1..r5; got {population} {run_id}")
    run_dir = SOURCE / population / run_id
    if not run_dir.is_dir():
        raise metrics.MobilityMetricError(f"missing Distinct run directory: {run_dir}")
    configuration, recorded_run, consumers, interval, final_observation_s = distinct.load_contract(run_dir)
    if recorded_run != run_id:
        raise metrics.MobilityMetricError(f"{run_dir} recorded run {recorded_run} != {run_id}")
    packets, handoffs, captures = _load_packets(run_dir, population, run_id)
    expected_nodes = len(config.physical_hosts(tuple(host for host, _identity, _attachment, _prefix in consumers)))
    if captures != expected_nodes:
        raise metrics.MobilityMetricError(f"{run_dir} captured {captures} pcaps; expected {expected_nodes}")
    if len(handoffs) != 8:
        raise metrics.MobilityMetricError(f"{run_dir} has {len(handoffs)} handoffs; expected 8")
    network, consumer, streams = distinct.measure_events(
        packets, handoffs, configuration, run_id, consumers, interval, captures,
    )
    problems = distinct.unique_problems(network, consumer, streams)
    problems.extend(distinct.overhead_mismatches(network, packets, handoffs, configuration, run_id, interval))
    if any(row["invalid_duration"] == "true" for row in consumer):
        problems.append(f"{configuration} {run_id} has a non-positive event duration")
    capture_end = max(packet.time for packet in packets)
    shortfall = _final_shortfall(handoffs[-1].abs_time, final_observation_s, capture_end)
    lines = [
        f"Distinct Streams measurement {configuration} {run_id}.",
        "Network SRT is the producer ingress of the earliest post-handoff content Interest across configured streams.",
        "Per-stream rows are diagnostics and are not averaged into the network SRT.",
        "CLF counts only Data under that consumer's recorded stream prefix.",
        "RFV and NLSR reuse the Solution sender-egress classifiers. measure_run SRT and CLF are not the Distinct reference.",
        f"network_rows={len(network)} consumer_rows={len(consumer)} stream_diagnostic_rows={len(streams)}",
        f"capture_end={capture_end:.6f} final_observation_s={final_observation_s:.6f} shortfall_s={shortfall:.6f}",
    ]
    if shortfall > 0:
        lines.append(
            f"SHORTFALL {configuration} {run_id}: capture ends {shortfall:.6f} s before "
            "the last handoff plus the recorded final observation interval."
        )
    outside = [row for row in consumer if row["clf_outside_unit_interval"] == "true"]
    lines.append(f"clf_outside_unit_interval_rows={len(outside)}")
    for row in outside:
        lines.append(
            f"CLF_OUTSIDE_UNIT {row['configuration']} {row['run_id']} {row['consumer_identity']} "
            f"{row['stream_prefix']} h{row['handoff_index']} clf={row['content_loss_fraction']} "
            f"delivered={row['delivered_unique_content_frames']} nominal={row['nominal_frame_opportunities']}"
        )
    for row in network:
        if row["recovered"] == "false":
            lines.append(
                f"RIGHT_CENSORED {row['configuration']} {row['run_id']} h{row['handoff_index']} "
                f"boundary_ms={row['srt_censor_boundary_ms']}"
            )
    if problems:
        lines.append("measurement mismatches:")
        lines.extend(f"  {item}" for item in problems)
    else:
        lines.append("RFV and NLSR bytes, rates, and event boundaries matched measure_run.")
    return network, consumer, streams, lines, problems


def _write_run(
    population: str,
    run_id: str,
    network: Sequence[Dict[str, object]],
    consumer: Sequence[Dict[str, object]],
    streams: Sequence[Dict[str, object]],
    lines: Sequence[str],
) -> None:
    destination = OUTPUT / "runs" / population / run_id
    _write_csv(destination / "network_handoffs.csv", distinct.NETWORK_FIELDS, network)
    _write_csv(destination / "consumer_handoffs.csv", distinct.CONSUMER_FIELDS, consumer)
    _write_csv(destination / "stream_recovery_diagnostics.csv", distinct.STREAM_FIELDS, streams)
    (destination / "analysis_audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _campaign_audit(
    network: Sequence[Dict[str, object]],
    consumer: Sequence[Dict[str, object]],
    streams: Sequence[Dict[str, object]],
    run_lines: Sequence[str],
    problems: Sequence[str],
) -> str:
    lines = [
        "Exp2(b) Distinct Streams analysis.",
        "Outputs are under results/extended/exp2/distinct/analysis and do not replace Exp2(a).",
        "One network SRT per producer handoff. Per-stream diagnostics are not a replacement SRT.",
        "A positive CLF is not by itself evidence of transmitted Data loss.",
        f"network_rows={len(network)} consumer_rows={len(consumer)} stream_diagnostic_rows={len(streams)}",
    ]
    for configuration, network_expected, consumer_expected in (("N=2", 40, 80), ("N=4", 40, 160)):
        network_count = sum(1 for row in network if row["configuration"] == configuration)
        consumer_count = sum(1 for row in consumer if row["configuration"] == configuration)
        lines.append(
            f"{configuration}: network={network_count}/{network_expected} consumer={consumer_count}/{consumer_expected}"
        )
    lines.extend(distinct.unique_problems(network, consumer, streams))
    if len(network) != 80 or len(consumer) != 240:
        lines.append(f"ROW_COUNT network={len(network)}/80 consumer={len(consumer)}/240")
    lines.extend(run_lines)
    if problems:
        lines.append("FAILED")
        lines.extend(f"  {item}" for item in problems)
    else:
        lines.append("campaign checks passed")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--all"]:
        selected = [(population, run_id) for population in POPULATIONS for run_id in RUNS]
        aggregate = True
    elif len(arguments) == 2 and arguments[0] in POPULATIONS and arguments[1] in RUNS:
        selected = [(arguments[0], arguments[1])]
        aggregate = False
    else:
        print(
            "usage: run_exp2_distinct_analysis.py n2|n4 r1|r2|r3|r4|r5\n"
            "       run_exp2_distinct_analysis.py --all",
            file=sys.stderr,
        )
        return 2
    combined_network: List[Dict[str, object]] = []
    combined_consumer: List[Dict[str, object]] = []
    combined_streams: List[Dict[str, object]] = []
    run_lines: List[str] = []
    problems: List[str] = []
    for population, run_id in selected:
        print(f"measure distinct {population} {run_id}", flush=True)
        try:
            network, consumer, streams, lines, run_problems = measure_run(population, run_id)
        except (metrics.MobilityMetricError, config.Exp2ConfigError) as error:
            print(f"FAILED {population} {run_id}: {error}", flush=True)
            return 1
        problems.extend(run_problems)
        _write_run(population, run_id, network, consumer, streams, lines)
        combined_network.extend(network)
        combined_consumer.extend(consumer)
        combined_streams.extend(streams)
        run_lines.extend(lines)
        print(f"wrote {OUTPUT / 'runs' / population / run_id}", flush=True)
    if not aggregate:
        return 1 if problems else 0
    problems.extend(distinct.unique_problems(combined_network, combined_consumer, combined_streams))
    if len(combined_network) != 80 or len(combined_consumer) != 240:
        problems.append(f"expected 80 network and 240 consumer rows; got {len(combined_network)} and {len(combined_consumer)}")
    text = _campaign_audit(combined_network, combined_consumer, combined_streams, run_lines, problems)
    _write_csv(OUTPUT / "network_handoffs.csv", distinct.NETWORK_FIELDS, combined_network)
    _write_csv(OUTPUT / "consumer_handoffs.csv", distinct.CONSUMER_FIELDS, combined_consumer)
    _write_csv(OUTPUT / "stream_recovery_diagnostics.csv", distinct.STREAM_FIELDS, combined_streams)
    (OUTPUT / "analysis_audit.txt").write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}", flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
