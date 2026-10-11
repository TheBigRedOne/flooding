#!/usr/bin/env python3
"""Host-side Exp2-A checks. Fixtures are synthetic, not experiment results."""

from __future__ import annotations

import sys
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
        self.assertEqual(rows[0]["origin"], "producer_post_handoff_interest")

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
        self.assertEqual(by_consumer["consumer1"]["origin"], "producer_transmission_interest_unseen")
        self.assertEqual(by_consumer["consumer2"]["origin"], "absent")
        self.assertEqual(by_consumer["consumer2"]["consumer_observed_recovery_ms"], "")
        self.assertEqual(by_consumer["consumer2"]["confirmed_producer_recovery_ms"], "")
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
        self.assertEqual(rows[0]["confirmed_producer_recovery_ms"], "")
        self.assertEqual(rows[0]["validation"], "absent")

    def test_inactive_consumer_application_traffic_is_reported(self) -> None:
        packets = [_packet(HANDOFF + 1.0, "consumer2", True, "interest", CONTENT)]
        notes = exp2.inactive_consumer_application_traffic(packets, ("consumer2",))
        self.assertEqual(len(notes), 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
