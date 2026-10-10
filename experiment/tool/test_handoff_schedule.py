#!/usr/bin/env python3
"""Host-side checks for explicit handoff interval lists. No Mini-NDN import."""

from __future__ import annotations

import sys
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


if __name__ == "__main__":
    raise SystemExit(unittest.main())
