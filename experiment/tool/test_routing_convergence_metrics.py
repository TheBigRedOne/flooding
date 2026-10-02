#!/usr/bin/env python3
"""Tests for production routing-convergence analysis. Not a protocol test."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routing_convergence_metrics as routing


def event(kind: str, time: float, **kwargs) -> routing.LogEvent:
    return routing.LogEvent(time, kind, kind, **kwargs)


class RoutingPrototypeTest(unittest.TestCase):
    def test_baseline_skips_build_before_old_adjacency_is_inactive(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = [
            event("status", 110.0, neighbor="acc3", status="ACTIVE"),
            event("build", 120.0),
            event("seq", 120.1, seq=4),
            event("inactive", 130.0, neighbor="acc2", status="INACTIVE"),
            event("build", 140.0),
            event("seq", 140.1, seq=5),
        ]
        result = routing.select_complete_publication(events, handoff, False)
        self.assertEqual(result["complete_adj_lsa_seq"], 5)
        self.assertAlmostEqual(float(result["topology_update_latency_ms"]), 40000.0)

    def test_optoflood_requires_both_verification_facts(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = [
            event("verify-start", 100.1, serial=1),
            event("verify", 100.2, neighbor="acc3", status="REACHABLE", serial=1),
            event("verify", 100.3, neighbor="acc2", status="UNREACHABLE", serial=1),
            event("verify-complete", 100.3),
            event("build", 100.3),
            event("seq", 100.31, seq=7),
            event("settle", 101.3),
        ]
        result = routing.select_complete_publication(events, handoff, True)
        self.assertEqual(result["complete_adj_lsa_seq"], 7)
        self.assertAlmostEqual(float(result["verification_complete_ms"]), 300.0)
        self.assertAlmostEqual(float(result["nlsr_sync_trigger_latency_ms"]), 1300.0)

    def test_incomplete_verification_does_not_invent_a_latency(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = [
            event("verify-start", 100.1, serial=1),
            event("verify", 100.2, neighbor="acc3", status="REACHABLE", serial=1),
            event("verify-complete", 100.3),
            event("build", 100.3),
            event("seq", 100.31, seq=7),
        ]
        result = routing.select_complete_publication(events, handoff, True)
        self.assertEqual(result["topology_update_latency_ms"], "")

    def test_corridor_sequence_matches_encoded_component(self) -> None:
        name = (
            "/localhop/ndn/nlsr/optoflood/corridor/ADJACENCY/%03/"
            "%07%2C%08%03%6E%64%6E%08%0D%70%72%6F%64%75%63%65%72"
        )
        self.assertEqual(routing.corridor_seq(name), 3)
        self.assertIsNone(routing.corridor_seq("/localhop/ndn/nlsr/LSA/producer/ADJACENCY/%03"))

    def test_priority_timestamp_prefers_corridor_data_over_earlier_interest(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = {"acc3": [routing.LogEvent(110.0, "sync", "sync", seq=3)]}
        observations = [
            (101.0, "acc3", "corridor-interest", False),
            (102.0, "acc3", "corridor-data", False),
        ]
        rows = routing.priority_from_observations(events, handoff, 3, "OptoFlood", "r1", observations)
        self.assertEqual(rows[0]["corridor_data_time"], 102.0)
        self.assertNotIn("priority_time", rows[0])
        self.assertAlmostEqual(rows[0]["lead_ms"], 8000.0)

    def test_interest_only_does_not_create_a_formal_lead(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = {"acc3": [routing.LogEvent(110.0, "sync", "sync", seq=3)]}
        observations = [(101.0, "acc3", "corridor-interest", False)]
        self.assertEqual(routing.priority_from_observations(events, handoff, 3, "OptoFlood", "r1", observations), [])

    def test_lead_is_not_subtracted_across_routers(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = {"core": [routing.LogEvent(110.0, "sync", "sync", seq=3)]}
        observations = [(101.0, "acc3", "corridor-data", False)]
        self.assertEqual(routing.priority_from_observations(events, handoff, 3, "OptoFlood", "r1", observations), [])

    def test_per_handoff_median_weights_each_handoff_once(self) -> None:
        pairs = [
            {"run_id": "r1", "handoff_index": 1, "lead_ms": 1000.0},
            {"run_id": "r1", "handoff_index": 1, "lead_ms": 3000.0},
            {"run_id": "r1", "handoff_index": 2, "lead_ms": 1100.0},
        ]
        rows = routing.per_handoff_leads(pairs)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["paired_router_count"], 2)
        self.assertAlmostEqual(float(rows[0]["median_lead_ms"]), 2000.0)

    def test_service_path_excludes_the_consumer(self) -> None:
        graph = {
            "consumer": {"acc1": "udp4://10.0.0.2:6363"},
            "acc1": {"consumer": "udp4://10.0.0.1:6363", "acc3": "udp4://10.0.0.3:6363"},
            "acc3": {"acc1": "udp4://10.0.0.4:6363", "producer": "udp4://10.0.0.5:6363"},
            "producer": {"acc3": "udp4://10.0.0.6:6363"},
        }
        self.assertEqual(routing.routers_toward(graph, "consumer", "acc3"), ["acc1", "acc3"])

    def test_face_mapping_selects_first_hop_toward_new_attachment(self) -> None:
        graph = {
            "consumer": {"acc1": "udp4://10.0.0.2:6363"},
            "acc1": {"consumer": "udp4://10.0.0.1:6363", "agg1": "udp4://10.0.0.3:6363"},
            "agg1": {"acc1": "udp4://10.0.0.4:6363", "acc3": "udp4://10.0.0.5:6363"},
            "acc3": {"agg1": "udp4://10.0.0.6:6363", "producer": "udp4://10.0.0.7:6363"},
            "producer": {"acc3": "udp4://10.0.0.8:6363"},
        }
        self.assertEqual(routing.expected_next_hop(graph, "consumer", "acc3"), "acc1")
        self.assertEqual(routing.expected_next_hop(graph, "acc3", "acc3"), "producer")
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        events = [
            event("fib-add", 110.0, uri="udp4://10.0.0.2:6363"),
            event("fib-remove", 150.0, uri="udp4://10.9.9.9:6363"),
        ]
        self.assertEqual(routing.first_stable_fib(events, handoff, "udp4://10.0.0.2:6363"), 110.0)
        reverted = events + [event("fib-remove", 160.0, uri="udp4://10.0.0.2:6363")]
        self.assertIsNone(routing.first_stable_fib(reverted, handoff, "udp4://10.0.0.2:6363"))

    def test_unchanged_consumer_next_hop_is_not_a_required_change(self) -> None:
        graph = {
            "consumer": {"acc1": "udp4://10.0.0.2:6363"},
            "acc1": {"consumer": "udp4://10.0.0.1:6363", "agg1": "udp4://10.0.0.3:6363"},
            "agg1": {"acc1": "udp4://10.0.0.4:6363", "acc2": "udp4://10.0.0.9:6363", "acc3": "udp4://10.0.0.5:6363"},
            "acc2": {"agg1": "udp4://10.0.0.10:6363"},
            "acc3": {"agg1": "udp4://10.0.0.6:6363", "producer": "udp4://10.0.0.7:6363"},
            "producer": {"acc3": "udp4://10.0.0.8:6363"},
        }
        self.assertEqual(routing.expected_next_hop(graph, "consumer", "acc2"), "acc1")
        self.assertEqual(routing.expected_next_hop(graph, "consumer", "acc3"), "acc1")
        required = [
            router for router in routing.routers_toward(graph, "consumer", "acc3")
            if routing.expected_next_hop(graph, router, "acc2") != routing.expected_next_hop(graph, router, "acc3")
        ]
        self.assertNotIn("consumer", required)
        self.assertEqual(required, ["agg1", "acc3"])

    def test_tfib_standby_is_not_fib_convergence(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        standby = event("tfib-standby", 105.07, uri="udp4://10.0.0.2:6363")
        self.assertIsNone(routing.first_stable_fib([standby], handoff, "udp4://10.0.0.2:6363"))
        installed = routing.first_stable_fib(
            [event("fib-add", 100.2, uri="udp4://10.0.0.2:6363"), standby],
            handoff,
            "udp4://10.0.0.2:6363",
        )
        self.assertEqual(installed, 100.2)

    def test_standby_window_is_five_seconds_of_fib_agreement(self) -> None:
        source = Path(routing.__file__).read_text(encoding="utf-8")
        self.assertIn("TFIB_FIB_STABLE_WINDOW = 5000 ms", source)
        self.assertIn("daemon/fw/forwarder.cpp", source)
        self.assertIn("not the first instant the FIB is correct", source)

    def test_nfd_success_matches_face_and_rejects_unrelated_rib_updates(self) -> None:
        lines = [
            "100.0 DEBUG: [nfd.RibManager] RIB update succeeded for RibUpdate {",
            "  Name: /ndn/other",
            "  Action: REGISTER",
            "  Route(faceid: 1, origin: nlsr, cost: 1, flags: 0x2, never expires)",
            "}",
            "101.0 DEBUG: [nfd.RibManager] RIB update succeeded for RibUpdate {",
            "  Name: /LiveStream",
            "  Action: REGISTER",
            "  Route(faceid: 9, origin: app, cost: 0, flags: 0x0, never expires)",
            "}",
            "102.0 DEBUG: [nfd.RibManager] RIB update succeeded for RibUpdate {",
            "  Name: /LiveStream",
            "  Action: REGISTER",
            "  Route(faceid: 270, origin: nlsr, cost: 10, flags: 0x2, expires in: 1000 milliseconds)",
            "}",
            "103.0 DEBUG: [nfd.RibManager] RIB update failed for RibUpdate {",
            "  Name: /LiveStream",
            "  Action: REGISTER",
            "  Route(faceid: 271, origin: nlsr, cost: 10, flags: 0x2, never expires)",
            "}",
        ]
        operations = routing.parse_nfd_livestream_lines(lines)
        self.assertEqual(operations, [(102.0, "REGISTER", 270)])
        bound, unmapped = routing.bind_nfd_operations(operations, {270: "udp4://10.0.0.18:6363"})
        self.assertEqual(unmapped, 0)
        self.assertEqual(bound, [(102.0, "REGISTER", "udp4://10.0.0.18:6363")])
        unbound, missed = routing.bind_nfd_operations(operations, {})
        self.assertEqual(unbound, [])
        self.assertEqual(missed, 1)

    def test_nfd_confirmation_is_not_taken_from_a_different_face(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        operations = [
            (110.0, "REGISTER", "udp4://10.0.0.10:6363"),
            (130.0, "REGISTER", "udp4://10.0.0.18:6363"),
        ]
        self.assertEqual(
            routing.first_stable_confirmed(operations, handoff, "udp4://10.0.0.18:6363"),
            130.0,
        )

    def test_confirmed_route_reversion_invalidates_the_router(self) -> None:
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        operations = [
            (110.0, "REGISTER", "udp4://10.0.0.18:6363"),
            (150.0, "UNREGISTER", "udp4://10.0.0.18:6363"),
        ]
        self.assertIsNone(routing.first_stable_confirmed(operations, handoff, "udp4://10.0.0.18:6363"))

    def test_final_handoff_horizon_stops_at_capture_end(self) -> None:
        final = routing.Handoff(8, 100.0, 100.02, "acc3", "acc2", True)
        self.assertFalse(routing.in_observation_window(100.03, final))
        self.assertTrue(routing.in_observation_window(100.02, final))
        following = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3", False)
        self.assertFalse(routing.in_observation_window(200.0, following))

    def test_evidence_level_is_not_mixed(self) -> None:
        rows = [{
            "handoff_time": 100.0,
            "fib_observation_end_time": 200.0,
            "_nlsr_service_ms": 1000.0,
            "_nlsr_first_ms": 900.0,
            "_nfd_service_ms": 1010.0,
            "_nfd_first_ms": 905.0,
            "_nlsr_network_ms": 1200.0,
            "_nfd_network_ms": 1210.0,
            "_nlsr_network_limiter": "acc2",
            "_nfd_network_limiter": "acc2",
            "_ecmp": False,
        }]
        routing.apply_evidence_level(rows, "NFD_CONFIRMED")
        self.assertEqual(rows[0]["service_path_fib_convergence_ms"], 1010.0)
        self.assertEqual(rows[0]["service_path_fib_registration_ms"], 1000.0)
        self.assertEqual(rows[0]["network_fib_convergence_ms"], 1210.0)
        self.assertNotIn("_nlsr_service_ms", rows[0])
        nlsr_rows = [{
            "handoff_time": 100.0,
            "fib_observation_end_time": 200.0,
            "_nlsr_service_ms": 1000.0,
            "_nlsr_first_ms": 900.0,
            "_nfd_service_ms": "",
            "_nfd_first_ms": "",
            "_nlsr_network_ms": 1200.0,
            "_nfd_network_ms": "",
            "_nlsr_network_limiter": "acc2",
            "_nfd_network_limiter": "",
            "_ecmp": False,
        }]
        routing.apply_evidence_level(nlsr_rows, "NLSR_CONFIRMED")
        self.assertEqual(nlsr_rows[0]["service_path_fib_convergence_ms"], 1000.0)
        self.assertEqual(nlsr_rows[0]["network_fib_convergence_ms"], 1200.0)
        self.assertEqual(nlsr_rows[0]["fib_endpoint_evidence_level"], "NLSR_CONFIRMED")

    def test_affected_routers_exclude_unchanged_and_allow_ecmp_sets(self) -> None:
        base = {
            "consumer": {"acc1": 5.0},
            "acc1": {"consumer": 5.0, "agg1": 5.0},
            "agg1": {"acc1": 5.0, "core": 1.0, "acc2": 5.0, "acc3": 5.0},
            "core": {"agg1": 1.0, "agg2": 1.0},
            "agg2": {"core": 1.0, "acc4": 5.0},
            "acc2": {"agg1": 5.0, "producer": 5.0},
            "acc3": {"agg1": 5.0, "producer": 5.0},
            "acc4": {"agg2": 5.0},
            "producer": {"acc2": 5.0, "acc3": 5.0},
        }
        old = routing.graph_for_attachment(base, "acc2")
        new = routing.graph_for_attachment(base, "acc3")
        old_distance = routing.distances_from(old, "producer")
        new_distance = routing.distances_from(new, "producer")
        affected = []
        for router in ("consumer", "acc1", "agg1", "core", "agg2", "acc2", "acc3", "acc4"):
            before = routing.acceptable_next_hops(old, old_distance, router)
            after = routing.acceptable_next_hops(new, new_distance, router)
            self.assertEqual(len(before), 1)
            self.assertEqual(len(after), 1)
            if before != after:
                affected.append(router)
        self.assertEqual(affected, ["agg1", "acc2", "acc3"])
        self.assertEqual(routing.acceptable_next_hops(new, new_distance, "consumer"), {"acc1"})
        tied = {
            "source": {"a": 1.0, "b": 1.0},
            "a": {"source": 1.0, "producer": 1.0},
            "b": {"source": 1.0, "producer": 1.0},
            "producer": {"a": 1.0, "b": 1.0},
        }
        distance = routing.distances_from(tied, "producer")
        self.assertEqual(routing.acceptable_next_hops(tied, distance, "source"), {"a", "b"})

    def test_service_routers_are_a_subset_and_network_time_is_the_max(self) -> None:
        graph = {
            "consumer": {"acc1": "udp4://10.0.0.2:6363"},
            "acc1": {"consumer": "udp4://10.0.0.1:6363", "agg1": "udp4://10.0.0.3:6363"},
            "agg1": {"acc1": "udp4://10.0.0.4:6363", "acc2": "udp4://10.0.0.9:6363", "acc3": "udp4://10.0.0.5:6363"},
            "acc2": {"agg1": "udp4://10.0.0.10:6363"},
            "acc3": {"agg1": "udp4://10.0.0.6:6363", "producer": "udp4://10.0.0.7:6363"},
            "producer": {"acc3": "udp4://10.0.0.8:6363"},
        }
        required = [
            router for router in routing.routers_toward(graph, "consumer", "acc3")
            if routing.expected_next_hop(graph, router, "acc2") != routing.expected_next_hop(graph, router, "acc3")
        ]
        affected = ["agg1", "acc2", "acc3"]
        self.assertTrue(set(required) <= set(affected))
        self.assertNotIn("consumer", required)
        handoff = routing.Handoff(1, 100.0, 200.0, "acc2", "acc3")
        agg = [
            (90.0, "REGISTER", "old"),
            (110.0, "UNREGISTER", "old"),
            (120.0, "REGISTER", "new-agg"),
        ]
        poa = [
            (90.0, "REGISTER", "old"),
            (130.0, "REGISTER", "new-poa"),
            (140.0, "UNREGISTER", "old"),
        ]
        self.assertEqual(routing.first_stable_next_hop_set(agg, handoff, {"new-agg"}), 120.0)
        self.assertEqual(routing.first_stable_next_hop_set(poa, handoff, {"new-poa"}), 140.0)
        self.assertEqual(max(120.0, 140.0), 140.0)
        reverted = agg + [(150.0, "REGISTER", "extra")]
        self.assertIsNone(routing.first_stable_next_hop_set(reverted, handoff, {"new-agg"}))

    def test_unfinished_network_router_is_right_censored_not_a_convergence_time(self) -> None:
        rows = [{
            "handoff_time": 0.0,
            "fib_observation_end_time": 94.332,
            "_nlsr_service_ms": 90000.0,
            "_nlsr_first_ms": 80000.0,
            "_nfd_service_ms": 94315.0,
            "_nfd_first_ms": 90000.0,
            "_nlsr_network_ms": "",
            "_nfd_network_ms": "",
            "_nlsr_network_limiter": "",
            "_nfd_network_limiter": "",
            "_network_censored": True,
            "_network_censor_boundary_ms": 94332.0,
            "_ecmp": False,
        }]
        routing.apply_evidence_level(rows, "NFD_CONFIRMED")
        self.assertEqual(rows[0]["network_fib_converged"], "false")
        self.assertEqual(rows[0]["network_fib_convergence_ms"], "")
        self.assertEqual(rows[0]["network_fib_censor_boundary_ms"], 94332.0)
        self.assertEqual(rows[0]["service_path_fib_convergence_ms"], 94315.0)
        self.assertNotIn("tfib_standby_fib_agrees_ms", str(rows[0]["network_fib_convergence_ms"]))

    def test_censored_boundary_is_excluded_from_box_numbers_but_event_is_retained(self) -> None:
        rows = [
            {"network_fib_converged": "true", "network_fib_convergence_ms": 10.0, "network_fib_censor_boundary_ms": ""},
            {"network_fib_converged": "true", "network_fib_convergence_ms": 30.0, "network_fib_censor_boundary_ms": ""},
            {"network_fib_converged": "false", "network_fib_convergence_ms": "", "network_fib_censor_boundary_ms": 94.33},
        ]
        observed = routing.numeric(rows, "network_fib_convergence_ms")
        self.assertEqual(observed, [10.0, 30.0])
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row["network_fib_converged"] == "false" for row in rows), 1)
        self.assertNotIn(94.33, observed)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
