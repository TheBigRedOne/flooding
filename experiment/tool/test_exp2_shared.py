#!/usr/bin/env python3
"""Host-side Exp2-A checks. Fixtures are synthetic, not experiment results."""

from __future__ import annotations

import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from typing import Dict, List

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
    def test_n2_and_n4_share_infrastructure_and_differ_in_consumers(self) -> None:
        n2 = config.parse_active_consumers("n2")
        n4 = config.parse_active_consumers("4")
        self.assertEqual(n2, ("consumer1", "consumer2"))
        self.assertEqual(n4, ("consumer1", "consumer2", "consumer3", "consumer4"))
        self.assertEqual(len(config.physical_hosts(n2)), 12)
        self.assertEqual(len(config.physical_hosts(n4)), 14)
        self.assertEqual(config.nlsr_hosts(n2), config.physical_hosts(n2))
        self.assertEqual(config.capture_nodes(n4), config.physical_hosts(n4))
        self.assertNotIn("consumer3", config.physical_hosts(n2))
        self.assertNotIn("consumer4", config.physical_hosts(n2))
        self.assertEqual(config.common_links(), config.BACKBONE_LINKS + config.PRODUCER_LINKS)
        self.assertEqual(
            tuple(link for link in config.links(n2) if link in config.common_links()),
            config.common_links(),
        )
        self.assertEqual(
            tuple(link for link in config.links(n4) if link in config.common_links()),
            config.common_links(),
        )
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer1"], "acc1")
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer2"], "acc4")
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer3"], "acc3")
        self.assertEqual(config.CONSUMER_ATTACHMENT["consumer4"], "acc6")
        text_n2 = config.topology_text(n2)
        text_n4 = config.topology_text(n4)
        self.assertIn("physical_node_count=12", text_n2)
        self.assertIn("physical_node_count=14", text_n4)
        self.assertNotIn("consumer3", text_n2)
        self.assertIn("attachment consumer3 acc3", text_n4)
        self.assertIn("attachment consumer4 acc6", text_n4)
        self.assertIn("nlsr_hosts=" + ",".join(config.nlsr_hosts(n2)), text_n2)
        self.assertIn("capture_nodes=" + ",".join(config.capture_nodes(n4)), text_n4)

    def test_active_applications_and_guard_daemons(self) -> None:
        n2 = config.parse_active_consumers("consumer1,consumer2")
        n4 = config.parse_active_consumers("n4")
        self.assertEqual(config.application_hosts(n2), ("producer", "consumer1", "consumer2"))
        self.assertEqual(config.guard_daemon_hosts(n2), config.application_hosts(n2))
        self.assertEqual(
            config.application_hosts(n4),
            ("producer", "consumer1", "consumer2", "consumer3", "consumer4"),
        )
        self.assertEqual(config.guard_daemon_hosts(n4), config.application_hosts(n4))
        self.assertNotIn("consumer3", config.application_hosts(n2))

    def test_capture_and_log_paths_are_unique(self) -> None:
        n2 = config.parse_active_consumers("2")
        n4 = config.parse_active_consumers("n4")
        names = config.result_names(n2)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("campaign.txt", names)
        self.assertIn("consumer1.log", names)
        self.assertIn("consumer2.log", names)
        self.assertNotIn("consumer3.log", names)
        self.assertNotIn("pcap_nodes/consumer3.pcap", names)
        self.assertIn("pcap_nodes/consumer2.pcap", names)
        self.assertIn("tcpdump_producer.log", names)
        n4_names = config.result_names(n4)
        self.assertEqual(len(n4_names), len(set(n4_names)))
        for consumer in n4:
            self.assertIn(f"{consumer}.log", n4_names)
            self.assertIn(f"optoflood_{consumer}.log", n4_names)
            self.assertIn(f"pcap_nodes/{consumer}.pcap", n4_names)
            self.assertIn(f"minindn-logs/{consumer}/nfd.log", n4_names)
            self.assertIn(f"minindn-logs/{consumer}/nlsr.log", n4_names)

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
        for text in ("", "1", "n1", "consumer1", "3", "n3", "consumer1,consumer2,consumer3", "consumer2"):
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
        smoke_dirs = {config.smoke_directory(root, population) for population in ("n2", "n4")}
        full_dirs = {
            config.full_run_directory(root, population, run_id)
            for population in ("n2", "n4")
            for run_id in config.FULL_RUN_IDS
        }
        self.assertEqual(len(full_dirs), 10)
        self.assertTrue(smoke_dirs.isdisjoint(full_dirs))
        self.assertEqual(config.smoke_directory(root, "n2"), f"{root}/n2/smoke")
        self.assertEqual(config.full_run_directory(root, "n2", "r1"), f"{root}/n2/r1")
        self.assertEqual(config.full_run_directory(root, "n4", "r5"), f"{root}/n4/r5")
        self.assertEqual(config.recorded_run_id("smoke", ""), "smoke")
        self.assertEqual(config.recorded_run_id("full", "r3"), "r3")
        for text in ("", "r6", "smoke"):
            with self.assertRaises(config.Exp2ConfigError):
                config.recorded_run_id("full", text)
        with self.assertRaises(config.Exp2ConfigError):
            config.full_run_directory(root, "n1", "r1")
        with self.assertRaises(config.Exp2ConfigError):
            config.smoke_directory(root, "n3")

    def test_populated_run_directory_is_not_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = root / "n2" / "smoke"
            smoke.mkdir(parents=True)
            (smoke / "params.txt").write_text("smoke\n", encoding="utf-8")
            populated = root / "n2" / "r1"
            populated.mkdir()
            (populated / "handoffs.txt").write_text("index\n", encoding="utf-8")
            empty = root / "n4" / "r2"
            empty.mkdir(parents=True)
            self.assertTrue(config.directory_has_entries(smoke))
            self.assertTrue(config.directory_has_entries(populated))
            self.assertFalse(config.directory_has_entries(empty))
            self.assertFalse(config.directory_has_entries(root / "n4" / "r3"))
        repo = Path(__file__).resolve().parents[2]
        script = (repo / "scripts" / "run-in-vm.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$experiment" = "exp2" ]; then', script)
        self.assertIn("refusing to replace existing Exp2 results", script)
        self.assertIn("remote_subdir=experiment/extended/exp2", script)
        self.assertIn("--exclude box --exclude '*.box'", script)
        makefile = (repo / "Makefile.exp2").read_text(encoding="utf-8")
        self.assertIn("experiment-exp2-shared-$(3)-$(2):", makefile)
        self.assertIn("check-exp2-shared-$(3)-$(2):", makefile)
        self.assertIn("experiment-exp2-shared-n2-smoke:", makefile)
        self.assertIn("experiment-exp2-shared-n4-smoke:", makefile)
        self.assertIn("experiment-exp2-shared-n2-full:", makefile)
        self.assertIn("experiment-exp2-shared-n4-full:", makefile)
        self.assertIn("$(EXP2_SHARED_ROOT)/n2/smoke", makefile)
        self.assertIn("$(EXP2_SHARED_ROOT)/n4/smoke", makefile)
        self.assertNotIn("experiment-exp2-shared-n1", makefile)
        self.assertIn("NLSR_HANDOFF_COUNT='8'", makefile)
        self.assertIn("NLSR_HANDOFF_INTERVALS=''", makefile)
        self.assertIn("EXP2_SCHEDULE='full'", makefile)
        self.assertIn("campaign.txt", makefile)
        self.assertIn("acc2,acc3,acc4,acc5,acc6,acc5,acc4,acc3,acc2", makefile)
        top = (repo / "Makefile").read_text(encoding="utf-8")
        self.assertNotIn("experiment-exp2-shared-n2-full", top)
        self.assertNotIn("experiment-exp2-shared-n4-r1", top)
        self.assertNotIn("experiment-exp2-shared-n1", top)

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
        self.assertEqual(config.topology_position("consumer3", "acc2", "acc3"), "moves_onto_consumer_access")
        self.assertEqual(config.topology_position("consumer3", "acc3", "acc4"), "moves_away_from_consumer_access")
        self.assertEqual(config.topology_position("consumer4", "acc5", "acc6"), "moves_onto_consumer_access")
        self.assertEqual(config.topology_position("consumer4", "acc6", "acc5"), "moves_away_from_consumer_access")
        with self.assertRaises(config.Exp2ConfigError):
            config.topology_position("consumer5", "acc2", "acc3")


