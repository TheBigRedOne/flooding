#!/usr/bin/env python3
"""Unified Exp2-A scalability analysis. Does not start a VM or modify inputs."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import mobility_event_metrics as metrics
import run_mobility_event_analysis as decoder

import exp2_scale_metrics as scale
import exp2_shared_config as config
import plot_exp2_scale as plots

ROOT = Path(__file__).resolve().parents[2]
SOLUTION = ROOT / "results" / "solution"
EXP2 = ROOT / "results" / "extended" / "exp2" / "shared"
OUTPUT = ROOT / "results" / "extended" / "exp2" / "analysis"
RUNS = ("r1", "r2", "r3", "r4", "r5")
FLOAT_TOLERANCE = 1e-6
SOLUTION_FIELDS = (
    "recovered",
    "service_recovery_time_ms",
    "recovery_name",
    "producer_interest_time",
    "event_duration_s",
    "event_end_time",
    "handoff_time",
    "from_node",
    "to_node",
    "recovery_flood_bytes",
    "recovery_interest_flood_bytes",
    "recovery_data_flood_bytes",
    "nlsr_control_bytes",
    "nlsr_control_rate_bytes_per_s",
)
CONSUMER_COMPARE = (
    "content_loss_fraction",
    "delivered_unique_content_frames",
    "nominal_frame_opportunities",
)


def _consumers_for(population: str) -> Tuple[Tuple[str, str, str], ...]:
    if population == "N=1":
        return (("consumer", "C1", "acc1"),)
    active = config.parse_active_consumers("n2" if population == "N=2" else "n4")
    return tuple((host, "C" + host.replace("consumer", ""), config.CONSUMER_ATTACHMENT[host]) for host in active)


def _load_solution_packets(run_id: str) -> Tuple[List[metrics.Packet], List[metrics.Handoff], int, int]:
    run_dir = SOLUTION / run_id
    packets_path = run_dir / "mobility_packets.csv"
    if not packets_path.is_file():
        raise metrics.MobilityMetricError(f"missing decoded Solution packets: {packets_path}")
    _segments, interval = metrics.load_run_config(str(run_dir / "params.txt"))
    pcaps = list((run_dir / "pcap_nodes").glob("*.pcap"))
    return (
        metrics.load_packets(str(packets_path)),
        metrics.load_handoffs(str(run_dir / "handoffs.txt")),
        interval,
        len(pcaps),
    )


def _load_exp2_packets(population: str, run_id: str) -> Tuple[List[metrics.Packet], List[metrics.Handoff], int, int]:
    folder = "n2" if population == "N=2" else "n4"
    run_dir = EXP2 / folder / run_id
    decoded = OUTPUT / "packets" / folder / run_id / "mobility_packets.csv"
    if not decoded.is_file() or decoded.stat().st_size == 0:
        decoded.parent.mkdir(parents=True, exist_ok=True)
        decoder.decode_run(run_dir, decoded)
    _segments, interval = metrics.load_run_config(str(run_dir / "params.txt"))
    recorded = config.read_active_consumers(run_dir / "params.txt")
    expected = config.parse_active_consumers(folder)
    if recorded != expected:
        raise metrics.MobilityMetricError(f"{run_dir} active consumers {recorded} != {expected}")
    pcaps = list((run_dir / "pcap_nodes").glob("*.pcap"))
    return metrics.load_packets(str(decoded)), metrics.load_handoffs(str(run_dir / "handoffs.txt")), interval, len(pcaps)


def _close(left: object, right: object) -> bool:
    if left == "" or right == "" or left is None or right is None:
        return str(left) == str(right)
    return abs(float(str(left)) - float(str(right))) <= FLOAT_TOLERANCE


def _compare_solution(
    run_id: str,
    fresh_network: Sequence[Dict[str, object]],
    fresh_consumer: Sequence[Dict[str, object]],
    reference_packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    frame_period_ms: int,
) -> List[str]:
    stored_path = SOLUTION / run_id / "mobility_events.csv"
    stored = list(csv.DictReader(stored_path.open(encoding="utf-8", newline="")))
    reference = metrics.measure_run(
        reference_packets, handoffs, "OptoFlood", "solution", run_id, frame_period_ms=frame_period_ms,
    )
    problems = []
    if len(stored) != 8 or len(fresh_network) != 8 or len(reference) != 8 or len(fresh_consumer) != 8:
        problems.append(
            f"{run_id}: row counts stored={len(stored)} network={len(fresh_network)} "
            f"reference={len(reference)} consumer={len(fresh_consumer)}"
        )
        return problems
    for index, (ours, old, ref) in enumerate(zip(fresh_network, stored, reference), start=1):
        for field in SOLUTION_FIELDS:
            if field in ("recovery_flood_bytes", "recovery_interest_flood_bytes", "recovery_data_flood_bytes", "nlsr_control_bytes"):
                if int(str(ours[field])) != int(float(str(old[field]))) or int(str(ours[field])) != int(str(ref[field])):
                    problems.append(f"{run_id} h{index} {field}: new={ours[field]} stored={old[field]} reference={ref[field]}")
            elif field == "recovered":
                stored_flag = str(old[field]) in ("True", "true", "1")
                reference_flag = bool(ref[field])
                if (ours[field] == "true") != stored_flag or (ours[field] == "true") != reference_flag:
                    problems.append(f"{run_id} h{index} recovered: new={ours[field]} stored={old[field]} reference={ref[field]}")
            elif field in ("recovery_name", "from_node", "to_node"):
                if str(ours[field]) != str(old[field]) or str(ours[field]) != str(ref[field]):
                    problems.append(f"{run_id} h{index} {field}: new={ours[field]} stored={old[field]} reference={ref[field]}")
            elif not _close(ours[field], old[field]) or not _close(ours[field], ref[field]):
                problems.append(f"{run_id} h{index} {field}: new={ours[field]} stored={old[field]} reference={ref[field]}")
        consumer = fresh_consumer[index - 1]
        for field in CONSUMER_COMPARE:
            if field == "delivered_unique_content_frames":
                if int(str(consumer[field])) != int(float(str(old[field]))) or int(str(consumer[field])) != int(str(ref[field])):
                    problems.append(f"{run_id} h{index} {field}: new={consumer[field]} stored={old[field]} reference={ref[field]}")
            elif not _close(consumer[field], old[field]) or not _close(consumer[field], ref[field]):
                problems.append(f"{run_id} h{index} {field}: new={consumer[field]} stored={old[field]} reference={ref[field]}")
        if int(str(ours["eligible_consumer_witnesses"])) != (1 if ours["recovered"] == "true" else 0):
            problems.append(f"{run_id} h{index} N=1 witness count {ours['eligible_consumer_witnesses']}")
        if ours["recovered"] == "true" and ours["srt_attribution"] != "unique":
            problems.append(f"{run_id} h{index} N=1 attribution {ours['srt_attribution']}")
    return problems


def _compare_overhead(
    population: str,
    run_id: str,
    network: Sequence[Dict[str, object]],
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    frame_period_ms: int,
) -> List[str]:
    reference = metrics.measure_run(packets, handoffs, population, population, run_id, frame_period_ms=frame_period_ms)
    problems = []
    for index, (ours, ref) in enumerate(zip(network, reference), start=1):
        for field in (
            "recovery_flood_bytes",
            "recovery_interest_flood_bytes",
            "recovery_data_flood_bytes",
            "nlsr_control_bytes",
        ):
            if int(str(ours[field])) != int(str(ref[field])):
                problems.append(f"{population} {run_id} h{index} {field}: new={ours[field]} reference={ref[field]}")
        for field in ("event_duration_s", "event_end_time", "nlsr_control_rate_bytes_per_s"):
            if not _close(ours[field], ref[field]):
                problems.append(f"{population} {run_id} h{index} {field}: new={ours[field]} reference={ref[field]}")
    return problems


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _audit(
    network: Sequence[Dict[str, object]],
    consumer: Sequence[Dict[str, object]],
    regression: Sequence[str],
    overhead: Sequence[str],
) -> str:
    lines = [
        "Exp2-A scalability analysis.",
        "SRT, CLF, RFV, and NLSR accounting use the Solution measurement rules.",
        "Name/time matching is an operational rule. It is not cryptographic proof of which Consumer transmission reached the Producer.",
        "N=1 packets were read from the existing Solution mobility_packets.csv files.",
        "N=2 and N=4 packets were decoded into this analysis directory.",
        f"network_rows={len(network)} consumer_rows={len(consumer)}",
    ]
    for configuration, network_expected, consumer_expected in (("N=1", 40, 40), ("N=2", 40, 80), ("N=4", 40, 160)):
        network_count = sum(1 for row in network if row["configuration"] == configuration)
        consumer_count = sum(1 for row in consumer if row["configuration"] == configuration)
        recovered = sum(1 for row in network if row["configuration"] == configuration and row["recovered"] == "true")
        censored = sum(1 for row in network if row["configuration"] == configuration and row["recovered"] == "false")
        ambiguous = sum(1 for row in network if row["configuration"] == configuration and row["srt_attribution"] == "ambiguous")
        lines.append(
            f"{configuration}: network={network_count}/{network_expected} consumer={consumer_count}/{consumer_expected} "
            f"srt_recovered={recovered} srt_censored={censored} srt_ambiguous={ambiguous}"
        )
    network_keys = {(row["configuration"], row["run_id"], row["handoff_index"]) for row in network}
    consumer_keys = {(row["configuration"], row["run_id"], row["handoff_index"], row["consumer_identity"]) for row in consumer}
    lines.append(f"unique_network_keys={len(network_keys)} unique_consumer_keys={len(consumer_keys)}")
    if regression:
        lines.append("N=1 regression mismatches:")
        lines.extend(f"  {item}" for item in regression)
    else:
        lines.append("N=1 regression: r1 r2 r3 r4 r5 matched stored mobility_events.csv and measure_run.")
    if overhead:
        lines.append("RFV/NLSR reference mismatches:")
        lines.extend(f"  {item}" for item in overhead)
    else:
        lines.append("RFV and NLSR bytes, rates, and event boundaries matched measure_run for every run.")
    invalid = [row for row in consumer if row["invalid_duration"] == "true"]
    outside = [row for row in consumer if row["clf_outside_unit_interval"] == "true"]
    lines.append(f"invalid_duration_rows={len(invalid)} clf_outside_unit_interval_rows={len(outside)}")
    for row in outside:
        lines.append(
            f"CLF_OUTSIDE_UNIT {row['configuration']} {row['run_id']} {row['consumer_identity']} "
            f"h{row['handoff_index']} clf={row['content_loss_fraction']} "
            f"delivered={row['delivered_unique_content_frames']} nominal={row['nominal_frame_opportunities']}"
        )
    for row in network:
        if row["recovered"] == "false":
            lines.append(
                f"RIGHT_CENSORED {row['configuration']} {row['run_id']} h{row['handoff_index']} "
                f"boundary_ms={row['srt_censor_boundary_ms']}"
            )
        elif row["srt_attribution"] == "ambiguous":
            lines.append(
                f"AMBIGUOUS_SRT {row['configuration']} {row['run_id']} h{row['handoff_index']} "
                f"witnesses={row['eligible_consumer_witnesses']} name={row['recovery_name']} "
                f"srt_ms={row['service_recovery_time_ms']}"
            )
    by_consumer: Dict[Tuple[str, str], List[float]] = {}
    for row in consumer:
        if row["content_loss_fraction"] == "":
            continue
        by_consumer.setdefault((str(row["configuration"]), str(row["consumer_identity"])), []).append(
            float(str(row["content_loss_fraction"]))
        )
    for key in sorted(by_consumer):
        values = by_consumer[key]
        lines.append(
            f"CLF {key[0]} {key[1]}: n={len(values)} min={min(values):.6g} max={max(values):.6g} "
            f"zero_delivery={sum(1 for row in consumer if row['configuration']==key[0] and row['consumer_identity']==key[1] and row['zero_delivery']=='true')}"
        )
    lines.append(
        "Nominal frame opportunities use the recorded 20 ms request interval. "
        "A positive CLF is not by itself evidence of network loss."
    )
    lines.append(
        "N=1 has 11 captured nodes, N=2 has 12, and N=4 has 14. "
        "NLSR byte totals include every captured NLSR speaker."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    network: List[Dict[str, object]] = []
    consumer: List[Dict[str, object]] = []
    regression: List[str] = []
    overhead: List[str] = []
    for run_id in RUNS:
        print(f"measure N=1 {run_id}", flush=True)
        packets, handoffs, interval, captures = _load_solution_packets(run_id)
        net, cons = scale.measure_events(
            packets, handoffs, "N=1", run_id, _consumers_for("N=1"), interval, captures,
        )
        regression.extend(_compare_solution(run_id, net, cons, packets, handoffs, interval))
        overhead.extend(_compare_overhead("N=1", run_id, net, packets, handoffs, interval))
        network.extend(net)
        consumer.extend(cons)
        del packets
    if regression:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "analysis_audit.txt").write_text(
            "N=1 regression failed. N=2/N=4 metrics and figures were not produced.\n"
            + "\n".join(regression)
            + "\n",
            encoding="utf-8",
        )
        print(f"N=1 regression failed with {len(regression)} mismatches", flush=True)
        return 1
    for population in ("N=2", "N=4"):
        for run_id in RUNS:
            print(f"measure {population} {run_id}", flush=True)
            packets, handoffs, interval, captures = _load_exp2_packets(population, run_id)
            net, cons = scale.measure_events(
                packets, handoffs, population, run_id, _consumers_for(population), interval, captures,
            )
            overhead.extend(_compare_overhead(population, run_id, net, packets, handoffs, interval))
            network.extend(net)
            consumer.extend(cons)
            del packets
    network = scale.sort_network(network)
    consumer = scale.sort_consumer(consumer)
    if len(network) != 120 or len(consumer) != 280:
        raise metrics.MobilityMetricError(f"unexpected table sizes network={len(network)} consumer={len(consumer)}")
    if overhead:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "analysis_audit.txt").write_text(
            "RFV or NLSR reference comparison failed. Figures were not produced.\n"
            + "\n".join(overhead)
            + "\n",
            encoding="utf-8",
        )
        print(f"overhead comparison failed with {len(overhead)} mismatches", flush=True)
        return 1
    _write_csv(OUTPUT / "network_handoffs.csv", scale.NETWORK_FIELDS, network)
    _write_csv(OUTPUT / "consumer_handoffs.csv", scale.CONSUMER_FIELDS, consumer)
    text = _audit(network, consumer, regression, overhead)
    (OUTPUT / "analysis_audit.txt").write_text(text, encoding="utf-8")
    plots.write_figures(str(OUTPUT), network, consumer)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
