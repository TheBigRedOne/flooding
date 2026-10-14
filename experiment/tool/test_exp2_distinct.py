#!/usr/bin/env python3
"""Host-side Exp2(b) Distinct Streams checks. Fixtures are synthetic."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_exp2_shared_evidence as checker
import exp2_shared_config as config
import run_exp2_shared_analysis as shared_analysis

HANDOFF = 1_700_000_000.0
REPO = Path(__file__).resolve().parents[2]


def _content_name(prefix: str) -> str:
    return f"{prefix}/54=%01/50=%00"


def _populate(root: Path, consumers: tuple, pattern: str, mode: str = "smoke") -> Path:
    run_dir = root / config.population_of(consumers) / ("smoke" if mode == "smoke" else "r1")
    sequence = config.SMOKE_HANDOFF_SEQUENCE if mode == "smoke" else config.FULL_HANDOFF_SEQUENCE
    count = 1 if mode == "smoke" else 8
    run_id = "smoke" if mode == "smoke" else "r1"
    for name in config.result_names(consumers):
        path = run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".pcap"):
            path.write_bytes(b"pcap-bytes-beyond-global-header")
        elif name.startswith("tcpdump_"):
            path.write_text("", encoding="utf-8")
        else:
            path.write_text("placeholder\n", encoding="utf-8")
    (run_dir / "campaign.txt").write_text(
        config.campaign_text(consumers, mode, run_id, pattern), encoding="utf-8",
    )
    (run_dir / "topology.txt").write_text(
        config.topology_text(consumers, sequence, pattern), encoding="utf-8",
    )
    intervals = [20.0, 30.0] if mode == "smoke" else [90.0 + index for index in range(count + 1)]
    mapping = config.stream_mapping(pattern, consumers)
    params = {
        "exp2_experiment": pattern,
        "exp2_demand_pattern": pattern,
        "exp2_active_consumers": ",".join(consumers),
        "exp2_schedule": mode,
        "exp2_campaign": config.campaign_id_for(pattern),
        "exp2_interval_source": "configured" if mode == "smoke" else "sampled",
        "exp2_realized_intervals_s": ",".join(f"{value:.6f}" for value in intervals),
        "handoff_sequence": ",".join(sequence),
        "handoff_count": str(count),
        "handoff_interval_base_s": "20.000" if mode == "smoke" else "90.000",
        "handoff_interval_jitter_s": "0.000" if mode == "smoke" else "60.000",
        "request_interval_ms": "20",
        "segments_per_frame": "1",
        "window_frames": "4",
        "guard_interval_ms": "1000",
        "neighbors.result-driven-adj-lsa-build": "on",
        "neighbors.event-driven-adjacency-verification": "on",
        "neighbors.corridor-prioritised-routing": "on",
        "neighbors.corridor-adj-lsa-sync-publish-delay": "1",
        "neighbors.event-driven-verification-timeout-ms": "50",
        "exp2_stream_map": config.format_stream_map(mapping),
        "exp2_advertised_prefix": config.ADVERTISED_PREFIX,
        "exp2_guard_name": config.GUARD_NAME,
    }
    if pattern == "shared":
        params["exp2_stream_prefix"] = config.STREAM_PREFIX
    (run_dir / "params.txt").write_text(
        "".join(f"{key}={value}\n" for key, value in params.items()), encoding="utf-8",
    )
    handoff_lines = ["index\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n"]
    for index in range(count):
        stamp = HANDOFF + index * 10.0
        handoff_lines.append(
            f"{index + 1}\t{stamp:.6f}\t{index * 10.0:.6f}\t"
            f"{sequence[index]}\t{sequence[index + 1]}\t{intervals[index]:.6f}\n"
        )
    (run_dir / "handoffs.txt").write_text("".join(handoff_lines), encoding="utf-8")
    if mode == "smoke":
        _write_smoke_logs(run_dir, consumers, mapping)
    return run_dir


def _write_smoke_logs(run_dir: Path, consumers: tuple, mapping: dict) -> None:
    stamp = int((HANDOFF + 1.0) * 1e9)
    interest_lines = []
    data_lines = []
    for prefix in mapping.values():
        name = _content_name(prefix)
        interest_lines.append(
            f"[{stamp}] INTEREST: Received #1 Name: {name} CanBePrefix: 0 MustBeFresh: 1\n"
        )
        data_lines.append(
            f"[{stamp}] DATA: Sending response Size: 100 bytes Name: {name}\n"
        )
    (run_dir / "producer.log").write_text(
        "[1] PREFIX: Successfully registered prefix: /LiveStream\n"
        "[1] PREFIX: Advertising prefix via NLSR\n"
        + "".join(interest_lines)
        + "".join(data_lines),
        encoding="utf-8",
    )
    (run_dir / "optoflood_producer.log").write_text(
        "[1] STARTUP: OptoFlood daemon role='producer' prefix=/LiveStream pid=1\n"
        "[1] GUARD-PRODUCER: registered guard prefix /LiveStream/_guard\n",
        encoding="utf-8",
    )
    for consumer in consumers:
        name = _content_name(mapping[consumer])
        (run_dir / f"{consumer}.log").write_text(
            f"[{stamp}] DATA: frame=1 seg=0 Size: 100 bytes\n"
            f"[{stamp}] VALIDATE: Data signature verified name={name} id={consumer}\n",
            encoding="utf-8",
        )
        (run_dir / f"optoflood_{consumer}.log").write_text(
            f"[1] STARTUP: OptoFlood daemon role='consumer' prefix=/LiveStream pid=1\n"
            f"[1] GUARD-CONSUMER: name=/LiveStream/_guard interval=1000\n",
            encoding="utf-8",
        )


class Exp2DistinctConfigTest(unittest.TestCase):
    def test_shared_mapping_and_process_environment_stay_unchanged(self) -> None:
        n2 = config.parse_active_consumers("n2")
        n4 = config.parse_active_consumers("n4")
        self.assertEqual(config.stream_mapping("shared", n2), {"consumer1": "/LiveStream/v0", "consumer2": "/LiveStream/v0"})
        self.assertEqual(
            config.stream_mapping("shared", n4),
            {name: "/LiveStream/v0" for name in n4},
        )
        environments = config.process_environments("shared", n2, 20, 4, 1)
        shared = (
            "EXP_REQUEST_INTERVAL_MS=20 EXP_WINDOW_FRAMES=4 EXP_SEGMENTS_PER_FRAME=1 "
            "EXP_STREAM_PREFIX=/LiveStream/v0 EXP_LOG_VALIDATION_NAME=1"
        )
        self.assertEqual(environments["producer"], shared)
        self.assertEqual(environments["consumer1"], shared + " EXP_CONSUMER_ID=consumer1")
        self.assertEqual(environments["consumer2"], shared + " EXP_CONSUMER_ID=consumer2")
        self.assertEqual(config.campaign_id_for("shared"), "shared-n2-n4")
        self.assertIn("exp2_campaign=shared-n2-n4", config.campaign_text(n2, "full", "r1"))
        self.assertIn("stream_prefix=/LiveStream/v0", config.topology_text(n2))

    def test_distinct_stream_mapping_and_single_recovery_prefix(self) -> None:
        n2 = config.parse_active_consumers("n2")
        n4 = config.parse_active_consumers("n4")
        self.assertEqual(
            config.stream_mapping("distinct", n2),
            {"consumer1": "/LiveStream/v0", "consumer2": "/LiveStream/v1"},
        )
        self.assertEqual(
            config.stream_mapping("distinct", n4),
            {
                "consumer1": "/LiveStream/v0",
                "consumer2": "/LiveStream/v1",
                "consumer3": "/LiveStream/v2",
                "consumer4": "/LiveStream/v3",
            },
        )
        self.assertEqual(len(set(config.stream_mapping("distinct", n4).values())), 4)
        for pattern in ("shared", "distinct"):
            for consumers in (n2, n4):
                text = config.topology_text(consumers, pattern=pattern)
                self.assertIn("advertised_prefix=/LiveStream\n", text)
                self.assertIn("guard_name=/LiveStream/_guard\n", text)
                self.assertEqual(config.physical_hosts(consumers).count("producer"), 1)
                self.assertNotIn("/_guard", config.format_stream_map(config.stream_mapping(pattern, consumers)))
                for forbidden in config.PER_STREAM_GUARD_NAMES:
                    self.assertNotIn(forbidden, text)
                self.assertNotIn("advertised_prefix=/LiveStream/v", text)
        environments = config.process_environments("distinct", n4, 20, 4, 1)
        self.assertNotIn("EXP_STREAM_PREFIX=", environments["producer"])
        self.assertIn("EXP_REQUEST_INTERVAL_MS=20", environments["producer"])
        self.assertIn("EXP_STREAM_PREFIX=/LiveStream/v0 ", environments["consumer1"])
        self.assertIn("EXP_STREAM_PREFIX=/LiveStream/v1 ", environments["consumer2"])
        self.assertIn("EXP_STREAM_PREFIX=/LiveStream/v2 ", environments["consumer3"])
        self.assertIn("EXP_STREAM_PREFIX=/LiveStream/v3 ", environments["consumer4"])
        self.assertNotIn("/LiveStream/v1", environments["consumer1"])
        self.assertNotIn("/LiveStream/v0", environments["consumer2"])

    def test_topologies_match_shared_populations(self) -> None:
        for label in ("n2", "n4"):
            consumers = config.parse_active_consumers(label)
            shared = config.topology_text(consumers, pattern="shared")
            distinct = config.topology_text(consumers, pattern="distinct")
            shared_links = [line for line in shared.splitlines() if line.startswith("link ")]
            distinct_links = [line for line in distinct.splitlines() if line.startswith("link ")]
            self.assertEqual(shared_links, distinct_links)
            self.assertEqual(
                [line for line in shared.splitlines() if line.startswith("attachment ")],
                [line for line in distinct.splitlines() if line.startswith("attachment ")],
            )
            self.assertEqual(
                next(line for line in shared.splitlines() if line.startswith("physical_nodes=")),
                next(line for line in distinct.splitlines() if line.startswith("physical_nodes=")),
            )
            self.assertIn("producer", config.physical_hosts(consumers))
            self.assertEqual(config.application_hosts(consumers)[0], "producer")
        n2 = config.parse_active_consumers("n2")
        n4 = config.parse_active_consumers("n4")
        self.assertEqual(len(config.physical_hosts(n2)), 12)
        self.assertEqual(len(config.physical_hosts(n4)), 14)
        self.assertNotIn("consumer3", config.topology_text(n2, pattern="distinct"))
        self.assertNotIn("consumer4", config.topology_text(n2, pattern="distinct"))
        distinct_n4 = config.topology_text(n4, pattern="distinct")
        self.assertIn("attachment consumer1 acc1", distinct_n4)
        self.assertIn("attachment consumer2 acc4", distinct_n4)
        self.assertIn("attachment consumer3 acc3", distinct_n4)
        self.assertIn("attachment consumer4 acc6", distinct_n4)
        self.assertIn("stream consumer2 /LiveStream/v1", distinct_n4)
        self.assertIn("stream consumer4 /LiveStream/v3", distinct_n4)

    def test_ordinary_stream_component_is_not_a_typed_version(self) -> None:
        self.assertTrue(config._content_name("/LiveStream/v1/54=%01/50=%00", "/LiveStream/v1"))
        self.assertFalse(config._content_name("/LiveStream/v0/54=%01/50=%00", "/LiveStream/v1"))
        self.assertFalse(config._content_name("/LiveStream/v10/54=%00/50=%00", "/LiveStream/v1"))
        self.assertFalse(config._content_name("/LiveStream/v1/_meta", "/LiveStream/v1"))
        self.assertNotIn("54=", config.DISTINCT_STREAM_PREFIX["consumer2"])

    def test_invalid_pattern_is_rejected_and_directories_do_not_collide(self) -> None:
        for text in ("", "both", "exp3", "n2"):
            with self.assertRaises(config.Exp2ConfigError):
                config.parse_demand_pattern(text)
        shared_root = config.result_root_for("shared")
        distinct_root = config.result_root_for("distinct")
        self.assertEqual(shared_root, "results/extended/exp2/shared")
        self.assertEqual(distinct_root, "results/extended/exp2/distinct")
        directories = []
        for population in ("n2", "n4"):
            directories.append(config.smoke_directory(shared_root, population))
            directories.append(config.smoke_directory(distinct_root, population))
            for run_id in config.FULL_RUN_IDS:
                directories.append(config.full_run_directory(shared_root, population, run_id))
                directories.append(config.full_run_directory(distinct_root, population, run_id))
        self.assertEqual(len(directories), len(set(directories)))
        self.assertTrue(all(not path.startswith(distinct_root) for path in directories if "/shared/" in path))

    def test_makefile_targets_and_vm_lock(self) -> None:
        makefile = (REPO / "Makefile.exp2").read_text(encoding="utf-8")
        guest = (REPO / "experiment" / "extended" / "exp2" / "Makefile").read_text(encoding="utf-8")
        script = (REPO / "scripts" / "run-in-vm.sh").read_text(encoding="utf-8")
        top = (REPO / "Makefile").read_text(encoding="utf-8")
        self.assertIn("experiment-exp2-shared-n2-smoke:", makefile)
        self.assertIn("experiment-exp2-shared-n4-full:", makefile)
        self.assertIn("check-exp2-shared-$(3)-$(2):", makefile)
        self.assertIn("experiment-exp2-distinct-n2-smoke:", makefile)
        self.assertIn("experiment-exp2-distinct-n4-smoke:", makefile)
        self.assertIn("experiment-exp2-distinct-n2-full:", makefile)
        self.assertIn("experiment-exp2-distinct-n4-full:", makefile)
        self.assertIn("check-exp2-distinct-$(3)-$(2):", makefile)
        self.assertIn("$(EXP2_DISTINCT_ROOT)/n2/smoke", makefile)
        self.assertIn("$(EXP2_DISTINCT_ROOT)/n4/smoke", makefile)
        self.assertIn("--pattern distinct", makefile)
        self.assertIn("analyze-exp2-distinct-n2-r1:", makefile)
        self.assertIn("run_exp2_distinct_analysis.py n2 r1", makefile)
        self.assertIn("run_exp2_distinct_analysis.py n4 r1", makefile)
        self.assertIn("run_exp2_distinct_analysis.py --all", makefile)
        self.assertNotIn("run_exp2_scale_analysis.py --all", makefile)
        smoke_lines = [line for line in makefile.splitlines() if "EXP2_SCHEDULE='smoke'" in line]
        self.assertEqual(len([line for line in smoke_lines if "EXP2_DEMAND_PATTERN" not in line]), 2)
        self.assertEqual(len([line for line in smoke_lines if "EXP2_DEMAND_PATTERN='distinct'" in line]), 2)
        self.assertEqual(makefile.count("EXP2_DEMAND_PATTERN='distinct'"), 3)
        self.assertIn("$(EXP2_N2_NODES)", makefile)
        self.assertIn("$(EXP2_N4_NODES)", makefile)
        self.assertIn("consumer1 consumer2,$(EXP2_N2_NODES)", makefile)
        self.assertIn("consumer3 consumer4,$(EXP2_N4_NODES)", makefile)
        self.assertIn("EXP2_DEMAND_PATTERN ?= shared", guest)
        driver_lines = [line for line in guest.splitlines() if "exp2_shared_driver.py" in line]
        self.assertEqual(len(driver_lines), 1)
        self.assertIn("EXP2_DEMAND_PATTERN='$(EXP2_DEMAND_PATTERN)'", driver_lines[0])
        self.assertIn("refusing to replace existing Exp2 results", script)
        self.assertIn("exp2_lock=${RUN_IN_VM_LOCK:-.exp2-vm.lock}", script)
        self.assertNotIn("experiment-exp2-distinct-n2-full", top)
        self.assertNotIn("experiment-exp2-shared-n2-full", top)


class Exp2DistinctEvidenceTest(unittest.TestCase):
    def test_distinct_smoke_and_full_records_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n2 = config.parse_active_consumers("n2")
            n4 = config.parse_active_consumers("n4")
            smoke = _populate(root, n2, "distinct", "smoke")
            full = _populate(root / "full", n4, "distinct", "full")
            self.assertEqual(config.inspect_run(smoke), [])
            self.assertEqual(config.inspect_run(smoke, expected_pattern="distinct"), [])
            self.assertEqual(checker.main(["--pattern", "distinct", str(smoke)]), 0)
            self.assertEqual(config.inspect_run(full, expected_pattern="distinct"), [])
            text = (smoke / "campaign.txt").read_text(encoding="utf-8")
            self.assertIn("demand_pattern=distinct", text)
            self.assertIn("stream_map=consumer1=/LiveStream/v0,consumer2=/LiveStream/v1", text)
            self.assertIn("advertised_prefix=/LiveStream", text)
            self.assertIn("guard_name=/LiveStream/_guard", text)

    def test_wrong_or_missing_stream_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n4 = config.parse_active_consumers("n4")
            run_dir = _populate(root, n4, "distinct", "smoke")
            stamp = int((HANDOFF + 1.0) * 1e9)
            (run_dir / "consumer2.log").write_text(
                f"[{stamp}] DATA: frame=1 seg=0 Size: 100 bytes\n"
                f"[{stamp}] VALIDATE: Data signature verified name=/LiveStream/v0/54=%01/50=%00 id=consumer2\n",
                encoding="utf-8",
            )
            problems = config.inspect_run(run_dir, expected_pattern="distinct")
            self.assertTrue(any("consumer2" in problem and "assigned stream" in problem for problem in problems))
            (run_dir / "consumer3.log").write_text(
                f"[{stamp}] DATA: frame=1 seg=0 Size: 100 bytes\n",
                encoding="utf-8",
            )
            problems = config.inspect_run(run_dir, expected_pattern="distinct")
            self.assertTrue(any("consumer3" in problem and "validation" in problem for problem in problems))
            producer = (run_dir / "producer.log").read_text(encoding="utf-8")
            (run_dir / "producer.log").write_text(
                producer.replace("/LiveStream/v3/54=%01/50=%00", "/LiveStream/v0/54=%01/50=%00"),
                encoding="utf-8",
            )
            problems = config.inspect_run(run_dir, expected_pattern="distinct")
            self.assertTrue(any("content Data for /LiveStream/v3" in problem for problem in problems))
            daemon = (run_dir / "optoflood_consumer4.log").read_text(encoding="utf-8")
            (run_dir / "optoflood_consumer4.log").write_text(
                daemon + "[1] GUARD-CONSUMER: name=/LiveStream/v3/_guard interval=1000\n",
                encoding="utf-8",
            )
            problems = config.inspect_run(run_dir, expected_pattern="distinct")
            self.assertTrue(any("per-stream guard" in problem for problem in problems))

    def test_shared_results_do_not_satisfy_distinct_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n2 = config.parse_active_consumers("n2")
            shared = _populate(root, n2, "shared", "smoke")
            problems = config.inspect_run(shared, expected_pattern="distinct")
            self.assertTrue(any("demand pattern must be distinct" in problem for problem in problems))
            self.assertEqual(config.inspect_run(shared, expected_pattern="shared"), [])
            self.assertEqual(checker.main([str(shared)]), 0)
            with self.assertRaises(SystemExit) as caught:
                shared_analysis.reject_distinct_run(
                    _populate(root / "other", n2, "distinct", "full"),
                )
            self.assertIn("Distinct Streams", str(caught.exception))
            shared_analysis.reject_distinct_run(shared)

    def test_n2_distinct_rejects_absent_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _populate(Path(tmp), config.parse_active_consumers("n2"), "distinct", "smoke")
            stray = run_dir / "consumer3.log"
            stray.write_text("unexpected\n", encoding="utf-8")
            problems = config.inspect_run(run_dir, expected_pattern="distinct")
            self.assertTrue(any("consumer3" in problem for problem in problems))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
