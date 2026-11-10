"""Host-side checks for the smoke log parser. Not part of make test."""

from __future__ import annotations

import os
import tempfile
import unittest

import smoke_validate as smoke


HANDOFF_NS = 2_000_000_000_000


def _consumer(
    pre_frame: int,
    post_frame: int,
    post_ns: int,
    post_send_ns: int | None = None,
) -> str:
    send_ns = post_ns - 1_000_000 if post_send_ns is None else post_send_ns
    return "\n".join([
        "[1000000000000] DISCOVER: live edge = 10",
        f"[1400000000000] SEND: frame={pre_frame} seg=0 Name: /LiveStream/v0/v={pre_frame}/seg=0",
        f"[1500000000000] FRAME: delivered frame={pre_frame} latency_ms=1",
        f"[{send_ns}] SEND: frame={post_frame} seg=0 Name: /LiveStream/v0/v={post_frame}/seg=0",
        f"[{post_ns}] FRAME: delivered frame={post_frame} latency_ms=1",
    ])


def _nfd(handoff_s: float) -> str:
    arm = handoff_s + 0.1
    forward = arm + 0.1
    update = forward + 0.1
    use = update + 0.1
    return "\n".join([
        f"{arm:.6f} DEBUG: [nfd.Forwarder] OptoFlood arm prefix=/LiveStream epoch=1 stranded=1",
        f"{forward:.6f} DEBUG: [nfd.Forwarder] OptoFlood forward data=/LiveStream/%FD%01 floodId=1 outFace=2",
        f"{update:.6f} DEBUG: [nfd.Forwarder] OptoFlood TFIB update prefix=/LiveStream face=3 newFaceSeq=1 floodId=1",
        f"{use:.6f} DEBUG: [nfd.Forwarder] OptoFlood tfib-forward interest=/LiveStream/%FD%02 nonce=9",
        f"{use + 1:.6f} DEBUG: [nfd.Forwarder] OptoFlood tfib-forward interest=/LiveStream/_guard nonce=8",
    ])


class BaselineSmokeTextTest(unittest.TestCase):
    def test_discovery_before_delivery_passes(self) -> None:
        text = "\n".join([
            "[10] DISCOVER: live edge = 4",
            "[20] FRAME: delivered frame=4 latency_ms=1",
            "[30] PREFIX: Successfully advertised prefix via NLSR",
        ])
        self.assertIsNone(smoke.discover_and_delivery(text))

    def test_delivery_before_discovery_fails(self) -> None:
        text = "\n".join([
            "[20] FRAME: delivered frame=4 latency_ms=1",
            "[30] DISCOVER: live edge = 4",
        ])
        self.assertIsNotNone(smoke.discover_and_delivery(text))


class SolutionSmokeTextTest(unittest.TestCase):
    def test_ordered_handoff_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self._write(temporary, post_frame=8, post_ns=HANDOFF_NS + 50_000_000_000)
            self.assertEqual(smoke.check_solution(temporary), [])

    def test_guard_interest_does_not_count_as_tfib_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self._write(temporary, post_frame=8, post_ns=HANDOFF_NS + 50_000_000_000)
            path = os.path.join(temporary, "r3_nfd.log")
            kept = [
                line for line in smoke.read_text(path).splitlines()
                if "interest=/LiveStream/%FD%02" not in line
            ]
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(kept) + "\n")
            errors = smoke.check_solution(temporary)
            self.assertTrue(any("TFIB" in error for error in errors))

    def test_inflight_request_delivered_after_handoff_is_not_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self._write(
                temporary,
                post_frame=8,
                post_ns=HANDOFF_NS + 50_000_000_000,
                post_send_ns=HANDOFF_NS - 10_000_000,
            )
            errors = smoke.check_solution(temporary)
            self.assertTrue(any("fresh" in error for error in errors))

    def test_root_fib_is_not_a_livestream_route(self) -> None:
        self.assertFalse(smoke.has_non_root_livestream_fib("FIB:\n  / nexthops={faceid=1 (cost=0)}\n"))
        self.assertTrue(smoke.has_non_root_livestream_fib(
            "FIB:\n  / nexthops={faceid=1 (cost=0)}\n  /LiveStream nexthops={faceid=256 (cost=0)}\n"
        ))
        business, guard, fib = smoke.pre_handoff_status(
            _consumer(4, 8, HANDOFF_NS - 1),
            "[1] GUARD-PRODUCER: holding guard /LiveStream/_guard lifetime_ms=4000",
            "  /LiveStream nexthops={faceid=256 (cost=0)}",
        )
        self.assertEqual((business, guard, fib), (True, True, True))
        held_without_business = smoke.pre_handoff_status(
            "[1] GUARD-CONSUMER: sent #1 nonce=1",
            "[1] GUARD-PRODUCER: holding guard /LiveStream/_guard lifetime_ms=4000",
            "  / nexthops={faceid=1 (cost=0)}",
        )
        self.assertEqual(held_without_business, (False, True, False))

    def test_same_frame_after_handoff_is_not_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self._write(temporary, post_frame=4, post_ns=HANDOFF_NS + 50_000_000_000)
            errors = smoke.check_solution(temporary)
            self.assertTrue(any("fresh" in error for error in errors))

    def _write(self, directory: str, post_frame: int, post_ns: int, post_send_ns: int | None = None) -> None:
        with open(os.path.join(directory, "handoff.txt"), "w", encoding="utf-8") as handle:
            handle.write(f"handoff_ns={HANDOFF_NS}\nprefix=/LiveStream\nfrom=r2\nto=r3\n")
        with open(os.path.join(directory, "consumer.log"), "w", encoding="utf-8") as handle:
            handle.write(_consumer(4, post_frame, post_ns, post_send_ns))
        with open(os.path.join(directory, "optoflood_producer.log"), "w", encoding="utf-8") as handle:
            handle.write(
                f"[{HANDOFF_NS + 1_000_000_000}] MOBILITY: armed NFD "
                "/localhost/nfd/optoflood/arm/LiveStream\n"
            )
        with open(os.path.join(directory, "r3_nfd.log"), "w", encoding="utf-8") as handle:
            handle.write(_nfd(HANDOFF_NS / 1_000_000_000.0))


if __name__ == "__main__":
    unittest.main()
