"""Exp2-A per-consumer observations. Does not change main-experiment metrics."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import mobility_event_metrics as metrics

from exp2_shared_config import FRAME_PERIOD_MS, GUARD_NAME, STREAM_PREFIX

_TYPED_ALIAS = {"v": metrics.COMPONENT_VERSION, "seg": metrics.COMPONENT_SEGMENT}
_PRODUCER_DATA = re.compile(r"^\[(\d+)\].*\bDATA: Sending response\b.*\bName: (\S+)")
_PRODUCER_INTEREST = re.compile(r"^\[(\d+)\].*\bINTEREST: Received\b.*\bName: (\S+)")

OBSERVATION_FIELDS = (
    "consumer",
    "handoff_index",
    "from_node",
    "to_node",
    "handoff_time",
    "event_end_time",
    "observed_data_time",
    "first_arrival_name",
    "first_arrival_origin",
    "consumer_observed_recovery_ms",
    "validated_producer_service_recovery_ms",
    "recovery_name",
    "producer_send_time",
    "producer_egress_time",
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


def encode_non_negative_integer(value: int) -> bytes:
    """NDN name-component integer: the smallest width in {1, 2, 4, 8} bytes."""
    if value < 0:
        raise ValueError(f"negative NDN integer: {value}")
    if value <= 0xFF:
        width = 1
    elif value <= 0xFFFF:
        width = 2
    elif value <= 0xFFFFFFFF:
        width = 4
    else:
        width = 8
    return value.to_bytes(width, "big")


def semantic_components(raw: str) -> Tuple[Tuple[int, bytes], ...]:
    """Typed name identity. v=N and seg=N match PCAP type-54 and type-50 components."""
    text = (raw or "").strip()
    if ",/" in text:
        text = text.split(",/", 1)[0]
    components: List[Tuple[int, bytes]] = []
    for part in [item for item in text.split("/") if item]:
        if "=" in part:
            key, value = part.split("=", 1)
            if key in _TYPED_ALIAS and value.isdigit():
                components.append((_TYPED_ALIAS[key], encode_non_negative_integer(int(value))))
                continue
            if key.isdigit():
                components.append((int(key), metrics._decode_uri_bytes(value)))
                continue
        components.append((metrics.COMPONENT_GENERIC, metrics._decode_uri_bytes(part)))
    return tuple(components)


def semantic_name(raw: str) -> str:
    """One audit spelling for a typed name from either a log or a PCAP."""
    return metrics.render_components(semantic_components(raw))


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
        if useful and not metrics.is_useful_content(semantic_name(packet.name)):
            continue
        grouped.setdefault(semantic_name(packet.name), []).append(packet.time)
    for times in grouped.values():
        times.sort()
    return grouped


def _earliest(times: Sequence[float], start: float, end: float, last: bool) -> Optional[float]:
    for item in times:
        if _in_window(item, start, end, last):
            return item
    return None


def parse_producer_log(text: str) -> List[Dict[str, object]]:
    """Application send and Interest-reception lines from producer.log."""
    records: List[Dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        data_match = _PRODUCER_DATA.match(stripped)
        if data_match:
            records.append({
                "kind": "data",
                "time_s": log_timestamp_seconds(int(data_match.group(1))),
                "name": semantic_name(data_match.group(2)),
            })
            continue
        interest_match = _PRODUCER_INTEREST.match(stripped)
        if interest_match:
            records.append({
                "kind": "interest",
                "time_s": log_timestamp_seconds(int(interest_match.group(1))),
                "name": semantic_name(interest_match.group(2)),
            })
    return records


def match_validation(
    records: Sequence[Mapping[str, object]],
    name: str,
    data_time: float,
    consumer: str,
) -> Tuple[str, str]:
    """Match by semantic name and consumer id. Time only picks among those matches."""
    canonical = semantic_name(name)
    matched: List[Mapping[str, object]] = []
    for record in records:
        record_name = str(record.get("name") or "")
        if not record_name or semantic_name(record_name) != canonical:
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
    result = "success" if best["ok"] else "failure"
    return result, f"{float(str(best['time_s'])):.9f}"


def _times_for(records: Sequence[Mapping[str, object]], kind: str, name: str) -> List[float]:
    canonical = semantic_name(name)
    values = [
        float(str(record["time_s"]))
        for record in records
        if record.get("kind") == kind and record.get("name") == canonical
    ]
    values.sort()
    return values


def _latest_at_or_before(times: Sequence[float], limit: float) -> Optional[float]:
    found = None
    for item in times:
        if item <= limit:
            found = item
        else:
            break
    return found


def classify_delivery(
    handoff_time: float,
    receive_time: float,
    interest_time: Optional[float],
    application_send_time: Optional[float],
    egress_time: Optional[float],
    validation: str,
) -> Tuple[str, str, bool]:
    """Return origin, audit text, and whether this reception is validated producer-service recovery.

    Application send time is the generation clock. Network egress is used only when the
    producer log has no send for this name. A send at or before the handoff is in-flight
    Data, even if the consumer receives it afterwards.
    """
    if application_send_time is not None:
        generated = application_send_time
        source = "application send"
    elif egress_time is not None:
        generated = egress_time
        source = "network egress"
    else:
        return (
            "origin_uncertain",
            "No producer application send or network egress was observed for this name. "
            "Cached Data and a missing capture cannot be separated.",
            False,
        )
    if generated <= handoff_time:
        return (
            "in_flight_arrival",
            f"The producer {source} for this Data is at or before the handoff "
            f"({generated:.9f} <= {handoff_time:.9f}). Post-handoff reception is not "
            "restored producer service.",
            False,
        )
    if validation == "failure":
        return (
            "validation_failure",
            "The producer transmitted this Data after the handoff, and validation of that name failed.",
            False,
        )
    if validation != "success":
        return (
            "validation_absent",
            "The producer transmitted this Data after the handoff, but this consumer has no "
            "successful validation for that name.",
            False,
        )
    if interest_time is not None and interest_time <= handoff_time:
        return (
            "producer_pending_interest",
            "A pre-handoff Interest was satisfied by producer Data transmitted after the handoff, "
            "and the consumer validated that name.",
            True,
        )
    return (
        "producer_post_handoff_interest",
        "The producer transmitted this Data after the handoff and the consumer validated that name.",
        True,
    )


def observe_run(
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    active_consumers: Sequence[str],
    validation_by_consumer: Mapping[str, Sequence[Mapping[str, object]]],
    producer_log: Sequence[Mapping[str, object]] = (),
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
            semantic_name(packet.name), packet.length,
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
            arrivals: List[Tuple[float, str]] = []
            for name, times in data.items():
                earliest = _earliest(times, handoff.abs_time, event_end, last)
                if earliest is not None:
                    arrivals.append((earliest, name))
            arrivals.sort()
            observed_time = arrivals[0][0] if arrivals else None
            observed_name = arrivals[0][1] if arrivals else ""
            recovery: Optional[Tuple[float, str, str, str, Optional[float], Optional[float], Optional[float], str]] = None
            first_origin = "absent"
            first_audit = "No post-handoff content Data at this consumer in the event window."
            first_validation = "absent"
            first_validation_time = ""
            first_interest: Optional[float] = None
            first_send: Optional[float] = None
            first_egress: Optional[float] = None
            first_producer_interest: Optional[float] = None
            for receive_time, name in arrivals:
                interest_time = None
                for item in interests.get(name) or []:
                    if item <= receive_time:
                        interest_time = item
                        break
                send_time = _latest_at_or_before(_times_for(producer_log, "data", name), receive_time)
                egress_time = _latest_at_or_before(producer_data.get(name) or [], receive_time)
                producer_interest_time = _latest_at_or_before(producer_interests.get(name) or [], receive_time)
                validation, validation_time = match_validation(
                    validation_by_consumer.get(consumer) or [], name, receive_time, consumer,
                )
                origin, audit, qualifies = classify_delivery(
                    handoff.abs_time, receive_time, interest_time, send_time, egress_time, validation,
                )
                if receive_time == observed_time:
                    first_origin = origin
                    first_audit = audit
                    first_validation = validation
                    first_validation_time = validation_time
                    first_interest = interest_time
                    first_send = send_time
                    first_egress = egress_time
                    first_producer_interest = producer_interest_time
                if qualifies and recovery is None:
                    recovery = (
                        receive_time, name, origin, audit, interest_time, send_time, egress_time, validation_time,
                    )
            if recovery is None:
                content_name = observed_name
                origin = first_origin
                audit = first_audit
                validation = first_validation
                validation_time = first_validation_time
                interest_time = first_interest
                producer_send = first_send
                producer_egress = first_egress
                producer_interest_time = first_producer_interest
                receive_time = observed_time
                primary = ""
            else:
                receive_time, content_name, origin, audit, interest_time, producer_send, producer_egress, validation_time = recovery
                validation = "success"
                producer_interest_time = _latest_at_or_before(producer_interests.get(content_name) or [], receive_time)
                primary = f"{(receive_time - handoff.abs_time) * 1000.0:.6f}"
            observed_ms = "" if observed_time is None else f"{(observed_time - handoff.abs_time) * 1000.0:.6f}"
            request_anchor = receive_time
            request_ms = ""
            if interest_time is not None and request_anchor is not None:
                request_ms = f"{(request_anchor - interest_time) * 1000.0:.6f}"
            predates = "true" if interest_time is not None and interest_time <= handoff.abs_time else "false"
            rows.append({
                "consumer": consumer,
                "handoff_index": handoff.index,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": f"{handoff.abs_time:.6f}",
                "event_end_time": f"{event_end:.6f}",
                "observed_data_time": "" if observed_time is None else f"{observed_time:.6f}",
                "first_arrival_name": observed_name,
                "first_arrival_origin": first_origin,
                "consumer_observed_recovery_ms": observed_ms,
                "validated_producer_service_recovery_ms": primary,
                "recovery_name": content_name if primary else "",
                "producer_send_time": "" if producer_send is None else f"{producer_send:.9f}",
                "producer_egress_time": "" if producer_egress is None else f"{producer_egress:.9f}",
                "interest_to_data_ms": request_ms,
                "content_name": content_name,
                "frame_id": metrics.content_frame_id(content_name) if content_name else "",
                "interest_time": "" if interest_time is None else f"{interest_time:.6f}",
                "interest_predates_handoff": predates if content_name else "",
                "producer_interest_time": "" if producer_interest_time is None else f"{producer_interest_time:.6f}",
                "producer_data_time": "" if producer_egress is None else f"{producer_egress:.9f}",
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
