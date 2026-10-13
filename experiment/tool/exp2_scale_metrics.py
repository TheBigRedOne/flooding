"""Exp2-A scalability metrics using the Solution measurement rules.

SRT, CLF, RFV, and NLSR byte accounting call the Solution classifiers and the
Solution event window. Consumer hosts are supplied by the caller. N=1 passes
the host ``consumer``; N=2 and N=4 pass the hosts recorded for that run.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import mobility_event_metrics as metrics

NETWORK_FIELDS = (
    "configuration",
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
    "producer_interest_time",
    "eligible_consumer_witnesses",
    "srt_attribution",
    "srt_censor_boundary_ms",
    "recovery_flood_bytes",
    "recovery_interest_flood_bytes",
    "recovery_data_flood_bytes",
    "nlsr_control_bytes",
    "nlsr_control_rate_bytes_per_s",
    "physical_capture_nodes",
)

CONSUMER_FIELDS = (
    "configuration",
    "run_id",
    "handoff_index",
    "consumer_identity",
    "consumer_host",
    "consumer_attachment",
    "from_node",
    "to_node",
    "handoff_time",
    "event_end_time",
    "event_duration_s",
    "frame_period_ms",
    "nominal_frame_opportunities",
    "delivered_unique_content_frames",
    "content_loss_fraction",
    "zero_delivery",
    "clf_outside_unit_interval",
    "invalid_duration",
)

CONFIGURATION_ORDER = {"N=1": 0, "N=2": 1, "N=4": 2}


def _text_number(value: float) -> str:
    return format(value, ".17g")


def _merge_interests(per_host: Mapping[str, Mapping[str, Sequence[float]]]) -> Dict[str, List[float]]:
    merged: Dict[str, List[float]] = {}
    for host_index in per_host.values():
        for name, times in host_index.items():
            merged.setdefault(name, []).extend(times)
    for times in merged.values():
        times.sort()
    return merged


def _host_witnesses(
    per_host: Mapping[str, Mapping[str, Sequence[float]]],
    name: str,
    handoff_time: float,
    event_end: float,
    last: bool,
    producer_time: float,
) -> int:
    """Hosts with a post-handoff same-name egress at or before this producer ingress."""
    count = 0
    for host_index in per_host.values():
        matched = False
        for item in host_index.get(name) or []:
            if item <= handoff_time or item > producer_time:
                continue
            if metrics._before_end(item, event_end, last):
                matched = True
                break
        if matched:
            count += 1
    return count


def _delivered_frames(
    packets: Sequence[metrics.Packet],
    host: str,
    start: float,
    end: float,
    last: bool,
) -> int:
    frames = set()
    for packet in packets:
        if packet.node != host or packet.outbound or packet.ptype != "data":
            continue
        if not metrics._in_interval(packet, start, end, last):
            continue
        if not metrics.is_useful_content(packet.name):
            continue
        frame_id = metrics.content_frame_id(packet.name)
        if frame_id:
            frames.add(frame_id)
    return len(frames)


def measure_events(
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    configuration: str,
    run_id: str,
    consumers: Sequence[Tuple[str, str, str]],
    frame_period_ms: int,
    capture_nodes: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Return network rows and one CLF row per consumer per handoff.

    ``consumers`` entries are ``(host, display identity, attachment)``.
    Name/time matching follows ``match_service_recovery_interest``. A witness
    count above one marks attribution ambiguous and does not remove the SRT.
    """
    if frame_period_ms <= 0:
        raise metrics.MobilityMetricError(f"frame_period_ms must be positive, got {frame_period_ms}")
    if not packets:
        raise metrics.MobilityMetricError("no packets")
    if not handoffs:
        raise metrics.MobilityMetricError("no handoffs")
    if capture_nodes <= 0:
        raise metrics.MobilityMetricError(f"capture_nodes must be positive, got {capture_nodes}")
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
    per_host = {
        host: metrics._index_times(named, host, True, "interest", True)
        for host, _identity, _attachment in consumers
    }
    pooled = _merge_interests(per_host)
    producer_interests = metrics._index_times(named, "producer", False, "interest", True)
    network_rows: List[Dict[str, object]] = []
    consumer_rows: List[Dict[str, object]] = []
    for position, handoff in enumerate(handoffs):
        last = position == len(handoffs) - 1
        event_end = capture_end if last else handoffs[position + 1].abs_time
        duration = event_end - handoff.abs_time
        interest_flood = 0
        data_flood = 0
        nlsr_bytes = 0
        if duration > 0:
            for packet in named:
                if not metrics._in_interval(packet, handoff.abs_time, event_end, last):
                    continue
                if metrics.is_recovery_interest_flood(packet):
                    interest_flood += packet.length
                elif metrics.is_recovery_data_flood(packet):
                    data_flood += packet.length
                if packet.outbound and metrics.is_nlsr(packet.name) and not metrics.is_management(packet.name):
                    nlsr_bytes += packet.length
        recovery = None
        witnesses = 0
        if duration > 0:
            recovery = metrics.match_service_recovery_interest(
                handoff.abs_time,
                event_end,
                pooled,
                producer_interests,
                inclusive_end=last,
            )
            if recovery is not None:
                witnesses = _host_witnesses(
                    per_host, recovery[0], handoff.abs_time, event_end, last, recovery[2],
                )
        recovered = recovery is not None
        if recovered and witnesses < 1:
            raise metrics.MobilityMetricError(
                f"{configuration} {run_id} handoff {handoff.index}: "
                "SRT matched a name with no eligible consumer witness"
            )
        if witnesses > 1:
            attribution = "ambiguous"
        elif recovered:
            attribution = "unique"
        else:
            attribution = "none"
        censor = ""
        if not recovered and duration > 0:
            censor = _text_number(duration * 1000.0)
        network_rows.append({
            "configuration": configuration,
            "run_id": run_id,
            "handoff_index": handoff.index,
            "from_node": handoff.from_node,
            "to_node": handoff.to_node,
            "handoff_time": _text_number(handoff.abs_time),
            "event_end_time": _text_number(event_end),
            "event_duration_s": _text_number(duration),
            "recovered": "true" if recovered else "false",
            "service_recovery_time_ms": "" if recovery is None else _text_number((recovery[2] - handoff.abs_time) * 1000.0),
            "recovery_name": "" if recovery is None else recovery[0],
            "producer_interest_time": "" if recovery is None else _text_number(recovery[2]),
            "eligible_consumer_witnesses": witnesses,
            "srt_attribution": attribution,
            "srt_censor_boundary_ms": censor,
            "recovery_flood_bytes": interest_flood + data_flood,
            "recovery_interest_flood_bytes": interest_flood,
            "recovery_data_flood_bytes": data_flood,
            "nlsr_control_bytes": nlsr_bytes,
            "nlsr_control_rate_bytes_per_s": "" if duration <= 0 else _text_number(nlsr_bytes / duration),
            "physical_capture_nodes": capture_nodes,
        })
        for host, identity, attachment in consumers:
            delivered = 0 if duration <= 0 else _delivered_frames(named, host, handoff.abs_time, event_end, last)
            nominal = "" if duration <= 0 else duration * 1000.0 / frame_period_ms
            fraction = "" if nominal == "" else 1.0 - (delivered / float(nominal))
            outside = fraction != "" and (float(fraction) < 0.0 or float(fraction) > 1.0)
            consumer_rows.append({
                "configuration": configuration,
                "run_id": run_id,
                "handoff_index": handoff.index,
                "consumer_identity": identity,
                "consumer_host": host,
                "consumer_attachment": attachment,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": _text_number(handoff.abs_time),
                "event_end_time": _text_number(event_end),
                "event_duration_s": _text_number(duration),
                "frame_period_ms": frame_period_ms,
                "nominal_frame_opportunities": "" if nominal == "" else _text_number(float(nominal)),
                "delivered_unique_content_frames": delivered,
                "content_loss_fraction": "" if fraction == "" else _text_number(float(fraction)),
                "zero_delivery": "true" if duration > 0 and delivered == 0 else "false",
                "clf_outside_unit_interval": "true" if outside else "false",
                "invalid_duration": "true" if duration <= 0 else "false",
            })
    return network_rows, consumer_rows


def sort_network(rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            CONFIGURATION_ORDER[str(row["configuration"])],
            str(row["run_id"]),
            int(str(row["handoff_index"])),
        ),
    )


def sort_consumer(rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            CONFIGURATION_ORDER[str(row["configuration"])],
            str(row["run_id"]),
            int(str(row["handoff_index"])),
            str(row["consumer_identity"]),
        ),
    )
