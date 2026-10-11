"""Exp2-A per-consumer observations. Does not change main-experiment metrics."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import mobility_event_metrics as metrics

from exp2_shared_config import FRAME_PERIOD_MS, GUARD_NAME, STREAM_PREFIX

OBSERVATION_FIELDS = (
    "consumer",
    "handoff_index",
    "from_node",
    "to_node",
    "handoff_time",
    "event_end_time",
    "observed_data_time",
    "consumer_observed_recovery_ms",
    "confirmed_producer_recovery_ms",
    "interest_to_data_ms",
    "content_name",
    "frame_id",
    "interest_time",
    "interest_predates_handoff",
    "producer_interest_time",
    "producer_data_time",
    "origin",
    "validation",
    "validation_time",
    "delivered_unique_frames",
    "nominal_frame_opportunities",
    "content_loss_fraction",
    "network_recovery_flood_bytes",
    "nlsr_control_bytes",
    "audit",
)

_VALIDATE_OK = re.compile(
    r"^\[(\d+)\] VALIDATE: Data signature verified(?: name=(\S+))?(?: id=(\S+))?"
)
_VALIDATE_BAD = re.compile(
    r"^\[(\d+)\] ERROR: Data validation failed: (.*?)(?: name=(\S+))?(?: id=(\S+))?\s*$"
)


def log_timestamp_seconds(raw: int) -> float:
    """Convert a system_clock count to seconds. Nanosecond counts are the experiment clock."""
    if raw > 10**14:
        return raw / 1e9
    if raw > 10**11:
        return raw / 1e6
    return float(raw)


def parse_validation_log(text: str) -> List[Dict[str, object]]:
    """Validation lines that name a Data packet. Lines without a name stay unmatched."""
    records: List[Dict[str, object]] = []
    for line in text.splitlines():
        ok_match = _VALIDATE_OK.match(line.strip())
        if ok_match:
            records.append({
                "ok": True,
                "time_s": log_timestamp_seconds(int(ok_match.group(1))),
                "name": ok_match.group(2) or "",
                "consumer_id": ok_match.group(3) or "",
            })
            continue
        bad_match = _VALIDATE_BAD.match(line.strip())
        if bad_match:
            records.append({
                "ok": False,
                "time_s": log_timestamp_seconds(int(bad_match.group(1))),
                "name": bad_match.group(3) or "",
                "consumer_id": bad_match.group(4) or "",
                "error": bad_match.group(2),
            })
    return records


def _in_window(item: float, start: float, end: float, last: bool) -> bool:
    if item <= start:
        return False
    if last:
        return item <= end
    return item < end


def _index(packets: Iterable[metrics.Packet], node: str, outbound: bool, ptype: str, useful: bool) -> Dict[str, List[float]]:
    grouped: Dict[str, List[float]] = {}
    for packet in packets:
        if packet.node != node or packet.outbound != outbound or packet.ptype != ptype:
            continue
        if useful and not metrics.is_useful_content(packet.name):
            continue
        grouped.setdefault(packet.name, []).append(packet.time)
    for times in grouped.values():
        times.sort()
    return grouped


def _earliest(times: Sequence[float], start: float, end: float, last: bool) -> Optional[float]:
    for item in times:
        if _in_window(item, start, end, last):
            return item
    return None


def match_validation(records: Sequence[Mapping[str, object]], name: str, data_time: float) -> Tuple[str, str]:
    """Return (result, validation_time). Result is success, failure, or absent."""
    best_gap = None
    best: Optional[Mapping[str, object]] = None
    canonical = metrics.canonical_name(name)
    for record in records:
        record_name = str(record.get("name") or "")
        if not record_name or metrics.canonical_name(record_name) != canonical:
            continue
        gap = abs(float(str(record["time_s"])) - data_time)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = record
    if best is None or best_gap is None or best_gap > 5.0:
        return "absent", ""
    result = "success" if best["ok"] else "failure"
    return result, f"{float(str(best['time_s'])):.9f}"


def _origin(
    interest_time: Optional[float],
    handoff_time: float,
    producer_interest_time: Optional[float],
    producer_data_time: Optional[float],
) -> Tuple[str, str]:
    if producer_data_time is None:
        return (
            "origin_uncertain",
            "Consumer received content Data after the handoff, but this capture has no "
            "producer egress Data for that name after the handoff. Cache delivery and "
            "pending-Interest delivery cannot be separated.",
        )
    if interest_time is not None and interest_time <= handoff_time:
        return (
            "producer_pending_interest",
            "The consumer Interest predates the handoff and the producer transmitted this Data after the handoff.",
        )
    if producer_interest_time is not None:
        return (
            "producer_post_handoff_interest",
            "The producer received a content Interest for this name after the handoff and then transmitted the Data.",
        )
    return (
        "producer_transmission_interest_unseen",
        "The producer transmitted this Data after the handoff. No matching post-handoff producer Interest was observed.",
    )


def observe_run(
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    active_consumers: Sequence[str],
    validation_by_consumer: Mapping[str, Sequence[Mapping[str, object]]],
    frame_period_ms: int = FRAME_PERIOD_MS,
) -> Tuple[List[Dict[str, object]], List[str]]:
    """Per-consumer rows and audit lines. Shared flood bytes are counted once per handoff."""
    if not packets:
        raise metrics.MobilityMetricError("no packets")
    if not handoffs:
        raise metrics.MobilityMetricError("no handoffs")
    named = [
        metrics.Packet(
            packet.time, packet.node, packet.outbound, packet.ptype,
            metrics.canonical_name(packet.name), packet.length,
            packet.interest_flood, packet.data_flood,
            packet.interest_hop_limit, packet.data_lp_hop_limit, packet.data_mobility_flag,
        )
        for packet in packets
    ]
    capture_end = max(packet.time for packet in named)
    producer_interests = _index(named, "producer", False, "interest", True)
    producer_data = _index(named, "producer", True, "data", True)
    rows: List[Dict[str, object]] = []
    audits: List[str] = []
    for position, handoff in enumerate(handoffs):
        last = position == len(handoffs) - 1
        event_end = capture_end if last else handoffs[position + 1].abs_time
        flood_bytes = 0
        nlsr_bytes = 0
        guard_sends: Dict[str, int] = {consumer: 0 for consumer in active_consumers}
        for packet in named:
            if not _in_window(packet.time, handoff.abs_time, event_end, last):
                continue
            if metrics.is_recovery_interest_flood(packet) or metrics.is_recovery_data_flood(packet):
                flood_bytes += packet.length
            if packet.outbound and metrics.is_nlsr(packet.name) and not metrics.is_management(packet.name):
                nlsr_bytes += packet.length
            if packet.outbound and packet.ptype == "interest" and metrics.is_guard(packet.name):
                if packet.node in guard_sends and metrics.canonical_name(packet.name) == metrics.canonical_name(GUARD_NAME):
                    guard_sends[packet.node] += 1
        audits.append(
            f"handoff {handoff.index} guard_sends="
            + ",".join(f"{consumer}:{guard_sends[consumer]}" for consumer in active_consumers)
            + f" network_recovery_flood_bytes={flood_bytes} nlsr_control_bytes={nlsr_bytes}"
        )
        duration = event_end - handoff.abs_time
        nominal = duration * 1000.0 / frame_period_ms if duration > 0 else 0.0
        for consumer in active_consumers:
            interests = _index(named, consumer, True, "interest", True)
            data = _index(named, consumer, False, "data", True)
            delivered = set()
            for name, times in data.items():
                if any(_in_window(item, handoff.abs_time, event_end, last) for item in times):
                    frame_id = metrics.content_frame_id(name)
                    if frame_id:
                        delivered.add(frame_id)
            loss = "" if nominal <= 0 else (nominal - len(delivered)) / nominal
            observed_name = ""
            observed_time: Optional[float] = None
            for name, times in data.items():
                earliest = _earliest(times, handoff.abs_time, event_end, last)
                if earliest is None:
                    continue
                if observed_time is None or earliest < observed_time:
                    observed_time = earliest
                    observed_name = name
            interest_time = None
            if observed_name and observed_time is not None:
                for item in interests.get(observed_name) or []:
                    if item <= observed_time:
                        interest_time = item
                        break
            producer_data_time = None
            producer_interest_time = None
            if observed_name and observed_time is not None:
                for item in producer_data.get(observed_name) or []:
                    if handoff.abs_time < item <= observed_time:
                        producer_data_time = item
                        break
                for item in producer_interests.get(observed_name) or []:
                    if _in_window(item, handoff.abs_time, event_end, last) and item <= observed_time:
                        producer_interest_time = item
                        break
            observed_ms: object = ""
            if observed_time is None:
                origin = "absent"
                audit = "No post-handoff content Data at this consumer in the event window."
                validation = "absent"
                validation_time = ""
                confirmed = ""
                request_ms = ""
                predates = ""
            else:
                origin, audit = _origin(interest_time, handoff.abs_time, producer_interest_time, producer_data_time)
                validation, validation_time = match_validation(
                    validation_by_consumer.get(consumer) or [], observed_name, observed_time,
                )
                observed_ms = (observed_time - handoff.abs_time) * 1000.0
                confirmed = "" if origin == "origin_uncertain" else f"{observed_ms:.6f}"
                request_ms = ""
                if interest_time is not None:
                    request_ms = f"{(observed_time - interest_time) * 1000.0:.6f}"
                predates = "true" if interest_time is not None and interest_time <= handoff.abs_time else "false"
            rows.append({
                "consumer": consumer,
                "handoff_index": handoff.index,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": f"{handoff.abs_time:.6f}",
                "event_end_time": f"{event_end:.6f}",
                "observed_data_time": "" if observed_time is None else f"{observed_time:.6f}",
                "consumer_observed_recovery_ms": "" if observed_ms == "" else f"{float(str(observed_ms)):.6f}",
                "confirmed_producer_recovery_ms": confirmed,
                "interest_to_data_ms": request_ms,
                "content_name": observed_name,
                "frame_id": metrics.content_frame_id(observed_name) if observed_name else "",
                "interest_time": "" if interest_time is None else f"{interest_time:.6f}",
                "interest_predates_handoff": predates,
                "producer_interest_time": "" if producer_interest_time is None else f"{producer_interest_time:.6f}",
                "producer_data_time": "" if producer_data_time is None else f"{producer_data_time:.6f}",
                "origin": origin,
                "validation": validation,
                "validation_time": validation_time,
                "delivered_unique_frames": len(delivered),
                "nominal_frame_opportunities": f"{nominal:.6f}",
                "content_loss_fraction": "" if loss == "" else f"{float(loss):.6f}",
                "network_recovery_flood_bytes": flood_bytes,
                "nlsr_control_bytes": nlsr_bytes,
                "audit": audit,
            })
    return rows, audits


def inactive_consumer_application_traffic(packets: Sequence[metrics.Packet], inactive: Sequence[str]) -> List[str]:
    """Useful content sent by a host that should be application-silent."""
    notes = []
    for packet in packets:
        if packet.node in inactive and packet.outbound and packet.ptype == "interest" and metrics.is_useful_content(packet.name):
            notes.append(f"{packet.node} sent application content Interest {packet.name}")
    return notes
