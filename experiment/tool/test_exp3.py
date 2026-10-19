#!/usr/bin/env python3
"""Host-side Exp3 configuration and smoke-evidence checks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp3_config as config
import exp3_processes as procs
import check_exp3_evidence as checker

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = 1_700_000_000.0


class Exp3ConfigTest(unittest.TestCase):
    def test_populations_and_stable_p1_sequence(self) -> None:
        self.assertEqual(len(config.physical_hosts(1)), 11)
        self.assertEqual(len(config.physical_hosts(2)), 13)
        self.assertEqual(len(config.physical_hosts(4)), 17)
        p1 = config.pairs_for(1)[0]
        self.assertEqual(p1.sequence, (
            "acc2", "acc3", "acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2",
        ))
        self.assertEqual(config.pairs_for(4)[0].sequence, p1.sequence)
        self.assertEqual(config.pairs_for(2)[1].sequence[0], "acc5")
        self.assertEqual(config.pairs_for(4)[1].sequence, config.pairs_for(2)[1].sequence)
        self.assertEqual(config.pairs_for(4)[3].smoke_handoff(), ("acc3", "acc4"))
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer3"], "acc3")
        self.assertNotIn("producer3", config.physical_hosts(2))

    def test_producer_schedules_do_not_depend_on_population_order(self) -> None:
        alone = config.sample_intervals(1, 1)
        with_others = config.sample_intervals(1, 1)
        self.assertEqual(alone, with_others)
        second_before = config.sample_intervals(1, 2)
        _ = [config.sample_intervals(1, index) for index in (4, 3, 1)]
        self.assertEqual(config.sample_intervals(1, 2), second_before)
        self.assertEqual(len(alone), 9)
        self.assertTrue(all(90.0 <= value <= 150.0 for value in alone))
        selected = config.pairs_for(4)
        schedules = {pair.index: config.sample_intervals(3, pair.index) for pair in selected}
        events = config.plan_events(selected, schedules, "full")
        self.assertEqual(len(events), 32)
        self.assertEqual(events, tuple(sorted(events, key=lambda item: (item[0], item[1], item[2]))))
        alone_events = config.plan_events(config.pairs_for(1), {1: schedules[1]}, "full")
        self.assertEqual(alone_events, tuple(item for item in events if item[1] == 1))
        self.assertEqual((alone_events[0][3], alone_events[0][4]), ("acc2", "acc3"))
        smoke = config.plan_events(
            config.pairs_for(2),
            {1: config.smoke_intervals(), 2: config.smoke_intervals()},
            "smoke",
        )
        self.assertEqual(
            [(item[1], item[3], item[4]) for item in smoke],
            [(1, "acc2", "acc3"), (2, "acc5", "acc6")],
        )
        for pair in selected:
            own = [item for item in events if item[1] == pair.index]
            endpoint = config.schedule_end(schedules[pair.index])
            self.assertEqual(len(own), 8)
            self.assertLess(own[-1][0], endpoint)
            self.assertAlmostEqual(endpoint - own[-1][0], schedules[pair.index][-1])

    def test_flood_ids_and_signing_relationships(self) -> None:
        self.assertEqual(config.guard_flood_id(1, 1), 4294967297)
        self.assertEqual(config.guard_flood_id(1, 2), 4294967298)
        self.assertEqual(config.guard_flood_id(2, 1), 8589934593)
        self.assertEqual(config.guard_flood_id(2, 1), config.guard_flood_id(2, 1))
        data = "/LiveStream/v0/54=%01/50=%00"
        self.assertTrue(config.identity_may_sign("/LiveStream/v0", data))
        self.assertFalse(config.identity_may_sign("/LiveStream/v1", data))
        schema = config.trust_schema_text(["/tmp/exp3/certs/producer1.cert"])
        legacy = (ROOT / "experiment" / "app" / "trust-schema.conf").read_text(encoding="utf-8")
        for marker in ("k-regex", "k-expand", "h-relation", "p-regex", "p-expand"):
            legacy_line = next(line.strip() for line in legacy.splitlines() if marker in line)
            generated_line = next(line.strip() for line in schema.splitlines() if marker in line)
            self.assertEqual(generated_line, legacy_line)
        self.assertEqual(
            sum(1 for line in schema.splitlines() if line.strip() == "trust-anchor"), 1)
        four = config.trust_schema_text([f"certs/producer{index}.cert" for index in range(1, 5)])
        self.assertEqual(
            sum(1 for line in four.splitlines() if line.strip() == "trust-anchor"), 4)
        self.assertNotIn(config.LEGACY_TRUST_ANCHOR, schema)
        self.assertIn("is-prefix-of", schema)
        self.assertIn(config.LEGACY_TRUST_ANCHOR, legacy)
        self.assertEqual(
            sum(1 for line in legacy.splitlines() if line.strip() == "trust-anchor"), 1)
        with self.assertRaises(config.Exp3ConfigError):
            config.trust_schema_text([config.LEGACY_TRUST_ANCHOR])
        for signer in range(4):
            for owner in range(4):
                data_name = f"/LiveStream/v{owner}/54=%01/50=%00"
                self.assertEqual(
                    config.identity_may_sign(f"/LiveStream/v{signer}", data_name),
                    signer == owner,
                )

    def test_sources_keep_legacy_defaults(self) -> None:
        producer = (ROOT / "experiment" / "app" / "producer.cpp").read_text(encoding="utf-8")
        consumer = (ROOT / "experiment" / "app" / "consumer.cpp").read_text(encoding="utf-8")
        daemon = (ROOT / "experiment" / "app" / "optoflood-daemon.cpp").read_text(encoding="utf-8")
        self.assertIn('? raw : "/LiveStream"', producer)
        self.assertIn("EXP_ADVERTISED_PREFIX", producer)
        self.assertIn(config.LEGACY_TRUST_SCHEMA, consumer)
        self.assertIn("EXP_TRUST_SCHEMA", consumer)
        self.assertIn("guardFloodId", daemon)
        self.assertIn("OPTOFLOOD_PRODUCER_INDEX", daemon)
        self.assertIn("if (producerIndex)", daemon)
        self.assertIn('<< " pid=" << getpid()', daemon)


def _populate(root: Path, population: int) -> Path:
    run_dir = root / f"p{population}" / "smoke"
    for name in config.result_names(population):
        path = run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".pcap"):
            path.write_bytes(b"pcap-bytes-beyond-global-header")
        elif name.startswith("tcpdump_"):
            path.write_text("", encoding="utf-8")
        else:
            path.write_text("placeholder\n", encoding="utf-8")
    selected = config.pairs_for(population)
    (run_dir / "trust-schema.conf").write_text(
        config.trust_schema_text([f"{run_dir.as_posix()}/certs/{pair.producer}.cert" for pair in selected]),
        encoding="utf-8",
    )
    (run_dir / "params.txt").write_text(
        f"exp3_population=p{population}\nexp3_campaign={config.CAMPAIGN_ID}\n"
        f"exp3_schedule=smoke\ncommon_end_s={config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S:.6f}\n",
        encoding="utf-8",
    )
    lines = ["producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n"]
    for pair in selected:
        source, destination = pair.smoke_handoff()
        lines.append(f"{pair.producer}\t1\t{HANDOFF:.6f}\t20.000000\t{source}\t{destination}\t20.000000\n")
    (run_dir / "handoffs.txt").write_text("".join(lines), encoding="utf-8")
    endpoint = HANDOFF + config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S
    observation = ["producer\tindex\trel_end_s\tabs_end\n"]
    for pair in selected:
        observation.append(
            f"{pair.producer}\t{pair.index}\t{config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S:.6f}\t{endpoint:.6f}\n"
        )
    (run_dir / "observation_ends.txt").write_text("".join(observation), encoding="utf-8")
    shutdown_at = config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S + 1.0
    health = [procs.HEALTH_HEADER]
    for pair in selected:
        identities = (
            (pair.producer, "producer-app", 1100 + pair.index, ""),
            (pair.consumer, "consumer-app", 1200 + pair.index, ""),
            (pair.producer, "producer-daemon", 1300 + pair.index, "producer"),
            (pair.consumer, "consumer-daemon", 1400 + pair.index, "consumer"),
        )
        for host, kind, pid, _role in identities:
            health.append(procs.health_row(
                host, kind, pid, "intentional-shutdown", shutdown_at, "sigterm-before-nfd-stop"))
    (run_dir / "process-health.txt").write_text("".join(health), encoding="utf-8")
    received = int((HANDOFF + 1.0) * 1e9)
    for pair in selected:
        flood_id = config.guard_flood_id(pair.index, 1)
        (run_dir / f"{pair.producer}.log").write_text(
            f"[1] PREFIX: Successfully registered prefix: {pair.prefix}\n"
            f"[1] PREFIX: Advertising prefix via NLSR: {pair.prefix}\n",
            encoding="utf-8",
        )
        (run_dir / f"optoflood_{pair.producer}.log").write_text(
            f"[1] STARTUP: OptoFlood daemon role='producer' prefix={pair.prefix} "
            f"producer_index={pair.index} pid={pair.index}\n"
            f"[1] GUARD-PRODUCER: registered guard prefix {pair.guard}\n"
            f"[1] GUARD-PRODUCER: flooded guard NewFaceSeq=1 FloodId={flood_id} size=10 bytes\n",
            encoding="utf-8",
        )
        (run_dir / f"optoflood_{pair.consumer}.log").write_text(
            f"[1] STARTUP: OptoFlood daemon role='consumer' prefix={pair.prefix} pid={pair.index}\n",
            encoding="utf-8",
        )
        (run_dir / f"{pair.consumer}.log").write_text(
            f"[{received}] DATA: frame=1 seg=0 Size: 100 bytes\n"
            f"[{received}] VALIDATE: Data signature verified name={pair.prefix}/54=%01/50=%00 "
            f"id={pair.consumer}\n",
            encoding="utf-8",
        )
        for node in ("core", "agg1", pair.smoke_handoff()[1]):
            log_path = run_dir / "minindn-logs" / node / "nfd.log"
            previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            log_path.write_text(
                previous
                + f"OptoFlood TFIB update prefix={pair.prefix} face=4 newFaceSeq=1 floodId={flood_id}\n",
                encoding="utf-8",
            )
    for extra in ("capture-health.txt", "timing-summary.txt"):
        (run_dir / extra).unlink(missing_ok=True)
    return run_dir


class Exp3EvidenceTest(unittest.TestCase):
    def test_p1_and_p2_smoke_fixtures_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(checker.inspect_run(_populate(root, 1)), [])
            self.assertEqual(checker.inspect_run(_populate(root, 2)), [])

    def test_restart_and_cross_producer_dedup_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _populate(Path(tmp), 2)
            daemon = run_dir / "optoflood_producer2.log"
            daemon.write_text(daemon.read_text(encoding="utf-8") + "[2] STARTUP: OptoFlood daemon role='producer'\n", encoding="utf-8")
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("restart" in problem for problem in problems))
            daemon.write_text(
                "[1] STARTUP: OptoFlood daemon role='producer' prefix=/LiveStream/v1 producer_index=2 pid=2\n"
                "[1] GUARD-PRODUCER: registered guard prefix /LiveStream/v1/_guard\n"
                "[1] GUARD-PRODUCER: flooded guard NewFaceSeq=1 FloodId=8589934593 size=10 bytes\n",
                encoding="utf-8",
            )
            for node in ("core", "agg1"):
                log_path = run_dir / "minindn-logs" / node / "nfd.log"
                text = log_path.read_text(encoding="utf-8").replace(
                    "TFIB update prefix=/LiveStream/v1 face=4 newFaceSeq=1 floodId=8589934593",
                    "dedup drop data=/LiveStream/v1/_guard floodId=8589934593",
                )
                log_path.write_text(text, encoding="utf-8")
            destination = run_dir / "minindn-logs" / "acc6" / "nfd.log"
            destination.write_text(destination.read_text(encoding="utf-8").replace(
                "TFIB update prefix=/LiveStream/v1 face=4 newFaceSeq=1 floodId=8589934593",
                "dedup drop data=/LiveStream/v1/_guard floodId=8589934593",
            ), encoding="utf-8")
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("8589934593" in problem or "v1" in problem for problem in problems))

    def test_cross_prefix_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _populate(Path(tmp), 2)
            consumer = run_dir / "consumer1.log"
            consumer.write_text(
                consumer.read_text(encoding="utf-8")
                + f"[{int((HANDOFF + 2.0) * 1e9)}] VALIDATE: Data signature verified "
                + "name=/LiveStream/v1/54=%01/50=%00 id=consumer1\n",
                encoding="utf-8",
            )
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("cannot sign" in problem for problem in problems))

    def test_teardown_fatal_and_premature_exit_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _populate(Path(tmp), 1)
            daemon = run_dir / "optoflood_producer1.log"
            daemon.write_text(
                daemon.read_text(encoding="utf-8")
                + "[51500000000] FATAL: socket read error (End of file)\n",
                encoding="utf-8",
            )
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("FATAL" in problem for problem in problems))
            daemon.write_text(
                "[1] STARTUP: OptoFlood daemon role='producer' prefix=/LiveStream/v0 "
                "producer_index=1 pid=1\n"
                "[1] GUARD-PRODUCER: registered guard prefix /LiveStream/v0/_guard\n"
                "[1] GUARD-PRODUCER: flooded guard NewFaceSeq=1 FloodId=4294967297 size=10 bytes\n",
                encoding="utf-8",
            )
            health = (run_dir / "process-health.txt").read_text(encoding="utf-8")
            health = health.replace(
                "producer1\tproducer-daemon\t1301\tintentional-shutdown",
                "producer1\tproducer-daemon\t1301\tpremature-exit",
            )
            (run_dir / "process-health.txt").write_text(health, encoding="utf-8")
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("producer-daemon exited" in problem for problem in problems))
            self.assertTrue(any("intentional shutdown" in problem for problem in problems))
            consumer_daemon = run_dir / "optoflood_consumer1.log"
            consumer_daemon.write_text(
                consumer_daemon.read_text(encoding="utf-8")
                + "[1000000000] FATAL: socket read error (End of file)\n",
                encoding="utf-8",
            )
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("consumer1 daemon contains a daemon FATAL" in problem for problem in problems))


class ProcessLaunchTest(unittest.TestCase):
    def test_pid_parsing_refuses_ambiguous_or_privileged_pids(self) -> None:
        self.assertEqual(procs.parse_background_pid("noise\n4321\n"), 4321)
        with self.assertRaises(procs.ProcessError):
            procs.parse_background_pid("1\n")
        with self.assertRaises(procs.ProcessError):
            procs.parse_background_pid("4321\n4322\n")

    def test_shutdown_signal_matches_only_the_started_command(self) -> None:
        executable = "/home/vagrant/flooding/experiment/extended/exp3/optoflood-daemon"
        self.assertTrue(procs.command_owns_pid(
            f"{executable} producer", executable, "producer"))
        self.assertFalse(procs.command_owns_pid("/usr/bin/nfd", executable, "producer"))
        self.assertFalse(procs.command_owns_pid(
            f"{executable} consumer", executable, "producer"))
        self.assertTrue(procs.command_owns_pid(
            "/home/vagrant/flooding/experiment/extended/exp3/producer",
            "/home/vagrant/flooding/experiment/extended/exp3/producer", ""))
        self.assertTrue(procs.command_owns_pid("/usr/bin/tcpdump -i any", "tcpdump", ""))
        self.assertFalse(procs.command_owns_pid("/usr/bin/nfd", "tcpdump", ""))
        own = "/tmp/exp3/pcap_nodes/core.pcap"
        other = "/tmp/exp3/pcap_nodes/acc1.pcap"
        self.assertTrue(procs.command_owns_capture(f"tcpdump -i any -U -w {own} udp port 6363", own))
        self.assertFalse(procs.command_owns_capture(f"tcpdump -i any -U -w {other} udp port 6363", own))
        self.assertFalse(procs.command_owns_capture(f"nfd -w {own}", own))


class ScheduleClockTest(unittest.TestCase):
    def test_overhead_does_not_move_later_deadlines(self) -> None:
        arrivals = config.scheduled_arrivals((10.0, 20.0, 30.0), (0.4, 0.4, 0.4))
        self.assertEqual(arrivals, (10.0, 20.0, 30.0))
        late = config.scheduled_arrivals((10.0, 20.0), (15.0, 0.0))
        self.assertEqual(late, (10.0, 25.0))
        self.assertAlmostEqual(config.scheduling_lateness(25.0, 20.0), 5.0)

    def test_equal_planned_times_keep_producer_order(self) -> None:
        selected = config.pairs_for(2)
        events = config.plan_events(
            selected,
            {1: config.smoke_intervals(), 2: config.smoke_intervals()},
            "smoke",
        )
        self.assertEqual([item[1] for item in events], [1, 2])
        self.assertEqual(events[0][0], events[1][0])

    def test_p1_schedule_matches_across_populations_and_pilot_seed(self) -> None:
        alone = config.sample_intervals(1, 1)
        self.assertEqual(alone, config.sample_intervals(1, 1))
        self.assertEqual(config.run_seed_for("pilot", "1"), config.run_seed_for("r1"))
        self.assertEqual(config.sample_intervals(config.run_seed_for("pilot", "1"), 2),
                         config.sample_intervals(config.run_seed_for("r1"), 2))
        with self.assertRaises(config.Exp3ConfigError):
            config.run_seed_for("pilot")


class WindowAndCaptureTest(unittest.TestCase):
    def test_non_positive_window_is_infrastructure_invalid(self) -> None:
        self.assertLess(
            config.event_window_end(0, (10.0, 20.0), 50.0),
            config.event_window_end(1, (10.0, 20.0), 50.0),
        )
        self.assertEqual(config.event_window_end(1, (10.0, 60.0), 50.0), 50.0)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _full_run(Path(tmp))
            (run_dir / "observation_ends.txt").write_text(
                "producer\tindex\trel_end_s\tabs_end\nproducer1\t1\t1.000000\t1700000001.000000\n",
                encoding="utf-8",
            )
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("observation endpoint" in problem or "non-positive" in problem
                                for problem in problems))

    def test_unsuccessful_recovery_remains_a_valid_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _full_run(Path(tmp))
            for path in run_dir.glob("minindn-logs/*/nfd.log"):
                path.write_text("no recovery state\n", encoding="utf-8")
            (run_dir / "consumer1.log").write_text("no validated data\n", encoding="utf-8")
            self.assertEqual(checker.inspect_run(run_dir), [])

    def test_capture_lifecycle_distinguishes_empty_from_failed(self) -> None:
        header = b"\xd4\xc3\xb2\xa1" + b"\x00" * 20
        self.assertEqual(procs.inspect_pcap(header), ("ok-empty", 0))
        self.assertEqual(procs.inspect_pcap(b"not-a-pcap-file-at-all!!"), ("bad-magic", 0))
        self.assertEqual(procs.inspect_pcap(header + b"\x00" * 10), ("truncated-record", 0))
        self.assertEqual(
            procs.tcpdump_drop_detail("0 packets captured\n0 packets dropped by kernel\n"),
            "captured=0 kernel_dropped=0 interface_dropped=absent",
        )
        self.assertEqual(procs.tcpdump_drop_detail(""), "unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _full_run(Path(tmp))
            health = (run_dir / "capture-health.txt").read_text(encoding="utf-8")
            health = health.replace("\talive\n", "\tdead\n")
            (run_dir / "capture-health.txt").write_text(health, encoding="utf-8")
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("was not running" in problem for problem in problems))

    def test_legacy_smoke_is_not_a_current_capture_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _populate(Path(tmp), 1)
            self.assertEqual(checker.evidence_format(run_dir), "legacy-smoke")
            self.assertFalse((run_dir / "capture-health.txt").exists())
            self.assertEqual(checker.inspect_run(run_dir), [])
            header = (run_dir / "handoffs.txt").read_text(encoding="utf-8").splitlines()[0]
            header = header + "\tplanned_rel_s\tlateness_s"
            body = (run_dir / "handoffs.txt").read_text(encoding="utf-8").splitlines()[1:]
            (run_dir / "handoffs.txt").write_text(
                header + "\n" + "\n".join(line + "\t20.000000\t0.000000" for line in body) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(checker.evidence_format(run_dir), "current")
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("missing capture-health.txt" in problem for problem in problems))
            self.assertTrue(any("missing timing-summary.txt" in problem for problem in problems))

    def test_zero_kernel_drops_are_not_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _full_run(Path(tmp))
            health = (run_dir / "capture-health.txt").read_text(encoding="utf-8")
            self.assertEqual(checker.inspect_run(run_dir), [])
            (run_dir / "capture-health.txt").write_text(
                health.replace("kernel_dropped=0", "kernel_dropped=absent"),
                encoding="utf-8",
            )
            problems = checker.inspect_run(run_dir)
            self.assertTrue(any("kernel drop" in problem for problem in problems))


def _pcap_header() -> bytes:
    return b"\xd4\xc3\xb2\xa1" + b"\x00" * 20


def _full_run(root: Path) -> Path:
    run_dir = _populate(root, 1)
    intervals = config.sample_intervals(1, 1)
    origin = 1_700_000_000.0
    planned_end = origin + config.schedule_end(intervals)
    shutdown_at = config.schedule_end(intervals) + 0.2
    (run_dir / "process-health.txt").write_text(
        procs.HEALTH_HEADER
        + "".join(
            procs.health_row(host, kind, pid, "intentional-shutdown", shutdown_at, "sigterm-before-nfd-stop")
            for host, kind, pid in (
                ("producer1", "producer-app", 1101),
                ("consumer1", "consumer-app", 1201),
                ("producer1", "producer-daemon", 1301),
                ("consumer1", "consumer-daemon", 1401),
            )
        ),
        encoding="utf-8",
    )
    cursor = 0.0
    lines = [
        "producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s"
        "\tplanned_rel_s\tlateness_s\n"
    ]
    sequence = config.pairs_for(1)[0].sequence
    for index in range(1, 9):
        cursor += intervals[index - 1]
        lines.append(
            f"producer1\t{index}\t{origin + cursor:.6f}\t{cursor:.6f}\t"
            f"{sequence[index - 1]}\t{sequence[index]}\t{intervals[index - 1]:.6f}\t"
            f"{cursor:.6f}\t0.000000\n"
        )
    (run_dir / "handoffs.txt").write_text("".join(lines), encoding="utf-8")
    (run_dir / "params.txt").write_text(
        f"exp3_population=p1\nexp3_campaign={config.CAMPAIGN_ID}\nexp3_schedule=full\n"
        f"exp3_run_id=r1\nexp3_run_seed=1\ncommon_end_s={config.schedule_end(intervals):.6f}\n"
        f"producer1_prefix=/LiveStream/v0\n",
        encoding="utf-8",
    )
    (run_dir / "observation_ends.txt").write_text(
        f"producer\tindex\trel_end_s\tabs_end\n"
        f"producer1\t1\t{config.schedule_end(intervals):.6f}\t{planned_end:.6f}\n",
        encoding="utf-8",
    )
    values = [0.0] * 8
    maximum, median, upper = config.lateness_summary(values)
    (run_dir / "timing-summary.txt").write_text(
        "scope\tn\tmax_lateness_s\tmedian_lateness_s\tp90_lateness_s\n"
        f"producer1\t8\t{maximum:.6f}\t{median:.6f}\t{upper:.6f}\n"
        f"run\t8\t{maximum:.6f}\t{median:.6f}\t{upper:.6f}\n"
        "review\tlateness-recorded-not-thresholded\n",
        encoding="utf-8",
    )
    stopped = config.schedule_end(intervals) + 0.2
    health = ["host\tpid\tevent\trel_s\tdetail\n"]
    for offset, host in enumerate(config.physical_hosts(1), start=2):
        health.extend([
            f"{host}\t{2000 + offset}\tstarted\t0.000000\ttcpdump\n",
            f"{host}\t{2000 + offset}\trunning-at-common-end\t{config.schedule_end(intervals):.6f}\talive\n",
            f"{host}\t{2000 + offset}\tstopped\t{stopped:.6f}\tsigterm-after-common-end\n",
            f"{host}\t{2000 + offset}\tfinalized\t{stopped:.6f}\texited\n",
            f"{host}\t{2000 + offset}\tdrops\t{stopped:.6f}\tcaptured=0 kernel_dropped=0 interface_dropped=0\n",
            f"{host}\t{2000 + offset}\tdecode\t{stopped:.6f}\tok-empty packets=0\n",
        ])
        (run_dir / "pcap_nodes" / f"{host}.pcap").write_bytes(_pcap_header())
    (run_dir / "capture-health.txt").write_text("".join(health), encoding="utf-8")
    return run_dir


if __name__ == "__main__":
    raise SystemExit(unittest.main())