class Exp2NameTest(unittest.TestCase):
    def test_version_and_segment_aliases_match_pcap_spellings(self) -> None:
        alias = "/LiveStream/v0/v=998/seg=0"
        pcap = "/LiveStream/v0/54=%03%E6/50=%00"
        self.assertEqual(exp2.semantic_components(alias), exp2.semantic_components(pcap))
        self.assertEqual(exp2.semantic_name(alias), exp2.semantic_name(pcap))
        self.assertEqual(exp2.semantic_name(exp2.semantic_name(alias)), exp2.semantic_name(alias))
        self.assertEqual(exp2.semantic_name(exp2.semantic_name(pcap)), exp2.semantic_name(pcap))
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


def _reference_match(records, name, data_time, consumer):
    """Independent scan of the accepted validation rule, used only by tests."""
    canonical = exp2.semantic_name(name)
    matched = []
    for record in records:
        record_name = str(record.get("name") or "")
        if not record_name or exp2.semantic_name(record_name) != canonical:
            continue
        record_consumer = str(record.get("consumer_id") or "")
        if record_consumer and record_consumer != consumer:
            continue
        matched.append(record)
    if not matched:
        return "absent", ""
    successes = [record for record in matched if record["ok"]]
    pool = successes or matched
    best = min(pool, key=lambda record: abs(float(str(record["time_s"])) - data_time))
    outcome = "success" if best["ok"] else "failure"
    return outcome, f"{float(str(best['time_s'])):.9f}"


