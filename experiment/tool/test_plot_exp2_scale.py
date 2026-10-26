#!/usr/bin/env python3
"""Host-side checks for the Exp2 scalability figures."""

from __future__ import annotations

import csv
import statistics
import sys
import unittest
from pathlib import Path
from typing import Sequence, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plot_exp2_scale as plots

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "results" / "extended" / "exp2" / "analysis"


def _load(name: str):
    with (ANALYSIS / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class Exp2PlotTest(unittest.TestCase):
    network: list
    consumer: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.network = _load("network_handoffs.csv")
        cls.consumer = _load("consumer_handoffs.csv")

    def test_srt_axis_is_linear_and_contains_every_observation(self) -> None:
        values = [float(row["service_recovery_time_ms"]) for row in self.network]
        figure = plots._population_panel(
            "",
            self.network,
            "service_recovery_time_ms",
            "Service recovery time (ms)",
            ["N=1", "N=2", "N=4"],
            "Configuration",
        )
        axis = figure.axes[0]
        self.assertEqual(axis.get_yscale(), "linear")
        bottom, top = axis.get_ylim()
        self.assertEqual(bottom, 0.0)
        self.assertGreaterEqual(top, max(values))
        self.assertLessEqual(bottom, min(values))
        self.assertEqual([tick.get_text() for tick in axis.get_xticklabels()], ["N=1", "N=2", "N=4"])
        figure.clf()

    def test_clf_panels_keep_every_observation_and_omit_means(self) -> None:
        positions, data, labels, _centers = plots.clf_series(self.consumer)
        full, zoom = plots.clf_axis_limits(data)
        flat = [value for values in data for value in values]
        medians = [statistics.median(values) for values in data]
        self.assertEqual(labels, ["C1", "C1", "C2", "C1", "C2", "C3", "C4"])
        self.assertEqual(plots.group_medians(data), medians)
        self.assertLess(full[0], min(flat))
        self.assertGreater(full[1], max(flat))
        self.assertLess(zoom[0], min(flat))
        self.assertLess(zoom[1], max(flat))
        self.assertGreater(zoom[1], max(data[0]))
        figure = plots._clf_figure("", self.consumer)
        left, right = figure.axes
        self.assertEqual(len(left.patches), 7)
        self.assertEqual(left.get_ylim(), full)
        self.assertEqual(right.get_ylim(), zoom)
        self.assertEqual(len(right.patches), 0)
        self.assertEqual(len(right.collections), 7)
        self.assertEqual(len(right.lines), 7)
        drawn: list = []
        for line in left.lines:
            drawn.extend(float(value) for value in cast(Sequence[float], line.get_ydata()))
        self.assertIn(min(flat), drawn)
        self.assertIn(max(flat), drawn)
        for position, values, median, collection, line in zip(
            positions, data, medians, right.collections, right.lines,
        ):
            offsets = cast(Sequence[Sequence[float]], collection.get_offsets())
            self.assertEqual([float(point[1]) for point in offsets], values)
            self.assertTrue(all(abs(float(point[0]) - position) <= 0.18 for point in offsets))
            self.assertEqual([float(value) for value in cast(Sequence[float], line.get_ydata())], [median, median])
            visible = [value for value in values if zoom[0] <= value <= zoom[1]]
            if len(visible) != len(values):
                self.assertNotEqual(statistics.median(visible), median)
        for axis in figure.axes:
            self.assertFalse(any(line.get_marker() == "D" for line in axis.lines))
            self.assertEqual([tick.get_text() for tick in axis.get_xticklabels()], labels)
        figure.clf()

    def test_rfv_and_nlsr_inputs_are_unchanged_by_limits(self) -> None:
        interest = {row["recovery_interest_flood_bytes"] for row in self.network}
        nodes = {(row["configuration"], row["physical_capture_nodes"]) for row in self.network}
        self.assertEqual(interest, {"0"})
        self.assertEqual(nodes, {("N=1", "11"), ("N=2", "12"), ("N=4", "14")})
        rfv = [float(row["recovery_flood_bytes"]) for row in self.network]
        rate = [float(row["nlsr_control_rate_bytes_per_s"]) for row in self.network]
        rfv_figure = plots._population_panel(
            "", self.network, "recovery_flood_bytes", "RFV", ["N=1", "N=2", "N=4"], "Configuration",
        )
        nlsr_figure = plots._population_panel(
            "", self.network, "nlsr_control_rate_bytes_per_s", "NLSR",
            ["N=1\n11 nodes", "N=2\n12 nodes", "N=4\n14 nodes"], "note",
        )
        self.assertGreaterEqual(rfv_figure.axes[0].get_ylim()[1], max(rfv))
        self.assertGreaterEqual(nlsr_figure.axes[0].get_ylim()[1], max(rate))
        self.assertEqual(rfv_figure.axes[0].get_yscale(), "linear")
        self.assertEqual(nlsr_figure.axes[0].get_yscale(), "linear")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
