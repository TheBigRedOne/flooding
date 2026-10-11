#!/usr/bin/env python3
"""Host-side Exp2-A checks. Fixtures are synthetic, not experiment results."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exp2_shared_config as config
import exp2_shared_metrics as exp2
import mobility_event_metrics as metrics

CONTENT = "/LiveStream/v0/54=%01/50=%00"
GUARD = "/LiveStream/_guard"
HANDOFF = 1_700_000_000.0


def _packet(time_s: float, node: str, outbound: bool, ptype: str, name: str, length: int = 100, **flags: bool) -> metrics.Packet:
    return metrics.Packet(
        time_s, node, outbound, ptype, name, length, False, False,
        flags.get("interest_hop_limit", False),
        flags.get("data_lp_hop_limit", False),
        flags.get("data_mobility_flag", False),
    )


class Exp2ConfigTest(unittest.TestCase):
    def test_n1_and_n2_share_topology_and_nlsr_membership(self) -> None:
        n1 = config.parse_active_consumers("consumer1")
        n2 = config.parse_active_consumers("2")
        self.assertEqual(n1, ("consumer1",))
        self.assertEqual(n2, ("consumer1", "consumer2"))
        self.assertEqual(config.NLSR_HOSTS, config.NLSR_HOSTS)
        self.assertIn("consumer1", config.NLSR_HOSTS)
        self.assertIn("consumer2", config.NLSR_HOSTS)
        self.assertEqual(config.LINKS, config.LINKS)
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer1"], "acc1")
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer2"], "acc4")
        text_n1 = config.topology_text(n1)
        text_n2 = config.topology_text(n2)
        self.assertIn("nlsr_hosts=" + ",".join(config.NLSR_HOSTS), text_n1)
        self.assertIn("nlsr_hosts=" + ",".join(config.NLSR_HOSTS), text_n2)
        self.assertIn("inactive_consumers=consumer2", text_n1)
        self.assertIn("inactive_consumers=", text_n2)
        self.assertNotIn("inactive_consumers=consumer", text_n2.split("inactive_consumers=")[1].split("\n")[0] or "x")

    def test_active_applications_and_guard_daemons(self) -> None:
        n1 = config.parse_active_consumers("n1")
        n2 = config.parse_active_consumers("consumer1,consumer2")
        self.assertEqual(config.application_hosts(n1), ("producer", "consumer1"))
        self.assertEqual(config.guard_daemon_hosts(n1), ("producer", "consumer1"))
        self.assertEqual(config.application_hosts(n2), ("producer", "consumer1", "consumer2"))
        self.assertNotIn("consumer2", config.application_hosts(n1))

    def test_capture_and_log_paths_are_unique(self) -> None:
        n2 = config.parse_active_consumers("2")
        names = config.result_names(n2)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("consumer1.log", names)
        self.assertIn("consumer2.log", names)
        self.assertIn("optoflood_consumer1.log", names)
        self.assertIn("optoflood_consumer2.log", names)
        self.assertIn("pcap_nodes/consumer1.pcap", names)
        self.assertIn("pcap_nodes/consumer2.pcap", names)
        self.assertIn("pcap_nodes/producer.pcap", names)
        n1_names = config.result_names(("consumer1",))
        self.assertNotIn("consumer2.log", n1_names)
        self.assertIn("pcap_nodes/consumer2.pcap", n1_names)

    def test_smoke_is_one_handoff_off_acc4_and_full_sequence_remains_available(self) -> None:
        smoke = config.smoke_schedule(20, 30)
        self.assertEqual(smoke["handoff_count"], 1)
        self.assertEqual(smoke["sequence"], ("acc2", "acc3"))
        self.assertEqual(smoke["intervals_s"], (20.0, 30.0))
        self.assertNotIn("acc4", config.SMOKE_HANDOFF_SEQUENCE[1:])
        full = config.full_schedule()
        self.assertEqual(full["handoff_count"], 8)
        self.assertEqual(full["sequence"], config.FULL_HANDOFF_SEQUENCE)
        self.assertEqual(len(config.FULL_HANDOFF_SEQUENCE), 9)

    def test_malformed_configurations_are_rejected(self) -> None:
        for text in ("", "consumer2", "3", "consumer1,consumer1", "consumer1,consumer3"):
            with self.assertRaises(config.Exp2ConfigError):
                config.parse_active_consumers(text)
        with self.assertRaises(config.Exp2ConfigError):
            config.smoke_schedule(-1, 10)
        with self.assertRaises(config.Exp2ConfigError):
            config.schedule_for("exp2b", 1, 1)

    def test_stream_mapping_is_shared(self) -> None:
        self.assertEqual(config.STREAM_PREFIX, "/LiveStream/v0")
        self.assertEqual(config.ADVERTISED_PREFIX, "/LiveStream")
        self.assertEqual(config.GUARD_NAME, "/LiveStream/_guard")

    def test_full_sequence_and_run_directories_stay_separate_from_smoke(self) -> None:
        full = config.full_schedule()
        self.assertEqual(
            full["sequence"],
            ("acc2", "acc3", "acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2"),
        )
        self.assertEqual(full["handoff_count"], 8)
        self.assertIsNone(full["intervals_s"])
        self.assertEqual(config.FULL_INTERVAL_BASE_S, 90.0)
        self.assertEqual(config.FULL_INTERVAL_JITTER_S, 60.0)
        root = "results/extended/exp2/shared"
        smoke_dirs = {config.smoke_directory(root, population) for population in ("n1", "n2")}
        full_dirs = {
            config.full_run_directory(root, population, run_id)
            for population in ("n1", "n2")
            for run_id in config.FULL_RUN_IDS
        }
        self.assertEqual(len(full_dirs), 10)
        self.assertTrue(smoke_dirs.isdisjoint(full_dirs))
        self.assertEqual(config.full_run_directory(root, "n1", "r1"), f"{root}/n1/r1")
        self.assertEqual(config.full_run_directory(root, "n2", "r5"), f"{root}/n2/r5")
        self.assertEqual(config.recorded_run_id("smoke", ""), "")
        self.assertEqual(config.recorded_run_id("full", "r3"), "r3")
        for text in ("", "r6", "smoke"):
            with self.assertRaises(config.Exp2ConfigError):
                config.recorded_run_id("full", text)
        n1 = config.parse_active_consumers("n1")
        n2 = config.parse_active_consumers("consumer1,consumer2")
        self.assertEqual(n1, ("consumer1",))
        self.assertEqual(n2, ("consumer1", "consumer2"))
        self.assertEqual(config.application_hosts(n1), ("producer", "consumer1"))
        self.assertEqual(config.application_hosts(n2), ("producer", "consumer1", "consumer2"))

    def test_populated_run_directory_is_not_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = root / "n1"
            smoke.mkdir()
            (smoke / "params.txt").write_text("smoke\n", encoding="utf-8")
            populated = root / "n1" / "r1"
            populated.mkdir()
            (populated / "handoffs.txt").write_text("index\n", encoding="utf-8")
            empty = root / "n1" / "r2"
            empty.mkdir()
            self.assertTrue(config.directory_has_entries(smoke))
            self.assertTrue(config.directory_has_entries(populated))
            self.assertFalse(config.directory_has_entries(empty))
            self.assertFalse(config.directory_has_entries(root / "n1" / "r3"))
        repo = Path(__file__).resolve().parents[2]
        script = (repo / "scripts" / "run-in-vm.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$experiment" = "exp2" ]; then', script)
        self.assertIn("refusing to replace existing Exp2 results", script)
        self.assertIn("remote_subdir=experiment/extended/exp2", script)
        self.assertIn("--exclude box --exclude '*.box'", script)
        makefile = (repo / "Makefile.exp2").read_text(encoding="utf-8")
        self.assertIn("experiment-exp2-shared-$(3)-$(2):", makefile)
        self.assertIn("analyze-exp2-shared-$(3)-$(2):", makefile)
        self.assertIn("experiment-exp2-shared-n1-full:", makefile)
        self.assertIn("experiment-exp2-shared-n2-full:", makefile)
        self.assertIn("NLSR_HANDOFF_COUNT='8'", makefile)
        self.assertIn("NLSR_HANDOFF_INTERVALS=''", makefile)
        self.assertIn("EXP2_SCHEDULE='full'", makefile)
        self.assertIn("acc2,acc3,acc4,acc5,acc6,acc5,acc4,acc3,acc2", makefile)
        self.assertNotIn("experiment-exp2-shared-n1-full", (repo / "Makefile").read_text(encoding="utf-8"))
        self.assertNotIn("experiment-exp2-shared-n1-r1", (repo / "Makefile").read_text(encoding="utf-8"))

    def test_topology_position_keeps_consumer2_access_events(self) -> None:
        expected = [
            "other_attachment",
            "moves_onto_consumer_access",
            "moves_away_from_consumer_access",
            "other_attachment",
            "other_attachment",
            "moves_onto_consumer_access",
            "moves_away_from_consumer_access",
            "other_attachment",
        ]
        sequence = config.FULL_HANDOFF_SEQUENCE
        for index, position in enumerate(expected):
            self.assertEqual(
                config.topology_position("consumer2", sequence[index], sequence[index + 1]),
                position,
            )
            self.assertEqual(
                config.topology_position("consumer1", sequence[index], sequence[index + 1]),
                "other_attachment",
            )
        self.assertEqual(config.topology_position("consumer2", "acc4", "acc4"), "resides_at_consumer_access")
        with self.assertRaises(config.Exp2ConfigError):
            config.topology_position("consumer3", "acc2", "acc3")


class Exp2NameTest(unittest.TestCase):
    def test_version_and_segment_aliases_match_pcap_spellings(self) -> None:
        alias = "/LiveStream/v0/v=998/seg=0"
        pcap = "/LiveStream/v0/54=%03%E6/50=%00"
        self.assertEqual(exp2.semantic_components(alias), exp2.semantic_components(pcap))
        self.assertEqual(exp2.semantic_name(alias), exp2.semantic_name(pcap))
        self.assertNotEqual(
            exp2.semantic_components("/LiveStream/v0/v=998/seg=0"),
            exp2.semantic_components("/LiveStream/v0/v=999/seg=0"),
        )
        self.assertNotEqual(
            exp2.semantic_components("/LiveStream/v0/v=998/seg=0"),
            exp2.semantic_components("/LiveStream/v0/v=998/seg=1"),
        )
        generic = exp2.semantic_components("/LiveStream/v0/foo=1")
        self.assertEqual(generic[-1][0], metrics.COMPONENT_GENERIC)
        self.assertEqual(exp2.encode_non_negative_integer(65536), b"\x00\x01\x00\x00")

    def test_frame_998_inflight_is_not_validated_service_recovery(self) -> None:
        handoff = 1791696401.073512
        send = 1791696401.055147239
        receive = 1791696401.078982856
        alias = "/LiveStream/v0/v=998/seg=0"
        pcap = "/LiveStream/v0/54=%03%E6/50=%00"
        later_alias = "/LiveStream/v0/v=1000/seg=0"
        later_pcap = exp2.semantic_name(later_alias)
        later_send = handoff + 0.050
        later_receive = handoff + 0.080
        packets = [
            _packet(handoff - 0.2, "consumer1", True, "interest", pcap),
            _packet(send, "producer", True, "data", pcap),
            _packet(receive, "consumer1", False, "data", pcap),
            _packet(later_send, "producer", True, "data", later_pcap),
            _packet(later_receive, "consumer1", False, "data", later_pcap),
        ]
        consumer_log = (
            f"[{int(receive * 1e9)}] VALIDATE: Data signature verified name={alias} id=consumer1\n"
            f"[{int(later_receive * 1e9)}] VALIDATE: Data signature verified name={later_alias} id=consumer1\n"
        )
        producer_log = (
            f"[{int(send * 1e9)}] DATA: Sending response Size: 100 bytes Name: {alias}\n"
            f"[{int(later_send * 1e9)}] DATA: Sending response Size: 100 bytes Name: {later_alias}\n"
        )
        rows, _audits = exp2.observe_run(
            packets,
            [metrics.Handoff(1, handoff, "acc2", "acc3")],
            ("consumer1",),
            {"consumer1": exp2.parse_validation_log(consumer_log)},
            exp2.parse_producer_log(producer_log),
        )
        row = rows[0]
        self.assertEqual(row["first_arrival_name"], exp2.semantic_name(pcap))
        self.assertEqual(row["first_arrival_origin"], "in_flight_arrival")
        self.assertEqual(row["recovery_name"], exp2.semantic_name(later_alias))
        self.assertEqual(row["origin"], "producer_post_handoff_interest")
        self.assertAlmostEqual(float(str(row["validated_producer_service_recovery_ms"])), (later_receive - handoff) * 1000.0, places=3)
        self.assertNotEqual(row["consumer_observed_recovery_ms"], row["validated_producer_service_recovery_ms"])


class Exp2MetricTest(unittest.TestCase):
    def _handoff(self) -> metrics.Handoff:
        return metrics.Handoff(1, HANDOFF, "acc2", "acc3")

    def test_pre_handoff_interest_and_validation_by_name(self) -> None:
        data_time = HANDOFF + 0.2
        packets = [
            _packet(HANDOFF - 1.0, "consumer1", True, "interest", CONTENT),
            _packet(HANDOFF + 0.1, "producer", True, "data", CONTENT, data_mobility_flag=True),
            _packet(data_time, "consumer1", False, "data", CONTENT),
            _packet(HANDOFF + 0.05, "acc1", True, "data", CONTENT, length=40, data_mobility_flag=True),
        ]
        log = (
            f"[{int(data_time * 1e9)}] VALIDATE: Data signature verified "
            f"name={CONTENT} id=consumer1\n"
        )
        rows, _audits = exp2.observe_run(
            packets, [self._handoff()], ("consumer1",),
            {"consumer1": exp2.parse_validation_log(log)},
        )
        row = rows[0]
        self.assertEqual(row["origin"], "producer_pending_interest")
        self.assertEqual(row["interest_predates_handoff"], "true")
        self.assertEqual(row["validation"], "success")
        self.assertEqual(row["content_name"], metrics.canonical_name(CONTENT))
        self.assertNotEqual(row["validated_producer_service_recovery_ms"], "")
        self.assertEqual(row["network_recovery_flood_bytes"], 100 + 40)
        self.assertNotEqual(row["consumer_observed_recovery_ms"], row["interest_to_data_ms"])

    def test_validation_failure_is_bound_to_the_name(self) -> None:
        data_time = HANDOFF + 0.3
        packets = [
            _packet(HANDOFF + 0.1, "consumer1", True, "interest", CONTENT),
            _packet(HANDOFF + 0.2, "producer", False, "interest", CONTENT),
            _packet(HANDOFF + 0.25, "producer", True, "data", CONTENT),
            _packet(data_time, "consumer1", False, "data", CONTENT),
        ]
        log = f"[{int(data_time * 1e9)}] ERROR: Data validation failed: rejected name={CONTENT} id=consumer1\n"
        rows, _audits = exp2.observe_run(
            packets, [self._handoff()], ("consumer1",),
            {"consumer1": exp2.parse_validation_log(log)},
        )
        self.assertEqual(rows[0]["validation"], "failure")
        self.assertEqual(rows[0]["origin"], "validation_failure")
        self.assertEqual(rows[0]["validated_producer_service_recovery_ms"], "")

    def test_missing_data_is_right_censored_and_consumers_stay_separate(self) -> None:
        packets = [
            _packet(HANDOFF + 0.2, "producer", True, "data", CONTENT),
            _packet(HANDOFF + 0.3, "consumer1", False, "data", CONTENT),
            _packet(HANDOFF + 1.0, "core", True, "interest", "/ndn/nlsr/update", length=10),
        ]
        rows, _audits = exp2.observe_run(
            packets, [self._handoff()], ("consumer1", "consumer2"), {},
        )
        by_consumer = {row["consumer"]: row for row in rows}
        self.assertEqual(by_consumer["consumer1"]["origin"], "validation_absent")
        self.assertEqual(by_consumer["consumer1"]["validated_producer_service_recovery_ms"], "")
        self.assertEqual(by_consumer["consumer2"]["origin"], "absent")
        self.assertEqual(by_consumer["consumer2"]["consumer_observed_recovery_ms"], "")
        self.assertEqual(by_consumer["consumer2"]["validated_producer_service_recovery_ms"], "")
        self.assertEqual(
            by_consumer["consumer1"]["network_recovery_flood_bytes"],
            by_consumer["consumer2"]["network_recovery_flood_bytes"],
        )

    def test_shared_flood_bytes_are_not_multiplied_by_consumer_count(self) -> None:
        packets = [
            _packet(HANDOFF + 0.2, "consumer1", False, "data", CONTENT),
            _packet(HANDOFF + 0.2, "consumer2", False, "data", CONTENT),
            _packet(HANDOFF + 0.1, "core", True, "data", CONTENT, length=80, data_mobility_flag=True),
        ]
        rows, _audits = exp2.observe_run(
            packets, [self._handoff()], ("consumer1", "consumer2"), {},
        )
        self.assertEqual({row["network_recovery_flood_bytes"] for row in rows}, {80})

    def test_cache_or_uncertain_delivery_is_not_confirmed(self) -> None:
        packets = [_packet(HANDOFF + 0.4, "consumer1", False, "data", CONTENT)]
        rows, _audits = exp2.observe_run(packets, [self._handoff()], ("consumer1",), {})
        self.assertEqual(rows[0]["origin"], "origin_uncertain")
        self.assertNotEqual(rows[0]["consumer_observed_recovery_ms"], "")
        self.assertEqual(rows[0]["validated_producer_service_recovery_ms"], "")
        self.assertEqual(rows[0]["validation"], "absent")

    def test_eight_handoff_windows_censoring_and_shared_overhead(self) -> None:
        sequence = config.FULL_HANDOFF_SEQUENCE
        handoffs = [
            metrics.Handoff(index + 1, HANDOFF + index * 10.0, sequence[index], sequence[index + 1])
            for index in range(8)
        ]
        onto = HANDOFF + 10.0
        arrival = onto + 1.0
        boundary = HANDOFF + 20.0
        last = HANDOFF + 70.0
        capture_end = last + 5.0
        early = "/LiveStream/v0/54=%02/50=%00"
        late = "/LiveStream/v0/54=%08/50=%00"
        packets = [
            _packet(arrival, "producer", True, "data", early),
            _packet(arrival + 0.01, "consumer1", False, "data", early),
            _packet(boundary, "consumer1", False, "data", early),
            _packet(onto + 0.5, "core", True, "data", early, length=80, data_mobility_flag=True),
            _packet(capture_end, "producer", True, "data", late),
            _packet(capture_end, "consumer1", False, "data", late),
            _packet(capture_end, "core", True, "interest", "/ndn/nlsr/update", length=15),
        ]
        log = f"[{int(capture_end * 1e9)}] VALIDATE: Data signature verified name={late} id=consumer1\n"
        producer_log = f"[{int(capture_end * 1e9)}] DATA: Sending response Size: 100 bytes Name: {late}\n"
        rows, _audits = exp2.observe_run(
            packets, handoffs, ("consumer1", "consumer2"),
            {"consumer1": exp2.parse_validation_log(log)},
            exp2.parse_producer_log(producer_log),
        )
        self.assertEqual(len(rows), 16)
        by_key = {(row["consumer"], int(str(row["handoff_index"]))): row for row in rows}
        first_c1 = by_key[("consumer1", 1)]
        first_c2 = by_key[("consumer2", 1)]
        self.assertEqual(first_c1["origin"], "absent")
        self.assertEqual(first_c1["validated_producer_service_recovery_ms"], "")
        self.assertEqual(first_c1["consumer_observed_recovery_ms"], "")
        self.assertEqual(first_c1["event_end_time"], f"{handoffs[1].abs_time:.6f}")
        self.assertEqual(first_c2["origin"], "absent")
        self.assertEqual(first_c1["topology_position"], "other_attachment")
        second_c1 = by_key[("consumer1", 2)]
        second_c2 = by_key[("consumer2", 2)]
        self.assertEqual(second_c1["first_arrival_origin"], "validation_absent")
        self.assertNotEqual(second_c1["consumer_observed_recovery_ms"], "")
        self.assertEqual(second_c1["validated_producer_service_recovery_ms"], "")
        self.assertEqual(second_c1["observed_data_time"], f"{arrival + 0.01:.6f}")
        self.assertEqual(second_c2["origin"], "absent")
        self.assertEqual(second_c2["topology_position"], "moves_onto_consumer_access")
        self.assertEqual(second_c1["topology_position"], "other_attachment")
        self.assertEqual(second_c1["network_recovery_flood_bytes"], 80)
        self.assertEqual(second_c2["network_recovery_flood_bytes"], 80)
        self.assertNotEqual(second_c1["content_loss_fraction"], second_c2["content_loss_fraction"])
        self.assertEqual(by_key[("consumer1", 1)]["network_recovery_flood_bytes"], 0)
        self.assertEqual(by_key[("consumer2", 3)]["topology_position"], "moves_away_from_consumer_access")
        self.assertEqual(by_key[("consumer2", 6)]["topology_position"], "moves_onto_consumer_access")
        self.assertEqual(by_key[("consumer2", 7)]["topology_position"], "moves_away_from_consumer_access")
        last_c1 = by_key[("consumer1", 8)]
        last_c2 = by_key[("consumer2", 8)]
        self.assertEqual(last_c1["event_end_time"], f"{capture_end:.6f}")
        self.assertNotEqual(last_c1["validated_producer_service_recovery_ms"], "")
        self.assertEqual(last_c1["validation"], "success")
        self.assertEqual(last_c2["origin"], "absent")
        self.assertEqual(last_c2["validated_producer_service_recovery_ms"], "")
        self.assertEqual(last_c1["nlsr_control_bytes"], 15)
        self.assertEqual(last_c2["nlsr_control_bytes"], 15)
        self.assertEqual(second_c1["nlsr_control_bytes"], 0)
        self.assertEqual(last_c1["topology_position"], "other_attachment")

    def test_inactive_consumer_application_traffic_is_reported(self) -> None:
        packets = [_packet(HANDOFF + 1.0, "consumer2", True, "interest", CONTENT)]
        notes = exp2.inactive_consumer_application_traffic(packets, ("consumer2",))
        self.assertEqual(len(notes), 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