class Exp2ValidationIndexTest(unittest.TestCase):
    def test_match_agrees_with_reference_scan(self) -> None:
        tied = "/LiveStream/v0/v=4/seg=0"
        nearer = "/LiveStream/v0/v=5/seg=0"
        mixed = "/LiveStream/v0/v=6/seg=1"
        records = [
            {"ok": True, "time_s": 101.0, "name": tied, "consumer_id": "consumer1"},
            {"ok": True, "time_s": 99.0, "name": tied, "consumer_id": "consumer1"},
            {"ok": True, "time_s": 100.2, "name": nearer, "consumer_id": "consumer1"},
            {"ok": False, "time_s": 100.0, "name": mixed, "consumer_id": "consumer1"},
            {"ok": True, "time_s": 110.0, "name": mixed, "consumer_id": "consumer1"},
            {"ok": True, "time_s": 100.0, "name": tied, "consumer_id": "consumer2"},
            {"ok": True, "time_s": 50.0, "name": tied, "consumer_id": ""},
        ]
        queries = (
            (tied, 100.0, "consumer1"),
            (nearer, 100.0, "consumer1"),
            (mixed, 100.0, "consumer1"),
            (tied, 100.0, "consumer2"),
            (mixed, 100.0, "consumer2"),
        )
        for name, data_time, consumer in queries:
            self.assertEqual(
                exp2.match_validation(records, name, data_time, consumer),
                _reference_match(records, name, data_time, consumer),
            )
        equal = exp2.match_validation(records, tied, 100.0, "consumer1")
        self.assertEqual(equal[0], "success")
        self.assertEqual(equal[1], f"{101.0:.9f}")
        closer = exp2.match_validation(records, nearer, 100.0, "consumer1")
        self.assertEqual(closer[1], f"{100.2:.9f}")
        success_over_failure = exp2.match_validation(records, mixed, 100.0, "consumer1")
        self.assertEqual(success_over_failure[0], "success")
        self.assertEqual(success_over_failure[1], f"{110.0:.9f}")
        self.assertEqual(exp2.match_validation(records, tied, 100.0, "consumer2")[0], "success")
        self.assertEqual(exp2.match_validation(records, mixed, 100.0, "consumer2"), ("absent", ""))

    def test_latest_send_not_an_earlier_same_name_copy(self) -> None:
        send_early = HANDOFF - 1.0
        send_late = HANDOFF + 0.05
        receive = HANDOFF + 0.10
        producer_log = (
            f"[{int(send_early * 1e9)}] DATA: Sending response Size: 100 bytes Name: {CONTENT}\n"
            f"[{int(send_late * 1e9)}] DATA: Sending response Size: 100 bytes Name: {CONTENT}\n"
        )
        packets = [
            _packet(HANDOFF - 2.0, "consumer1", True, "interest", CONTENT),
            _packet(HANDOFF - 0.2, "consumer1", True, "interest", CONTENT),
            _packet(send_early, "producer", True, "data", CONTENT),
            _packet(send_late, "producer", True, "data", CONTENT),
            _packet(receive, "consumer1", False, "data", CONTENT),
        ]
        log = f"[{int(receive * 1e9)}] VALIDATE: Data signature verified name={CONTENT} id=consumer1\n"
        rows, _audits = exp2.observe_run(
            packets, [metrics.Handoff(1, HANDOFF, "acc2", "acc3")], ("consumer1",),
            {"consumer1": exp2.parse_validation_log(log)},
            exp2.parse_producer_log(producer_log),
        )
        row = rows[0]
        self.assertEqual(row["producer_send_time"], f"{send_late:.9f}")
        self.assertEqual(row["origin"], "producer_pending_interest")
        self.assertEqual(row["interest_time"], f"{HANDOFF - 2.0:.6f}")
        self.assertEqual(row["interest_predates_handoff"], "true")
        self.assertNotEqual(row["validated_producer_service_recovery_ms"], "")

    def test_later_same_name_copy_does_not_open_a_second_candidate(self) -> None:
        name = CONTENT
        first_receive = HANDOFF + 0.01
        second_receive = HANDOFF + 0.30
        packets = [
            _packet(HANDOFF - 1.0, "producer", True, "data", name),
            _packet(first_receive, "consumer1", False, "data", name),
            _packet(HANDOFF + 0.20, "producer", True, "data", name),
            _packet(second_receive, "consumer1", False, "data", name),
            _packet(HANDOFF + 0.05, "consumer1", False, "data", "/LiveStream/v0/v=2/seg=0"),
        ]
        producer_log = (
            f"[{int((HANDOFF - 1.0) * 1e9)}] DATA: Sending response Size: 100 bytes Name: {name}\n"
            f"[{int((HANDOFF + 0.20) * 1e9)}] DATA: Sending response Size: 100 bytes Name: {name}\n"
            f"[{int((HANDOFF + 0.04) * 1e9)}] DATA: Sending response Size: 100 bytes Name: /LiveStream/v0/v=2/seg=0\n"
        )
        validation = (
            f"[{int(first_receive * 1e9)}] VALIDATE: Data signature verified name={name} id=consumer1\n"
            f"[{int(second_receive * 1e9)}] VALIDATE: Data signature verified name={name} id=consumer1\n"
            f"[{int((HANDOFF + 0.05) * 1e9)}] VALIDATE: Data signature verified name=/LiveStream/v0/v=2/seg=0 id=consumer1\n"
        )
        rows, _audits = exp2.observe_run(
            packets, [metrics.Handoff(1, HANDOFF, "acc2", "acc3")], ("consumer1",),
            {"consumer1": exp2.parse_validation_log(validation)},
            exp2.parse_producer_log(producer_log),
        )
        row = rows[0]
        self.assertEqual(row["first_arrival_origin"], "in_flight_arrival")
        self.assertEqual(row["recovery_name"], exp2.semantic_name("/LiveStream/v0/v=2/seg=0"))
        self.assertEqual(row["delivered_unique_frames"], 2)
        self.assertNotEqual(row["recovery_name"], row["first_arrival_name"])

    def test_n1_and_n2_keep_shared_overhead_across_eight_handoffs(self) -> None:
        sequence = config.FULL_HANDOFF_SEQUENCE
        handoffs = [
            metrics.Handoff(index + 1, HANDOFF + index * 10.0, sequence[index], sequence[index + 1])
            for index in range(8)
        ]
        receive = HANDOFF + 71.0
        name = "/LiveStream/v0/v=8/seg=0"
        packets = [
            _packet(HANDOFF + 1.0, "core", True, "data", name, length=40, data_mobility_flag=True),
            _packet(HANDOFF + 1.0, "core", True, "interest", "/ndn/nlsr/update", length=12),
            _packet(receive, "producer", True, "data", name),
            _packet(receive, "consumer1", False, "data", name),
            _packet(receive + 0.01, "consumer2", False, "data", name),
        ]
        producer_log = f"[{int(receive * 1e9)}] DATA: Sending response Size: 100 bytes Name: {name}\n"
        validation = {
            "consumer1": exp2.parse_validation_log(
                f"[{int(receive * 1e9)}] VALIDATE: Data signature verified name={name} id=consumer1\n"
            ),
            "consumer2": exp2.parse_validation_log(
                f"[{int((receive + 0.01) * 1e9)}] VALIDATE: Data signature verified name={name} id=consumer2\n"
            ),
        }
        n1, _audits = exp2.observe_run(
            packets, handoffs, ("consumer1",), {"consumer1": validation["consumer1"]},
            exp2.parse_producer_log(producer_log),
        )
        n2, _audits = exp2.observe_run(
            packets, handoffs, ("consumer1", "consumer2"), validation,
            exp2.parse_producer_log(producer_log),
        )
        self.assertEqual(len(n1), 8)
        self.assertEqual(len(n2), 16)
        self.assertEqual({row["network_recovery_flood_bytes"] for row in n1 if row["handoff_index"] == 1}, {40})
        self.assertEqual({row["nlsr_control_bytes"] for row in n2 if row["handoff_index"] == 1}, {12})
        self.assertEqual(
            {row["network_recovery_flood_bytes"] for row in n2 if row["handoff_index"] == 1},
            {40},
        )
        by_key = {(row["consumer"], row["handoff_index"]): row for row in n2}
        self.assertEqual(by_key[("consumer1", 1)]["origin"], "absent")
        self.assertNotEqual(by_key[("consumer1", 8)]["validated_producer_service_recovery_ms"], "")
        self.assertNotEqual(by_key[("consumer2", 8)]["validated_producer_service_recovery_ms"], "")
        self.assertNotEqual(
            by_key[("consumer1", 8)]["validated_producer_service_recovery_ms"],
            by_key[("consumer2", 8)]["validated_producer_service_recovery_ms"],
        )


