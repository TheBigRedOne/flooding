#!/usr/bin/env python3
"""Synthetic Exp3 metric checks. No PCAPs, VMs, or scientific claims."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp2_distinct_metrics as distinct
import exp3_config as config
import exp3_metrics as exp3
import mobility_event_metrics as metrics
import plot_exp3
import run_exp3_analysis as runner
import run_mobility_event_analysis as decoder

ROOT = Path(__file__).resolve().parents[2]

ORIGIN = 1_700_000_000.0
V0 = "/LiveStream/v0/54=%30/50=%00"
V0_ALT = "/LiveStream/v0/54=0/50=%00"
V0_NEXT = "/LiveStream/v0/54=%02/50=%00"
V1 = "/LiveStream/v1/54=%03/50=%00"
V2 = "/LiveStream/v2/54=%04/50=%00"
V3 = "/LiveStream/v3/54=%05/50=%00"
NOT_V0 = "/LiveStream/54=v0/54=%01/50=%00"
GUARD = "/LiveStream/v0/_guard"
META = "/LiveStream/v0/_meta"
NLSR = "/ndn/nlsr/update"
MANAGEMENT = "/localhost/nfd/faces/list"


def _packet(time_s: float, node: str, outbound: bool, ptype: str, name: str, length: int = 100, **flags: bool) -> metrics.Packet:
    return metrics.Packet(
        time_s, node, outbound, ptype, name, length, False,
        flags.get("decoder_data_flood", False),
        flags.get("interest_hop_limit", False),
        flags.get("data_lp_hop_limit", False),
        flags.get("data_mobility_flag", False),
    )


def _records(population: int):
    rows = []
    endpoints = {}
    for pair in config.pairs_for(population):
        start = 100.0 + pair.index
        rels = [start + offset * 10.0 for offset in range(8)]
        end_rel = rels[-1] + 30.0 + pair.index * 10.0
        endpoints[pair.producer] = (end_rel, ORIGIN + end_rel)
        for index, rel in enumerate(rels, start=1):
            planned = rel - 0.25
            rows.append({
                "producer": pair.producer,
                "index": str(index),
                "abs_time": str(ORIGIN + rel),
                "rel_time": str(rel),
                "from_node": "acc2",
                "to_node": "acc3",
                "interval_s": "10",
                "planned_rel_s": str(planned),
                "lateness_s": str(rel - planned),
            })
    common = max(item[0] for item in endpoints.values())
    return rows, endpoints, common


def _context(population: int, run_id: str = "r1", frame_period_ms: int = 20) -> exp3.RunContext:
    rows, endpoints, common = _records(population)
    return exp3.RunContext(
        configuration=config.CAMPAIGN_ID,
        population=exp3.population_label(population),
        population_count=population,
        run_id=run_id,
        run_seed="1",
        source_kind=exp3.source_kind_for(run_id),
        origin_abs=ORIGIN,
        common_end_s=common,
        frame_period_ms=frame_period_ms,
        windows=exp3.build_event_windows(population, rows, endpoints, ORIGIN, common),
    )


def _window(context: exp3.RunContext, producer: str, index: int) -> exp3.EventWindow:
    return next(item for item in context.windows if item.producer == producer and item.index == index)


def _row(measurement: exp3.Measurement, producer: str, index: int) -> dict:
    return next(row for row in measurement.events if row["producer"] == producer and row["handoff_index"] == str(index))


def _packet_from_row(row: dict):
    name = metrics.canonical_name(row.get("ndn.name") or "")
    if not name or name == "/":
        return None
    try:
        timestamp = float(row["frame.time_epoch"])
        length = int(float(row["frame.len"]))
    except (KeyError, TypeError, ValueError):
        return None
    ptype = (row.get("ndn.type") or "").strip().lower()
    hop = bool((row.get("ndn.hoplimit") or "").strip())
    lp_hop = bool((row.get("ndn.lp.hoplimit") or "").strip())
    mobility = bool((row.get("ndn.lp.mobility_flag") or "").strip())
    flood_id = bool((row.get("ndn.flood_id") or "").strip())
    packet = metrics.Packet(
        timestamp, (row.get("node") or "").strip(), metrics.is_sender_egress(row.get("sll.pkttype") or ""),
        ptype, name, length, ptype == "interest" and hop, ptype == "data" and (lp_hop or mobility or flood_id),
        hop, lp_hop, mobility,
    )
    return packet, ((row.get("node") or "").strip(), (row.get("frame.number") or "").strip(), (row.get("sll.pkttype") or "").strip())


def _count_window(path: Path, recorded: dict) -> tuple:
    start = float(recorded["window_start_abs"])
    end = float(recorded["window_end_abs"])
    inclusive = recorded["window_inclusive_end"] == "true"
    prefix = recorded["prefix"]
    seen = set()
    count = 0
    total = 0
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            parsed = _packet_from_row(row)
            if parsed is None:
                continue
            packet, identity = parsed
            if identity[1] and identity in seen:
                continue
            if identity[1]:
                seen.add(identity)
            if packet.time < start or (packet.time > end if inclusive else packet.time >= end):
                continue
            hit = exp3.attribute_flood(packet, (prefix,))
            if hit is None or hit.detail not in {"interest", "guard-data", "content-data", "other-data"}:
                continue
            count += 1
            total += packet.length
    return count, total


def _count_network(path: Path, origin: float, end: float, windows: list) -> tuple:
    bounds = [
        (float(row["window_start_abs"]), float(row["window_end_abs"]), row["window_inclusive_end"] == "true", row["prefix"])
        for row in windows
    ]
    seen = set()
    inside = [0, 0]
    outside = [0, 0]
    interest_outside = [0, 0]
    prefixes = ("/LiveStream/v0", "/LiveStream/v1", "/LiveStream/v2", "/LiveStream/v3")
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            parsed = _packet_from_row(row)
            if parsed is None:
                continue
            packet, identity = parsed
            if packet.time < origin or packet.time > end:
                continue
            if identity[1] and identity in seen:
                continue
            if identity[1]:
                seen.add(identity)
            hit = exp3.attribute_flood(packet, prefixes)
            if hit is None:
                continue
            prefix = hit.prefixes[0] if hit.prefixes else ""
            matched = False
            if prefix:
                for start, stop, inclusive, window_prefix in bounds:
                    if window_prefix != prefix or packet.time < start:
                        continue
                    if packet.time <= stop if inclusive else packet.time < stop:
                        matched = True
                        break
            if matched:
                inside[0] += 1
                inside[1] += packet.length
            else:
                outside[0] += 1
                outside[1] += packet.length
                if hit.detail in {"interest", "unassigned-interest"}:
                    interest_outside[0] += 1
                    interest_outside[1] += packet.length
    return tuple(inside), tuple(outside), tuple(interest_outside)


def _flood(measurement: exp3.Measurement, producer: str, index: int) -> dict:
    return next(row for row in measurement.prefix_rfv if row["producer"] == producer and row["handoff_index"] == str(index))


def _write_run(root: Path, population: str, run_id: str, frame_period_ms: int = 20) -> Path:
    count = int(population[1:])
    rows, endpoints, common = _records(count)
    run_dir = root / population / run_id
    run_dir.mkdir(parents=True)
    with (run_dir / "handoffs.txt").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s"
            "\tplanned_rel_s\tlateness_s\n"
        )
        for row in rows:
            handle.write("\t".join(row[key] for key in (
                "producer", "index", "abs_time", "rel_time", "from_node", "to_node",
                "interval_s", "planned_rel_s", "lateness_s",
            )) + "\n")
    with (run_dir / "observation_ends.txt").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("producer\tindex\trel_end_s\tabs_end\n")
        for pair in config.pairs_for(count):
            rel, absolute = endpoints[pair.producer]
            handle.write(f"{pair.producer}\t{pair.index}\t{rel}\t{absolute}\n")
    lines = [
        f"exp3_campaign={config.CAMPAIGN_ID}",
        f"exp3_population={population}",
        "exp3_schedule=full",
        f"exp3_run_id={run_id}",
        "exp3_run_seed=1",
        f"common_end_s={common}",
        f"mobility_clock_origin_abs={ORIGIN}",
        "segments_per_frame=1",
        f"request_interval_ms={frame_period_ms}",
    ]
    for pair in config.pairs_for(count):
        lines.append(f"producer{pair.index}_prefix={pair.prefix}")
    (run_dir / "params.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return run_dir


class Exp3WindowTest(unittest.TestCase):
    def test_event_counts_and_same_producer_windows_do_not_overlap(self) -> None:
        for population, expected in ((1, 8), (2, 16), (4, 32)):
            context = _context(population)
            self.assertEqual(len(context.windows), expected)
            self.assertEqual(len(context.windows), exp3.expected_handoff_count(population))
            own = [item for item in context.windows if item.producer == "producer1"]
            self.assertEqual([item.index for item in own], list(range(1, 9)))
            for earlier, later in zip(own, own[1:]):
                self.assertEqual(earlier.window_end_abs, later.abs_time)
                self.assertFalse(earlier.inclusive_end)
                self.assertLess(earlier.abs_time, earlier.window_end_abs)
            self.assertTrue(own[-1].inclusive_end)
            self.assertGreater(own[-1].window_end_abs, own[-1].abs_time)

    def test_other_producer_handoff_does_not_end_the_window(self) -> None:
        context = _context(2)
        first = _window(context, "producer1", 1)
        other = _window(context, "producer2", 1)
        self.assertGreater(other.abs_time, first.abs_time)
        self.assertLess(other.abs_time, first.window_end_abs)
        self.assertNotEqual(first.window_end_abs, other.abs_time)
        self.assertLess(first.planned_end_abs, _window(context, "producer2", 8).planned_end_abs)

    def test_boundary_inclusion_matches_solution_intervals(self) -> None:
        context = _context(1)
        first = _window(context, "producer1", 1)
        second = _window(context, "producer1", 2)
        final = _window(context, "producer1", 8)
        boundary = _packet(second.abs_time, "producer1", True, "interest", V0, 10, interest_hop_limit=True)
        at_end = _packet(final.window_end_abs, "producer1", True, "interest", V0, 21, interest_hop_limit=True)
        after_end = _packet(final.window_end_abs + 1.0, "producer1", True, "interest", V0, 99, interest_hop_limit=True)
        measured = exp3.measure_run([boundary, at_end, after_end], context)
        self.assertEqual(int(_flood(measured, "producer1", 1)["prefix_rfv_bytes"]), 0)
        self.assertEqual(int(_flood(measured, "producer1", 2)["prefix_rfv_bytes"]), 10)
        self.assertEqual(int(_flood(measured, "producer1", 8)["prefix_rfv_bytes"]), 21)
        self.assertEqual(int(_flood(measured, "producer1", 1)["prefix_rfv_packets"]), 0)
        self.assertEqual(int(_flood(measured, "producer1", 2)["prefix_rfv_packets"]), 1)
        self.assertEqual(int(_flood(measured, "producer1", 8)["prefix_rfv_packets"]), 1)
        self.assertEqual(int(measured.network[0]["network_rfv_bytes"]), 31)
        self.assertEqual(int(measured.network[0]["network_rfv_packets"]), 2)
        self.assertIn("not shortened or extended to the latest packet", measured.audit)

    def test_invalid_boundaries_fail_instead_of_following_the_last_packet(self) -> None:
        rows, endpoints, common = _records(1)
        rows[-1]["abs_time"] = str(endpoints["producer1"][1])
        rows[-1]["rel_time"] = str(endpoints["producer1"][0])
        with self.assertRaises(exp3.Exp3AnalysisError):
            exp3.build_event_windows(1, rows, endpoints, ORIGIN, common)
        legacy = Path(tempfile.mkdtemp()) / "handoffs.txt"
        legacy.write_text("producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n", encoding="utf-8")
        with self.assertRaises(exp3.Exp3AnalysisError):
            exp3.load_handoff_rows(legacy)

    def test_recorded_frame_period_is_used_for_the_full_window(self) -> None:
        context = _context(1, frame_period_ms=40)
        first = _window(context, "producer1", 1)
        early = _packet(first.abs_time + 0.01, "consumer1", False, "data", V0)
        measured = exp3.measure_run([early], context)
        row = _row(measured, "producer1", 1)
        duration = first.duration_s
        self.assertAlmostEqual(float(row["window_duration_s"]), duration)
        self.assertAlmostEqual(float(row["nominal_frame_opportunities"]), duration * 1000.0 / 40.0)
        self.assertGreater(float(row["nominal_frame_opportunities"]), 1.0)
        self.assertEqual(row["frame_period_ms"], "40")


class Exp3MetricTest(unittest.TestCase):
    def test_solution_classifiers_and_typed_prefix_selection(self) -> None:
        self.assertTrue(metrics.is_useful_content(V0))
        self.assertFalse(metrics.is_useful_content(V1))
        self.assertEqual(metrics.content_frame_id(V1), "")
        self.assertTrue(distinct.is_stream_content(V1, "/LiveStream/v1"))
        self.assertFalse(exp3.name_has_prefix(NOT_V0, "/LiveStream/v0"))
        self.assertTrue(metrics.names_equal(V0, V0_ALT))
        interest = _packet(0, "core", True, "interest", V0, interest_hop_limit=True)
        guarded = _packet(0, "core", True, "data", GUARD, data_mobility_flag=True)
        marked = _packet(0, "core", True, "data", V0, data_lp_hop_limit=True)
        flood_id_only = _packet(0, "core", True, "data", V0, decoder_data_flood=True)
        self.assertTrue(metrics.is_recovery_interest_flood(interest))
        self.assertTrue(metrics.is_recovery_data_flood(guarded))
        self.assertTrue(metrics.is_recovery_data_flood(marked))
        self.assertFalse(metrics.is_recovery_data_flood(flood_id_only))
        self.assertEqual(exp3.attribute_flood(interest, ("/LiveStream/v0",)).detail, "interest")
        self.assertEqual(exp3.attribute_flood(guarded, ("/LiveStream/v0",)).detail, "guard-data")
        self.assertEqual(exp3.attribute_flood(marked, ("/LiveStream/v0",)).detail, "content-data")
        self.assertIsNone(exp3.attribute_flood(flood_id_only, ("/LiveStream/v0",)))
        ambiguous = "/LiveStream/v0/extra/54=%01/50=%00"
        hit = exp3.attribute_flood(
            _packet(0, "core", True, "data", ambiguous, data_mobility_flag=True),
            ("/LiveStream/v0", "/LiveStream/v0/extra"),
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.detail, "ambiguous")

    def test_srt_matches_the_paired_prefix_and_keeps_censored_rows(self) -> None:
        context = _context(2)
        first = _window(context, "producer1", 1)
        second = _window(context, "producer2", 1)
        packets = [
            _packet(first.abs_time, "consumer1", True, "interest", V0),
            _packet(first.abs_time + 0.2, "consumer1", True, "interest", V1),
            _packet(first.abs_time + 0.25, "producer1", False, "interest", V1),
            _packet(first.abs_time + 0.4, "consumer1", True, "interest", V0_ALT),
            _packet(first.abs_time + 0.9, "producer1", False, "interest", V0),
            _packet(first.abs_time + 0.5, "acc2", False, "interest", V0),
            _packet(second.abs_time + 0.2, "consumer2", True, "interest", V1),
            _packet(second.abs_time + 0.5, "producer2", False, "interest", V1),
            _packet(second.abs_time + 0.1, "consumer1", True, "interest", V1),
            _packet(second.abs_time + 0.15, "producer1", False, "interest", V1),
        ]
        measured = exp3.measure_run(packets, context)
        self.assertEqual(len(measured.events), 16)
        recovered = _row(measured, "producer1", 1)
        self.assertEqual(recovered["recovery_status"], "recovered")
        self.assertAlmostEqual(float(recovered["service_recovery_time_s"]), 0.9, delta=1e-4)
        self.assertAlmostEqual(float(recovered["service_recovery_time_ms"]), 900.0, delta=1e-1)
        self.assertEqual(recovered["recovery_name"], metrics.canonical_name(V0))
        self.assertEqual(recovered["service_recovery_time_ms"] != "0", True)
        other = _row(measured, "producer2", 1)
        self.assertAlmostEqual(float(other["service_recovery_time_s"]), 0.5, delta=1e-4)
        censored = _row(measured, "producer1", 2)
        self.assertEqual(censored["recovery_status"], "right-censored")
        self.assertEqual(censored["service_recovery_time_s"], "")
        self.assertEqual(censored["service_recovery_time_ms"], "")
        self.assertNotEqual(censored["srt_censor_time_s"], "")
        self.assertEqual(censored["srt_censor_boundary"], "next-handoff-of-same-producer")
        final = _row(measured, "producer1", 8)
        self.assertEqual(final["srt_censor_boundary"], "planned-observation-endpoint")
        run_summary = next(row for row in measured.summary if row["summary_scope"] == "run")
        self.assertEqual(run_summary["n_handoffs"], "16")
        self.assertEqual(run_summary["n_recovered"], "2")
        self.assertEqual(run_summary["n_censored"], "14")
        self.assertEqual(run_summary["srt_median_scope"], exp3.CONDITIONAL_SRT)
        self.assertNotIn("0", (censored["service_recovery_time_ms"],))

    def test_exact_handoff_interest_is_not_recovery_for_either_adjacent_window(self) -> None:
        context = _context(1)
        second = _window(context, "producer1", 2)
        packets = [
            _packet(second.abs_time, "consumer1", True, "interest", V0),
            _packet(second.abs_time + 0.01, "producer1", False, "interest", V0),
        ]
        measured = exp3.measure_run(packets, context)
        self.assertEqual(_row(measured, "producer1", 1)["recovery_status"], "right-censored")
        self.assertEqual(_row(measured, "producer1", 2)["recovery_status"], "right-censored")

    def test_consumer_specific_clf_counts_distinct_typed_frames_without_clipping(self) -> None:
        context = _context(4, frame_period_ms=20)
        first = _window(context, "producer1", 1)
        base = first.abs_time + 1.0
        packets = [
            _packet(base, "consumer1", False, "data", V0),
            _packet(base + 0.1, "consumer1", False, "data", V0_ALT),
            _packet(base + 0.2, "consumer1", False, "data", V0_NEXT),
            _packet(base + 0.3, "consumer1", False, "data", V1),
            _packet(base + 0.4, "consumer1", False, "data", V2),
            _packet(base + 0.5, "consumer1", False, "data", V3),
            _packet(base + 0.6, "consumer2", False, "data", V0),
            _packet(base + 0.7, "consumer1", True, "data", V0_NEXT),
        ]
        measured = exp3.measure_run(packets, context)
        row = _row(measured, "producer1", 1)
        nominal = first.duration_s * 1000.0 / 20.0
        self.assertEqual(int(row["delivered_unique_content_frames"]), 2)
        self.assertAlmostEqual(float(row["nominal_frame_opportunities"]), nominal)
        self.assertAlmostEqual(float(row["content_loss_fraction"]), 1.0 - (2.0 / nominal))
        self.assertEqual(row["clf_outside_unit_interval"], "false")
        self.assertEqual(int(_row(measured, "producer2", 1)["delivered_unique_content_frames"]), 0)
        wide = _context(1, frame_period_ms=200000)
        sample = _window(wide, "producer1", 1)
        overflow = exp3.measure_run([
            _packet(sample.abs_time + 0.2, "consumer1", False, "data", V0),
        ], wide)
        outside = _row(overflow, "producer1", 1)
        self.assertLess(float(outside["content_loss_fraction"]), 0.0)
        self.assertEqual(outside["clf_outside_unit_interval"], "true")

    def test_prefix_and_network_flood_are_counted_once(self) -> None:
        context = _context(2)
        first = _window(context, "producer1", 1)
        other = _window(context, "producer2", 1)
        final = _window(context, "producer1", 8)
        at = first.abs_time + 1.0
        packets = [
            _packet(at, "core", True, "interest", V0, 100, interest_hop_limit=True),
            _packet(at, "core", False, "interest", V0, 500, interest_hop_limit=True),
            _packet(at, "agg1", True, "data", GUARD, 40, data_mobility_flag=True),
            _packet(at, "agg1", True, "data", V0, 70, data_lp_hop_limit=True),
            _packet(at, "agg1", True, "data", META, 15, data_mobility_flag=True),
            _packet(at, "agg1", True, "data", V0, 999, decoder_data_flood=True),
            _packet(at, "core", True, "interest", V1, 80, interest_hop_limit=True),
            _packet(ORIGIN + 50.0, "core", True, "interest", V0, 33, interest_hop_limit=True),
            _packet(ORIGIN + 50.0, "core", True, "interest", "/LiveStream/v9/54=%09/50=%00", 44, interest_hop_limit=True),
            _packet(final.window_end_abs + 1.0, "core", True, "interest", V0, 17, interest_hop_limit=True),
            _packet(at, "core", True, "interest", NLSR, 60),
            _packet(at, "core", False, "interest", NLSR, 60),
            _packet(at, "core", True, "interest", MANAGEMENT, 60),
        ]
        measured = exp3.measure_run(packets, context)
        own = _flood(measured, "producer1", 1)
        self.assertEqual(int(own["flood_interest_bytes"]), 100)
        self.assertEqual(int(own["flood_guard_data_bytes"]), 40)
        self.assertEqual(int(own["flood_content_data_bytes"]), 70)
        self.assertEqual(int(own["flood_other_data_bytes"]), 15)
        self.assertEqual(int(own["prefix_rfv_bytes"]), 225)
        self.assertEqual(int(own["flood_interest_packets"]), 1)
        self.assertEqual(int(own["flood_guard_data_packets"]), 1)
        self.assertEqual(int(own["flood_content_data_packets"]), 1)
        self.assertEqual(int(own["flood_other_data_packets"]), 1)
        self.assertEqual(int(own["prefix_rfv_packets"]), 4)
        self.assertEqual(int(_flood(measured, "producer2", 1)["prefix_rfv_bytes"]), 80)
        self.assertEqual(int(_flood(measured, "producer2", 1)["prefix_rfv_packets"]), 1)
        self.assertEqual(int(_flood(measured, "producer1", 2)["prefix_rfv_bytes"]), 0)
        prefix_sum = sum(int(row["prefix_rfv_bytes"]) for row in measured.prefix_rfv)
        network = measured.network[0]
        self.assertEqual(prefix_sum, 305)
        self.assertEqual(int(network["network_rfv_bytes"]), 305 + 33 + 44 + 17)
        self.assertEqual(int(network["unassigned_flood_bytes"]), 44)
        self.assertEqual(int(network["assigned_flood_outside_event_windows_bytes"]), 33 + 17)
        self.assertEqual(int(network["network_rfv_packets"]), 8)
        self.assertEqual(int(network["unassigned_flood_packets"]), 1)
        self.assertEqual(int(network["assigned_flood_outside_event_windows_packets"]), 2)
        self.assertEqual(int(network["flood_interest_packets"]), 5)
        self.assertEqual(int(network["flood_data_packets"]), 3)
        self.assertEqual(int(network["nlsr_control_bytes"]), 60)
        self.assertEqual(network["population_multiplier_applied"], "false")
        self.assertNotEqual(int(network["network_rfv_bytes"]), prefix_sum)
        self.assertNotEqual(int(network["network_rfv_bytes"]), 60 * context.population_count)
        diagnostic = sum(int(row["event_window_nlsr_bytes_diagnostic"]) for row in measured.prefix_rfv)
        self.assertGreater(diagnostic, 60)
        self.assertEqual(int(own["event_window_nlsr_bytes_diagnostic"]), 60)
        self.assertEqual(int(_flood(measured, "producer2", 1)["event_window_nlsr_bytes_diagnostic"]), 60)
        self.assertTrue(first.abs_time < at < first.window_end_abs)
        self.assertTrue(other.abs_time <= at < other.window_end_abs)
        self.assertEqual(own["nlsr_diagnostic_is_network_total"], "false")
        self.assertIn("not multiplied by the producer population", measured.audit)

    def test_decoder_duplicate_rows_are_one_transmission(self) -> None:
        context = _context(1)
        first = _window(context, "producer1", 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "packets.csv"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.DictWriter(handle, fieldnames=decoder.PACKET_HEADER, lineterminator="\n")
                writer.writeheader()
                base = {
                    "node": "core",
                    "frame.number": "7",
                    "frame.time_epoch": str(first.abs_time + 1.0),
                    "frame.len": "100",
                    "sll.pkttype": "4",
                    "sll.ifindex": "1",
                    "ndn.type": "interest",
                    "ndn.name": V0,
                    "ndn.flood_id": "",
                    "ndn.new_face_seq": "",
                    "ndn.lp.hoplimit": "",
                    "ndn.lp.mobility_flag": "",
                    "ndn.hoplimit": "1",
                }
                writer.writerow(base)
                writer.writerow(base)
                ingress = dict(base)
                ingress["sll.pkttype"] = "0"
                ingress["frame.len"] = "100"
                writer.writerow(ingress)
            packets = metrics.load_packets(str(path))
        self.assertEqual(len(packets), 2)
        measured = exp3.measure_run(packets, context)
        self.assertEqual(int(_flood(measured, "producer1", 1)["flood_interest_bytes"]), 100)
        self.assertEqual(int(_flood(measured, "producer1", 1)["flood_interest_packets"]), 1)
        self.assertEqual(int(_flood(measured, "producer1", 1)["prefix_rfv_packets"]), 1)
        self.assertEqual(int(measured.network[0]["network_rfv_bytes"]), 100)
        self.assertEqual(int(measured.network[0]["network_rfv_packets"]), 1)

    def test_repeated_egress_counts_faces_not_names_and_keeps_startup_interest_out_of_the_handoff(self) -> None:
        context = _context(1)
        first = _window(context, "producer1", 1)
        at = first.abs_time + 1.0
        same = V0
        packets = [
            _packet(at, "acc2", True, "data", same, 200, data_mobility_flag=True),
            _packet(at, "agg1", True, "data", same, 200, data_mobility_flag=True),
            _packet(at, "core", True, "data", same, 210, data_lp_hop_limit=True),
            _packet(at, "core", True, "data", same, 999),
            _packet(at, "core", True, "data", GUARD, 40, decoder_data_flood=True),
            _packet(ORIGIN + 1.0, "core", True, "interest", same, 50, interest_hop_limit=True),
        ]
        measured = exp3.measure_run(packets, context)
        row = _flood(measured, "producer1", 1)
        self.assertEqual(int(row["flood_content_data_bytes"]), 610)
        self.assertEqual(int(row["flood_content_data_packets"]), 3)
        self.assertEqual(int(row["flood_interest_packets"]), 0)
        self.assertEqual(int(row["flood_guard_data_packets"]), 0)
        self.assertEqual(int(row["prefix_rfv_bytes"]), 610)
        self.assertEqual(int(row["prefix_rfv_packets"]), 3)
        network = measured.network[0]
        self.assertEqual(int(network["flood_content_data_packets"]), 3)
        self.assertEqual(int(network["flood_interest_packets"]), 1)
        self.assertEqual(int(network["flood_interest_bytes"]), 50)
        self.assertEqual(int(network["network_rfv_bytes"]), 660)
        self.assertEqual(int(network["network_rfv_packets"]), 4)
        self.assertEqual(int(network["assigned_flood_outside_event_windows_packets"]), 1)
        self.assertEqual(sum(int(item["prefix_rfv_packets"]) for item in measured.prefix_rfv), 3)

    def test_audited_formal_counts_match_existing_byte_totals(self) -> None:
        """Known cases from the completed campaign. Missing decoded tables skip the check."""
        packets_root = ROOT / "results" / "extended" / "exp3" / "analysis" / "packets"
        campaign = ROOT / "results" / "extended" / "exp3" / "analysis" / "campaign"
        required = (
            packets_root / "p1" / "r1" / "mobility_packets.csv",
            packets_root / "p4" / "r2" / "mobility_packets.csv",
            campaign / "prefix_rfv.csv",
            campaign / "network_overhead.csv",
        )
        if any(not path.is_file() for path in required):
            self.skipTest("formal decoded packet tables are not in this workspace")
        prefix_rows = {
            (row["population"], row["run_id"], row["producer"], row["handoff_index"]): row
            for row in csv.DictReader((campaign / "prefix_rfv.csv").open(encoding="utf-8"))
        }
        cases = (
            ("p1", "r1", "producer1", "1", 25, 6045),
            ("p1", "r1", "producer1", "2", 28, 6713),
            ("p4", "r2", "producer1", "6", 72, 17424),
        )
        for population, run_id, producer, handoff, transmissions, byte_total in cases:
            recorded = prefix_rows[(population, run_id, producer, handoff)]
            self.assertEqual(int(recorded["prefix_rfv_bytes"]), byte_total)
            counted, byte_sum = _count_window(packets_root / population / run_id / "mobility_packets.csv", recorded)
            self.assertEqual(byte_sum, byte_total)
            self.assertEqual(counted, transmissions)
        network = next(
            row for row in csv.DictReader((campaign / "network_overhead.csv").open(encoding="utf-8"))
            if row["population"] == "p4" and row["run_id"] == "r2"
        )
        self.assertEqual(int(network["network_rfv_bytes"]), 327503)
        inside, outside, interest_outside = _count_network(
            packets_root / "p4" / "r2" / "mobility_packets.csv",
            float(network["observation_start_abs"]),
            float(network["observation_end_abs"]),
            [row for row in prefix_rows.values() if row["population"] == "p4" and row["run_id"] == "r2"],
        )
        self.assertEqual(inside, (1312, 316802))
        self.assertEqual(outside, (121, 10701))
        self.assertEqual(interest_outside, (121, 10701))
        self.assertEqual(inside[0] + outside[0], 1433)
        self.assertEqual(inside[1] + outside[1], 327503)

    def test_diagnostics_do_not_redefine_a_censored_recovery(self) -> None:
        context = _context(1)
        window = _window(context, "producer1", 1)
        stamp = int((window.abs_time + 0.4) * 1e9)
        logs = exp3.LogEvidence(
            daemon={"producer1": (
                f"[{stamp}] GUARD-PRODUCER: flooded guard FloodId=111 size=10 bytes\n"
                f"[{stamp}] GUARD-PRODUCER: flooded guard FloodId=222 size=10 bytes\n"
            )},
            consumer={"consumer1": (
                f"[{int(window.abs_time * 1e9)}] VALIDATE: Data signature verified "
                f"name={V0} id=consumer1\n"
                f"[{stamp}] VALIDATE: Data signature verified name={V1} id=consumer1\n"
                f"[{stamp}] VALIDATE: Data signature verified name={V0} id=consumer1\n"
            )},
            nfd=(
                f"[{stamp}] OptoFlood TFIB update prefix=/LiveStream/v1 floodId=1\n"
                f"[{stamp}] OptoFlood TFIB update prefix=/LiveStream/v0 floodId=111\n"
                f"[{stamp}] OptoFlood tfib-forward interest={V0}\n"
                f"[{stamp}] OptoFlood tfib-standby prefix=/LiveStream/v0\n"
                f"[{stamp}] OptoFlood tfib-retire prefix=/LiveStream/v0\n"
                f"[{stamp}] OptoFlood new-path-calculated prefix=/LiveStream/v0 serial=4 ignored reason=no-tfib-authority\n"
            ),
            nlsr=f"[{stamp}] Announced new-path-calculated prefix=/LiveStream/v0 serial=4 origin=/router\n",
        )
        measured = exp3.measure_run([], context, logs)
        row = _row(measured, "producer1", 1)
        self.assertEqual(row["recovery_status"], "right-censored")
        self.assertEqual(row["service_recovery_time_ms"], "")
        self.assertEqual(row["guard_generation"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["guard_flood_ids_observed"], "111,222")
        self.assertEqual(row["guard_attribution"], "multiple-flood-ids-in-window")
        self.assertEqual(row["guard_flood_id_expectation"], "not-inferred-from-handoff-index")
        self.assertEqual(row["tfib_install"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["consumer_validation"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["tfib_active"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["tfib_standby"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["tfib_retirement"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["nlsr_new_path_announced"], exp3.OBSERVED_SUCCESS)
        self.assertEqual(row["nfd_new_path_proof"], exp3.OBSERVED_FAILURE)
        self.assertEqual(row["diagnostic_redefines_metrics"], "false")
        unavailable = exp3.measure_run([], context, None)
        self.assertEqual(_row(unavailable, "producer1", 1)["tfib_install"], exp3.EVIDENCE_UNAVAILABLE)
        untimed = exp3.measure_run([], context, exp3.LogEvidence(
            daemon={"producer1": "GUARD-PRODUCER: flooded guard FloodId=1\n"},
            consumer={"consumer1": ""},
            nfd="",
            nlsr="",
        ))
        self.assertEqual(_row(untimed, "producer1", 1)["guard_generation"], exp3.EVIDENCE_UNAVAILABLE)
        self.assertEqual(_row(untimed, "producer1", 1)["consumer_validation"], exp3.NOT_OBSERVED)

    def test_pilot_stays_distinct_from_formal_r1(self) -> None:
        context = _context(4, run_id="pilot")
        measured = exp3.measure_run([], context)
        self.assertEqual(measured.events[0]["run_id"], "pilot")
        self.assertEqual(measured.events[0]["source_kind"], "pilot")
        self.assertEqual(measured.events[0]["run_seed"], "1")
        self.assertEqual(len(measured.events), 32)
        self.assertEqual(exp3.analysis_relative("p4", "pilot"), "p4/pilot")
        self.assertNotEqual(exp3.analysis_relative("p4", "pilot"), "p4/r1")
        with self.assertRaises(exp3.Exp3AnalysisError):
            exp3.population_comparison(measured.summary, measured.network)

    def test_formal_comparison_keeps_network_overhead_independent(self) -> None:
        context = _context(1)
        measured = exp3.measure_run([
            _packet(ORIGIN + 10.0, "core", True, "interest", V0, 50, interest_hop_limit=True),
        ], context)
        comparison = exp3.population_comparison(measured.summary, measured.network)
        self.assertEqual(len(comparison), 1)
        self.assertEqual(comparison[0]["network_rfv_bytes"], "50")
        self.assertEqual(comparison[0]["prefix_rfv_event_sum_bytes"], "0")
        self.assertEqual(comparison[0]["prefix_rfv_sum_is_network_rfv"], "false")
        self.assertEqual(comparison[0]["replication_unit"], "run")
        self.assertEqual(comparison[0]["network_overhead_scope"], "one-independently-measured-observation-per-run")


class Exp3CampaignTest(unittest.TestCase):
    def test_recorded_run_identity_uses_the_directory_and_frame_period(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _write_run(Path(temporary), "p1", "r1", 40)
            context = exp3.load_run_context(run_dir)
        self.assertEqual(context.frame_period_ms, 40)
        self.assertEqual(context.run_id, "r1")
        self.assertEqual(len(context.windows), 8)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _write_run(Path(temporary), "p4", "pilot")
            context = exp3.load_run_context(run_dir)
        self.assertEqual(context.source_kind, "pilot")
        self.assertEqual(context.run_seed, "1")

    def test_missing_and_malformed_captures_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(exp3.Exp3AnalysisError):
                exp3.validate_packet_captures(root / "missing")
            run_dir = root / "p1" / "r1" / "pcap_nodes"
            run_dir.mkdir(parents=True)
            bad = run_dir / "core.pcap"
            bad.write_bytes(b"not a pcap, just text")
            with self.assertRaises(exp3.Exp3AnalysisError):
                exp3.validate_packet_captures(run_dir.parent)
            bad.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)
            self.assertEqual(exp3.validate_packet_captures(run_dir.parent), [bad])

    def test_analysis_does_not_write_into_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "p1" / "r1"
            raw.mkdir(parents=True)
            with self.assertRaises(exp3.Exp3AnalysisError):
                runner._refuse_raw_output(raw, raw / "events")
            output = root / "analysis" / "p1" / "r1"
            with self.assertRaises(exp3.Exp3AnalysisError):
                runner.analyze_run(raw, output, root / "analysis")
            self.assertFalse((output / "events.csv").exists())

    def test_incomplete_campaign_is_not_presented_as_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            pilot = root / "p4" / "pilot"
            pilot.mkdir(parents=True)
            (pilot / "handoffs.txt").write_text("producer\n", encoding="utf-8")
            (pilot / "params.txt").write_text("exp3_run_id=pilot\n", encoding="utf-8")
            present = root / "p1" / "r1"
            present.mkdir(parents=True)
            (present / "handoffs.txt").write_text("x\n", encoding="utf-8")
            (present / "params.txt").write_text("x\n", encoding="utf-8")
            missing = exp3.missing_formal_runs(root)
            self.assertIn("p4/r1", missing)
            self.assertIn("p1/r2", missing)
            self.assertNotIn("p4/pilot", missing)
            analysis = Path(temporary) / "analysis"
            stale = analysis / "campaign"
            stale.mkdir(parents=True)
            (stale / "population_comparison.csv").write_text("stale\n", encoding="utf-8", newline="\n")
            status = runner.analyze_campaign(root, analysis)
            self.assertEqual(status, 2)
            text = (analysis / "campaign" / "campaign_status.txt").read_text(encoding="utf-8")
            self.assertIn("complete=false", text)
            self.assertIn("pilot_included=false", text)
            self.assertFalse((analysis / "campaign" / "population_comparison.csv").exists())
            self.assertFalse((analysis / "campaign" / "events.csv").exists())


class Exp3PlotTest(unittest.TestCase):
    def _formal_tree(self, root: Path, censored: str) -> None:
        campaign = root / "campaign"
        campaign.mkdir(parents=True)
        (campaign / "campaign_status.txt").write_text(
            "complete=true\nformal_runs=15\nmissing=\npilot_included=false\ndetail=test\n",
            encoding="utf-8",
            newline="\n",
        )
        events = []
        prefix_rows = []
        comparison = []
        for population, run_id in exp3.formal_run_keys():
            consumer = "consumer1"
            events.append({
                "population": population,
                "run_id": run_id,
                "source_kind": "formal",
                "consumer": consumer,
                "recovery_status": "recovered",
                "service_recovery_time_ms": "12.5",
                "content_loss_fraction": "0.25",
            })
            prefix_rows.append({
                "population": population,
                "run_id": run_id,
                "source_kind": "formal",
                "prefix_rfv_bytes": "80",
            })
            comparison.append({
                "population": population,
                "run_id": run_id,
                "source_kind": "formal",
                "n_censored": censored,
                "recovery_success_fraction": "0.5",
                "network_rfv_bytes": "1000",
                "nlsr_control_rate_bytes_per_s": "3.5",
            })
        for name, rows in (
            ("events.csv", events),
            ("prefix_rfv.csv", prefix_rows),
            ("population_comparison.csv", comparison),
        ):
            with (campaign / name).open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

    def test_formal_figures_require_a_complete_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            figures = root / "figures"
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.draw_formal(root, figures)
            self.assertEqual(list(figures.glob("*.pdf")), [])
            self._formal_tree(root, "1")
            written = plot_exp3.draw_formal(root, figures)
            names = {path.name for path in written}
            self.assertIn("srt_conditional_by_population.pdf", names)
            self.assertIn("clf_by_population.pdf", names)
            self.assertIn("prefix_rfv_by_population.pdf", names)
            self.assertIn("network_rfv_by_population.pdf", names)
            self.assertIn("nlsr_control_rate_by_population.pdf", names)
            self.assertIn("recovery_success_by_population.pdf", names)
            text = (figures / "figure_units.txt").read_text(encoding="utf-8")
            self.assertIn("conditional on successful recovery", text)
            self.assertIn("not multiplied by P", text)

    def test_pilot_figures_are_not_labelled_as_formal_r1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pilot = root / "p4" / "pilot"
            pilot.mkdir(parents=True)
            rows = []
            floods = []
            for index in range(1, 5):
                for handoff in range(1, 3):
                    rows.append({
                        "population": "p4",
                        "run_id": "pilot",
                        "source_kind": "pilot",
                        "producer": f"producer{index}",
                        "consumer": f"consumer{index}",
                        "handoff_index": str(handoff),
                        "recovery_status": "right-censored" if handoff == 2 else "recovered",
                        "service_recovery_time_ms": "" if handoff == 2 else "8",
                        "content_loss_fraction": "0.4",
                    })
                    floods.append({
                        "population": "p4",
                        "run_id": "pilot",
                        "source_kind": "pilot",
                        "prefix_rfv_bytes": "12",
                    })
            for name, table in (("events.csv", rows), ("prefix_rfv.csv", floods)):
                with (pilot / name).open("w", encoding="utf-8", newline="\n") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(table[0].keys()), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(table)
            with (pilot / "network_overhead.csv").open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "population", "run_id", "source_kind", "network_rfv_bytes", "nlsr_control_rate_bytes_per_s",
                ), lineterminator="\n")
                writer.writeheader()
                writer.writerow({
                    "population": "p4",
                    "run_id": "pilot",
                    "source_kind": "pilot",
                    "network_rfv_bytes": "400",
                    "nlsr_control_rate_bytes_per_s": "2",
                })
            figures = root / "figures" / "pilot"
            written = plot_exp3.draw_pilot(root, figures)
            text = (figures / "pilot_figure_units.txt").read_text(encoding="utf-8")
            self.assertIn("not a formal r1", text)
            self.assertTrue(any(path.name == "pilot_srt_conditional.pdf" for path in written))
            self.assertFalse((root / "figures" / "srt_conditional_by_population.pdf").exists())

    def _write_campaign(self, root: Path, events: list, floods: list) -> None:
        campaign = root / "campaign"
        campaign.mkdir(parents=True, exist_ok=True)
        (campaign / "campaign_status.txt").write_text(
            "complete=true\nformal_runs=15\nmissing=\npilot_included=false\ndetail=test\n",
            encoding="utf-8",
            newline="\n",
        )
        for name, rows in (("events.csv", events), ("prefix_rfv.csv", floods)):
            with (campaign / name).open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

    def _event(self, **overrides) -> dict:
        row = {
            "population": "p1",
            "run_id": "r1",
            "producer": "producer1",
            "consumer": "consumer1",
            "handoff_index": "1",
            "to_node": "acc2",
            "recovery_status": "recovered",
            "service_recovery_time_ms": "80",
            "source_kind": "formal",
        }
        row.update(overrides)
        return row

    def _flood(self, event: dict, nbytes: str = "6000", packets: str = "25") -> dict:
        return {
            "population": event["population"],
            "run_id": event["run_id"],
            "producer": event["producer"],
            "consumer": event["consumer"],
            "handoff_index": event["handoff_index"],
            "prefix_rfv_bytes": nbytes,
            "prefix_rfv_packets": packets,
        }

    def test_attachment_category_uses_the_new_router_not_the_transition(self) -> None:
        self.assertEqual(plot_exp3.attachment_category("acc1", "consumer1"), "same-access")
        self.assertEqual(plot_exp3.attachment_category("acc2", "consumer1"), "same-aggregation")
        self.assertEqual(plot_exp3.attachment_category("acc5", "consumer1"), "opposite-aggregation")
        self.assertEqual(plot_exp3.attachment_category("acc4", "consumer2"), "same-access")
        self.assertEqual(plot_exp3.attachment_category("acc6", "consumer2"), "same-aggregation")
        self.assertEqual(plot_exp3.attachment_category("acc3", "consumer4"), "opposite-aggregation")
        self.assertEqual(plot_exp3.attachment_category("acc3", "consumer3"), "same-access")

    def test_extended_join_requires_unique_complete_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event = self._event()
            duplicate = self._event()
            self._write_campaign(root, [event, duplicate], [self._flood(event), self._flood(duplicate)])
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.load_extended_handoffs(root)
            other = self._event(handoff_index="2", to_node="acc5")
            self._write_campaign(root, [event], [self._flood(event), self._flood(other)])
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.load_extended_handoffs(root)
            self._write_campaign(root, [event, other], [self._flood(event)])
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.load_extended_handoffs(root)
            mismatch = self._flood(event)
            mismatch["consumer"] = "consumer2"
            self._write_campaign(root, [event], [mismatch])
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.load_extended_handoffs(root)

    def test_extended_figures_group_producers_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            figures = root / "figures"
            events = [
                self._event(handoff_index="1", to_node="acc2", service_recovery_time_ms="78"),
                self._event(handoff_index="2", to_node="acc5", service_recovery_time_ms="90"),
                self._event(
                    handoff_index="3", to_node="acc3", recovery_status="right-censored",
                    service_recovery_time_ms="",
                ),
                self._event(
                    population="p2", run_id="r2", producer="producer1", consumer="consumer1",
                    handoff_index="1", to_node="acc3", service_recovery_time_ms="82",
                ),
                self._event(
                    population="p2", run_id="r2", producer="producer2", consumer="consumer2",
                    handoff_index="1", to_node="acc4", service_recovery_time_ms="70",
                ),
                self._event(
                    population="p4", run_id="r3", producer="producer1", consumer="consumer1",
                    handoff_index="1", to_node="acc6", service_recovery_time_ms="111",
                ),
                self._event(
                    population="p4", run_id="r4", producer="producer2", consumer="consumer2",
                    handoff_index="1", to_node="acc5", service_recovery_time_ms="60",
                ),
                self._event(
                    population="p4", run_id="r5", producer="producer3", consumer="consumer3",
                    handoff_index="1", to_node="acc3", service_recovery_time_ms="55",
                ),
                self._event(
                    population="p4", run_id="r1", producer="producer4", consumer="consumer4",
                    handoff_index="1", to_node="acc2", service_recovery_time_ms="66",
                ),
            ]
            floods = [
                self._flood(events[0], "6025", "25"),
                self._flood(events[1], "12090", "50"),
                self._flood(events[2], "4800", "20"),
                self._flood(events[3], "6100", "26"),
                self._flood(events[4], "5804", "24"),
                self._flood(events[5], "17424", "72"),
                self._flood(events[6], "7000", "29"),
                self._flood(events[7], "3900", "16"),
                self._flood(events[8], "15000", "62"),
            ]
            self._write_campaign(root, events, floods)
            handoffs = plot_exp3.load_extended_handoffs(root)
            self.assertEqual(len(handoffs), 9)
            identities = [
                (row["population"], row["run_id"], row["producer"], row["handoff_index"])
                for row in handoffs
            ]
            self.assertEqual(len(identities), len(set(identities)))
            by_producer: dict[tuple[str, str], int] = {}
            for row in handoffs:
                by_producer.setdefault((row["population"], row["producer"]), 0)
                by_producer[(row["population"], row["producer"])] += 1
            self.assertEqual(by_producer[("p1", "producer1")], 3)
            self.assertEqual(by_producer[("p2", "producer1")], 1)
            self.assertEqual(by_producer[("p2", "producer2")], 1)
            self.assertEqual(by_producer[("p4", "producer4")], 1)
            p1_categories = {row["attachment_category"] for row in handoffs if row["population"] == "p1"}
            self.assertEqual(p1_categories, {"same-aggregation", "opposite-aggregation"})
            self.assertNotIn("same-access", p1_categories)
            same_access = [
                row for row in handoffs
                if row["attachment_category"] == "same-access"
            ]
            self.assertEqual(
                {(row["population"], row["producer"]) for row in same_access},
                {("p2", "producer2"), ("p4", "producer3")},
            )
            recovered = [row for row in handoffs if row["recovery_status"] == "recovered"]
            self.assertTrue(all(row["service_recovery_time_ms"] != "0" for row in recovered))
            self.assertTrue(all(row["service_recovery_time_ms"] == "" for row in handoffs if row not in recovered))
            byte_ids = identities
            packet_ids = [
                (row["population"], row["run_id"], row["producer"], row["handoff_index"])
                for row in handoffs
                if row["prefix_rfv_bytes"] and row["prefix_rfv_packets"]
            ]
            self.assertEqual(byte_ids, packet_ids)
            written = plot_exp3.draw_extended(root, figures)
            self.assertEqual(
                {path.name for path in written},
                {"srt_by_producer.pdf", "prefix_rfv_by_attachment.pdf"},
            )
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in written))
            self.assertEqual({path.name for path in figures.glob("*.pdf")}, {path.name for path in written})

    def test_missing_packet_counts_and_inputs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            figures = root / "figures"
            event = self._event()
            flood = self._flood(event)
            del flood["prefix_rfv_packets"]
            self._write_campaign(root, [event], [flood])
            with self.assertRaises(plot_exp3.PlotDataError):
                plot_exp3.load_extended_handoffs(root)
            self.assertFalse(figures.exists())
            missing = root / "empty"
            status = plot_exp3.main([
                "--extended",
                "--analysis-root", str(missing),
                "--figure-dir", str(figures),
            ])
            self.assertEqual(status, 2)
            self.assertEqual(list(figures.glob("*.pdf")), [])

    def test_extended_plot_refuses_the_formal_analysis_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_campaign(root, [self._event()], [self._flood(self._event())])
            formal_figures = plot_exp3.ANALYSIS_ROOT / "figures"
            before = {
                path.name: path.stat().st_mtime_ns
                for path in formal_figures.glob("*")
                if path.is_file()
            }
            status = plot_exp3.main([
                "--extended",
                "--analysis-root", str(root),
                "--figure-dir", str(formal_figures),
            ])
            self.assertEqual(status, 2)
            after = {
                path.name: path.stat().st_mtime_ns
                for path in formal_figures.glob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertFalse((formal_figures / "srt_by_producer.pdf").exists())
            self.assertFalse((formal_figures / "prefix_rfv_by_attachment.pdf").exists())

    def _capture_srt_figure(self, handoffs: list, figure_dir: Path) -> dict:
        seen = {}
        original = plot_exp3._save

        def spy(figure, path, **kwargs):
            axes = figure.axes
            seen["ylims"] = [axis.get_ylim() for axis in axes]
            seen["widths"] = [axis.get_position().width for axis in axes]
            seen["labels"] = [
                tuple(label.get_text() for label in axis.get_xticklabels()) for axis in axes
            ]
            seen["points"] = [
                sum(len(collection.get_offsets()) for collection in axis.collections)
                for axis in axes
            ]
            original(figure, path, **kwargs)

        plot_exp3._save = spy
        try:
            plot_exp3.draw_srt_by_producer(handoffs, figure_dir)
        finally:
            plot_exp3._save = original
        return seen

    def test_srt_axis_keeps_extremes_inside_shared_limits(self) -> None:
        low, high = plot_exp3.conditional_srt_limits((42.03200340270996, 80.0, 114.57109451293945))
        self.assertLess(low, 42.03200340270996)
        self.assertGreater(high, 114.57109451293945)
        self.assertGreater(42.03200340270996 - low, 1.0)
        self.assertGreater(high - 114.57109451293945, 1.0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = [
                self._event(population="p1", run_id="r1", producer="producer1", handoff_index="1",
                            service_recovery_time_ms="42.032"),
                self._event(population="p2", run_id="r2", producer="producer1", handoff_index="1",
                            service_recovery_time_ms="80"),
                self._event(population="p2", run_id="r3", producer="producer2", consumer="consumer2",
                            handoff_index="1", service_recovery_time_ms="70"),
                self._event(population="p4", run_id="r4", producer="producer1", handoff_index="1",
                            service_recovery_time_ms="90"),
                self._event(population="p4", run_id="r5", producer="producer2", consumer="consumer2",
                            handoff_index="1", service_recovery_time_ms="114.571"),
                self._event(population="p4", run_id="r1", producer="producer3", consumer="consumer3",
                            handoff_index="1", service_recovery_time_ms="60"),
                self._event(population="p4", run_id="r2", producer="producer4", consumer="consumer4",
                            handoff_index="1", service_recovery_time_ms="55"),
                self._event(population="p1", run_id="r1", producer="producer1", handoff_index="2",
                            recovery_status="right-censored", service_recovery_time_ms=""),
            ]
            floods = [self._flood(event) for event in events]
            self._write_campaign(root, events, floods)
            handoffs = plot_exp3.load_extended_handoffs(root)
            seen = self._capture_srt_figure(handoffs, root / "figures")
            self.assertEqual(seen["labels"][0], ("Producer 1",))
            self.assertEqual(seen["labels"][1], ("Producer 1", "Producer 2"))
            self.assertEqual(seen["labels"][2], ("Producer 1", "Producer 2", "Producer 3", "Producer 4"))
            self.assertEqual(sum(seen["points"]), 7)
            self.assertEqual(len({tuple(limit) for limit in seen["ylims"]}), 1)
            ymin, ymax = seen["ylims"][0]
            self.assertLess(ymin, 42.032)
            self.assertGreater(ymax, 114.571)
            self.assertAlmostEqual(seen["widths"][1] / seen["widths"][0], 1.8 / 1.2, places=2)
            self.assertAlmostEqual(seen["widths"][2] / seen["widths"][0], 3.0 / 1.2, places=2)

    def test_campaign_srt_figure_includes_every_recovered_observation(self) -> None:
        root = ROOT / "results" / "extended" / "exp3" / "validation-packet-counts"
        if not (root / "campaign" / "events.csv").is_file():
            self.skipTest("validated Exp3 campaign is not in this workspace")
        before = (root / "campaign" / "events.csv").read_bytes()
        handoffs = plot_exp3.load_extended_handoffs(root)
        recovered = [row for row in handoffs if row["recovery_status"] == "recovered"]
        self.assertEqual(len(handoffs), 280)
        self.assertEqual(len(recovered), 280)
        values = [float(row["service_recovery_time_ms"]) for row in recovered]
        self.assertAlmostEqual(min(values), 42.03200340270996, places=6)
        self.assertAlmostEqual(max(values), 114.57109451293945, places=6)
        groups: dict[tuple[str, str], int] = {}
        for row in recovered:
            groups.setdefault((row["population"], row["producer"]), 0)
            groups[(row["population"], row["producer"])] += 1
        self.assertEqual(groups[("p1", "producer1")], 40)
        self.assertEqual(groups[("p4", "producer2")], 40)
        self.assertEqual(len(groups), 7)
        with tempfile.TemporaryDirectory() as temporary:
            seen = self._capture_srt_figure(handoffs, Path(temporary))
            self.assertEqual(sum(seen["points"]), 280)
            self.assertEqual(len({tuple(limit) for limit in seen["ylims"]}), 1)
            ymin, ymax = seen["ylims"][0]
            self.assertLess(ymin, min(values))
            self.assertGreater(ymax, max(values))
            self.assertGreater(min(values) - ymin, 1.0)
            self.assertGreater(ymax - max(values), 1.0)
        self.assertEqual((root / "campaign" / "events.csv").read_bytes(), before)

    def test_clf_display_includes_extreme_and_negative_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._formal_tree(root, "0")
            campaign = root / "campaign" / "events.csv"
            with campaign.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0].keys())
            extra = dict(rows[0])
            extra["content_loss_fraction"] = "5"
            low = dict(rows[0])
            low["content_loss_fraction"] = "-0.001"
            rows.extend((extra, low))
            with campaign.open("w", encoding="utf-8", newline="\n") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            seen = {}
            original = plot_exp3._save

            def spy(figure, path, **kwargs):
                title = " ".join(text.get_text() for text in figure.texts)
                if "content loss fraction" in title:
                    values = []
                    for axis in figure.axes:
                        for line in axis.lines:
                            values.extend(float(item) for item in line.get_ydata())
                        for collection in axis.collections:
                            offsets = collection.get_offsets()
                            if len(offsets):
                                values.extend(float(item) for item in offsets[:, 1])
                    seen["values"] = values
                original(figure, path, **kwargs)

            plot_exp3._save = spy
            try:
                plot_exp3.draw_formal(root, root / "figures")
            finally:
                plot_exp3._save = original
            self.assertIn(5.0, seen["values"])
            self.assertIn(-0.001, seen["values"])

    def test_paper_figure_directory_is_outside_the_analysis_guard(self) -> None:
        paper_figures = plot_exp3.ROOT / "results" / "extended" / "exp3" / "paper-figures"
        plot_exp3._refuse_extended_output(paper_figures)
        with self.assertRaises(plot_exp3.PlotDataError):
            plot_exp3._refuse_extended_output(plot_exp3.ANALYSIS_ROOT / "figures")


if __name__ == "__main__":
    unittest.main()
