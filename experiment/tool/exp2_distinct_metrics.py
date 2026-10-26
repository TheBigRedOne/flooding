"""Exp2(b) Distinct Streams metrics. Solution classifiers for /LiveStream/v0 are not changed.

Network SRT, per-consumer CLF, RFV, and NLSR use the same event window and
matching rules as Exp2(a). Content names are selected with the recorded
consumer-to-stream map. Ordinary vN components are not typed Version components.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

import exp2_scale_metrics as scale
import exp2_shared_config as config
import mobility_event_metrics as metrics

NETWORK_FIELDS = (
    "demand_pattern",
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
    "recovery_stream_prefix",
    "producer_interest_time",
    "eligible_consumer_witnesses",
    "srt_witness_identities",
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
    "demand_pattern",
    "configuration",
    "run_id",
    "handoff_index",
    "consumer_identity",
    "consumer_host",
    "consumer_attachment",
    "stream_prefix",
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

STREAM_FIELDS = (
    "demand_pattern",
    "configuration",
    "run_id",
    "handoff_index",
    "stream_prefix",
    "consumer_host",
    "consumer_identity",
    "from_node",
    "to_node",
    "handoff_time",
    "event_end_time",
    "event_duration_s",
    "recovered",
    "service_recovery_time_ms",
    "recovery_name",
    "producer_interest_time",
    "srt_censor_boundary_ms",
    "diagnostic_not_network_srt",
)

DEMAND_PATTERN = "distinct"
ConsumerSpec = Tuple[str, str, str, str]


def stream_components(prefix: str) -> metrics.NameKey:
    """Ordinary-component key of one configured stream prefix."""
    components = metrics.parse_name(prefix)
    if len(components) < 2 or any(component_type != metrics.COMPONENT_GENERIC for component_type, _value in components):
        raise metrics.MobilityMetricError(
            f"stream prefix must be ordinary NDN components, not a typed Version: {prefix}"
        )
    return components


def is_stream_content(name: str, prefix: str) -> bool:
    """Versioned, segmented content under one stream prefix.

    The prefix match is typed-component equality. Guard, discovery, NLSR, and
    management names are not content. This does not alter ``is_useful_content``.
    """
    components = metrics.parse_name(name)
    prefix_key = stream_components(prefix)
    if components[:len(prefix_key)] != prefix_key:
        return False
    types = [component_type for component_type, _value in components]
    if metrics.COMPONENT_VERSION not in types or metrics.COMPONENT_SEGMENT not in types:
        return False
    if metrics.is_guard_or_meta(name) or metrics.is_nlsr(name) or metrics.is_management(name):
        return False
    return True


def stream_frame_id(name: str, prefix: str) -> str:
    """Hex of the typed Version component. Empty when the name is not this stream's content."""
    if not is_stream_content(name, prefix):
        return ""
    for component_type, value in metrics.parse_name(name):
        if component_type == metrics.COMPONENT_VERSION:
            return value.hex()
    return ""


def stream_of_content(name: str, prefixes: Sequence[str]) -> str:
    """Return the configured prefix of a content name, or empty when none matches."""
    for prefix in prefixes:
        if is_stream_content(name, prefix):
            return prefix
    return ""


def _index_content_interests(
    packets: Sequence[metrics.Packet],
    node: str,
    outbound: bool,
    prefix: str,
) -> Dict[str, List[float]]:
    grouped: Dict[str, List[float]] = {}
    for packet in packets:
        if packet.node != node or packet.outbound != outbound or packet.ptype != "interest":
            continue
        if not is_stream_content(packet.name, prefix):
            continue
        grouped.setdefault(packet.name, []).append(packet.time)
    for times in grouped.values():
        times.sort()
    return grouped


