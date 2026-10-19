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
        self.assertEqual(int(measured.network[0]["network_rfv_bytes"]), 31)
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
        self.assertEqual(int(_flood(measured, "producer2", 1)["prefix_rfv_bytes"]), 80)
        self.assertEqual(int(_flood(measured, "producer1", 2)["prefix_rfv_bytes"]), 0)
        prefix_sum = sum(int(row["prefix_rfv_bytes"]) for row in measured.prefix_rfv)
        network = measured.network[0]
        self.assertEqual(prefix_sum, 305)
        self.assertEqual(int(network["network_rfv_bytes"]), 305 + 33 + 44 + 17)
        self.assertEqual(int(network["unassigned_flood_bytes"]), 44)
        self.assertEqual(int(network["assigned_flood_outside_event_windows_bytes"]), 33 + 17)
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
        self.assertEqual(int(measured.network[0]["network_rfv_bytes"]), 100)

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


if __name__ == "__main__":
    unittest.main()
