#!/usr/bin/env python3
"""Host-side checks for the Shared-versus-Distinct comparison figures."""

from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path
from typing import Sequence, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plot_exp2_comparison as comparison

ROOT = Path(__file__).resolve().parents[2]


class ComparisonPlotTest(unittest.TestCase):
    tables: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = comparison.load_tables(ROOT)
        comparison.validate(cls.tables)

    def test_five_configurations_keep_every_network_observation(self) -> None:
        grouped = [
            comparison.network_rows(self.tables, source, configuration)
            for _label, configuration, source, _pattern in comparison.CONFIGS
        ]
        self.assertEqual([len(rows) for rows in grouped], [40, 40, 40, 40, 40])
        self.assertEqual([label for label, _configuration, _source, _pattern in comparison.CONFIGS][0], "N=1 Solution")
        self.assertEqual(sum(1 for row in self.tables["distinct_network"] if row["configuration"] == "N=1"), 0)
        rfv = []
        for rows in grouped:
            rfv.append([float(row["recovery_flood_bytes"]) for row in rows])
        figure = comparison._metric_figure(
            "", rfv, [[] for _rows in grouped], grouped, "recovery_flood_bytes", False, "RFV", "note",
        )
        axis = figure.axes[0]
        self.assertEqual(axis.get_yscale(), "linear")
        self.assertEqual(axis.get_ylim()[0], 0.0)
        self.assertGreaterEqual(axis.get_ylim()[1], max(max(values) for values in rfv))
        self.assertEqual(len(axis.get_xticks()), 5)
        marks = [line for line in axis.lines if str(line.get_gid() or "").startswith("run-median-")]
        box_z = max(patch.get_zorder() for patch in axis.patches)
        self.assertEqual(len(marks), 25)
        self.assertTrue(all(line.get_zorder() > box_z for line in marks))
        def _x(line: object) -> float:
            data = cast(Sequence[float], getattr(line, "get_xdata")())
            return float(data[0])

        for position in range(5):
            xs = sorted(_x(line) for line in marks if abs(_x(line) - position) < 0.4)
            self.assertEqual(len(xs), 5)
            self.assertGreater(min(xs[index + 1] - xs[index] for index in range(4)), 0.05)
        self.assertEqual([line.get_marker() for line in marks[:5]], list(comparison.RUN_MARKERS))
        figure.clf()

    def test_srt_keeps_measured_values_and_reports_censoring_separately(self) -> None:
        rows = list(comparison.network_rows(self.tables, "shared", "N=1"))
        observed, censored = comparison.measured_srt(rows)
        self.assertEqual(len(observed) + len(censored), 40)
        self.assertEqual(censored, [])
        blank = dict(rows[0])
        blank["recovered"] = "false"
        blank["service_recovery_time_ms"] = ""
        blank["srt_censor_boundary_ms"] = "1000"
        measured, boundaries = comparison.measured_srt(rows[:1] + [blank])
        self.assertEqual(len(measured), 1)
        self.assertEqual(boundaries, [1000.0])
        self.assertNotIn(0.0, measured)

    def test_clf_groups_keep_consumers_separate_and_negative_values(self) -> None:
        labels, series, centers = comparison.clf_groups(self.tables)
        self.assertEqual(labels, ["C1", "C2", "C1", "C2", "C1", "C2", "C3", "C4", "C1", "C2", "C3", "C4"])
        self.assertEqual([title for _center, title in centers], [
            "N=2 Shared", "N=2 Distinct", "N=4 Shared", "N=4 Distinct",
        ])
        flat = [value for values in series for value in values]
        self.assertEqual(len(flat), 80 + 80 + 160 + 160)
        self.assertLess(min(flat), 0.0)
        full, zoom = comparison.clf_limits(series)
        self.assertLess(full[0], min(flat))
        self.assertGreater(full[1], max(flat))
        self.assertLess(zoom[0], min(flat))
        self.assertGreater(zoom[1], max(statistics.median(values) for values in series))
        figure = comparison._clf_figure("", labels, series, centers)
        self.assertEqual(figure.axes[0].get_ylim(), full)
        offsets = cast(Sequence[Sequence[float]], figure.axes[1].collections[0].get_offsets())
        self.assertEqual([float(point[1]) for point in offsets], series[0])
        figure.clf()

    def test_summary_separates_run_medians_and_copies_shortfall_warnings(self) -> None:
        lines, records = comparison.summary_rows(self.tables)
        text = "\n".join(lines)
        self.assertIn("correlated handoffs", text)
        self.assertIn("No significance test", text)
        self.assertEqual(sum(1 for row in records if row["record_type"] == "run_median" and row["metric"] == "recovery_flood_bytes"), 25)
        self.assertEqual(sum(1 for row in records if row["record_type"] == "stream_recovery"), 6)
        self.assertTrue(any(row["note"].startswith("SHORTFALL ") for row in records))
        self.assertIn("SHORTFALL N=2 r1", text)
        self.assertIn("Shared/Solution audit records no SHORTFALL warnings.", text)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
