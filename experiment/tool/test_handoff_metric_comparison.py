#!/usr/bin/env python3
"""Structural checks for the 5x8 per-handoff comparison aggregator."""

from __future__ import annotations

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import handoff_metric_comparison as cmp


PROFILES = (
    "g0-h60-a10-r15-s60",
    "g1-h54-a9-r14-s54",
    "g2-h48-a8-r12-s48",
    "g3-h42-a7-r10-s42",
    "g4-h36-a6-r9-s36",
)
FULL_RUN_FCR = "999999.25"
FULL_RUN_CONTROL = "888888"


def disruption_ms(profile_index: int, run_index: int, handoff: int, *, solution: bool) -> float:
    base = 5000 if solution else profile_index * 1000
    return float(base + run_index * 10 + handoff)


def fcr_value(profile_index: int, run_index: int, handoff: int, *, solution: bool) -> float:
    base = 50 if solution else profile_index
    return base + run_index / 10.0 + handoff / 100.0


def control_bytes(profile_index: int, run_index: int, handoff: int, *, solution: bool) -> int:
    base = 70000 if solution else profile_index * 10000
    return base + run_index * 100 + handoff


def _write_disruption(path: Path, profile_index: int, *, solution: bool, handoff_count: int = 8) -> None:
    run_index = int(path.parent.name[1:])
    lines = []
    for handoff in range(1, handoff_count + 1):
        value = disruption_ms(profile_index, run_index, handoff, solution=solution)
        lines.append(f"Handoff {handoff} Disruption Time: {value:.2f} ms\n")
    path.write_text("".join(lines), encoding="utf-8")


def _write_overhead(
    path: Path,
    profile_index: int,
    *,
    solution: bool,
    handoff_count: int = 8,
    window: str = "10.00",
    include_handoffs: bool = True,
) -> None:
    run_index = int(path.parent.name[1:])
    lines = [
        "Relay Nodes: core,agg1,agg2,acc1,acc2,acc3,acc4,acc5,acc6\n",
        "Consumer Node: consumer\n",
        f"Handoff Window Seconds: {window}\n",
        "\n",
    ]
    if include_handoffs:
        for handoff in range(1, handoff_count + 1):
            fcr = fcr_value(profile_index, run_index, handoff, solution=solution)
            control = control_bytes(profile_index, run_index, handoff, solution=solution)
            lines.extend([
                f"[Handoff {handoff}]\n",
                f"Forwarding Cost Ratio: {fcr:.2f}\n",
                f"NLSR Control Bytes: {control}\n",
                "\n",
            ])
    lines.extend([
        "[Full Run]\n",
        f"Forwarding Cost Ratio: {FULL_RUN_FCR}\n",
        f"NLSR Control Bytes: {FULL_RUN_CONTROL}\n",
        "\n",
    ])
    path.write_text("".join(lines), encoding="utf-8")


def _write_tree(root: Path) -> None:
    for profile_index, profile in enumerate(PROFILES):
        for run_id in cmp.EXPECTED_RUN_IDS:
            run_dir = root / "baseline" / profile / run_id
            run_dir.mkdir(parents=True)
            _write_disruption(run_dir / "disruption_metrics.txt", profile_index, solution=False)
            _write_overhead(run_dir / "overhead_total.txt", profile_index, solution=False)
    for run_id in cmp.EXPECTED_RUN_IDS:
        run_dir = root / "solution" / run_id
        run_dir.mkdir(parents=True)
        _write_disruption(run_dir / "disruption_metrics.txt", 0, solution=True)
        _write_overhead(run_dir / "overhead_total.txt", 0, solution=True)


def _read_csv(path: Path) -> list:
    with path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