def _delivered_frames(
    packets: Sequence[metrics.Packet],
    host: str,
    prefix: str,
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
        frame_id = stream_frame_id(packet.name, prefix)
        if frame_id:
            frames.add(frame_id)
    return len(frames)


def _witness_identities(
    per_host: Mapping[str, Mapping[str, Sequence[float]]],
    consumers: Sequence[ConsumerSpec],
    name: str,
    handoff_time: float,
    event_end: float,
    last: bool,
    producer_time: float,
) -> str:
    identities = []
    for host, identity, _attachment, _prefix in consumers:
        matched = False
        for item in per_host.get(host, {}).get(name) or []:
            if item <= handoff_time or item > producer_time:
                continue
            if metrics._before_end(item, event_end, last):
                matched = True
                break
        if matched:
            identities.append(identity)
    return ",".join(identities)


def measure_events(
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    configuration: str,
    run_id: str,
    consumers: Sequence[ConsumerSpec],
    frame_period_ms: int,
    capture_nodes: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    """Network SRT, per-consumer CLF, and per-stream recovery diagnostics.

    ``consumers`` entries are ``(host, display identity, attachment, stream prefix)``.
    The network SRT is one observation per handoff: the earliest producer ingress
    across configured streams. Per-stream rows use the same matcher on one stream
    and are not a replacement SRT.
    """
    if frame_period_ms <= 0:
        raise metrics.MobilityMetricError(f"frame_period_ms must be positive, got {frame_period_ms}")
    if not packets:
        raise metrics.MobilityMetricError("no packets")
    if not handoffs:
        raise metrics.MobilityMetricError("no handoffs")
    if capture_nodes <= 0:
        raise metrics.MobilityMetricError(f"capture_nodes must be positive, got {capture_nodes}")
    if not consumers:
        raise metrics.MobilityMetricError("no consumers")
    prefixes = []
    for host, identity, _attachment, prefix in consumers:
        if not host or not identity or not prefix:
            raise metrics.MobilityMetricError("consumer host, identity, and stream prefix are required")
        stream_components(prefix)
        if prefix in prefixes:
            raise metrics.MobilityMetricError(f"duplicate stream prefix in one run: {prefix}")
        prefixes.append(prefix)
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
        host: _index_content_interests(named, host, True, prefix)
        for host, _identity, _attachment, prefix in consumers
    }
    pooled = scale._merge_interests(per_host)
    producer_by_prefix = {
        prefix: _index_content_interests(named, "producer", False, prefix)
        for prefix in prefixes
    }
    producer_interests = scale._merge_interests(producer_by_prefix)
    network_rows: List[Dict[str, object]] = []
    consumer_rows: List[Dict[str, object]] = []
    stream_rows: List[Dict[str, object]] = []
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
        witness_names = ""
        if duration > 0:
            recovery = metrics.match_service_recovery_interest(
                handoff.abs_time,
                event_end,
                pooled,
                producer_interests,
                inclusive_end=last,
            )
            if recovery is not None:
                witnesses = scale._host_witnesses(
                    per_host, recovery[0], handoff.abs_time, event_end, last, recovery[2],
                )
                witness_names = _witness_identities(
                    per_host, consumers, recovery[0], handoff.abs_time, event_end, last, recovery[2],
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
            censor = scale._text_number(duration * 1000.0)
        winning_prefix = "" if recovery is None else stream_of_content(recovery[0], prefixes)
        if recovered and not winning_prefix:
            raise metrics.MobilityMetricError(
                f"{configuration} {run_id} handoff {handoff.index}: "
                f"SRT name is not a configured stream: {recovery[0] if recovery else ''}"
            )
        network_rows.append({
            "demand_pattern": DEMAND_PATTERN,
            "configuration": configuration,
            "run_id": run_id,
            "handoff_index": handoff.index,
            "from_node": handoff.from_node,
            "to_node": handoff.to_node,
            "handoff_time": scale._text_number(handoff.abs_time),
            "event_end_time": scale._text_number(event_end),
            "event_duration_s": scale._text_number(duration),
            "recovered": "true" if recovered else "false",
            "service_recovery_time_ms": "" if recovery is None else scale._text_number((recovery[2] - handoff.abs_time) * 1000.0),
            "recovery_name": "" if recovery is None else recovery[0],
            "recovery_stream_prefix": winning_prefix,
            "producer_interest_time": "" if recovery is None else scale._text_number(recovery[2]),
            "eligible_consumer_witnesses": witnesses,
            "srt_witness_identities": witness_names,
            "srt_attribution": attribution,
            "srt_censor_boundary_ms": censor,
            "recovery_flood_bytes": interest_flood + data_flood,
            "recovery_interest_flood_bytes": interest_flood,
            "recovery_data_flood_bytes": data_flood,
            "nlsr_control_bytes": nlsr_bytes,
            "nlsr_control_rate_bytes_per_s": "" if duration <= 0 else scale._text_number(nlsr_bytes / duration),
            "physical_capture_nodes": capture_nodes,
        })
        for host, identity, attachment, prefix in consumers:
            delivered = 0 if duration <= 0 else _delivered_frames(
                named, host, prefix, handoff.abs_time, event_end, last,
            )
            nominal = "" if duration <= 0 else duration * 1000.0 / frame_period_ms
            fraction = "" if nominal == "" else 1.0 - (delivered / float(nominal))
            outside = fraction != "" and (float(fraction) < 0.0 or float(fraction) > 1.0)
            consumer_rows.append({
                "demand_pattern": DEMAND_PATTERN,
                "configuration": configuration,
                "run_id": run_id,
                "handoff_index": handoff.index,
                "consumer_identity": identity,
                "consumer_host": host,
                "consumer_attachment": attachment,
                "stream_prefix": prefix,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": scale._text_number(handoff.abs_time),
                "event_end_time": scale._text_number(event_end),
                "event_duration_s": scale._text_number(duration),
                "frame_period_ms": frame_period_ms,
                "nominal_frame_opportunities": "" if nominal == "" else scale._text_number(float(nominal)),
                "delivered_unique_content_frames": delivered,
                "content_loss_fraction": "" if fraction == "" else scale._text_number(float(fraction)),
                "zero_delivery": "true" if duration > 0 and delivered == 0 else "false",
                "clf_outside_unit_interval": "true" if outside else "false",
                "invalid_duration": "true" if duration <= 0 else "false",
            })
            stream_recovery = None
            if duration > 0:
                stream_recovery = metrics.match_service_recovery_interest(
                    handoff.abs_time,
                    event_end,
                    per_host[host],
                    producer_by_prefix[prefix],
                    inclusive_end=last,
                )
            stream_censor = ""
            if stream_recovery is None and duration > 0:
                stream_censor = scale._text_number(duration * 1000.0)
            stream_rows.append({
                "demand_pattern": DEMAND_PATTERN,
                "configuration": configuration,
                "run_id": run_id,
                "handoff_index": handoff.index,
                "stream_prefix": prefix,
                "consumer_host": host,
                "consumer_identity": identity,
                "from_node": handoff.from_node,
                "to_node": handoff.to_node,
                "handoff_time": scale._text_number(handoff.abs_time),
                "event_end_time": scale._text_number(event_end),
                "event_duration_s": scale._text_number(duration),
                "recovered": "true" if stream_recovery is not None else "false",
                "service_recovery_time_ms": "" if stream_recovery is None else scale._text_number((stream_recovery[2] - handoff.abs_time) * 1000.0),
                "recovery_name": "" if stream_recovery is None else stream_recovery[0],
                "producer_interest_time": "" if stream_recovery is None else scale._text_number(stream_recovery[2]),
                "srt_censor_boundary_ms": stream_censor,
                "diagnostic_not_network_srt": "true",
            })
    return network_rows, consumer_rows, stream_rows


def overhead_mismatches(
    network: Sequence[Mapping[str, object]],
    packets: Sequence[metrics.Packet],
    handoffs: Sequence[metrics.Handoff],
    configuration: str,
    run_id: str,
    frame_period_ms: int,
) -> List[str]:
    """Compare reusable RFV and NLSR totals with ``measure_run``.

    ``measure_run`` content classification is /LiveStream/v0 and the host name
    ``consumer``. Its SRT and CLF are not a Distinct reference and are not compared.
    """
    reference = metrics.measure_run(
        packets, handoffs, configuration, "distinct", run_id, frame_period_ms=frame_period_ms,
    )
    problems = []
    if len(reference) != len(network):
        return [f"{configuration} {run_id}: measure_run rows {len(reference)} != {len(network)}"]
    for index, (ours, ref) in enumerate(zip(network, reference), start=1):
        for field in (
            "recovery_flood_bytes",
            "recovery_interest_flood_bytes",
            "recovery_data_flood_bytes",
            "nlsr_control_bytes",
        ):
            if int(str(ours[field])) != int(str(ref[field])):
                problems.append(f"{configuration} {run_id} h{index} {field}: distinct={ours[field]} measure_run={ref[field]}")
        for field in ("event_duration_s", "event_end_time", "nlsr_control_rate_bytes_per_s"):
            if ours[field] == "" or ref[field] == "":
                if str(ours[field]) != str(ref[field]):
                    problems.append(f"{configuration} {run_id} h{index} {field}: distinct={ours[field]} measure_run={ref[field]}")
                continue
            if abs(float(str(ours[field])) - float(str(ref[field]))) > 1e-6:
                problems.append(f"{configuration} {run_id} h{index} {field}: distinct={ours[field]} measure_run={ref[field]}")
    return problems


def _assignments(path: Path) -> Dict[str, str]:
    return config._read_assignments(path)


def load_contract(run_dir: Path) -> Tuple[str, str, List[ConsumerSpec], int, float]:
    """Read and check one Distinct run's campaign metadata.

    Returns configuration, run id, consumer specs, frame period, and the final
    recorded observation interval in seconds.
    """
    params = _assignments(run_dir / "params.txt")
    campaign = _assignments(run_dir / "campaign.txt")
    topology = _assignments(run_dir / "topology.txt")
    if not params:
        raise metrics.MobilityMetricError(f"missing params.txt: {run_dir}")
    try:
        pattern = config.recorded_demand_pattern(params, campaign, topology)
    except config.Exp2ConfigError as error:
        raise metrics.MobilityMetricError(str(error)) from error
    if pattern != DEMAND_PATTERN:
        raise metrics.MobilityMetricError(f"{run_dir} demand pattern is {pattern}, not distinct")
    campaign_id = params.get("exp2_campaign") or campaign.get("exp2_campaign")
    if campaign_id != config.DISTINCT_CAMPAIGN_ID or campaign.get("exp2_campaign") != config.DISTINCT_CAMPAIGN_ID:
        raise metrics.MobilityMetricError(
            f"{run_dir} campaign must be {config.DISTINCT_CAMPAIGN_ID}; got {campaign_id!r}"
        )
    if params.get("exp2_advertised_prefix") != config.ADVERTISED_PREFIX:
        raise metrics.MobilityMetricError(f"{run_dir} advertised prefix must be {config.ADVERTISED_PREFIX}")
    if params.get("exp2_guard_name") != config.GUARD_NAME:
        raise metrics.MobilityMetricError(f"{run_dir} guard name must be {config.GUARD_NAME}")
    try:
        consumers = config.parse_active_consumers(params.get("exp2_active_consumers", ""))
    except config.Exp2ConfigError as error:
        raise metrics.MobilityMetricError(str(error)) from error
    expected = config.stream_mapping(DEMAND_PATTERN, consumers)
    for label, text in (
        ("params.txt", params.get("exp2_stream_map", "")),
        ("campaign.txt", campaign.get("stream_map", "")),
        ("topology.txt", topology.get("stream_map", "")),
    ):
        if not text:
            raise metrics.MobilityMetricError(f"{run_dir} {label} has no stream_map")
        try:
            recorded = config.parse_stream_map(text)
        except config.Exp2ConfigError as error:
            raise metrics.MobilityMetricError(f"{run_dir} {label}: {error}") from error
        if recorded != expected:
            raise metrics.MobilityMetricError(
                f"{run_dir} {label} stream_map {text!r} != {config.format_stream_map(expected)}"
            )
    run_id = (params.get("exp2_run_id") or "").strip()
    if run_id != run_dir.name:
        raise metrics.MobilityMetricError(f"{run_dir} exp2_run_id {run_id!r} != directory {run_dir.name}")
    if params.get("handoff_sequence") != ",".join(config.FULL_HANDOFF_SEQUENCE):
        raise metrics.MobilityMetricError(f"{run_dir} handoff sequence is not the eight-handoff Exp2 sequence")
    _segments, interval = metrics.load_run_config(str(run_dir / "params.txt"))
    if interval != config.FRAME_PERIOD_MS:
        raise metrics.MobilityMetricError(f"{run_dir} request_interval_ms must be {config.FRAME_PERIOD_MS}; got {interval}")
    realized = [item for item in params.get("exp2_realized_intervals_s", "").split(",") if item]
    if len(realized) != len(config.FULL_HANDOFF_SEQUENCE):
        raise metrics.MobilityMetricError(
            f"{run_dir} expected {len(config.FULL_HANDOFF_SEQUENCE)} realised intervals; got {len(realized)}"
        )
    try:
        final_observation_s = float(realized[-1])
    except ValueError as error:
        raise metrics.MobilityMetricError(f"{run_dir} final observation interval is not numeric") from error
    population = config.population_of(consumers)
    configuration = "N=2" if population == "n2" else "N=4"
    specs = [
        (host, "C" + host.replace("consumer", ""), config.CONSUMER_ATTACHMENT[host], expected[host])
        for host in consumers
    ]
    return configuration, run_id, specs, interval, final_observation_s


def unique_problems(
    network: Sequence[Mapping[str, object]],
    consumer: Sequence[Mapping[str, object]],
    streams: Sequence[Mapping[str, object]],
) -> List[str]:
    problems = []
    network_keys = [(row["configuration"], row["run_id"], row["handoff_index"]) for row in network]
    if len(network_keys) != len(set(network_keys)):
        problems.append(f"duplicated network keys: {len(network_keys) - len(set(network_keys))}")
    consumer_keys = [
        (row["configuration"], row["run_id"], row["handoff_index"], row["consumer_identity"])
        for row in consumer
    ]
    if len(consumer_keys) != len(set(consumer_keys)):
        problems.append(f"duplicated consumer keys: {len(consumer_keys) - len(set(consumer_keys))}")
    stream_keys = [
        (row["configuration"], row["run_id"], row["handoff_index"], row["stream_prefix"])
        for row in streams
    ]
    if len(stream_keys) != len(set(stream_keys)):
        problems.append(f"duplicated stream-diagnostic keys: {len(stream_keys) - len(set(stream_keys))}")
    return problems
