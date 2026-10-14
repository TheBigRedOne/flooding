#!/usr/bin/env python3
"""Synthetic Distinct Streams metric checks. No PCAPs or VM runs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp2_distinct_metrics as distinct
import exp2_scale_metrics as scale
import exp2_shared_config as config
import mobility_event_metrics as metrics

HANDOFF = 1_700_000_000.0
V0 = "/LiveStream/v0/54=%01/50=%00"
V0_NEXT = "/LiveStream/v0/54=%02/50=%00"
V1 = "/LiveStream/v1/54=%03/50=%00"
V2 = "/LiveStream/v2/54=%04/50=%00"
V3 = "/LiveStream/v3/54=%05/50=%00"
N2 = (
    ("consumer1", "C1", "acc1", "/LiveStream/v0"),
    ("consumer2", "C2", "acc4", "/LiveStream/v1"),
)


def _packet(time_s: float, node: str, outbound: bool, ptype: str, name: str, length: int = 100, **flags: bool) -> metrics.Packet:
    return metrics.Packet(
        time_s, node, outbound, ptype, name, length, False, False,
        flags.get("interest_hop_limit", False),
        flags.get("data_lp_hop_limit", False),
        flags.get("data_mobility_flag", False),
    )


def _measure(packets, handoffs, consumers=N2, capture_nodes=12):
    return distinct.measure_events(packets, handoffs, "N=2", "r1", consumers, 20, capture_nodes)


class DistinctClassificationTest(unittest.TestCase):
    def test_typed_content_names_follow_the_configured_stream(self) -> None:
        for prefix, name in (
            ("/LiveStream/v0", V0),
            ("/LiveStream/v1", V1),
            ("/LiveStream/v2", V2),
            ("/LiveStream/v3", V3),
        ):
            self.assertTrue(distinct.is_stream_content(name, prefix))
            self.assertEqual(distinct.stream_of_content(name, [prefix]), prefix)
        self.assertTrue(metrics.is_useful_content(V0))
        self.assertFalse(metrics.is_useful_content(V1))
        self.assertFalse(distinct.is_stream_content(V1, "/LiveStream/v0"))
        self.assertFalse(distinct.is_stream_content("/LiveStream/v10/54=%01/50=%00", "/LiveStream/v1"))
        self.assertNotEqual(metrics.parse_name("/LiveStream/v1")[1][0], metrics.COMPONENT_VERSION)

    def test_guard_discovery_management_and_unrelated_names_are_rejected(self) -> None:
        for name in (
            "/LiveStream/_guard",
            "/LiveStream/v1/_meta",
            "/LiveStream/v1/_guard",
            "/localhop/nfd/faces/list",
            "/ndn/nlsr/update",
            "/OtherApp/v1/54=%01/50=%00",
        ):
            self.assertFalse(distinct.is_stream_content(name, "/LiveStream/v1"))
            self.assertEqual(distinct.stream_frame_id(name, "/LiveStream/v1"), "")


class DistinctMetricTest(unittest.TestCase):
    def test_network_srt_uses_the_earliest_stream_and_keeps_per_stream_diagnostics(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.30, "consumer1", True, "interest", V0),
            _packet(HANDOFF + 0.50, "producer", False, "interest", V0),
            _packet(HANDOFF + 0.10, "consumer2", True, "interest", V1),
            _packet(HANDOFF + 0.20, "producer", False, "interest", V1),
        ]
        network, consumer, streams = _measure(packets, [handoff])
        self.assertEqual(len(network), 1)
        self.assertEqual(network[0]["recovered"], "true")
        self.assertEqual(network[0]["recovery_stream_prefix"], "/LiveStream/v1")
        self.assertEqual(network[0]["srt_witness_identities"], "C2")
        self.assertEqual(network[0]["eligible_consumer_witnesses"], 1)
        self.assertAlmostEqual(
            float(str(network[0]["service_recovery_time_ms"])),
            ((HANDOFF + 0.20) - HANDOFF) * 1000.0,
            places=6,
        )
        by_stream = {row["stream_prefix"]: row for row in streams}
        self.assertEqual(by_stream["/LiveStream/v1"]["recovered"], "true")
        self.assertEqual(by_stream["/LiveStream/v0"]["recovered"], "true")
        self.assertGreater(
            float(str(by_stream["/LiveStream/v0"]["service_recovery_time_ms"])),
            float(str(network[0]["service_recovery_time_ms"])),
        )
        self.assertTrue(all(row["diagnostic_not_network_srt"] == "true" for row in streams))
        self.assertEqual(len(consumer), 2)

    def test_same_canonical_name_is_required_and_pre_handoff_interest_is_excluded(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF - 0.2, "consumer2", True, "interest", V1),
            _packet(HANDOFF + 0.1, "consumer2", True, "interest", V1),
            _packet(HANDOFF + 0.2, "producer", False, "interest", V0),
        ]
        network, _consumer, streams = _measure(packets, [handoff])
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(network[0]["recovery_stream_prefix"], "")
        self.assertNotEqual(network[0]["srt_censor_boundary_ms"], "")
        self.assertEqual(streams[1]["recovered"], "false")

    def test_nonfinal_boundary_excludes_the_next_handoff_and_final_includes_capture_end(self) -> None:
        handoffs = [
            metrics.Handoff(1, HANDOFF, "acc2", "acc3"),
            metrics.Handoff(2, HANDOFF + 100.0, "acc3", "acc4"),
        ]
        packets = [
            _packet(HANDOFF + 100.0, "consumer2", True, "interest", V1),
            _packet(HANDOFF + 100.0, "producer", False, "interest", V1),
            _packet(HANDOFF + 150.0, "consumer1", True, "interest", V0),
            _packet(HANDOFF + 150.2, "producer", False, "interest", V0),
        ]
        network, _consumer, _streams = _measure(packets, handoffs)
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(network[1]["recovered"], "true")
        self.assertEqual(network[1]["recovery_stream_prefix"], "/LiveStream/v0")
        self.assertAlmostEqual(
            float(str(network[1]["service_recovery_time_ms"])),
            ((HANDOFF + 150.2) - (HANDOFF + 100.0)) * 1000.0,
            places=6,
        )

    def test_clf_counts_only_the_assigned_stream_and_keeps_negative_values(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.01, "consumer1", False, "data", V1),
            _packet(HANDOFF + 0.02, "consumer1", False, "data", V0),
            _packet(HANDOFF + 0.03, "consumer1", False, "data", V0),
            _packet(HANDOFF + 0.04, "consumer2", False, "data", V1),
            _packet(HANDOFF + 0.04, "consumer2", False, "data", V1),
            _packet(HANDOFF + 0.04, "consumer2", False, "data", "/LiveStream/v1/54=%06/50=%00"),
            _packet(HANDOFF + 0.04, "consumer2", False, "data", "/LiveStream/v1/54=%07/50=%00"),
        ]
        _network, consumer, _streams = _measure(packets, [handoff])
        by_identity = {row["consumer_identity"]: row for row in consumer}
        self.assertEqual(by_identity["C1"]["stream_prefix"], "/LiveStream/v0")
        self.assertEqual(int(str(by_identity["C1"]["delivered_unique_content_frames"])), 1)
        self.assertEqual(int(str(by_identity["C2"]["delivered_unique_content_frames"])), 3)
        self.assertEqual(by_identity["C2"]["clf_outside_unit_interval"], "true")
        self.assertLess(float(str(by_identity["C2"]["content_loss_fraction"])), 0.0)
        self.assertNotEqual(by_identity["C1"]["content_loss_fraction"], by_identity["C2"]["content_loss_fraction"])

    def test_rfv_includes_every_stream_and_the_guard_without_dividing_by_consumers(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.1, "consumer2", True, "interest", V1),
            _packet(HANDOFF + 0.2, "producer", False, "interest", V1),
            _packet(HANDOFF + 0.3, "core", True, "interest", V1, length=10, interest_hop_limit=True),
            _packet(HANDOFF + 0.3, "acc3", True, "data", V3, length=20, data_mobility_flag=True),
            _packet(HANDOFF + 0.3, "agg1", True, "interest", "/LiveStream/_guard", length=7, interest_hop_limit=True),
            _packet(HANDOFF + 0.3, "core", True, "interest", "/ndn/nlsr/update", length=15),
        ]
        network, _consumer, _streams = _measure(packets, [handoff])
        self.assertEqual(network[0]["recovery_interest_flood_bytes"], 17)
        self.assertEqual(network[0]["recovery_data_flood_bytes"], 20)
        self.assertEqual(network[0]["recovery_flood_bytes"], 37)
        self.assertEqual(network[0]["nlsr_control_bytes"], 15)
        self.assertEqual(network[0]["physical_capture_nodes"], 12)
        reference = metrics.measure_run(packets, [handoff], "N=2", "distinct", "r1", frame_period_ms=20)
        self.assertEqual(network[0]["recovery_flood_bytes"], reference[0]["recovery_flood_bytes"])
        self.assertEqual(network[0]["nlsr_control_bytes"], reference[0]["nlsr_control_bytes"])
        self.assertEqual(reference[0]["recovered"], False)
        self.assertEqual(network[0]["recovered"], "true")
        self.assertEqual(distinct.overhead_mismatches(network, packets, [handoff], "N=2", "r1", 20), [])

    def test_shared_measurement_still_ignores_v1_content(self) -> None:
        handoff = metrics.Handoff(1, HANDOFF, "acc2", "acc3")
        packets = [
            _packet(HANDOFF + 0.1, "consumer1", True, "interest", V1),
            _packet(HANDOFF + 0.2, "producer", False, "interest", V1),
            _packet(HANDOFF + 0.3, "consumer1", False, "data", V1),
        ]
        network, consumer = scale.measure_events(
            packets, [handoff], "N=2", "r1",
            (("consumer1", "C1", "acc1"), ("consumer2", "C2", "acc4")),
            20, 12,
        )
        self.assertEqual(network[0]["recovered"], "false")
        self.assertEqual(int(str(consumer[0]["delivered_unique_content_frames"])), 0)


class DistinctContractTest(unittest.TestCase):
    def _write_run(self, root: Path, consumers: tuple, stream_map: str) -> Path:
        run_dir = root / "r1"
        run_dir.mkdir(parents=True)
        sequence = config.FULL_HANDOFF_SEQUENCE
        (run_dir / "campaign.txt").write_text(
            config.campaign_text(consumers, "full", "r1", "distinct").replace(
                config.format_stream_map(config.stream_mapping("distinct", consumers)),
                stream_map,
            ),
            encoding="utf-8",
        )
        topology = config.topology_text(consumers, sequence, "distinct")
        (run_dir / "topology.txt").write_text(
            topology.replace(
                "stream_map=" + config.format_stream_map(config.stream_mapping("distinct", consumers)),
                "stream_map=" + stream_map,
            ),
            encoding="utf-8",
        )
        params = {
            "exp2_experiment": "distinct",
            "exp2_demand_pattern": "distinct",
            "exp2_active_consumers": ",".join(consumers),
            "exp2_schedule": "full",
            "exp2_run_id": "r1",
            "exp2_campaign": config.DISTINCT_CAMPAIGN_ID,
            "exp2_stream_map": stream_map,
            "exp2_advertised_prefix": "/LiveStream",
            "exp2_guard_name": "/LiveStream/_guard",
            "handoff_sequence": ",".join(sequence),
            "handoff_count": "8",
            "request_interval_ms": "20",
            "segments_per_frame": "1",
            "exp2_realized_intervals_s": ",".join(f"{90.0 + index:.6f}" for index in range(9)),
        }
        (run_dir / "params.txt").write_text("".join(f"{key}={value}\n" for key, value in params.items()), encoding="utf-8")
        return run_dir

    def test_recorded_mapping_must_match_the_approved_distinct_map(self) -> None:
        consumers = config.parse_active_consumers("n2")
        approved = config.format_stream_map(config.stream_mapping("distinct", consumers))
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._write_run(Path(tmp), consumers, approved)
            configuration, run_id, specs, interval, final_observation = distinct.load_contract(run_dir)
            self.assertEqual((configuration, run_id, interval), ("N=2", "r1", 20))
            self.assertEqual([item[3] for item in specs], ["/LiveStream/v0", "/LiveStream/v1"])
            self.assertAlmostEqual(final_observation, 98.0, places=6)
            broken = self._write_run(Path(tmp) / "bad", consumers, "consumer1=/LiveStream/v0,consumer2=/LiveStream/v0")
            with self.assertRaises(metrics.MobilityMetricError):
                distinct.load_contract(broken)
            missing = self._write_run(Path(tmp) / "missing", consumers, approved)
            text = (missing / "params.txt").read_text(encoding="utf-8").replace("exp2_stream_map=" + approved + "\n", "")
            (missing / "params.txt").write_text(text, encoding="utf-8")
            with self.assertRaises(metrics.MobilityMetricError):
                distinct.load_contract(missing)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