def _synthetic_workload(frame_count: int):
    sequence = config.FULL_HANDOFF_SEQUENCE
    base = HANDOFF
    handoffs = [
        metrics.Handoff(index + 1, base + index * 100.0, sequence[index], sequence[index + 1])
        for index in range(8)
    ]
    packets = []
    validation: Dict[str, List[Dict[str, object]]] = {"consumer1": [], "consumer2": []}
    producer = []
    for frame in range(frame_count):
        window = frame % 8
        start = handoffs[window].abs_time
        alias = f"/LiveStream/v0/v={frame}/seg=0"
        if frame % 17 == 0:
            send = start - 0.02
            receive = start + 0.01
        else:
            send = start + 0.03
            receive = start + 0.04
        packets.append(_packet(send, "producer", True, "data", alias))
        producer.append({"kind": "data", "time_s": send, "name": alias})
        for consumer in ("consumer1", "consumer2"):
            packets.append(_packet(start - 1.0, consumer, True, "interest", alias))
            packets.append(_packet(receive, consumer, False, "data", alias))
            if frame % 13 != 0:
                validation[consumer].append({
                    "ok": frame % 29 != 0,
                    "time_s": receive,
                    "name": alias,
                    "consumer_id": consumer,
                })
        if frame % 8 == 0:
            packets.append(_packet(start + 0.05, "core", True, "data", alias, length=40, data_mobility_flag=True))
            packets.append(_packet(start + 0.06, "core", True, "interest", "/ndn/nlsr/update", length=12))
    return packets, handoffs, validation, producer


