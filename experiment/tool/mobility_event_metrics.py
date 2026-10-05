#!/usr/bin/env python3
"""Per-handoff mobility-event metrics from existing packet captures.

The event interval is [handoff_i, handoff_(i+1)) and, for the last handoff,
[handoff_K, capture_end]. Capture end is the latest packet timestamp.

Service recovery time ends when the producer receives the first fresh
post-handoff content Interest. Recovery Flooding Volume is the byte sum of
flood-marked sender-egress transmissions in that interval. Forwarding cost
ratio remains only so the current manuscript can still build its old figures.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

RELAY_NODES = (
    "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
APP_PREFIX = "/LiveStream"
STREAM_PREFIX = "/LiveStream/v0"
# Linux cooked-capture PACKET_OUTGOING. Sender egress, not receiver ingress.
PACKET_OUTGOING = 4
COMPONENT_GENERIC = 8
COMPONENT_SEGMENT = 50
COMPONENT_VERSION = 54
STREAM_COMPONENTS = ((COMPONENT_GENERIC, b"LiveStream"), (COMPONENT_GENERIC, b"v0"))
NameKey = Tuple[Tuple[int, bytes], ...]

EVENT_FIELDS = [
    "configuration",
    "profile",
    "run_id",
    "handoff_index",
    "from_node",
    "to_node",
    "handoff_time",
    "event_end_time",
    "event_duration_s",
    "recovered",
    "service_recovery_time_ms",
    "recovery_name",
    "consumer_interest_time",
    "producer_interest_time",
    "first_post_handoff_producer_data_arrival_ms",
    "logical_request_count",
    "satisfied_request_count",
    "unmet_request_count",
    "unmet_interest_ratio",
    "unmet_request_rate",
    "relay_application_forwarded_bytes",
    "useful_content_delivered_bytes",
    "forwarding_cost_ratio",
    "application_forwarding_rate_bytes_per_s",
    "nlsr_control_bytes",
    "nlsr_control_rate_bytes_per_s",
    "recovery_interest_flood_bytes",
    "recovery_data_flood_bytes",
    "recovery_flood_bytes",
    # Exp1 sensitivity still plots these rates. They are not Recovery Flooding Volume.
    "explicit_flood_bytes",
    "interest_flood_bytes",
    "data_flood_bytes",
    "explicit_flood_rate_bytes_per_s",
    "interest_flood_rate_bytes_per_s",
    "data_flood_rate_bytes_per_s",
    "frame_period_ms",
    "nominal_frame_opportunities",
    "delivered_unique_content_frames",
    "content_delivery_ratio",
    "content_loss_fraction",
    "delivered_frame_rate_fps",
    "nominal_frame_rate_fps",
    "relay_content_bytes",
    "relay_guard_bytes",
    "relay_meta_bytes",
    "relay_other_application_bytes",
]


class MobilityMetricError(Exception):
    """Raised when a required run or event cannot be measured."""


@dataclass
class Handoff:
    index: int
    abs_time: float
    from_node: str
    to_node: str


@dataclass
class Packet:
    time: float
    node: str
    outbound: bool
    ptype: str
    name: str
    length: int
    interest_flood: bool
    data_flood: bool
    interest_hop_limit: bool = False
    data_lp_hop_limit: bool = False
    data_mobility_flag: bool = False


@dataclass
class EventRow:
    values: Dict[str, object] = field(default_factory=dict)

    def get(self, key: str) -> object:
        return self.values.get(key)


def _decode_uri_bytes(text: str) -> bytes:
    """Decode a mixed URI body. %XX is one byte; every other character is itself."""
    output = bytearray()
    index = 0
    while index < len(text):
        if text[index] == "%" and index + 2 < len(text):
            try:
                output.append(int(text[index + 1:index + 3], 16))
            except ValueError:
                output.append(ord(text[index]))
                index += 1
                continue
            index += 3
            continue
        output.append(ord(text[index]))
        index += 1
    return bytes(output)


def _percent(value: bytes) -> str:
    return "".join(f"%{byte:02X}" for byte in value)


def parse_name(raw: str) -> NameKey:
    """Parse a rendered NDN name into (component type, raw value) pairs.

    Equality uses this key. tshark and the Python renderer may spell the same
    component differently; both spellings parse to the same bytes.
    A second name after ',/' is a KeyLocator and is not part of the packet name.
    """
    text = (raw or "").strip()
    if ",/" in text:
        text = text.split(",/", 1)[0]
    components: List[Tuple[int, bytes]] = []
    for part in [item for item in text.split("/") if item]:
        typed = part.split("=", 1)
        if len(typed) == 2 and typed[0].isdigit():
            components.append((int(typed[0]), _decode_uri_bytes(typed[1])))
        else:
            components.append((COMPONENT_GENERIC, _decode_uri_bytes(part)))
    return tuple(components)


def render_components(components: Sequence[Tuple[int, bytes]]) -> str:
    """Stable audit URI. It is not the equality key."""
    parts: List[str] = []
    for component_type, value in components:
        if component_type == COMPONENT_GENERIC and value and all(32 < byte < 127 for byte in value):
            parts.append(value.decode("ascii"))
        elif component_type == COMPONENT_GENERIC:
            parts.append(_percent(value))
        else:
            parts.append(f"{component_type}={_percent(value)}")
    return "/" + "/".join(parts)


def canonical_name(raw: str) -> str:
    """Return the stable audit URI of the semantic name."""
    return render_components(parse_name(raw))


def names_equal(left: str, right: str) -> bool:
    return parse_name(left) == parse_name(right)


def is_sender_egress(pkttype: str) -> bool:
    """True only for a Linux cooked-capture sender-egress observation."""
    return (pkttype or "").strip() == str(PACKET_OUTGOING)


def _generic_values(name: str) -> List[bytes]:
    return [value for component_type, value in parse_name(name) if component_type == COMPONENT_GENERIC]


def is_nlsr(name: str) -> bool:
    return b"nlsr" in _generic_values(name)


def is_management(name: str) -> bool:
    """Local management names. NLSR uses /localhop/ndn/nlsr and is not management."""
    if is_nlsr(name):
        return False
    values = _generic_values(name)
    return bool(values) and values[0] in (b"localhost", b"localhop")


def _marker(name: str, marker: bytes) -> bool:
    return any(value == marker or value.startswith(marker) for value in _generic_values(name))


def is_guard(name: str) -> bool:
    return _marker(name, b"_guard")


def is_meta(name: str) -> bool:
    return _marker(name, b"_meta")


def is_guard_or_meta(name: str) -> bool:
    return is_guard(name) or is_meta(name)


def content_frame_id(name: str) -> str:
    """Raw version-component value of one normal live-stream frame. Empty otherwise."""
    if not is_useful_content(name):
        return ""
    for component_type, value in parse_name(name):
        if component_type == COMPONENT_VERSION:
            return value.hex()
    return ""


def load_run_config(path: str) -> Tuple[int, int]:
    """Return (segments_per_frame, request_interval_ms) from params.txt."""
    segments = None
    interval = None
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("segments_per_frame="):
                segments = int(line.split("=", 1)[1])
            elif line.startswith("request_interval_ms="):
                interval = int(line.split("=", 1)[1])
    if segments is None or interval is None:
        raise MobilityMetricError(f"params.txt missing segment or request interval: {path}")
    if segments != 1:
        raise MobilityMetricError(
            f"{path}: EXP_SEGMENTS_PER_FRAME={segments}; refusing the single-segment content-loss definition"
        )
    if interval <= 0:
        raise MobilityMetricError(f"{path}: request_interval_ms must be positive")
    return segments, interval


def is_application(name: str) -> bool:
    """Application prefix traffic, including guard and discovery, excluding NLSR and management."""
    components = parse_name(name)
    if components[:len(STREAM_COMPONENTS) - 1] != STREAM_COMPONENTS[:1]:
        return False
    return not is_nlsr(name) and not is_management(name)


def is_useful_content(name: str) -> bool:
    """Versioned, segmented live-stream content. Guard and discovery names are excluded."""
    components = parse_name(name)
    if components[:len(STREAM_COMPONENTS)] != STREAM_COMPONENTS:
        return False
    types = [component_type for component_type, _value in components]
    if COMPONENT_VERSION not in types or COMPONENT_SEGMENT not in types:
        return False
    if is_guard_or_meta(name) or is_nlsr(name) or is_management(name):
        return False
    return True


def load_handoffs(path: str) -> List[Handoff]:
    handoffs: List[Handoff] = []
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.lower().startswith("index"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            handoffs.append(Handoff(int(parts[0]), float(parts[1]), parts[3], parts[4]))
    if not handoffs:
        raise MobilityMetricError(f"no handoffs in {path}")
    return handoffs


def _flag(text: str) -> bool:
    return bool((text or "").strip())


def load_packets(path: str) -> List[Packet]:
    """Load one row per PCAP frame, node, and direction.

    Distinct frames on different nodes are different transmissions. A repeated
    decoder row for the same frame is not a second transmission. Ingress copies
    are not sender egress; only PACKET_OUTGOING is egress.
    """
    packets: List[Packet] = []
    seen = set()
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = canonical_name(row.get("ndn.name") or "")
            if not name or name == "/":
                continue
            frame_number = (row.get("frame.number") or "").strip()
            node = (row.get("node") or "").strip()
            pkttype = (row.get("sll.pkttype") or "").strip()
            identity = (node, frame_number, pkttype)
            if frame_number and identity in seen:
                continue
            if frame_number:
                seen.add(identity)
            try:
                timestamp = float(row["frame.time_epoch"])
                length = int(float(row["frame.len"]))
            except (KeyError, TypeError, ValueError):
                continue
            ptype = (row.get("ndn.type") or "").strip().lower()
            hop_limit = _flag(row.get("ndn.hoplimit") or "")
            lp_hop_limit = _flag(row.get("ndn.lp.hoplimit") or "")
            mobility_flag = _flag(row.get("ndn.lp.mobility_flag") or "")
            flood_id = _flag(row.get("ndn.flood_id") or "")
            # Exp1 explicit-flood rates keep the previous marker union, including FloodId.
            interest_flood = ptype == "interest" and hop_limit
            data_flood = ptype == "data" and (lp_hop_limit or mobility_flag or flood_id)
            packets.append(Packet(
                time=timestamp,
                node=(row.get("node") or "").strip(),
                outbound=is_sender_egress(pkttype),
                ptype=ptype,
                name=name,
                length=length,
                interest_flood=interest_flood,
                data_flood=data_flood,
                interest_hop_limit=hop_limit,
                data_lp_hop_limit=lp_hop_limit,
                data_mobility_flag=mobility_flag,
            ))
    if not packets:
        raise MobilityMetricError(f"no packets in {path}")
    return packets


def _earliest_at_or_after(times: Sequence[float], limit: float) -> Optional[float]:
    position = bisect.bisect_left(times, limit)
    if position >= len(times):
        return None
    return times[position]


def _before_end(timestamp: float, event_end: float, inclusive_end: bool) -> bool:
    return timestamp <= event_end if inclusive_end else timestamp < event_end


def _earliest_after(times: Sequence[float], limit: float) -> Optional[float]:
    position = bisect.bisect_right(times, limit)
    if position >= len(times):
        return None
    return times[position]


def match_service_recovery_interest(
    handoff_time: float,
    event_end: float,
    consumer_interests: Dict[str, List[float]],
    producer_interests: Dict[str, List[float]],
    inclusive_end: bool = False,
) -> Optional[Tuple[str, float, float]]:
    """Earliest producer receipt of a fresh post-handoff content Interest.

    handoff < consumer Interest <= producer Interest, same canonical name.
    Data generation and Data return are not part of this endpoint.
    A non-final event ends strictly before the next handoff. The final event includes capture end.
    """
    best: Optional[Tuple[float, str, float]] = None
    for name, interest_times in consumer_interests.items():
        producer_in = producer_interests.get(name) or []
        if not producer_in:
            continue
        for consumer_interest_time in interest_times:
            if consumer_interest_time <= handoff_time or not _before_end(consumer_interest_time, event_end, inclusive_end):
                continue
            producer_interest_time = _earliest_at_or_after(producer_in, consumer_interest_time)
            if producer_interest_time is None or not _before_end(producer_interest_time, event_end, inclusive_end):
                continue
            if best is None or producer_interest_time < best[0]:
                best = (producer_interest_time, name, consumer_interest_time)
    if best is None:
        return None
    producer_interest_time, name, consumer_interest_time = best
    return name, consumer_interest_time, producer_interest_time


def is_recovery_interest_flood(packet: Packet) -> bool:
    """Sender-egress application Interest carrying the OptoFlood HopLimit marker."""
    return (
        packet.outbound
        and packet.ptype == "interest"
        and packet.interest_hop_limit
        and is_application(packet.name)
    )


def is_recovery_data_flood(packet: Packet) -> bool:
    """Sender-egress application Data carrying a hop-by-hop flood marker.

    LP MobilityFlag is set on the flood send and removed before PIT unicast
    satisfaction. LP OptoHopLimit is the same class of tag. MetaInfo FloodId
    is not used here: it can remain on a later non-flooded copy.
    """
    return (
        packet.outbound
        and packet.ptype == "data"
        and (packet.data_mobility_flag or packet.data_lp_hop_limit)
        and is_application(packet.name)
    )


def _index_times(packets: Iterable[Packet], node: str, outbound: bool, ptype: str, useful_only: bool) -> Dict[str, List[float]]:
    grouped: Dict[str, List[float]] = {}
    for packet in packets:
        if packet.node != node or packet.outbound != outbound or packet.ptype != ptype:
            continue
        if useful_only and not is_useful_content(packet.name):
            continue
        grouped.setdefault(packet.name, []).append(packet.time)
    for times in grouped.values():
        times.sort()
    return grouped


def _in_interval(packet: Packet, start: float, end: float, last: bool) -> bool:
    if packet.time < start:
        return False
    if last:
        return packet.time <= end
    return packet.time < end


def _blank_cost_fields(frame_period_ms: int) -> Dict[str, object]:
    return {
        "frame_period_ms": frame_period_ms,
        "nominal_frame_opportunities": "",
        "delivered_unique_content_frames": 0,
        "content_delivery_ratio": "",
        "content_loss_fraction": "",
        "delivered_frame_rate_fps": "",
        "nominal_frame_rate_fps": 1000.0 / frame_period_ms,
        "relay_content_bytes": 0,
        "relay_guard_bytes": 0,
        "relay_meta_bytes": 0,
        "relay_other_application_bytes": 0,
    }


def measure_run(
    packets: Sequence[Packet],
    handoffs: Sequence[Handoff],
    configuration: str,
    profile: str,
    run_id: str,
    frame_period_ms: int = 20,
) -> List[Dict[str, object]]:
    if frame_period_ms <= 0:
        raise MobilityMetricError(f"frame_period_ms must be positive, got {frame_period_ms}")
    packets = [
        Packet(
            packet.time, packet.node, packet.outbound, packet.ptype,
            canonical_name(packet.name), packet.length, packet.interest_flood, packet.data_flood,
            packet.interest_hop_limit, packet.data_lp_hop_limit, packet.data_mobility_flag,
        )
        for packet in packets
    ]
    capture_end = max(packet.time for packet in packets)
    consumer_interests = _index_times(packets, "consumer", True, "interest", True)
    producer_interests = _index_times(packets, "producer", False, "interest", True)
    producer_data = _index_times(packets, "producer", True, "data", True)
    consumer_data = _index_times(packets, "consumer", False, "data", True)
    rows: List[Dict[str, object]] = []
    for position, handoff in enumerate(handoffs):
        last = position == len(handoffs) - 1
        event_end = capture_end if last else handoffs[position + 1].abs_time
        duration = event_end - handoff.abs_time
        if duration <= 0:
            rows.append({
                "configuration": configuration,
                "profile": profile,
                "run_id": run_id,
                "handoff_index": handoff.index,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": handoff.abs_time,
                "event_end_time": event_end,
                "event_duration_s": duration,
                "recovered": False,
                "service_recovery_time_ms": "",
                "recovery_name": "",
                "consumer_interest_time": "",
                "producer_interest_time": "",
                "first_post_handoff_producer_data_arrival_ms": "",
                "logical_request_count": 0,
                "satisfied_request_count": 0,
                "unmet_request_count": 0,
                "unmet_interest_ratio": "",
                "unmet_request_rate": "",
                "relay_application_forwarded_bytes": 0,
                "useful_content_delivered_bytes": 0,
                "forwarding_cost_ratio": "",
                "application_forwarding_rate_bytes_per_s": "",
                "nlsr_control_bytes": 0,
                "nlsr_control_rate_bytes_per_s": "",
                "recovery_interest_flood_bytes": 0,
                "recovery_data_flood_bytes": 0,
                "recovery_flood_bytes": 0,
                "explicit_flood_bytes": 0,
                "interest_flood_bytes": 0,
                "data_flood_bytes": 0,
                "explicit_flood_rate_bytes_per_s": "",
                "interest_flood_rate_bytes_per_s": "",
                "data_flood_rate_bytes_per_s": "",
                **_blank_cost_fields(frame_period_ms),
            })
            continue
        recovery = match_service_recovery_interest(
            handoff.abs_time,
            event_end,
            consumer_interests,
            producer_interests,
            inclusive_end=last,
        )
        first_arrival = None
        for name, times in consumer_data.items():
            produced = producer_data.get(name) or []
            for arrival in times:
                if arrival <= handoff.abs_time or arrival > event_end:
                    continue
                if not any(handoff.abs_time < produced_time <= arrival for produced_time in produced):
                    continue
                if first_arrival is None or arrival < first_arrival:
                    first_arrival = arrival

        def _during(item: float) -> bool:
            if item <= handoff.abs_time:
                return False
            return item <= event_end if last else item < event_end

        request_names = {
            name for name, times in consumer_interests.items()
            if any(_during(item) for item in times)
        }
        satisfied = 0
        for name in request_names:
            deliveries = consumer_data.get(name) or []
            if any(_during(item) for item in deliveries):
                satisfied += 1
        logical = len(request_names)
        unmet = logical - satisfied

        relay_bytes = 0
        relay_content = 0
        relay_guard = 0
        relay_meta = 0
        relay_other = 0
        useful_bytes = 0
        nlsr_bytes = 0
        interest_flood = 0
        data_flood = 0
        recovery_interest = 0
        recovery_data = 0
        delivered_frames = set()
        for packet in packets:
            if not _in_interval(packet, handoff.abs_time, event_end, last):
                continue
            if is_recovery_interest_flood(packet):
                recovery_interest += packet.length
            elif is_recovery_data_flood(packet):
                recovery_data += packet.length
            if packet.outbound and is_nlsr(packet.name) and not is_management(packet.name):
                nlsr_bytes += packet.length
            if not packet.outbound:
                if packet.node == "consumer" and packet.ptype == "data" and is_useful_content(packet.name):
                    useful_bytes += packet.length
                    frame_id = content_frame_id(packet.name)
                    if frame_id:
                        delivered_frames.add(frame_id)
                continue
            if packet.node not in RELAY_NODES:
                continue
            if is_useful_content(packet.name):
                relay_content += packet.length
            elif is_guard(packet.name):
                relay_guard += packet.length
            elif is_meta(packet.name):
                relay_meta += packet.length
            elif is_application(packet.name):
                relay_other += packet.length
            else:
                continue
            relay_bytes += packet.length
            if packet.interest_flood and packet.ptype == "interest":
                interest_flood += packet.length
            if packet.data_flood and packet.ptype == "data":
                data_flood += packet.length
        flood_bytes = interest_flood + data_flood
        ratio = "" if useful_bytes == 0 else relay_bytes / useful_bytes
        delivered = len(delivered_frames)
        nominal = duration * 1000.0 / frame_period_ms
        delivery_ratio = delivered / nominal
        uir = "" if logical == 0 else unmet / logical
        row: Dict[str, object] = {
            "configuration": configuration,
            "profile": profile,
            "run_id": run_id,
            "handoff_index": handoff.index,
            "from_node": handoff.from_node,
            "to_node": handoff.to_node,
            "handoff_time": handoff.abs_time,
            "event_end_time": event_end,
            "event_duration_s": duration,
            "recovered": recovery is not None,
            "service_recovery_time_ms": "" if recovery is None else (recovery[2] - handoff.abs_time) * 1000.0,
            "recovery_name": "" if recovery is None else recovery[0],
            "consumer_interest_time": "" if recovery is None else recovery[1],
            "producer_interest_time": "" if recovery is None else recovery[2],
            "first_post_handoff_producer_data_arrival_ms": "" if first_arrival is None else (first_arrival - handoff.abs_time) * 1000.0,
            "logical_request_count": logical,
            "satisfied_request_count": satisfied,
            "unmet_request_count": unmet,
            "unmet_interest_ratio": uir,
            "unmet_request_rate": unmet / duration,
            "relay_application_forwarded_bytes": relay_bytes,
            "useful_content_delivered_bytes": useful_bytes,
            "forwarding_cost_ratio": ratio,
            "application_forwarding_rate_bytes_per_s": relay_bytes / duration,
            "nlsr_control_bytes": nlsr_bytes,
            "nlsr_control_rate_bytes_per_s": nlsr_bytes / duration,
            "recovery_interest_flood_bytes": recovery_interest,
            "recovery_data_flood_bytes": recovery_data,
            "recovery_flood_bytes": recovery_interest + recovery_data,
            "explicit_flood_bytes": flood_bytes,
            "interest_flood_bytes": interest_flood,
            "data_flood_bytes": data_flood,
            "explicit_flood_rate_bytes_per_s": flood_bytes / duration,
            "interest_flood_rate_bytes_per_s": interest_flood / duration,
            "data_flood_rate_bytes_per_s": data_flood / duration,
            "frame_period_ms": frame_period_ms,
            "nominal_frame_opportunities": nominal,
            "delivered_unique_content_frames": delivered,
            "content_delivery_ratio": delivery_ratio,
            "content_loss_fraction": 1.0 - delivery_ratio,
            "delivered_frame_rate_fps": delivered / duration,
            "nominal_frame_rate_fps": 1000.0 / frame_period_ms,
            "relay_content_bytes": relay_content,
            "relay_guard_bytes": relay_guard,
            "relay_meta_bytes": relay_meta,
            "relay_other_application_bytes": relay_other,
        }
        rows.append(row)
    return rows


def write_csv(path: str, rows: Sequence[Dict[str, object]]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def format_audit(rows: Sequence[Dict[str, object]]) -> str:
    lines: List[str] = [
        "SRT endpoint is the producer receipt of the first fresh post-handoff content Interest. Data return is not part of SRT.",
        "Recovery Flooding Volume is all-node flood-marked sender-egress bytes per handoff. "
        "Interest flooding uses NDN HopLimit. Data flooding uses LP MobilityFlag or LP OptoHopLimit. "
        "MetaInfo FloodId alone is not a flood transmission.",
        "forwarding_cost_ratio is retained only as legacy manuscript compatibility.",
    ]
    for row in rows:
        identity = f"{row['configuration']}/{row['run_id']} handoff {row['handoff_index']}"
        if float(str(row["event_duration_s"])) <= 0:
            lines.append(f"EMPTY_EVENT {identity}: capture end is not after the handoff")
        recovered = row["recovered"] is True or str(row["recovered"]) == "True"
        if not recovered and float(str(row["event_duration_s"])) > 0:
            boundary_ms = float(str(row["event_duration_s"])) * 1000.0
            lines.append(
                f"RIGHT_CENSORED {identity}: SRT > {boundary_ms:.6g} ms "
                f"(event boundary); recovered=false and service_recovery_time_ms left empty"
            )
        ratio = row.get("content_delivery_ratio", "")
        if ratio != "" and ratio is not None:
            value = float(str(ratio))
            if value < 0.0 or value > 1.0:
                lines.append(
                    f"CLF_OUTSIDE_UNIT {identity}: content_delivery_ratio={value:.6g} "
                    f"content_loss_fraction={float(str(row['content_loss_fraction'])):.6g} "
                    f"delivered_frames={row['delivered_unique_content_frames']} "
                    f"nominal={row['nominal_frame_opportunities']}"
                )
        if row["forwarding_cost_ratio"] == "":
            lines.append(
                f"LEGACY_FCR {identity}: useful_content_delivered_bytes=0 "
                f"relay_application_forwarded_bytes={row['relay_application_forwarded_bytes']}"
            )
        if recovered:
            lines.append(
                f"SRT {identity}: name={row['recovery_name']} "
                f"handoff={row['handoff_time']} "
                f"consumer_interest={row['consumer_interest_time']} "
                f"producer_interest={row['producer_interest_time']} "
                f"srt_ms={row['service_recovery_time_ms']}"
            )
    return "\n".join(lines) + "\n"


def srt_censor_boundary_ms(row: Dict[str, object]) -> Optional[float]:
    """Right-censor boundary for an unrecovered event. Not a numeric SRT."""
    if row.get("recovered") is True or str(row.get("recovered")) == "True":
        return None
    duration = _numeric(row.get("event_duration_s"))
    if duration is None or duration <= 0:
        return None
    return duration * 1000.0


def srt_observation_summary(rows: Sequence[Dict[str, object]]) -> str:
    lines = ["SRT observation counts (censored events stay in the event total and out of the numeric box):"]
    configurations = []
    for row in rows:
        label = str(row["configuration"])
        if label not in configurations:
            configurations.append(label)
    for label in configurations:
        selected = [row for row in rows if str(row["configuration"]) == label]
        observed = sum(1 for row in selected if _numeric(row.get("service_recovery_time_ms")) is not None)
        censored = sum(1 for row in selected if srt_censor_boundary_ms(row) is not None)
        lines.append(f"{label}: total_events={len(selected)} observed_srt={observed} censored={censored}")
    return "\n".join(lines)


def _numeric(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(str(value))


def require_complete(rows: Sequence[Dict[str, object]], configuration: str, run_ids: Sequence[str], handoff_count: int) -> None:
    expected = {(run_id, index) for run_id in run_ids for index in range(1, handoff_count + 1)}
    found = {(str(row["run_id"]), int(str(row["handoff_index"]))) for row in rows if row["configuration"] == configuration}
    missing = sorted(expected - found)
    if missing:
        raise MobilityMetricError(f"{configuration}: missing events {missing}")
    extra = sorted(found - expected)
    if extra:
        raise MobilityMetricError(f"{configuration}: unexpected events {extra}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Measure one run's mobility events.")
    parser.add_argument("--packets", required=True)
    parser.add_argument("--handoffs", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit", required=True)
    args = parser.parse_args(argv)
    try:
        rows = measure_run(
            load_packets(args.packets),
            load_handoffs(args.handoffs),
            args.configuration,
            args.profile,
            args.run_id,
        )
    except MobilityMetricError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    write_csv(args.output, rows)
    audit = format_audit(rows)
    parent = os.path.dirname(args.audit)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.audit, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(audit)
    print(audit, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
