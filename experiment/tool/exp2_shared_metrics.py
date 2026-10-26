"""Exp2-A per-consumer observations. Does not change main-experiment metrics."""

from __future__ import annotations

import bisect
import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import mobility_event_metrics as metrics

from exp2_shared_config import FRAME_PERIOD_MS, GUARD_NAME, STREAM_PREFIX, topology_position

_TYPED_ALIAS = {"v": metrics.COMPONENT_VERSION, "seg": metrics.COMPONENT_SEGMENT}
_PRODUCER_DATA = re.compile(r"^\[(\d+)\].*\bDATA: Sending response\b.*\bName: (\S+)")
_PRODUCER_INTEREST = re.compile(r"^\[(\d+)\].*\bINTEREST: Received\b.*\bName: (\S+)")

OBSERVATION_FIELDS = (
    "consumer",
    "handoff_index",
    "from_node",
    "to_node",
    "topology_position",
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


def _cached_semantic(raw: str, cache: Dict[str, str]) -> str:
    """Return one semantic audit spelling. The cache lives only for the current index."""
    found = cache.get(raw)
    if found is None:
        found = semantic_name(raw)
        cache[raw] = found
    return found


def parse_validation_log(text: str) -> List[Dict[str, object]]:
    """Validation lines that name a Data packet. Lines without a name stay unmatched.

    Stored names are semantic audit spellings, so later matching does not parse the log again.
    """
    records: List[Dict[str, object]] = []
    cache: Dict[str, str] = {}
    for line in text.splitlines():
        ok_match = _VALIDATE_OK.match(line.strip())
        if ok_match:
            raw_name = ok_match.group(2) or ""
            records.append({
                "ok": True,
                "time_s": log_timestamp_seconds(int(ok_match.group(1))),
                "name": _cached_semantic(raw_name, cache) if raw_name else "",
                "consumer_id": ok_match.group(3) or "",
            })
            continue
        bad_match = _VALIDATE_BAD.match(line.strip())
        if bad_match:
            raw_name = bad_match.group(3) or ""
            records.append({
                "ok": False,
                "time_s": log_timestamp_seconds(int(bad_match.group(1))),
                "name": _cached_semantic(raw_name, cache) if raw_name else "",
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


def _window_events(
    events: Sequence[Tuple[float, str]], start: float, end: float, last: bool,
) -> Sequence[Tuple[float, str]]:
    """Events with start < time and time < end, or time <= end when this is the final event."""
    if not events:
        return ()
    lo = bisect.bisect_right(events, (start, "\U0010ffff"))
    if last:
        hi = bisect.bisect_right(events, (end, "\U0010ffff"))
    else:
        hi = bisect.bisect_left(events, (end, ""))
    return events[lo:hi]


def _latest_at_or_before(times: Sequence[float], limit: float) -> Optional[float]:
    """Last sorted timestamp at or before limit."""
    if not times:
        return None
    pos = bisect.bisect_right(times, limit) - 1
    if pos < 0:
        return None
    return times[pos]


def _earliest_at_or_before(times: Sequence[float], limit: float) -> Optional[float]:
    """First sorted timestamp at or before limit.

    The previous per-reception scan walked the sorted Interest list and stopped at the
    first timestamp that was at or before reception. That timestamp is the earliest one.
    """
    if not times or times[0] > limit:
        return None
    return times[0]


def _closest_validation(entries: Sequence[Tuple[float, int]], data_time: float) -> Optional[float]:
    """Closest validation time. Equal distances keep the earlier record."""
    if not entries:
        return None
    times = [item[0] for item in entries]
    index = bisect.bisect_left(times, data_time)
    best_time = 0.0
    best_dist = 0.0
    best_seq = 0
    found = False

    def consider(pos: int) -> None:
        nonlocal best_time, best_dist, best_seq, found
        if pos < 0 or pos >= len(entries):
            return
        stamp = entries[pos][0]
        left = pos
        while left > 0 and entries[left - 1][0] == stamp:
            left -= 1
        right = pos
        while right + 1 < len(entries) and entries[right + 1][0] == stamp:
            right += 1
        for cursor in range(left, right + 1):
            candidate_time, candidate_seq = entries[cursor]
            dist = abs(candidate_time - data_time)
            if not found or dist < best_dist or (dist == best_dist and candidate_seq < best_seq):
                best_time = candidate_time
                best_dist = dist
                best_seq = candidate_seq
                found = True

    consider(index - 1)
    consider(index)
    if not found:
        return None
    return best_time


def _index_validation(
    records: Sequence[Mapping[str, object]],
    consumer: str,
    cache: Dict[str, str],
) -> Dict[str, Tuple[List[Tuple[float, int]], List[Tuple[float, int]]]]:
    """Success and failure times for one consumer, keyed by semantic Data name."""
    grouped: Dict[str, Tuple[List[Tuple[float, int]], List[Tuple[float, int]]]] = {}
    for seq, record in enumerate(records):
        raw_name = str(record.get("name") or "")
        if not raw_name:
            continue
        record_consumer = str(record.get("consumer_id") or "")
        if record_consumer and record_consumer != consumer:
            continue
        canonical = _cached_semantic(raw_name, cache)
        slot = grouped.get(canonical)
        if slot is None:
            slot = ([], [])
            grouped[canonical] = slot
        item = (float(str(record["time_s"])), seq)
        if record.get("ok"):
            slot[0].append(item)
        else:
            slot[1].append(item)
    for successes, failures in grouped.values():
        successes.sort(key=lambda item: (item[0], item[1]))
        failures.sort(key=lambda item: (item[0], item[1]))
    return grouped


def _match_indexed(
    pools: Mapping[str, Tuple[Sequence[Tuple[float, int]], Sequence[Tuple[float, int]]]],
    canonical: str,
    data_time: float,
) -> Tuple[str, str]:
    """Prefer the closest success for this name. Failures are used only when no success exists."""
    slot = pools.get(canonical)
    if slot is None:
        return "absent", ""
    chosen = _closest_validation(slot[0], data_time)
    outcome = "success"
    if chosen is None:
        chosen = _closest_validation(slot[1], data_time)
        outcome = "failure"
    if chosen is None:
        return "absent", ""
    return outcome, f"{chosen:.9f}"


def parse_producer_log(text: str) -> List[Dict[str, object]]:
    """Application send and Interest-reception lines from producer.log.

    Stored names are semantic audit spellings.
    """
    records: List[Dict[str, object]] = []
    cache: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        data_match = _PRODUCER_DATA.match(stripped)
        if data_match:
            records.append({
                "kind": "data",
                "time_s": log_timestamp_seconds(int(data_match.group(1))),
                "name": _cached_semantic(data_match.group(2), cache),
            })
            continue
        interest_match = _PRODUCER_INTEREST.match(stripped)
        if interest_match:
            records.append({
                "kind": "interest",
                "time_s": log_timestamp_seconds(int(interest_match.group(1))),
                "name": _cached_semantic(interest_match.group(2), cache),
            })
    return records


def match_validation(
    records: Sequence[Mapping[str, object]],
    name: str,
    data_time: float,
    consumer: str,
) -> Tuple[str, str]:
    """Match by semantic name and consumer id. Time only picks among those matches.

    A successful record for this consumer and name is preferred to every failure.
    Among the chosen outcome, the closest timestamp is used. There is no separate
    acceptance window: closeness does not reject the only remaining record.
    """
    cache: Dict[str, str] = {}
    canonical = _cached_semantic(name, cache)
    pools = _index_validation(records, consumer, cache)
    return _match_indexed(pools, canonical, data_time)


def _index_producer_log(
    records: Sequence[Mapping[str, object]],
    cache: Dict[str, str],
) -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
    """Application send and Interest times keyed by semantic Data name."""
    sends: Dict[str, List[float]] = {}
    interests: Dict[str, List[float]] = {}
    for record in records:
        raw_name = str(record.get("name") or "")
        if not raw_name:
            continue
        canonical = _cached_semantic(raw_name, cache)
        kind = record.get("kind")
        target = sends if kind == "data" else interests if kind == "interest" else None
        if target is None:
            continue
        target.setdefault(canonical, []).append(float(str(record["time_s"])))
    for times in sends.values():
        times.sort()
    for times in interests.values():
        times.sort()
    return sends, interests


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


def _sort_time_index(grouped: Dict[str, List[float]]) -> None:
    for times in grouped.values():
        times.sort()


def observe_run(
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    active_consumers: Sequence[str],
    validation_by_consumer: Mapping[str, Sequence[Mapping[str, object]]],
    producer_log: Sequence[Mapping[str, object]] = (),
    frame_period_ms: int = FRAME_PERIOD_MS,
) -> Tuple[List[Dict[str, object]], List[str]]:
    """Per-consumer rows and audit lines. Shared flood bytes are counted once per handoff.

    Names, logs, and packet roles are indexed once. Each handoff then reads the sorted
    slices for its event window. A consumer row stops provenance matching after the
    first qualifying recovery and the first-arrival timestamp have both been resolved.
    """
    if not packets:
        raise metrics.MobilityMetricError("no packets")
    if not handoffs:
        raise metrics.MobilityMetricError("no handoffs")
    active = tuple(active_consumers)
    cache: Dict[str, str] = {}
    useful: Dict[str, bool] = {}
    frame_ids: Dict[str, str] = {}
    app_sends, app_interests = _index_producer_log(producer_log, cache)
    validation_index = {
        consumer: _index_validation(validation_by_consumer.get(consumer) or [], consumer, cache)
        for consumer in active
    }
    producer_interests: Dict[str, List[float]] = {}
    producer_egress_times: Dict[str, List[float]] = {}
    consumer_interests: Dict[str, Dict[str, List[float]]] = {consumer: {} for consumer in active}
    consumer_data: Dict[str, List[Tuple[float, str]]] = {consumer: [] for consumer in active}
    named: List[metrics.Packet] = []
    capture_end = packets[0].time
    for packet in packets:
        name = _cached_semantic(packet.name, cache)
        if packet.time > capture_end:
            capture_end = packet.time
        named.append(metrics.Packet(
            packet.time, packet.node, packet.outbound, packet.ptype,
            name, packet.length,
            packet.interest_flood, packet.data_flood,
            packet.interest_hop_limit, packet.data_lp_hop_limit, packet.data_mobility_flag,
        ))
        is_content = useful.get(name)
        if is_content is None:
            is_content = metrics.is_useful_content(name)
            useful[name] = is_content
        if not is_content:
            continue
        if packet.node == "producer" and packet.ptype == "interest" and not packet.outbound:
            producer_interests.setdefault(name, []).append(packet.time)
        elif packet.node == "producer" and packet.ptype == "data" and packet.outbound:
            producer_egress_times.setdefault(name, []).append(packet.time)
        elif packet.node in consumer_data and packet.ptype == "interest" and packet.outbound:
            consumer_interests[packet.node].setdefault(name, []).append(packet.time)
        elif packet.node in consumer_data and packet.ptype == "data" and not packet.outbound:
            consumer_data[packet.node].append((packet.time, name))
    _sort_time_index(producer_interests)
    _sort_time_index(producer_egress_times)
    for interests in consumer_interests.values():
        _sort_time_index(interests)
    for events in consumer_data.values():
        events.sort()

    event_last = []
    event_end_at = []
    for position, handoff in enumerate(handoffs):
        last = position == len(handoffs) - 1
        event_last.append(last)
        event_end_at.append(capture_end if last else handoffs[position + 1].abs_time)
    flood_totals = [0] * len(handoffs)
    nlsr_totals = [0] * len(handoffs)
    guard_sends = [{consumer: 0 for consumer in active} for _handoff in handoffs]
    guard_name = metrics.canonical_name(GUARD_NAME)
    canonical_names: Dict[str, str] = {}
    nlsr_names: Dict[str, bool] = {}
    management_names: Dict[str, bool] = {}
    guard_names: Dict[str, bool] = {}
    application_names: Dict[str, bool] = {}
    for packet in named:
        position = None
        for index, handoff in enumerate(handoffs):
            if _in_window(packet.time, handoff.abs_time, event_end_at[index], event_last[index]):
                position = index
                break
        if position is None:
            continue
        flood_marked = packet.outbound and (
            (packet.ptype == "interest" and packet.interest_hop_limit)
            or (packet.ptype == "data" and (packet.data_mobility_flag or packet.data_lp_hop_limit))
        )
        if flood_marked:
            is_application = application_names.get(packet.name)
            if is_application is None:
                is_application = metrics.is_application(packet.name)
                application_names[packet.name] = is_application
            if is_application:
                flood_totals[position] += packet.length
        is_nlsr = nlsr_names.get(packet.name)
        if is_nlsr is None:
            is_nlsr = metrics.is_nlsr(packet.name)
            nlsr_names[packet.name] = is_nlsr
        if packet.outbound and is_nlsr:
            is_management = management_names.get(packet.name)
            if is_management is None:
                is_management = metrics.is_management(packet.name)
                management_names[packet.name] = is_management
            if not is_management:
                nlsr_totals[position] += packet.length
        if packet.outbound and packet.ptype == "interest" and packet.node in guard_sends[position]:
            is_guard = guard_names.get(packet.name)
            if is_guard is None:
                is_guard = metrics.is_guard(packet.name)
                guard_names[packet.name] = is_guard
            if is_guard:
                spelled = canonical_names.get(packet.name)
                if spelled is None:
                    spelled = metrics.canonical_name(packet.name)
                    canonical_names[packet.name] = spelled
                if spelled == guard_name:
                    guard_sends[position][packet.node] += 1

    rows: List[Dict[str, object]] = []
    audits: List[str] = []
    for position, handoff in enumerate(handoffs):
        last = event_last[position]
        event_end = event_end_at[position]
        flood_bytes = flood_totals[position]
        nlsr_bytes = nlsr_totals[position]
        audits.append(
            f"handoff {handoff.index} guard_sends="
            + ",".join(f"{consumer}:{guard_sends[position][consumer]}" for consumer in active)
            + f" network_recovery_flood_bytes={flood_bytes} nlsr_control_bytes={nlsr_bytes}"
        )
        duration = event_end - handoff.abs_time
        nominal = duration * 1000.0 / frame_period_ms if duration > 0 else 0.0
        for consumer in active:
            window = _window_events(consumer_data[consumer], handoff.abs_time, event_end, last)
            earliest: Dict[str, float] = {}
            for stamp, name in window:
                if name not in earliest:
                    earliest[name] = stamp
            delivered = set()
            for name in earliest:
                frame_id = frame_ids.get(name)
                if frame_id is None:
                    frame_id = metrics.content_frame_id(name)
                    frame_ids[name] = frame_id
                if frame_id:
                    delivered.add(frame_id)
            loss = "" if nominal <= 0 else (nominal - len(delivered)) / nominal
            arrivals = sorted((stamp, name) for name, stamp in earliest.items())
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
            interests = consumer_interests[consumer]
            pools = validation_index[consumer]
            for receive_time, name in arrivals:
                if recovery is not None and observed_time is not None and receive_time != observed_time:
                    break
                interest_time = _earliest_at_or_before(interests.get(name) or [], receive_time)
                send_time = _latest_at_or_before(app_sends.get(name) or [], receive_time)
                egress_time = _latest_at_or_before(producer_egress_times.get(name) or [], receive_time)
                producer_interest_time = _latest_at_or_before(producer_interests.get(name) or [], receive_time)
                validation, validation_time = _match_indexed(pools, name, receive_time)
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
                "topology_position": topology_position(consumer, handoff.from_node, handoff.to_node),
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