def _populate_run(root: Path, consumers: tuple, mode: str = "smoke") -> Path:
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
    (run_dir / "campaign.txt").write_text(config.campaign_text(consumers, mode, run_id), encoding="utf-8")
    (run_dir / "topology.txt").write_text(config.topology_text(consumers, sequence), encoding="utf-8")
    intervals = [20.0, 30.0] if mode == "smoke" else [90.0 + index for index in range(count + 1)]
    params = {
        "exp2_active_consumers": ",".join(consumers),
        "exp2_schedule": mode,
        "exp2_campaign": config.CAMPAIGN_ID,
        "exp2_interval_source": "configured" if mode == "smoke" else "sampled",
        "exp2_realized_intervals_s": ",".join(f"{value:.6f}" for value in intervals),
        "handoff_sequence": ",".join(sequence),
        "handoff_count": str(count),
        "handoff_interval_base_s": "20.000" if mode == "smoke" else "90.000",
        "handoff_interval_jitter_s": "0.000" if mode == "smoke" else "60.000",
        "request_interval_ms": "20",
        "segments_per_frame": "1",
        "exp2_stream_prefix": config.STREAM_PREFIX,
        "exp2_advertised_prefix": config.ADVERTISED_PREFIX,
        "exp2_guard_name": config.GUARD_NAME,
    }
    (run_dir / "params.txt").write_text("".join(f"{key}={value}\n" for key, value in params.items()), encoding="utf-8")
    handoff_lines = ["index\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n"]
    for index in range(count):
        stamp = HANDOFF + index * 10.0
        handoff_lines.append(
            f"{index + 1}\t{stamp:.6f}\t{index * 10.0:.6f}\t{sequence[index]}\t{sequence[index + 1]}\t{intervals[index]:.6f}\n"
        )
    (run_dir / "handoffs.txt").write_text("".join(handoff_lines), encoding="utf-8")
    if mode == "smoke":
        received = int((HANDOFF + 1.0) * 1e9)
        for consumer in consumers:
            (run_dir / f"{consumer}.log").write_text(
                f"[{received}] DATA: frame=1 seg=0 Size: 100 bytes\n"
                f"[{received}] VALIDATE: Data signature verified name=/LiveStream/v0/v=1/seg=0 id={consumer}\n",
                encoding="utf-8",
            )
    return run_dir


