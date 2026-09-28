#!/usr/bin/env python3
"""Synthetic checks for mobility-event SRT, reliability, and cost."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobility_event_metrics as metrics


def packet(time, node, outbound, ptype, name, length=100, interest_flood=False, data_flood=False):
    return metrics.Packet(time, node, outbound, ptype, name, length, interest_flood, data_flood)


CONTENT = "/LiveStream/v0/54=%01/50=%00"
OTHER = "/LiveStream/v0/54=%02/50=%00"
GUARD = "/LiveStream/_guard"
META = "/LiveStream/v0/_meta"


class MobilityEventTest(unittest.TestCase):
    def test_pre_handoff_interest_does_not_qualify(self) -> None:
        packets = [
            packet(10.0, "consumer", True, "interest", CONTENT),
            packet(10.1, "producer", False, "interest", CONTENT),
            packet(11.2, "producer", True, "data", CONTENT),
            packet(11.3, "consumer", False, "data", CONTENT),
        ]
        handoffs = [metrics.Handoff(1, 11.0, "acc2", "acc3")]
        rows = metrics.measure_run(packets, handoffs, "G0", "g0", "r1")
        self.assertFalse(rows[0]["recovered"])
        self.assertEqual(rows[0]["service_recovery_time_ms"], "")
        self.assertAlmostEqual(float(str(rows[0]["first_post_handoff_producer_data_arrival_ms"])), 300.0)

    def test_post_handoff_chain_qualifies(self) -> None:
        packets = [
            packet(11.1, "consumer", True, "interest", CONTENT),
            packet(11.2, "producer", False, "interest", CONTENT),
            packet(11.4, "producer", True, "data", CONTENT),
            packet(11.5, "consumer", False, "data", CONTENT),
            packet(20.0, "consumer", False, "data", CONTENT),
        ]
        handoffs = [metrics.Handoff(1, 11.0, "acc2", "acc3")]
        rows = metrics.measure_run(packets, handoffs, "G0", "g0", "r1")
        self.assertTrue(rows[0]["recovered"])
        self.assertAlmostEqual(float(str(rows[0]["service_recovery_time_ms"])), 500.0)
        self.assertEqual(rows[0]["recovery_name"], CONTENT)
        self.assertEqual(rows[0]["event_end_time"], 20.0)

    def test_relay_only_data_does_not_qualify(self) -> None:
        packets = [
            packet(11.1, "consumer", True, "interest", CONTENT),
            packet(11.2, "acc2", True, "data", CONTENT),
            packet(11.3, "consumer", False, "data", CONTENT),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertFalse(rows[0]["recovered"])

    def test_guard_and_meta_are_not_content_recovery(self) -> None:
        packets = [
            packet(11.1, "consumer", True, "interest", GUARD),
            packet(11.2, "producer", False, "interest", GUARD),
            packet(11.3, "producer", True, "data", GUARD),
            packet(11.4, "consumer", False, "data", GUARD, length=40),
            packet(11.1, "consumer", True, "interest", META),
            packet(11.2, "producer", False, "interest", META),
            packet(11.3, "producer", True, "data", META),
            packet(11.4, "consumer", False, "data", META, length=40),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertFalse(rows[0]["recovered"])
        self.assertEqual(rows[0]["logical_request_count"], 0)
        self.assertEqual(rows[0]["useful_content_delivered_bytes"], 0)
        self.assertEqual(rows[0]["forwarding_cost_ratio"], "")

    def test_retransmission_is_one_logical_request(self) -> None:
        packets = [
            packet(11.1, "consumer", True, "interest", CONTENT),
            packet(11.2, "consumer", True, "interest", CONTENT),
            packet(11.3, "producer", False, "interest", CONTENT),
            packet(11.4, "producer", True, "data", CONTENT),
            packet(11.5, "consumer", False, "data", CONTENT, length=80),
            packet(12.0, "consumer", True, "interest", OTHER),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertEqual(rows[0]["logical_request_count"], 2)
        self.assertEqual(rows[0]["satisfied_request_count"], 1)
        self.assertEqual(rows[0]["unmet_request_count"], 1)
        self.assertAlmostEqual(float(str(rows[0]["unmet_interest_ratio"])), 0.5)

    def test_fcr_counts_relay_app_bytes_and_excludes_guard_from_delivery(self) -> None:
        packets = [
            packet(11.1, "core", True, "interest", CONTENT, length=30),
            packet(11.2, "acc3", True, "data", GUARD, length=50),
            packet(11.3, "consumer", False, "data", CONTENT, length=80),
            packet(11.4, "consumer", False, "data", GUARD, length=999),
            packet(11.5, "core", True, "interest", "/localhop/ndn/nlsr/sync/x", length=10),
            packet(11.6, "producer", True, "data", CONTENT, length=80),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertEqual(rows[0]["relay_application_forwarded_bytes"], 80)
        self.assertEqual(rows[0]["useful_content_delivered_bytes"], 80)
        self.assertAlmostEqual(float(str(rows[0]["forwarding_cost_ratio"])), 1.0)
        self.assertEqual(rows[0]["nlsr_control_bytes"], 10)

    def test_rates_use_event_duration_and_final_handoff_uses_capture_end(self) -> None:
        packets = [
            packet(10.0, "core", True, "data", CONTENT, length=100),
            packet(12.0, "consumer", False, "data", CONTENT, length=50),
            packet(30.0, "core", True, "data", CONTENT, length=100),
        ]
        handoffs = [
            metrics.Handoff(1, 10.0, "acc2", "acc3"),
            metrics.Handoff(2, 20.0, "acc3", "acc4"),
        ]
        rows = metrics.measure_run(packets, handoffs, "G0", "g0", "r1")
        self.assertAlmostEqual(float(str(rows[0]["event_duration_s"])), 10.0)
        self.assertAlmostEqual(float(str(rows[1]["event_duration_s"])), 10.0)
        self.assertEqual(rows[1]["event_end_time"], 30.0)
        self.assertAlmostEqual(float(str(rows[0]["application_forwarding_rate_bytes_per_s"])), 10.0)
        self.assertAlmostEqual(float(str(rows[1]["application_forwarding_rate_bytes_per_s"])), 10.0)

    def test_missing_recovery_is_reported(self) -> None:
        packets = [packet(12.0, "consumer", True, "interest", CONTENT)]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        audit = metrics.format_audit(rows)
        self.assertIn("RIGHT_CENSORED", audit)
        self.assertIn("handoff 1", audit)
        self.assertEqual(len(rows), 1)

    def test_inbound_is_not_treated_as_consumer_send(self) -> None:
        packets = [
            packet(11.1, "consumer", False, "interest", CONTENT),
            packet(11.2, "producer", False, "interest", CONTENT),
            packet(11.3, "producer", True, "data", CONTENT),
            packet(11.4, "consumer", False, "data", CONTENT),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertFalse(rows[0]["recovered"])

    def test_censored_srt_is_retained_and_excluded_from_quartiles(self) -> None:
        from matplotlib.cbook import boxplot_stats
        packets = [packet(12.0, "consumer", True, "interest", CONTENT)]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G1", "g1", "r1", frame_period_ms=20)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["recovered"])
        self.assertEqual(rows[0]["service_recovery_time_ms"], "")
        boundary = metrics.srt_censor_boundary_ms(rows[0])
        self.assertAlmostEqual(float(str(boundary)), 1000.0)
        observed = [100.0, 200.0, 300.0, 400.0]
        stats = boxplot_stats(observed, whis=1.5)[0]
        self.assertNotIn(boundary, observed)
        self.assertLess(float(stats["q3"]), float(str(boundary)))

    def test_content_loss_fraction_counts_unique_frames(self) -> None:
        frame_a = "/LiveStream/v0/54=%01/50=%00"
        frame_b = "/LiveStream/v0/54=%02/50=%00"
        packets = [
            packet(11.02, "consumer", False, "data", frame_a, length=40),
            packet(11.04, "consumer", False, "data", frame_a, length=40),
            packet(11.06, "consumer", False, "data", frame_b, length=40),
            packet(11.08, "consumer", False, "data", GUARD, length=40),
            packet(11.09, "consumer", False, "data", META, length=40),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1", frame_period_ms=20)
        self.assertEqual(rows[0]["delivered_unique_content_frames"], 2)
        self.assertAlmostEqual(float(str(rows[0]["event_duration_s"])), 0.09)
        self.assertAlmostEqual(float(str(rows[0]["nominal_frame_opportunities"])), 0.09 * 1000.0 / 20.0)
        self.assertAlmostEqual(float(str(rows[0]["nominal_frame_rate_fps"])), 50.0)
        expected_ratio = 2.0 / (0.09 * 1000.0 / 20.0)
        self.assertAlmostEqual(float(str(rows[0]["content_delivery_ratio"])), expected_ratio)
        self.assertAlmostEqual(float(str(rows[0]["content_loss_fraction"])), 1.0 - expected_ratio)

    def test_single_segment_assumption_is_explicit(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "params.txt"
            path.write_text("segments_per_frame=2\nrequest_interval_ms=20\n", encoding="utf-8")
            with self.assertRaises(metrics.MobilityMetricError):
                metrics.load_run_config(str(path))
            path.write_text("segments_per_frame=1\nrequest_interval_ms=20\n", encoding="utf-8")
            self.assertEqual(metrics.load_run_config(str(path)), (1, 20))

    def test_log_axis_lower_bound_is_strictly_positive(self) -> None:
        import plot_mobility_event_metrics as plots
        low, high = plots.positive_log_bounds([168.0, 49700.0, 606.3])
        self.assertGreater(low, 0.0)
        self.assertGreater(high, 606.3)
        self.assertLess(low, 168.0)

    def test_extreme_fcr_remains_in_plotted_values(self) -> None:
        import plot_mobility_event_metrics as plots
        rows = []
        for index in range(39):
            rows.append({"configuration": "G1", "forwarding_cost_ratio": "6.89", "service_recovery_time_ms": "1000", "event_duration_s": "100", "recovered": "True"})
        rows.append({"configuration": "G1", "forwarding_cost_ratio": "606.3", "service_recovery_time_ms": "", "event_duration_s": "94.3", "recovered": "False"})
        _labels, data, _notes, counts = plots.groups_for(rows, ["G1"], "forwarding_cost_ratio")
        self.assertEqual(counts, [40])
        self.assertIn(606.3, data[0])
        self.assertEqual(len(data[0]), 40)

    def test_missing_raw_capture_fails_without_a_substitute(self) -> None:
        import run_mobility_event_analysis as analysis
        missing = Path("results/__missing_raw_probe__/consumer_capture.pcap")
        with self.assertRaises(metrics.MobilityMetricError) as caught:
            analysis.require_raw([missing])
        self.assertIn("required raw capture missing", str(caught.exception))
        self.assertIn(str(missing), str(caught.exception))

    def test_decoder_mismatch_is_not_ignored(self) -> None:
        import audit_decoder_parity as parity
        reference = {
            "frame.time_epoch": "1.0", "frame.len": "10", "sll.pkttype": "4",
            "ndn.type": "Interest", "ndn.name": "/LiveStream/v0/54=%01/50=%00",
            "ndn.flood_id": "", "ndn.lp.hoplimit": "", "ndn.lp.mobility_flag": "", "ndn.hoplimit": "",
        }
        candidate = dict(reference)
        candidate["ndn.name"] = "/LiveStream/v0/54=%02/50=%00"
        found = parity.row_mismatches(reference, candidate)
        self.assertTrue(any(item.startswith("ndn.name:") for item in found))

    def test_uri_spellings_are_the_same_semantic_name(self) -> None:
        tshark = "/LiveStream/v0/54=0/50=%00"
        python_form = "/LiveStream/v0/54=%30/50=%00"
        self.assertTrue(metrics.names_equal(tshark, python_form))
        self.assertEqual(metrics.parse_name(tshark)[2], (54, b"0"))
        self.assertEqual(metrics.parse_name(python_form)[3][0], 50)
        self.assertEqual(metrics.content_frame_id(tshark), metrics.content_frame_id(python_form))

    def test_generic_percent_spellings_match(self) -> None:
        left = "/%C1.Router"
        right = "/%C1%2E%52%6F%75%74%65%72"
        self.assertEqual(metrics.parse_name(left), metrics.parse_name(right))

    def test_direction_and_duplicate_egress(self) -> None:
        self.assertTrue(metrics.is_sender_egress("4"))
        self.assertFalse(metrics.is_sender_egress("0"))
        import tempfile
        content = "/LiveStream/v0/54=%01/50=%00"
        header = "node,frame.number,frame.time_epoch,frame.len,sll.pkttype,ndn.type,ndn.name,ndn.hoplimit,ndn.lp.hoplimit,ndn.lp.mobility_flag,ndn.flood_id\n"
        body = (
            f"core,1,11.1,30,4,interest,{content},,,,\n"
            f"core,1,11.1,30,4,interest,{content},,,,\n"
            f"core,1,11.1,30,0,interest,{content},,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packets.csv"
            path.write_text(header + body, encoding="utf-8")
            packets = metrics.load_packets(str(path))
        self.assertEqual(len(packets), 2)
        egress = [packet for packet in packets if packet.outbound]
        self.assertEqual(len(egress), 1)
        self.assertEqual(egress[0].length, 30)

    def test_srt_matches_alternate_uri_spellings(self) -> None:
        interest = "/LiveStream/v0/54=1/50=%00"
        data = "/LiveStream/v0/54=%31/50=%00"
        packets = [
            packet(11.1, "consumer", True, "interest", interest),
            packet(11.2, "producer", False, "interest", interest),
            packet(11.3, "producer", True, "data", data),
            packet(11.4, "consumer", False, "data", data),
        ]
        rows = metrics.measure_run(packets, [metrics.Handoff(1, 11.0, "acc2", "acc3")], "G0", "g0", "r1")
        self.assertTrue(rows[0]["recovered"])
        self.assertAlmostEqual(float(str(rows[0]["service_recovery_time_ms"])), 400.0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
