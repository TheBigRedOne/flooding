#!/usr/bin/env python3
"""Host-side checks for explicit handoff interval lists. No Mini-NDN import."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import handoff_schedule as schedule
import run_sensitivity_analysis as sensitivity


SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "extended" / "sensitivity_handoff_intervals.txt"
FULL_SCHEDULE = [
    111.011, 129.726, 92.531, 139.894, 105.427, 114.084, 111.401, 127.619, 100.418,
]


class HandoffScheduleTest(unittest.TestCase):
    def test_repository_schedule_is_nine_values_for_eight_handoffs(self) -> None:
        text = SCHEDULE_PATH.read_text(encoding="utf-8").strip()
        parsed = schedule.parse_explicit_intervals(text, 8)
        self.assertEqual(parsed, FULL_SCHEDULE)
        self.assertTrue(all(90.0 <= value <= 150.0 for value in parsed))
        self.assertEqual(schedule.format_intervals(parsed), text)

    def test_blank_environment_keeps_random_sampling(self) -> None:
        self.assertIsNone(schedule.intervals_from_env(None, 8))
        self.assertIsNone(schedule.intervals_from_env("  ", 8))

    def test_smoke_list_matches_one_handoff_plus_tail(self) -> None:
        self.assertEqual(schedule.parse_explicit_intervals("6,6", 1), [6.0, 6.0])

    def test_length_must_include_the_tail(self) -> None:
        with self.assertRaises(ValueError):
            schedule.parse_explicit_intervals("1,2,3,4,5,6,7,8", 8)

    def test_negative_and_empty_fields_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            schedule.parse_explicit_intervals("10,-1,12", 2)
        with self.assertRaises(ValueError):
            schedule.parse_explicit_intervals("10,,12", 2)
        with self.assertRaises(ValueError):
            schedule.parse_explicit_intervals("10,fast,12", 2)


class SensitivityRetentionTest(unittest.TestCase):
    def test_failed_verification_is_not_counted_as_established(self) -> None:
        self.assertFalse(sensitivity.verification_established(
            "verification did not establish old UNREACHABLE and new REACHABLE",
            "12",
            "10",
            "11",
        ))
        self.assertFalse(sensitivity.verification_established(
            "no mobility verification completion",
            "",
            "",
            "",
        ))
        self.assertTrue(sensitivity.verification_established("", "20", "15", "18"))

    def test_full_cells_are_eight_handoff_studies(self) -> None:
        self.assertEqual([cell for cell, _value in sensitivity.SYNC_CELLS], ["d0", "d1", "d2", "d4"])
        self.assertEqual([cell for cell, _value in sensitivity.TIMEOUT_CELLS], ["t10", "t25", "t50", "t100", "t250"])

    def test_pcap_directory_is_not_rejected_for_being_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "params.txt").write_text("request_interval_ms=20\n", encoding="utf-8")
            (run / "handoffs.txt").write_text("index\n", encoding="utf-8")
            (run / "pcap_nodes").mkdir()
            files, directories = sensitivity.cell_evidence(run)
            missing = sensitivity.missing_evidence(files, directories)
            self.assertNotIn(f"required sensitivity evidence missing: {run / 'pcap_nodes'}", missing)
            self.assertIn(f"required sensitivity evidence missing: {run / 'pcap_nodes' / 'producer.pcap'}", missing)
            self.assertTrue(any(path.name == "producer.pcap" for path in files))

    def test_missing_pcap_directory_is_reported_as_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            files, directories = sensitivity.cell_evidence(run)
            missing = sensitivity.missing_evidence(files, directories)
            self.assertIn(f"required sensitivity evidence missing: {run / 'pcap_nodes'}", missing)
            self.assertIn(f"required sensitivity evidence missing: {run / 'pcap_nodes' / 'acc2.pcap'}", missing)

    def test_timeout_status_keeps_failed_events_in_the_total(self) -> None:
        rows = [
            {
                "cell": "t10",
                "verification_established": True,
                "topology_update_latency_ms": "100",
                "service_path_fib_convergence_ms": "200",
                "network_fib_convergence_ms": "300",
                "network_fib_converged": "true",
            },
            {
                "cell": "t10",
                "verification_established": False,
                "topology_update_latency_ms": "",
                "service_path_fib_convergence_ms": "",
                "network_fib_convergence_ms": "",
                "network_fib_converged": "false",
            },
        ]
        text = sensitivity.timeout_cell_status("t10", rows)
        self.assertIn("events=2", text)
        self.assertIn("verification_established=1", text)
        self.assertIn("topology_numeric=1", text)
        self.assertIn("service_fib_numeric=1", text)
        self.assertIn("network_fib_numeric=1", text)
        self.assertIn("network_right_censored=1", text)
        self.assertIn("verification_not_established=1", text)

    def test_default_cross_check_reads_supplied_rows_only(self) -> None:
        main_mobility = [
            {"configuration": "OptoFlood", "service_recovery_time_ms": "80"},
            {"configuration": "OptoFlood", "service_recovery_time_ms": "100"},
            {"configuration": "G0", "service_recovery_time_ms": "50000"},
        ]
        main_routing = [
            {"configuration": "OptoFlood", "topology_update_latency_ms": "150", "service_path_fib_convergence_ms": "250", "network_fib_convergence_ms": "1400"},
            {"configuration": "OptoFlood", "topology_update_latency_ms": "170", "service_path_fib_convergence_ms": "260", "network_fib_convergence_ms": "1600"},
        ]
        d1 = [{"cell": "d1", "topology_update_latency_ms": "160", "service_path_fib_convergence_ms": "255", "network_fib_convergence_ms": "1500", "service_recovery_time_ms": "90"}]
        t50 = [{"cell": "t50", "topology_update_latency_ms": "165", "service_path_fib_convergence_ms": "258", "network_fib_convergence_ms": "1550", "service_recovery_time_ms": "88"}]
        lines = sensitivity.default_cross_check_lines(main_mobility, main_routing, d1, t50)
        srt = next(line for line in lines if line.startswith("SRT:"))
        self.assertIn("main_n=2", srt)
        self.assertIn("main_median=90", srt)
        self.assertIn("d1_median=90", srt)
        self.assertIn("t50_median=88", srt)
        self.assertNotIn("50000", srt)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