class Exp2EvidenceTest(unittest.TestCase):
    def test_complete_smoke_and_full_directories_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n2_smoke = _populate_run(root, config.parse_active_consumers("n2"), "smoke")
            n4_full = _populate_run(root, config.parse_active_consumers("n4"), "full")
            self.assertEqual(config.inspect_run(n2_smoke), [])
            self.assertEqual(config.inspect_run(n4_full), [])

    def test_n2_rejects_consumer3_and_missing_or_empty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = _populate_run(root, config.parse_active_consumers("n2"), "smoke")
            stray = run_dir / "pcap_nodes" / "consumer3.pcap"
            stray.write_bytes(b"not-an-n2-host")
            problems = config.inspect_run(run_dir)
            self.assertTrue(any("consumer3" in problem for problem in problems))
            stray.unlink()
            (run_dir / "pcap_nodes" / "acc1.pcap").write_bytes(b"short")
            problems = config.inspect_run(run_dir)
            self.assertTrue(any("acc1.pcap" in problem for problem in problems))
            (run_dir / "minindn-logs" / "producer" / "nfd.log").write_text("", encoding="utf-8")
            problems = config.inspect_run(run_dir)
            self.assertTrue(any("nfd.log" in problem for problem in problems))

    def test_smoke_without_validation_fails_and_old_campaign_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = _populate_run(root, config.parse_active_consumers("n4"), "smoke")
            (run_dir / "consumer4.log").write_text(
                f"[{int((HANDOFF - 5) * 1e9)}] DATA: frame=1 seg=0 Size: 10 bytes\n",
                encoding="utf-8",
            )
            problems = config.inspect_run(run_dir)
            self.assertTrue(any("consumer4" in problem and "validation" in problem for problem in problems))
            (run_dir / "campaign.txt").write_text("exp2_campaign=preliminary-n1\n", encoding="utf-8")
            problems = config.inspect_run(run_dir)
            self.assertTrue(any("campaign id" in problem for problem in problems))


class Exp2BenchmarkTest(unittest.TestCase):
    def test_observe_run_scales_linearly_for_synthetic_frames(self) -> None:
        _synthetic_workload(1000)
        measured = []
        for frame_count in (5000, 20000, 50000):
            packets, handoffs, validation, producer = _synthetic_workload(frame_count)
            tracemalloc.start()
            started = time.perf_counter()
            rows, _audits = exp2.observe_run(
                packets, handoffs, ("consumer1", "consumer2"), validation, producer,
            )
            elapsed = time.perf_counter() - started
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertEqual(len(rows), 16)
            measured.append((frame_count, elapsed, peak))
            print(f"EXP2_BENCH frames={frame_count} seconds={elapsed:.4f} peak_bytes={peak}")
        small_frames, small_time, small_peak = measured[0]
        large_frames, large_time, large_peak = measured[2]
        growth = large_frames / small_frames
        self.assertLess(large_time / small_time, growth * 3)
        self.assertLess(large_peak / small_peak, growth * 4)
        self.assertLess(measured[1][1] / small_time, (measured[1][0] / small_frames) * 3)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