class HandoffMetricComparisonTest(unittest.TestCase):
    def test_valid_baseline_and_solution_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_tree(root)
            baseline_pdf = root / "baseline_disruption.pdf"
            baseline_fcr = root / "baseline_fcr.pdf"
            baseline_control = root / "baseline_control.pdf"
            baseline_code = cmp.main([
                "baseline",
                "--root-dir", str(root / "baseline"),
                "--profiles", ",".join(PROFILES),
                "--observations", str(root / "baseline_obs.csv"),
                "--audit", str(root / "baseline_audit.txt"),
                "--disruption-pdf", str(baseline_pdf),
                "--fcr-pdf", str(baseline_fcr),
                "--control-pdf", str(baseline_control),
            ])
            self.assertEqual(baseline_code, 0)
            rows = _read_csv(root / "baseline_obs.csv")
            self.assertEqual(len(rows), 200)
            self.assertNotIn(FULL_RUN_FCR, (root / "baseline_obs.csv").read_text(encoding="utf-8"))
            self.assertNotIn(FULL_RUN_CONTROL, (root / "baseline_obs.csv").read_text(encoding="utf-8"))
            for profile_index, profile in enumerate(PROFILES):
                label = profile.split("-", 1)[0].upper()
                matched = [row for row in rows if row["configuration"] == label]
                self.assertEqual(len(matched), 40)
                runs = {row["run_id"] for row in matched}
                self.assertEqual(runs, set(cmp.EXPECTED_RUN_IDS))
                sample = next(
                    row for row in matched
                    if row["run_id"] == "r3" and row["handoff_index"] == "4"
                )
                self.assertEqual(sample["source"], profile)
                self.assertAlmostEqual(
                    float(sample["disruption_ms"]),
                    disruption_ms(profile_index, 3, 4, solution=False),
                )
                self.assertAlmostEqual(
                    float(sample["forwarding_cost_ratio"]),
                    fcr_value(profile_index, 3, 4, solution=False),
                )
                self.assertAlmostEqual(
                    float(sample["nlsr_control_bytes"]),
                    float(control_bytes(profile_index, 3, 4, solution=False)),
                )
            audit = (root / "baseline_audit.txt").read_text(encoding="utf-8")
            for metric in ("disruption", "fcr", "nlsr_control_bytes"):
                for label in ("G0", "G1", "G2", "G3", "G4"):
                    self.assertIn(f"{metric} {label}: n=40 ", audit)
                    self.assertIn("mean=", audit)
                    self.assertIn("tukey_outliers=", audit)
            for pdf in (baseline_pdf, baseline_fcr, baseline_control):
                self.assertGreater(pdf.stat().st_size, 500)

            solution_code = cmp.main([
                "solution",
                "--baseline-dir", str(root / "baseline" / PROFILES[0]),
                "--solution-dir", str(root / "solution"),
                "--observations", str(root / "solution_obs.csv"),
                "--audit", str(root / "solution_audit.txt"),
                "--disruption-pdf", str(root / "solution_disruption.pdf"),
                "--fcr-pdf", str(root / "solution_fcr.pdf"),
                "--control-pdf", str(root / "solution_control.pdf"),
            ])
            self.assertEqual(solution_code, 0)
            solution_rows = _read_csv(root / "solution_obs.csv")
            self.assertEqual(len(solution_rows), 80)
            self.assertEqual(
                sum(1 for row in solution_rows if row["configuration"] == "G0"),
                40,
            )
            self.assertEqual(
                sum(1 for row in solution_rows if row["configuration"] == "OptoFlood"),
                40,
            )
            solution_audit = (root / "solution_audit.txt").read_text(encoding="utf-8")
            self.assertIn("disruption G0: n=40 ", solution_audit)
            self.assertIn("disruption OptoFlood: n=40 ", solution_audit)
            self.assertIn("fcr OptoFlood: n=40 ", solution_audit)
            self.assertIn("nlsr_control_bytes OptoFlood: n=40 ", solution_audit)
            opto = next(
                row for row in solution_rows
                if row["configuration"] == "OptoFlood" and row["run_id"] == "r1" and row["handoff_index"] == "1"
            )
            self.assertAlmostEqual(float(opto["forwarding_cost_ratio"]), fcr_value(0, 1, 1, solution=True))
            self.assertNotEqual(float(opto["forwarding_cost_ratio"]), float(FULL_RUN_FCR))

            g0_rows = [row for row in rows if row["configuration"] == "G0"]
            drawn = cmp.metric_groups(g0_rows, ["G0"], "disruption_ms")
            # Rebuild the five baseline groups from the CSV and draw them.
            baseline_groups = cmp.metric_groups(rows, ["G0", "G1", "G2", "G3", "G4"], "forwarding_cost_ratio")
            self.assertEqual(len(baseline_groups), 5)
            figure, axis = cmp.plt.subplots()
            artists = cmp.draw_handoff_boxes(axis, baseline_groups)
            self.assertEqual(len(artists["boxes"]), 5)
            self.assertEqual(len(artists["means"]), 5)
            for mean_artist in artists["means"]:
                self.assertEqual(mean_artist.get_marker(), cmp.MEAN_MARKER)
            cmp.plt.close(figure)
            self.assertEqual(len(drawn[0][1]), 40)

            solution_groups = cmp.metric_groups(
                solution_rows,
                ["G0", "OptoFlood"],
                "nlsr_control_bytes",
            )
            self.assertEqual([label for label, _ in solution_groups], ["G0", "OptoFlood"])
            figure, axis = cmp.plt.subplots()
            solution_artists = cmp.draw_handoff_boxes(axis, solution_groups)
            self.assertEqual(len(solution_artists["boxes"]), 2)
            self.assertEqual(len(solution_artists["means"]), 2)
            cmp.plt.close(figure)

    def test_missing_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_tree(root)
            missing = root / "baseline" / PROFILES[0] / "r3" / "disruption_metrics.txt"
            missing.unlink()
            pdf = root / "should_not_exist.pdf"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = cmp.main([
                    "baseline",
                    "--root-dir", str(root / "baseline"),
                    "--profiles", ",".join(PROFILES),
                    "--observations", str(root / "obs.csv"),
                    "--audit", str(root / "audit.txt"),
                    "--disruption-pdf", str(pdf),
                    "--fcr-pdf", str(root / "fcr.pdf"),
                    "--control-pdf", str(root / "control.pdf"),
                ])
            self.assertEqual(code, 1)
            self.assertIn("r3", stderr.getvalue())
            self.assertIn("missing", stderr.getvalue())
            self.assertNotIn("n=39", stderr.getvalue())
            self.assertFalse(pdf.exists())
            self.assertFalse((root / "obs.csv").exists())

    def test_seven_disruption_observations_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_tree(root)
            short = root / "baseline" / PROFILES[1] / "r2" / "disruption_metrics.txt"
            _write_disruption(short, 1, solution=False, handoff_count=7)
            spec = cmp.SeriesSpec("G1", PROFILES[1], str(root / "baseline" / PROFILES[1]))
            with self.assertRaises(cmp.HandoffMetricError) as caught:
                cmp.load_series_rows(spec, cmp.EXPECTED_RUN_IDS)
            message = str(caught.exception)
            self.assertIn("r2", message)
            self.assertIn("refusing", message)
            self.assertNotIn("n=39", message)
            pdf = root / "should_not_exist.pdf"
            code = cmp.main([
                "baseline",
                "--root-dir", str(root / "baseline"),
                "--profiles", ",".join(PROFILES),
                "--observations", str(root / "obs.csv"),
                "--audit", str(root / "audit.txt"),
                "--disruption-pdf", str(pdf),
                "--fcr-pdf", str(root / "fcr.pdf"),
                "--control-pdf", str(root / "control.pdf"),
            ])
            self.assertEqual(code, 1)
            self.assertFalse(pdf.exists())

    def test_seven_overhead_windows_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_tree(root)
            short = root / "solution" / "r4" / "overhead_total.txt"
            _write_overhead(short, 0, solution=True, handoff_count=7)
            spec = cmp.SeriesSpec("OptoFlood", "solution", str(root / "solution"))
            with self.assertRaises(cmp.HandoffMetricError) as caught:
                cmp.load_series_rows(spec, cmp.EXPECTED_RUN_IDS)
            message = str(caught.exception)
            self.assertIn("r4", message)
            self.assertIn("refusing", message)
            self.assertNotIn("n=39", message)

    def test_full_run_section_is_not_a_handoff_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "r1"
            run_dir.mkdir()
            _write_overhead(
                run_dir / "overhead_total.txt",
                0,
                solution=False,
                include_handoffs=False,
            )
            spec = cmp.SeriesSpec("G0", "g0", str(Path(temporary)))
            with self.assertRaises(cmp.HandoffMetricError) as caught:
                cmp.parse_overhead_file(str(run_dir / "overhead_total.txt"), spec, "r1")
            self.assertIn("refusing", str(caught.exception))
            self.assertNotIn(FULL_RUN_FCR, str(caught.exception))

    def test_non_ten_second_window_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "r1"
            run_dir.mkdir()
            _write_overhead(run_dir / "overhead_total.txt", 0, solution=False, window="20.00")
            spec = cmp.SeriesSpec("G0", "g0", str(Path(temporary)))
            with self.assertRaises(cmp.HandoffMetricError) as caught:
                cmp.parse_overhead_file(str(run_dir / "overhead_total.txt"), spec, "r1")
            self.assertIn("20.0", str(caught.exception))
            self.assertIn("10", str(caught.exception))

    def test_tukey_whiskers_are_not_min_max_and_mean_marker_is_drawn(self) -> None:
        values = [10.0] * 39 + [1000.0]
        summary = cmp.summarise_values(values)
        self.assertEqual(summary["n"], 40)
        self.assertEqual(summary["min"], 10.0)
        self.assertEqual(summary["max"], 1000.0)
        self.assertNotEqual(summary["whishi"], summary["max"])
        self.assertEqual(summary["tukey_outliers"], [1000.0])
        self.assertAlmostEqual(summary["mean"], (39 * 10.0 + 1000.0) / 40.0)
        figure, axis = cmp.plt.subplots()
        artists = cmp.draw_handoff_boxes(axis, [("G0", values)])
        whisker_ends: list[float] = []
        for line in artists["whiskers"]:
            whisker_ends.extend(float(point) for point in line.get_ydata())
        self.assertNotIn(1000.0, whisker_ends)
        self.assertIn(1000.0, [float(point) for point in artists["fliers"][0].get_ydata()])
        self.assertEqual(artists["means"][0].get_marker(), "D")
        mean_y = float(artists["means"][0].get_ydata()[0])
        self.assertAlmostEqual(mean_y, summary["mean"])
        cmp.plt.close(figure)

    def test_run_list_must_be_the_five_named_runs(self) -> None:
        with self.assertRaises(cmp.HandoffMetricError):
            cmp.parse_run_ids("r1,r2,r3,r4")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
