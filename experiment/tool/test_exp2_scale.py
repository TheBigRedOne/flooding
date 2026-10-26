#!/usr/bin/env python3
"""Synthetic checks for the Exp2 scalability measurement adapter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp2_scale_metrics as scale
import mobility_event_metrics as metrics

HANDOFF = 1_700_000_000.0
NAME_A = "/LiveStream/v0/54=%01/50=%00"
NAME_B = "/LiveStream/v0/54=%02/50=%00"
N1 = (("consumer", "C1", "acc1"),)
N2 = (("consumer1", "C1", "acc1"), ("consumer2", "C2", "acc4"))


def _packet(time_s: float, node: str, outbound: bool, ptype: str, name: str, length: int = 100, **flags: bool) -> metrics.Packet:
    return metrics.Packet(
        time_s, node, outbound, ptype, name, length, False, False,
        flags.get("interest_hop_limit", False),
        flags.get("data_lp_hop_limit", False),
        flags.get("data_mobility_flag", False),
    )


def _measure(packets, handoffs, consumers=N2, capture_nodes=12):
    return scale.measure_events(packets, handoffs, "N=2", "r1", consumers, 20, capture_nodes)


class Exp2ScaleMetricTest(unittest.TestCase):
    def test_distinct_names_select_the_earliest_producer_ingress(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.10, "consumer1", True, "interest", NAME_A),
            _packet(HANDOFF + 0.20, "producer", False, "interest", NAME_A),
            _packet(HANDOFF + 0.40, "consumer2", True, "interest", NAME_B),
            _packet(HANDOFF + 0.50, "producer", False, "interest", NAME_B),
            _packet(HANDOFF + 1.00, "consumer1", False, "data", NAME_A),
        ]
        network, consumer = _measure(packets, [handoff])
        self.assertEqual(network[0]["recovered"], "true")
        self.assertEqual(network[0]["recovery_name"], metrics.canonical_name(NAME_A))
        self.assertAlmostEqual(float(str(network[0]["service_recovery_time_ms"])), (HANDOFF + 0.20 - HANDOFF) * 1000.0, places=6)
        self.assertEqual(network[0]["eligible_consumer_witnesses"], 1)
        self.assertEqual(network[0]["srt_attribution"], "unique")
        self.assertEqual(len(consumer), 2)

    def test_identical_names_keep_srt_and_mark_attribution_ambiguous(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.10, "consumer1", True, "interest", NAME_A),
            _packet(HANDOFF + 0.15, "consumer2", True, "interest", NAME_A),
            _packet(HANDOFF + 0.20, "producer", False, "interest", NAME_A),
        ]
        network, _consumer = _measure(packets, [handoff])
        self.assertEqual(network[0]["recovered"], "true")
        self.assertEqual(network[0]["eligible_consumer_witnesses"], 2)
        self.assertEqual(network[0]["srt_attribution"], "ambiguous")
        self.assertAlmostEqual(float(str(network[0]["service_recovery_time_ms"])), (HANDOFF + 0.20 - HANDOFF) * 1000.0, places=6)
        self.assertNotIn("consumer_identity", network[0])

    def test_pre_handoff_interest_does_not_qualify(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF - 1.0, "consumer1", True, "interest", NAME_A),
            _packet(HANDOFF - 0.5, "consumer2", True, "interest", NAME_A),
            _packet(HANDOFF + 0.2, "producer", False, "interest", NAME_A),
            _packet(HANDOFF + 0.4, "consumer1", False, "data", NAME_A),
        ]
        network, _consumer = _measure(packets, [handoff])
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(network[0]["service_recovery_time_ms"], "")
        self.assertEqual(network[0]["srt_attribution"], "none")
        self.assertNotEqual(network[0]["srt_censor_boundary_ms"], "")

    def test_missing_producer_ingress_is_censored_and_retained(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.1, "consumer1", True, "interest", NAME_A),
            _packet(HANDOFF + 0.2, "consumer2", True, "interest", NAME_A),
        ]
        network, consumer = _measure(packets, [handoff])
        self.assertEqual(len(network), 1)
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(len(consumer), 2)

    def test_nonfinal_boundary_excludes_the_next_handoff_and_final_includes_capture_end(self) -> None:
        handoffs = [
            metrics.Handoff(1, HANDOFF, "acc2", "acc3"),
            metrics.Handoff(2, HANDOFF + 100.0, "acc3", "acc4"),
        ]
        packets = [
            _packet(HANDOFF, "consumer", True, "interest", NAME_A),
            _packet(HANDOFF, "consumer", False, "data", NAME_A),
            _packet(HANDOFF + 100.0, "consumer", True, "interest", NAME_B),
            _packet(HANDOFF + 100.0, "producer", False, "interest", NAME_B),
            _packet(HANDOFF + 100.0, "consumer", False, "data", NAME_B),
            _packet(HANDOFF + 150.0, "consumer", True, "interest", NAME_A),
            _packet(HANDOFF + 150.0, "producer", False, "interest", NAME_A),
        ]
        network, consumer = _measure(packets, handoffs, consumers=N1, capture_nodes=11)
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(int(str(consumer[0]["delivered_unique_content_frames"])), 1)
        self.assertEqual(network[1]["recovered"], "true")
        self.assertAlmostEqual(float(str(network[1]["service_recovery_time_ms"])), 50000.0, places=6)

    def test_clf_is_independent_and_deduplicates_frames(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.1, "consumer1", False, "data", NAME_A),
            _packet(HANDOFF + 0.2, "consumer1", False, "data", NAME_A),
            _packet(HANDOFF + 0.3, "consumer1", False, "data", NAME_B),
            _packet(HANDOFF + 1.0, "core", True, "interest", NAME_A, length=80, interest_hop_limit=True),
            _packet(HANDOFF + 1.0, "acc4", True, "data", NAME_A, length=40, data_mobility_flag=True),
            _packet(HANDOFF + 1.0, "core", True, "interest", "/ndn/nlsr/update", length=15),
        ]
        network, consumer = _measure(packets, [handoff])
        by_identity = {row["consumer_identity"]: row for row in consumer}
        self.assertEqual(int(str(by_identity["C1"]["delivered_unique_content_frames"])), 2)
        self.assertEqual(by_identity["C2"]["zero_delivery"], "true")
        self.assertAlmostEqual(float(str(by_identity["C2"]["content_loss_fraction"])), 1.0, places=6)
        self.assertNotEqual(by_identity["C1"]["content_loss_fraction"], by_identity["C2"]["content_loss_fraction"])
        self.assertNotIn("recovery_flood_bytes", by_identity["C1"])
        self.assertEqual(network[0]["recovery_interest_flood_bytes"], 80)
        self.assertEqual(network[0]["recovery_data_flood_bytes"], 40)
        self.assertEqual(network[0]["recovery_flood_bytes"], 120)
        self.assertEqual(network[0]["nlsr_control_bytes"], 15)
        duration = float(str(network[0]["event_duration_s"]))
        self.assertAlmostEqual(float(str(network[0]["nlsr_control_rate_bytes_per_s"])), 15.0 / duration, places=6)

    def test_n1_adapter_matches_solution_measure_run(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF - 0.2, "consumer", True, "interest", NAME_A),
            _packet(HANDOFF + 0.05, "consumer", True, "interest", NAME_A),
            _packet(HANDOFF + 0.08, "producer", False, "interest", NAME_A),
            _packet(HANDOFF, "consumer", False, "data", NAME_A),
            _packet(HANDOFF + 0.2, "consumer", False, "data", NAME_B),
            _packet(HANDOFF + 0.2, "core", True, "data", NAME_B, length=25, data_lp_hop_limit=True),
        ]
        network, consumer = scale.measure_events(packets, [handoff], "N=1", "r1", N1, 20, 11)
        reference = metrics.measure_run(packets, [handoff], "OptoFlood", "solution", "r1", frame_period_ms=20)
        self.assertEqual(network[0]["recovery_flood_bytes"], reference[0]["recovery_flood_bytes"])
        self.assertEqual(network[0]["nlsr_control_bytes"], reference[0]["nlsr_control_bytes"])
        self.assertEqual(network[0]["recovered"], "true" if reference[0]["recovered"] else "false")
        self.assertAlmostEqual(
            float(str(network[0]["service_recovery_time_ms"])),
            float(str(reference[0]["service_recovery_time_ms"])),
            places=6,
        )
        self.assertEqual(consumer[0]["delivered_unique_content_frames"], reference[0]["delivered_unique_content_frames"])
        self.assertAlmostEqual(
            float(str(consumer[0]["content_loss_fraction"])),
            float(str(reference[0]["content_loss_fraction"])),
            places=6,
        )
        self.assertEqual(consumer[0]["consumer_identity"], "C1")
        self.assertEqual(consumer[0]["consumer_host"], "consumer")

    def test_output_order_is_deterministic(self) -> None:
        rows = [
            {"configuration": "N=4", "run_id": "r2", "handoff_index": 1},
            {"configuration": "N=1", "run_id": "r2", "handoff_index": 2},
            {"configuration": "N=1", "run_id": "r1", "handoff_index": 8},
            {"configuration": "N=2", "run_id": "r1", "handoff_index": 1},
        ]
        ordered = scale.sort_network(rows)
        self.assertEqual(
            [(row["configuration"], row["run_id"], row["handoff_index"]) for row in ordered],
            [("N=1", "r1", 8), ("N=1", "r2", 2), ("N=2", "r1", 1), ("N=4", "r2", 1)],
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
