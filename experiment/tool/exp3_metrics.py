"""Exp3 per-producer SRT, CLF, prefix RFV, and network-wide overhead.

Service recovery, content loss, and explicit-flood classification follow the
Solution and Exp2 definitions. ``is_useful_content`` remains /LiveStream/v0
only; Exp3 selects each pair with typed prefix equality. Network-wide totals
are one sender-egress pass over the common observation interval. They are not
the sum of overlapping per-producer windows.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import exp2_distinct_metrics as distinct
import exp2_scale_metrics as scale
import exp3_config as config
import mobility_event_metrics as metrics

HANDOFFS_PER_PRODUCER = 8
POPULATIONS = ("p1", "p2", "p4")
FORMAL_RUNS = config.RUN_IDS
PCAP_MAGICS = (
    b"\xd4\xc3\xb2\xa1",
    b"\xa1\xb2\xc3\xd4",
    b"\x4d\x3c\xb2\xa1",
    b"\xa1\xb2\x3c\x4d",
    b"\x0a\x0d\x0d\x0a",
)
OBSERVED_SUCCESS = "observed-success"
OBSERVED_FAILURE = "observed-failure"
NOT_OBSERVED = "not-observed"
EVIDENCE_UNAVAILABLE = "evidence-unavailable"
ATTRIBUTION_AMBIGUOUS = "attribution-ambiguous"
CONDITIONAL_SRT = "conditional-on-successful-recovery"
UNWEIGHTED_HANDOFFS = "unweighted-across-handoffs"
PREFIX_RFV_WEIGHT = "unweighted-event-median-and-sum-are-not-network-wide"
NETWORK_ACCOUNTING = "single-sender-egress-pass-over-common-interval"
INCLUSION = (
    "Non-final windows are [this producer's actual handoff, this producer's next "
    "actual handoff). The final window is [this producer's actual handoff, this "
    "producer's planned observation endpoint]. The common network interval is "
    "[mobility_clock_origin_abs, mobility_clock_origin_abs + common_end_s]."
)

EVENT_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "producer",
    "consumer",
    "prefix",
    "handoff_index",
    "from_node",
    "to_node",
    "abs_time",
    "rel_time",
    "planned_rel_s",
    "lateness_s",
    "window_start_abs",
    "window_end_abs",
    "window_inclusive_end",
    "window_duration_s",
    "planned_end_abs",
    "planned_end_rel_s",
    "recovery_status",
    "service_recovery_time_s",
    "service_recovery_time_ms",
    "recovery_name",
    "consumer_interest_time",
    "producer_interest_time",
    "srt_censor_time_s",
    "srt_censor_boundary_abs",
    "srt_censor_boundary",
    "frame_period_ms",
    "nominal_frame_opportunities",
    "delivered_unique_content_frames",
    "content_loss_fraction",
    "clf_outside_unit_interval",
    "zero_delivery",
    "guard_generation",
    "guard_flood_ids_observed",
    "guard_flood_id_expectation",
    "guard_attribution",
    "tfib_install",
    "consumer_validation",
    "tfib_active",
    "tfib_standby",
    "tfib_retirement",
    "nlsr_new_path_announced",
    "nfd_new_path_proof",
    "diagnostic_redefines_metrics",
)
PREFIX_RFV_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "producer",
    "consumer",
    "prefix",
    "handoff_index",
    "window_start_abs",
    "window_end_abs",
    "window_inclusive_end",
    "window_duration_s",
    "flood_interest_bytes",
    "flood_guard_data_bytes",
    "flood_content_data_bytes",
    "flood_other_data_bytes",
    "prefix_rfv_bytes",
    "event_window_nlsr_bytes_diagnostic",
    "nlsr_diagnostic_is_network_total",
    "flood_interest_packets",
    "flood_guard_data_packets",
    "flood_content_data_packets",
    "flood_other_data_packets",
    "prefix_rfv_packets",
)
NETWORK_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "observation_start_abs",
    "observation_end_abs",
    "common_duration_s",
    "flood_interest_bytes",
    "flood_data_bytes",
    "flood_guard_data_bytes",
    "flood_content_data_bytes",
    "flood_other_data_bytes",
    "unassigned_flood_bytes",
    "ambiguous_flood_bytes",
    "assigned_flood_outside_event_windows_bytes",
    "network_rfv_bytes",
    "nlsr_control_bytes",
    "nlsr_control_rate_bytes_per_s",
    "network_accounting",
    "population_multiplier_applied",
    "flood_interest_packets",
    "flood_data_packets",
    "flood_guard_data_packets",
    "flood_content_data_packets",
    "flood_other_data_packets",
    "unassigned_flood_packets",
    "ambiguous_flood_packets",
    "assigned_flood_outside_event_windows_packets",
    "network_rfv_packets",
)
SUMMARY_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "summary_scope",
    "producer",
    "consumer",
    "prefix",
    "n_handoffs",
    "n_recovered",
    "n_censored",
    "recovery_success_fraction",
    "srt_conditional_median_ms",
    "srt_conditional_min_ms",
    "srt_conditional_max_ms",
    "srt_median_scope",
    "clf_median",
    "clf_min",
    "clf_max",
    "clf_weighting",
    "prefix_rfv_event_median_bytes",
    "prefix_rfv_event_sum_bytes",
    "prefix_rfv_weighting",
    "prefix_rfv_sum_is_network_rfv",
)
TIMING_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "producer",
    "consumer",
    "prefix",
    "handoff_index",
    "abs_time",
    "rel_time",
    "planned_rel_s",
    "lateness_s",
    "window_start_abs",
    "window_end_abs",
    "window_inclusive_end",
    "planned_end_abs",
    "planned_end_rel_s",
)
COMPARISON_FIELDS = (
    "configuration",
    "population",
    "run_id",
    "run_seed",
    "source_kind",
    "n_handoffs",
    "n_recovered",
    "n_censored",
    "recovery_success_fraction",
    "srt_conditional_median_ms",
    "srt_median_scope",
    "clf_median",
    "clf_weighting",
    "prefix_rfv_event_median_bytes",
    "prefix_rfv_event_sum_bytes",
    "prefix_rfv_sum_is_network_rfv",
    "network_rfv_bytes",
    "nlsr_control_bytes",
    "nlsr_control_rate_bytes_per_s",
    "common_duration_s",
    "replication_unit",
    "network_overhead_scope",
)

_BRACKET_TIME = re.compile(r"^\[(\d+)\]")
_EPOCH_TIME = re.compile(r"^(\d{10}(?:\.\d+)?)")
_FLOOD_ID = re.compile(r"FloodId=(\d+)")
_PREFIX_VALUE = re.compile(r"prefix=(\S+)")
_INTEREST_NAME = re.compile(r"interest=(\S+)")
_VALIDATE = re.compile(
    r"^\[(\d+)\] VALIDATE: Data signature verified(?: name=(\S+))?(?: id=(\S+))?"
)


class Exp3AnalysisError(metrics.MobilityMetricError):
    """Raised when Exp3 evidence cannot be measured without changing its meaning."""


@dataclass
class EventWindow:
    producer: str
    consumer: str
    prefix: str
    producer_index: int
    index: int
    abs_time: float
    rel_time: float
    from_node: str
    to_node: str
    interval_s: float
    planned_rel_s: float
    lateness_s: float
    window_end_abs: float
    inclusive_end: bool
    planned_end_abs: float
    planned_end_rel_s: float

    @property
    def duration_s(self) -> float:
        return self.window_end_abs - self.abs_time


@dataclass
class RunContext:
    configuration: str
    population: str
    population_count: int
    run_id: str
    run_seed: str
    source_kind: str
    origin_abs: float
    common_end_s: float
    frame_period_ms: int
    windows: List[EventWindow]


@dataclass
class LogEvidence:
    """None means the file or log set is absent. An empty string was present but empty."""

    daemon: Dict[str, Optional[str]]
    consumer: Dict[str, Optional[str]]
    nfd: Optional[str]
    nlsr: Optional[str]


@dataclass
class FloodHit:
    detail: str
    prefixes: Tuple[str, ...]
    length: int
    family: str


@dataclass
class Measurement:
    events: List[Dict[str, str]]
    prefix_rfv: List[Dict[str, str]]
    network: List[Dict[str, str]]
    summary: List[Dict[str, str]]
    timing: List[Dict[str, str]]
    audit: str


def population_label(count: int) -> str:
    if count not in (1, 2, 4):
        raise Exp3AnalysisError(f"Exp3 population must be 1, 2, or 4; got {count}")
    return f"p{count}"


def source_kind_for(run_id: str) -> str:
    if run_id == config.PILOT_RUN_ID:
        return "pilot"
    if run_id in FORMAL_RUNS:
        return "formal"
    raise Exp3AnalysisError(f"Exp3 run id must be r1..r5 or pilot; got {run_id!r}")


def expected_handoff_count(population_count: int) -> int:
    return population_count * HANDOFFS_PER_PRODUCER


def formal_run_keys() -> Tuple[Tuple[str, str], ...]:
    return tuple((population, run_id) for population in POPULATIONS for run_id in FORMAL_RUNS)


def analysis_relative(population: str, run_id: str) -> str:
    """Derived-output path. A seed-1 pilot stays p4/pilot and is not p4/r1."""
    kind = source_kind_for(run_id)
    if population not in POPULATIONS:
        raise Exp3AnalysisError(f"Exp3 population directory must be p1, p2, or p4; got {population!r}")
    if kind == "pilot" and population != "p4":
        raise Exp3AnalysisError("the Exp3 pilot is a P=4 run")
    return f"{population}/{run_id}"


def missing_formal_runs(root: Path) -> List[str]:
    """Formal r1..r5 for P=1, P=2, and P=4. The P=4 pilot does not fill a missing r1."""
    missing = []
    for population, run_id in formal_run_keys():
        run_dir = root / population / run_id
        if not (run_dir / "handoffs.txt").is_file() or not (run_dir / "params.txt").is_file():
            missing.append(f"{population}/{run_id}")
    return missing


def name_has_prefix(name: str, prefix: str) -> bool:
    """Typed-component prefix match. Ordinary v0 does not match a Version component."""
    components = metrics.parse_name(name)
    prefix_key = distinct.stream_components(prefix)
    return components[:len(prefix_key)] == prefix_key


def read_assignments(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        raise Exp3AnalysisError(f"missing params.txt: {path}")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.startswith("link ") or line.startswith("pair "):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip()
    return values


def load_handoff_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise Exp3AnalysisError(f"missing handoffs.txt: {path}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or "planned_rel_s" not in lines[0] or "lateness_s" not in lines[0]:
        raise Exp3AnalysisError(
            f"{path} is not a Phase A handoff table; analysis requires planned_rel_s and lateness_s"
        )
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 9:
            raise Exp3AnalysisError(f"{path} handoff row does not have 9 columns")
        rows.append({
            "producer": parts[0],
            "index": parts[1],
            "abs_time": parts[2],
            "rel_time": parts[3],
            "from_node": parts[4],
            "to_node": parts[5],
            "interval_s": parts[6],
            "planned_rel_s": parts[7],
            "lateness_s": parts[8],
        })
    if not rows:
        raise Exp3AnalysisError(f"no handoffs in {path}")
    return rows


def load_observation_ends(path: Path) -> Dict[str, Tuple[float, float, int]]:
    if not path.is_file():
        raise Exp3AnalysisError(f"missing observation_ends.txt: {path}")
    ends: Dict[str, Tuple[float, float, int]] = {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        if not line.strip() or line.split("\t", 1)[0] == "producer":
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise Exp3AnalysisError(f"{path} row does not have 4 columns")
        try:
            ends[parts[0]] = (float(parts[2]), float(parts[3]), int(parts[1]))
        except ValueError as error:
            raise Exp3AnalysisError(f"{path} endpoint is not numeric") from error
    return ends


def build_event_windows(
    population_count: int,
    handoff_rows: Sequence[Mapping[str, str]],
    endpoints: Mapping[str, Tuple[float, float]],
    origin_abs: float,
    common_end_s: float,
) -> List[EventWindow]:
    """Build non-overlapping per-producer windows. Cross-producer overlap is retained."""
    if common_end_s <= 0 or origin_abs <= 0:
        raise Exp3AnalysisError("mobility origin and common_end_s must be positive")
    selected = config.pairs_for(population_count)
    grouped: Dict[str, List[Mapping[str, str]]] = {pair.producer: [] for pair in selected}
    for row in handoff_rows:
        producer = row["producer"]
        if producer not in grouped:
            raise Exp3AnalysisError(f"handoff producer {producer} is outside the recorded population")
        grouped[producer].append(row)
    if not endpoints:
        raise Exp3AnalysisError("observation endpoints are required")
    recorded_ends = {pair.producer: endpoints[pair.producer] for pair in selected if pair.producer in endpoints}
    if len(recorded_ends) != len(selected):
        raise Exp3AnalysisError("each active producer needs its own planned observation endpoint")
    if abs(max(item[0] for item in recorded_ends.values()) - common_end_s) > 1e-4:
        raise Exp3AnalysisError("common_end_s is not the maximum recorded producer observation end")
    windows: List[EventWindow] = []
    for pair in selected:
        own = grouped[pair.producer]
        if len(own) != HANDOFFS_PER_PRODUCER:
            raise Exp3AnalysisError(
                f"{pair.producer} has {len(own)} handoffs; a full Exp3 producer has {HANDOFFS_PER_PRODUCER}"
            )
        planned_rel, planned_abs = endpoints[pair.producer]
        if abs((origin_abs + planned_rel) - planned_abs) > 1e-3:
            raise Exp3AnalysisError(f"{pair.producer} planned endpoint is not origin plus relative end")
        if planned_abs - 1e-3 > origin_abs + common_end_s:
            raise Exp3AnalysisError(f"{pair.producer} planned endpoint is after the common interval")
        actual: List[float] = []
        parsed = []
        for offset, row in enumerate(own):
            try:
                index = int(row["index"])
                abs_time = float(row["abs_time"])
                rel_time = float(row["rel_time"])
                planned = float(row["planned_rel_s"])
                lateness = float(row["lateness_s"])
                interval = float(row["interval_s"])
            except (KeyError, ValueError) as error:
                raise Exp3AnalysisError(f"{pair.producer} handoff {offset + 1} is not numeric") from error
            if index != offset + 1:
                raise Exp3AnalysisError(f"{pair.producer} handoff index {index} is not {offset + 1}")
            if abs((origin_abs + rel_time) - abs_time) > 1e-3:
                raise Exp3AnalysisError(f"{pair.producer} handoff {index} absolute time is not origin plus relative time")
            if abs((rel_time - planned) - lateness) > 1e-3:
                raise Exp3AnalysisError(f"{pair.producer} handoff {index} lateness is not actual minus planned time")
            actual.append(abs_time)
            parsed.append((index, abs_time, rel_time, planned, lateness, interval, row["from_node"], row["to_node"]))
        for earlier, later in zip(actual, actual[1:]):
            if later <= earlier:
                raise Exp3AnalysisError(f"{pair.producer} handoff timestamps are not strictly increasing")
        if actual[-1] >= planned_abs:
            raise Exp3AnalysisError(
                f"{pair.producer} final handoff is not before its planned observation endpoint"
            )
        for position, item in enumerate(parsed):
            end = config.event_window_end(position, actual, planned_abs)
            if end <= item[1]:
                raise Exp3AnalysisError(f"{pair.producer} handoff {item[0]} has a non-positive window")
            windows.append(EventWindow(
                producer=pair.producer,
                consumer=pair.consumer,
                prefix=pair.prefix,
                producer_index=pair.index,
                index=item[0],
                abs_time=item[1],
                rel_time=item[2],
                from_node=item[6],
                to_node=item[7],
                interval_s=item[5],
                planned_rel_s=item[3],
                lateness_s=item[4],
                window_end_abs=end,
                inclusive_end=position == len(parsed) - 1,
                planned_end_abs=planned_abs,
                planned_end_rel_s=planned_rel,
            ))
    return windows


def load_run_context(run_dir: Path) -> RunContext:
    """Read identity from the run directory. The directory name must match the record."""
    params = read_assignments(run_dir / "params.txt")
    try:
        population_count = config.parse_population(params.get("exp3_population", ""))
    except config.Exp3ConfigError as error:
        raise Exp3AnalysisError(str(error)) from error
    population = population_label(population_count)
    run_id = params.get("exp3_run_id", "")
    kind = source_kind_for(run_id)
    if run_dir.name != run_id or run_dir.parent.name != population:
        raise Exp3AnalysisError(
            f"run directory {run_dir.parent.name}/{run_dir.name} does not match recorded {population}/{run_id}"
        )
    if params.get("exp3_schedule") != "full":
        raise Exp3AnalysisError("Phase B analysis requires a full schedule, not smoke")
    if params.get("exp3_campaign") != config.CAMPAIGN_ID:
        raise Exp3AnalysisError(f"campaign must be {config.CAMPAIGN_ID}")
    try:
        origin = float(params["mobility_clock_origin_abs"])
        common_end = float(params["common_end_s"])
        seed = str(int(params["exp3_run_seed"]))
    except (KeyError, ValueError) as error:
        raise Exp3AnalysisError("params.txt is missing origin, common_end_s, or run seed") from error
    _segments, frame_period_ms = metrics.load_run_config(str(run_dir / "params.txt"))
    raw_ends = load_observation_ends(run_dir / "observation_ends.txt")
    endpoints = {producer: (rel, absolute) for producer, (rel, absolute, _index) in raw_ends.items()}
    for pair in config.pairs_for(population_count):
        if params.get(f"producer{pair.index}_prefix") != pair.prefix:
            raise Exp3AnalysisError(f"params prefix for {pair.producer} is not {pair.prefix}")
        recorded = raw_ends.get(pair.producer)
        if recorded is None or recorded[2] != pair.index:
            raise Exp3AnalysisError(f"observation endpoint for {pair.producer} is missing or mis-indexed")
    windows = build_event_windows(
        population_count,
        load_handoff_rows(run_dir / "handoffs.txt"),
        endpoints,
        origin,
        common_end,
    )
    return RunContext(
        configuration=config.CAMPAIGN_ID,
        population=population,
        population_count=population_count,
        run_id=run_id,
        run_seed=seed,
        source_kind=kind,
        origin_abs=origin,
        common_end_s=common_end,
        frame_period_ms=frame_period_ms,
        windows=windows,
    )


def validate_packet_captures(run_dir: Path) -> List[Path]:
    """Refuse missing, truncated, or unrecognised captures. Do not trim windows to packet time."""
    pcap_dir = run_dir / "pcap_nodes"
    if not pcap_dir.is_dir():
        raise Exp3AnalysisError(f"missing packet captures in {pcap_dir}")
    pcaps = sorted(path for path in pcap_dir.glob("*.pcap") if path.is_file())
    if not pcaps:
        raise Exp3AnalysisError(f"missing packet captures in {pcap_dir}")
    for pcap in pcaps:
        payload = pcap.read_bytes()
        if len(payload) < 24 or payload[:4] not in PCAP_MAGICS:
            raise Exp3AnalysisError(f"malformed pcap: {pcap}")
    return pcaps


def _number(value: float) -> str:
    return scale._text_number(value)


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _line_timestamp(line: str) -> Optional[float]:
    text = line.strip()
    bracket = _BRACKET_TIME.match(text)
    if bracket:
        raw = int(bracket.group(1))
        if raw > 10**14:
            return raw / 1e9
        if raw > 10**11:
            return raw / 1e6
        return float(raw)
    epoch = _EPOCH_TIME.match(text)
    if epoch:
        return float(epoch.group(1))
    return None


def _in_event(timestamp: float, window: EventWindow) -> bool:
    if timestamp < window.abs_time:
        return False
    return metrics._before_end(timestamp, window.window_end_abs, window.inclusive_end)


def _prefix_in_line(line: str, prefix: str) -> bool:
    for match in _PREFIX_VALUE.finditer(line):
        if metrics.names_equal(match.group(1), prefix):
            return True
    for match in _INTEREST_NAME.finditer(line):
        if name_has_prefix(match.group(1), prefix):
            return True
    return False


def _status_from_lines(
    text: Optional[str],
    window: EventWindow,
    predicate,
) -> str:
    if text is None:
        return EVIDENCE_UNAVAILABLE
    in_window = False
    saw_timed = False
    saw_untimed = False
    for line in text.splitlines():
        if not predicate(line):
            continue
        timestamp = _line_timestamp(line)
        if timestamp is None:
            saw_untimed = True
            continue
        saw_timed = True
        if _in_event(timestamp, window):
            in_window = True
    if in_window:
        return OBSERVED_SUCCESS
    if saw_untimed and not saw_timed:
        return EVIDENCE_UNAVAILABLE
    return NOT_OBSERVED


def _proof_status(text: Optional[str], window: EventWindow, prefix: str) -> str:
    if text is None:
        return EVIDENCE_UNAVAILABLE
    accepted = False
    rejected = False
    saw_timed = False
    saw_untimed = False
    for line in text.splitlines():
        if "new-path-calculated" not in line or not _prefix_in_line(line, prefix):
            continue
        timestamp = _line_timestamp(line)
        if timestamp is None:
            saw_untimed = True
            continue
        saw_timed = True
        if not _in_event(timestamp, window):
            continue
        if "rejected" in line or "ignored" in line:
            rejected = True
        elif "accepted" in line:
            accepted = True
    if accepted and rejected:
        return ATTRIBUTION_AMBIGUOUS
    if rejected:
        return OBSERVED_FAILURE
    if accepted:
        return OBSERVED_SUCCESS
    if saw_untimed and not saw_timed:
        return EVIDENCE_UNAVAILABLE
    return NOT_OBSERVED


def _guard_observation(text: Optional[str], window: EventWindow) -> Tuple[str, str, str]:
    if text is None:
        return EVIDENCE_UNAVAILABLE, "", "not-inferred-from-handoff-index"
    found: List[int] = []
    saw_timed = False
    saw_untimed = False
    for line in text.splitlines():
        if "flooded guard" not in line:
            continue
        timestamp = _line_timestamp(line)
        if timestamp is None:
            saw_untimed = True
            continue
        saw_timed = True
        if not _in_event(timestamp, window):
            continue
        found.extend(int(item) for item in _FLOOD_ID.findall(line))
    if found:
        unique = ",".join(str(item) for item in sorted(set(found)))
        attribution = "single-flood-id" if len(set(found)) == 1 else "multiple-flood-ids-in-window"
        return OBSERVED_SUCCESS, unique, attribution
    if saw_untimed and not saw_timed:
        return EVIDENCE_UNAVAILABLE, "", "not-inferred-from-handoff-index"
    return NOT_OBSERVED, "", "not-inferred-from-handoff-index"


def _consumer_validation(text: Optional[str], window: EventWindow) -> str:
    if text is None:
        return EVIDENCE_UNAVAILABLE
    saw_timed = False
    saw_untimed = False
    for line in text.splitlines():
        match = _VALIDATE.match(line.strip())
        if not match:
            continue
        timestamp = _line_timestamp(line)
        if timestamp is None:
            saw_untimed = True
            continue
        saw_timed = True
        if timestamp <= window.abs_time or not _in_event(timestamp, window):
            continue
        name = match.group(2) or ""
        identity = match.group(3) or ""
        if identity == window.consumer and name_has_prefix(name, window.prefix):
            return OBSERVED_SUCCESS
    if saw_untimed and not saw_timed:
        return EVIDENCE_UNAVAILABLE
    return NOT_OBSERVED


def diagnose_window(window: EventWindow, logs: Optional[LogEvidence]) -> Dict[str, str]:
    """Protocol diagnostics. Missing logs are unavailable, not evidence of non-execution."""
    daemon = None if logs is None else logs.daemon.get(window.producer)
    consumer = None if logs is None else logs.consumer.get(window.consumer)
    nfd = None if logs is None else logs.nfd
    nlsr = None if logs is None else logs.nlsr
    generation, flood_ids, attribution = _guard_observation(daemon, window)
    announced = _status_from_lines(
        nlsr,
        window,
        lambda line: "Announced new-path-calculated" in line and _prefix_in_line(line, window.prefix),
    )
    return {
        "guard_generation": generation,
        "guard_flood_ids_observed": flood_ids,
        "guard_flood_id_expectation": "not-inferred-from-handoff-index",
        "guard_attribution": attribution,
        "tfib_install": _status_from_lines(
            nfd, window, lambda line: "TFIB update" in line and _prefix_in_line(line, window.prefix),
        ),
        "consumer_validation": _consumer_validation(consumer, window),
        "tfib_active": _status_from_lines(
            nfd, window, lambda line: "tfib-forward" in line and _prefix_in_line(line, window.prefix),
        ),
        "tfib_standby": _status_from_lines(
            nfd, window, lambda line: "tfib-standby" in line and _prefix_in_line(line, window.prefix),
        ),
        "tfib_retirement": _status_from_lines(
            nfd, window, lambda line: "tfib-retire" in line and _prefix_in_line(line, window.prefix),
        ),
        "nlsr_new_path_announced": announced,
        "nfd_new_path_proof": _proof_status(nfd, window, window.prefix),
        "diagnostic_redefines_metrics": "false",
    }


def attribute_flood(packet: metrics.Packet, prefixes: Sequence[str]) -> Optional[FloodHit]:
    """One sender-egress flood transmission. MetaInfo FloodId alone is not a flood."""
    if metrics.is_recovery_interest_flood(packet):
        kind = "interest"
    elif metrics.is_recovery_data_flood(packet):
        kind = "data"
    else:
        return None
    matched = tuple(prefix for prefix in prefixes if name_has_prefix(packet.name, prefix))
    if len(matched) > 1:
        return FloodHit("ambiguous", matched, packet.length, kind)
    if len(matched) == 0:
        detail = "unassigned-interest" if kind == "interest" else "unassigned-data"
        return FloodHit(detail, (), packet.length, kind)
    prefix = matched[0]
    if kind == "interest":
        return FloodHit("interest", (prefix,), packet.length, kind)
    if metrics.is_guard(packet.name):
        return FloodHit("guard-data", (prefix,), packet.length, kind)
    if distinct.is_stream_content(packet.name, prefix):
        return FloodHit("content-data", (prefix,), packet.length, kind)
    return FloodHit("other-data", (prefix,), packet.length, kind)


def _index_interests(
    packets: Sequence[metrics.Packet],
    node: str,
    outbound: bool,
    prefix: str,
) -> Dict[str, List[float]]:
    grouped: Dict[str, List[float]] = {}
    for packet in packets:
        if packet.node != node or packet.outbound != outbound or packet.ptype != "interest":
            continue
        if not distinct.is_stream_content(packet.name, prefix):
            continue
        grouped.setdefault(metrics.canonical_name(packet.name), []).append(packet.time)
    for times in grouped.values():
        times.sort()
    return grouped


def _window_contains(packet: metrics.Packet, window: EventWindow) -> bool:
    return metrics._in_interval(packet, window.abs_time, window.window_end_abs, window.inclusive_end)


def _empty_flood() -> Dict[str, int]:
    return {"interest": 0, "guard-data": 0, "content-data": 0, "other-data": 0}


def _median_text(values: Sequence[float]) -> str:
    if not values:
        return ""
    return _number(float(statistics.median(values)))


def _extent(values: Sequence[float]) -> Tuple[str, str]:
    if not values:
        return "", ""
    return _number(min(values)), _number(max(values))


def _summary_row(
    context: RunContext,
    scope: str,
    producer: str,
    consumer: str,
    prefix: str,
    events: Sequence[Mapping[str, str]],
    floods: Sequence[Mapping[str, str]],
) -> Dict[str, str]:
    recovered = [float(row["service_recovery_time_ms"]) for row in events if row["recovery_status"] == "recovered"]
    censored = [row for row in events if row["recovery_status"] == "right-censored"]
    fractions = [float(row["content_loss_fraction"]) for row in events]
    volumes = [int(row["prefix_rfv_bytes"]) for row in floods]
    low_srt, high_srt = _extent(recovered)
    low_clf, high_clf = _extent(fractions)
    count = len(events)
    return {
        "configuration": context.configuration,
        "population": context.population,
        "run_id": context.run_id,
        "run_seed": context.run_seed,
        "source_kind": context.source_kind,
        "summary_scope": scope,
        "producer": producer,
        "consumer": consumer,
        "prefix": prefix,
        "n_handoffs": str(count),
        "n_recovered": str(len(recovered)),
        "n_censored": str(len(censored)),
        "recovery_success_fraction": "" if count == 0 else _number(len(recovered) / count),
        "srt_conditional_median_ms": _median_text(recovered),
        "srt_conditional_min_ms": low_srt,
        "srt_conditional_max_ms": high_srt,
        "srt_median_scope": CONDITIONAL_SRT,
        "clf_median": _median_text(fractions),
        "clf_min": low_clf,
        "clf_max": high_clf,
        "clf_weighting": UNWEIGHTED_HANDOFFS,
        "prefix_rfv_event_median_bytes": _median_text([float(item) for item in volumes]),
        "prefix_rfv_event_sum_bytes": str(sum(volumes)),
        "prefix_rfv_weighting": PREFIX_RFV_WEIGHT,
        "prefix_rfv_sum_is_network_rfv": "false",
    }


def measure_run(
    packets: Sequence[metrics.Packet],
    context: RunContext,
    logs: Optional[LogEvidence] = None,
) -> Measurement:
    """Measure one run. Censored recoveries stay in the event table with a blank SRT."""
    if context.source_kind != source_kind_for(context.run_id):
        raise Exp3AnalysisError("source kind does not match the run id")
    if context.run_id == config.PILOT_RUN_ID and context.source_kind != "pilot":
        raise Exp3AnalysisError("a pilot measurement cannot be labelled as a formal replicate")
    prefixes = tuple(dict.fromkeys(window.prefix for window in context.windows))
    by_prefix: Dict[str, List[EventWindow]] = {}
    for window in context.windows:
        by_prefix.setdefault(window.prefix, []).append(window)
    common_end = context.origin_abs + context.common_end_s
    network_interest = 0
    network_guard = 0
    network_content = 0
    network_other = 0
    unassigned_interest = 0
    unassigned_data = 0
    ambiguous_interest = 0
    ambiguous_data = 0
    outside = 0
    network_interest_packets = 0
    network_guard_packets = 0
    network_content_packets = 0
    network_other_packets = 0
    unassigned_interest_packets = 0
    unassigned_data_packets = 0
    ambiguous_interest_packets = 0
    ambiguous_data_packets = 0
    outside_packets = 0
    nlsr_bytes = 0
    event_flood = {id(window): _empty_flood() for window in context.windows}
    event_packets = {id(window): _empty_flood() for window in context.windows}
    event_nlsr = {id(window): 0 for window in context.windows}
    for packet in packets:
        in_common = metrics._in_interval(packet, context.origin_abs, common_end, True)
        if in_common and packet.outbound and metrics.is_nlsr(packet.name) and not metrics.is_management(packet.name):
            nlsr_bytes += packet.length
            for window in context.windows:
                if _window_contains(packet, window):
                    event_nlsr[id(window)] += packet.length
        if not in_common:
            continue
        hit = attribute_flood(packet, prefixes)
        if hit is None:
            continue
        if hit.detail == "interest":
            network_interest += hit.length
            network_interest_packets += 1
        elif hit.detail == "guard-data":
            network_guard += hit.length
            network_guard_packets += 1
        elif hit.detail == "content-data":
            network_content += hit.length
            network_content_packets += 1
        elif hit.detail == "other-data":
            network_other += hit.length
            network_other_packets += 1
        elif hit.detail == "unassigned-interest":
            unassigned_interest += hit.length
            unassigned_interest_packets += 1
        elif hit.detail == "unassigned-data":
            unassigned_data += hit.length
            unassigned_data_packets += 1
        elif hit.detail == "ambiguous" and hit.family == "interest":
            ambiguous_interest += hit.length
            ambiguous_interest_packets += 1
        elif hit.detail == "ambiguous":
            ambiguous_data += hit.length
            ambiguous_data_packets += 1
        if len(hit.prefixes) == 1:
            matched_windows = [
                window for window in by_prefix.get(hit.prefixes[0], []) if _window_contains(packet, window)
            ]
            if not matched_windows:
                outside += hit.length
                outside_packets += 1
            for window in matched_windows:
                event_flood[id(window)][hit.detail] += hit.length
                event_packets[id(window)][hit.detail] += 1
    events = []
    prefix_rows = []
    timing = []
    for window in context.windows:
        consumer_interests = _index_interests(packets, window.consumer, True, window.prefix)
        producer_interests = _index_interests(packets, window.producer, False, window.prefix)
        recovery = metrics.match_service_recovery_interest(
            window.abs_time,
            window.window_end_abs,
            consumer_interests,
            producer_interests,
            window.inclusive_end,
        )
        duration = window.duration_s
        if duration <= 0:
            raise Exp3AnalysisError(f"{window.producer} handoff {window.index} has a non-positive window")
        nominal = duration * 1000.0 / context.frame_period_ms
        delivered = distinct._delivered_frames(
            packets, window.consumer, window.prefix, window.abs_time, window.window_end_abs, window.inclusive_end,
        )
        fraction = 1.0 - (delivered / nominal)
        if recovery is None:
            status = "right-censored"
            srt_s = ""
            srt_ms = ""
            recovery_name = ""
            consumer_time = ""
            producer_time = ""
            censor_time = _number(duration)
            censor_abs = _number(window.window_end_abs)
            censor_boundary = "planned-observation-endpoint" if window.inclusive_end else "next-handoff-of-same-producer"
        else:
            name, consumer_interest_time, producer_interest_time = recovery
            srt_value = producer_interest_time - window.abs_time
            if srt_value <= 0:
                raise Exp3AnalysisError("a successful recovery cannot have a non-positive SRT")
            status = "recovered"
            srt_s = _number(srt_value)
            srt_ms = _number(srt_value * 1000.0)
            recovery_name = name
            consumer_time = _number(consumer_interest_time)
            producer_time = _number(producer_interest_time)
            censor_time = ""
            censor_abs = ""
            censor_boundary = ""
        floods = event_flood[id(window)]
        counted = event_packets[id(window)]
        prefix_total = floods["interest"] + floods["guard-data"] + floods["content-data"] + floods["other-data"]
        prefix_count = counted["interest"] + counted["guard-data"] + counted["content-data"] + counted["other-data"]
        identity = {
            "configuration": context.configuration,
            "population": context.population,
            "run_id": context.run_id,
            "run_seed": context.run_seed,
            "source_kind": context.source_kind,
            "producer": window.producer,
            "consumer": window.consumer,
            "prefix": window.prefix,
            "handoff_index": str(window.index),
        }
        events.append({
            **identity,
            "from_node": window.from_node,
            "to_node": window.to_node,
            "abs_time": _number(window.abs_time),
            "rel_time": _number(window.rel_time),
            "planned_rel_s": _number(window.planned_rel_s),
            "lateness_s": _number(window.lateness_s),
            "window_start_abs": _number(window.abs_time),
            "window_end_abs": _number(window.window_end_abs),
            "window_inclusive_end": _flag(window.inclusive_end),
            "window_duration_s": _number(duration),
            "planned_end_abs": _number(window.planned_end_abs),
            "planned_end_rel_s": _number(window.planned_end_rel_s),
            "recovery_status": status,
            "service_recovery_time_s": srt_s,
            "service_recovery_time_ms": srt_ms,
            "recovery_name": recovery_name,
            "consumer_interest_time": consumer_time,
            "producer_interest_time": producer_time,
            "srt_censor_time_s": censor_time,
            "srt_censor_boundary_abs": censor_abs,
            "srt_censor_boundary": censor_boundary,
            "frame_period_ms": str(context.frame_period_ms),
            "nominal_frame_opportunities": _number(nominal),
            "delivered_unique_content_frames": str(delivered),
            "content_loss_fraction": _number(fraction),
            "clf_outside_unit_interval": _flag(fraction < 0.0 or fraction > 1.0),
            "zero_delivery": _flag(delivered == 0),
            **diagnose_window(window, logs),
        })
        prefix_rows.append({
            **identity,
            "window_start_abs": _number(window.abs_time),
            "window_end_abs": _number(window.window_end_abs),
            "window_inclusive_end": _flag(window.inclusive_end),
            "window_duration_s": _number(duration),
            "flood_interest_bytes": str(floods["interest"]),
            "flood_guard_data_bytes": str(floods["guard-data"]),
            "flood_content_data_bytes": str(floods["content-data"]),
            "flood_other_data_bytes": str(floods["other-data"]),
            "prefix_rfv_bytes": str(prefix_total),
            "event_window_nlsr_bytes_diagnostic": str(event_nlsr[id(window)]),
            "nlsr_diagnostic_is_network_total": "false",
            "flood_interest_packets": str(counted["interest"]),
            "flood_guard_data_packets": str(counted["guard-data"]),
            "flood_content_data_packets": str(counted["content-data"]),
            "flood_other_data_packets": str(counted["other-data"]),
            "prefix_rfv_packets": str(prefix_count),
        })
        timing.append({
            **identity,
            "abs_time": _number(window.abs_time),
            "rel_time": _number(window.rel_time),
            "planned_rel_s": _number(window.planned_rel_s),
            "lateness_s": _number(window.lateness_s),
            "window_start_abs": _number(window.abs_time),
            "window_end_abs": _number(window.window_end_abs),
            "window_inclusive_end": _flag(window.inclusive_end),
            "planned_end_abs": _number(window.planned_end_abs),
            "planned_end_rel_s": _number(window.planned_end_rel_s),
        })
    unassigned = unassigned_interest + unassigned_data
    ambiguous = ambiguous_interest + ambiguous_data
    flood_interest = network_interest + unassigned_interest + ambiguous_interest
    flood_data = network_guard + network_content + network_other + unassigned_data + ambiguous_data
    network_rfv = flood_interest + flood_data
    unassigned_packets = unassigned_interest_packets + unassigned_data_packets
    ambiguous_packets = ambiguous_interest_packets + ambiguous_data_packets
    flood_interest_packets = (
        network_interest_packets + unassigned_interest_packets + ambiguous_interest_packets
    )
    flood_data_packets = (
        network_guard_packets + network_content_packets + network_other_packets
        + unassigned_data_packets + ambiguous_data_packets
    )
    network_rfv_packets = flood_interest_packets + flood_data_packets
    rate = "" if context.common_end_s <= 0 else _number(nlsr_bytes / context.common_end_s)
    network = {
        "configuration": context.configuration,
        "population": context.population,
        "run_id": context.run_id,
        "run_seed": context.run_seed,
        "source_kind": context.source_kind,
        "observation_start_abs": _number(context.origin_abs),
        "observation_end_abs": _number(common_end),
        "common_duration_s": _number(context.common_end_s),
        "flood_interest_bytes": str(flood_interest),
        "flood_data_bytes": str(flood_data),
        "flood_guard_data_bytes": str(network_guard),
        "flood_content_data_bytes": str(network_content),
        "flood_other_data_bytes": str(network_other),
        "unassigned_flood_bytes": str(unassigned),
        "ambiguous_flood_bytes": str(ambiguous),
        "assigned_flood_outside_event_windows_bytes": str(outside),
        "network_rfv_bytes": str(network_rfv),
        "nlsr_control_bytes": str(nlsr_bytes),
        "nlsr_control_rate_bytes_per_s": rate,
        "network_accounting": NETWORK_ACCOUNTING,
        "population_multiplier_applied": "false",
        "flood_interest_packets": str(flood_interest_packets),
        "flood_data_packets": str(flood_data_packets),
        "flood_guard_data_packets": str(network_guard_packets),
        "flood_content_data_packets": str(network_content_packets),
        "flood_other_data_packets": str(network_other_packets),
        "unassigned_flood_packets": str(unassigned_packets),
        "ambiguous_flood_packets": str(ambiguous_packets),
        "assigned_flood_outside_event_windows_packets": str(outside_packets),
        "network_rfv_packets": str(network_rfv_packets),
    }
    summary = [_summary_row(context, "run", "all", "all", "all", events, prefix_rows)]
    for pair in config.pairs_for(context.population_count):
        own_events = [row for row in events if row["producer"] == pair.producer]
        own_floods = [row for row in prefix_rows if row["producer"] == pair.producer]
        summary.append(_summary_row(
            context, "producer", pair.producer, pair.consumer, pair.prefix, own_events, own_floods,
        ))
    audit = _audit(context, events, prefix_rows, network, logs)
    for table, fields in (
        (events, EVENT_FIELDS),
        (prefix_rows, PREFIX_RFV_FIELDS),
        ([network], NETWORK_FIELDS),
        (summary, SUMMARY_FIELDS),
        (timing, TIMING_FIELDS),
    ):
        for row in table:
            missing = [field for field in fields if field not in row]
            if missing:
                raise Exp3AnalysisError(f"measurement row is missing {', '.join(missing)}")
    return Measurement(events, prefix_rows, [network], summary, timing, audit)


def _audit(
    context: RunContext,
    events: Sequence[Mapping[str, str]],
    prefix_rows: Sequence[Mapping[str, str]],
    network: Mapping[str, str],
    logs: Optional[LogEvidence],
) -> str:
    censored = sum(1 for row in events if row["recovery_status"] == "right-censored")
    recovered = sum(1 for row in events if row["recovery_status"] == "recovered")
    outside_clf = sum(1 for row in events if row["clf_outside_unit_interval"] == "true")
    diagnostic_counts: Dict[str, int] = {}
    for row in events:
        for key in (
            "guard_generation", "tfib_install", "consumer_validation", "tfib_active",
            "tfib_standby", "tfib_retirement", "nlsr_new_path_announced", "nfd_new_path_proof",
        ):
            diagnostic_counts[f"{key}:{row[key]}"] = diagnostic_counts.get(f"{key}:{row[key]}", 0) + 1
    diagnostic_text = ", ".join(f"{key}={value}" for key, value in sorted(diagnostic_counts.items()))
    lines = [
        "Exp3 measurement audit",
        f"configuration={context.configuration}",
        f"population={context.population}",
        f"run_id={context.run_id}",
        f"run_seed={context.run_seed}",
        f"source_kind={context.source_kind}",
        "SRT is the elapsed time from the producer handoff until that producer receives",
        "the first fresh content Interest whose canonical name matches a post-handoff",
        "Interest sent by the paired consumer under that producer prefix.",
        "The endpoint is producer Interest ingress. It is not consumer Data receipt",
        "and it is not FIB or NLSR convergence.",
        "A handoff with no such ingress is right-censored at its own window end.",
        "Censored rows stay in events.csv. Their SRT fields are blank, never zero.",
        "A conditional median uses recovered events only and is labelled as such.",
        "CLF is 1 minus distinct delivered Version frames divided by nominal frame",
        "opportunities. Nominal opportunities are the actual window duration divided",
        "by the recorded request_interval_ms. This is not an Interest satisfaction ratio.",
        "Out-of-range CLF values are retained.",
        "Prefix RFV sums sender-egress transmissions inside that producer window:",
        "Interest floods require an OptoFlood HopLimit; Data floods require LP",
        "MobilityFlag or LP OptoHopLimit. MetaInfo FloodId alone is not a flood.",
        "Ordinary PIT-return Data is not recovery flooding.",
        "Each accepted sender-egress frame contributes one packet count and its frame length.",
        "Packet counts use the same classification and windows as the byte totals.",
        "Network RFV and network NLSR bytes are independent passes over the common",
        "interval. They are not sums of overlapping producer windows and they are",
        "not multiplied by the producer population.",
        "Event-level NLSR counts are diagnostics and are not the network total.",
        "Protocol-log diagnostics do not redefine SRT, CLF, or RFV.",
        "A missing log is evidence-unavailable, not proof that a mechanism did not run.",
        "Service recovery does not establish NLSR convergence.",
        INCLUSION,
        "Windows are not shortened or extended to the latest packet timestamp.",
        "CLF and per-event prefix RFV summaries weight each handoff equally.",
        "The run is the replication unit. Handoffs inside a run are repeated observations.",
        "Population comparisons remain descriptive: node population and offered",
        "prefixes change with P as well as the number of producers.",
        f"frame_period_ms={context.frame_period_ms}",
        f"handoff_events={len(events)}",
        f"recovered_events={recovered}",
        f"right_censored_events={censored}",
        f"clf_outside_unit_interval={outside_clf}",
        f"network_rfv_bytes={network['network_rfv_bytes']}",
        f"unassigned_flood_bytes={network['unassigned_flood_bytes']}",
        f"ambiguous_flood_bytes={network['ambiguous_flood_bytes']}",
        f"assigned_flood_outside_event_windows_bytes={network['assigned_flood_outside_event_windows_bytes']}",
        f"nlsr_control_bytes={network['nlsr_control_bytes']}",
        f"prefix_event_rfv_sum_bytes={sum(int(row['prefix_rfv_bytes']) for row in prefix_rows)}",
        "prefix_event_rfv_sum_is_network_rfv=false",
        f"log_evidence={'present' if logs is not None else 'not-supplied'}",
        f"diagnostics {diagnostic_text}",
    ]
    return "\n".join(lines) + "\n"


def population_comparison(
    summaries: Sequence[Mapping[str, str]],
    networks: Sequence[Mapping[str, str]],
) -> List[Dict[str, str]]:
    """One formal run produces one comparison row. Pilot rows are rejected."""
    network_by_key = {}
    for row in networks:
        if row["source_kind"] != "formal" or row["run_id"] == config.PILOT_RUN_ID:
            raise Exp3AnalysisError("formal comparison cannot include a pilot network row")
        network_by_key[(row["population"], row["run_id"])] = row
    comparison = []
    for row in summaries:
        if row["summary_scope"] != "run":
            continue
        if row["source_kind"] != "formal" or row["run_id"] == config.PILOT_RUN_ID:
            raise Exp3AnalysisError("formal comparison cannot include a pilot summary")
        network = network_by_key.get((row["population"], row["run_id"]))
        if network is None:
            raise Exp3AnalysisError(f"missing network overhead for {row['population']}/{row['run_id']}")
        comparison.append({
            "configuration": row["configuration"],
            "population": row["population"],
            "run_id": row["run_id"],
            "run_seed": row["run_seed"],
            "source_kind": "formal",
            "n_handoffs": row["n_handoffs"],
            "n_recovered": row["n_recovered"],
            "n_censored": row["n_censored"],
            "recovery_success_fraction": row["recovery_success_fraction"],
            "srt_conditional_median_ms": row["srt_conditional_median_ms"],
            "srt_median_scope": row["srt_median_scope"],
            "clf_median": row["clf_median"],
            "clf_weighting": row["clf_weighting"],
            "prefix_rfv_event_median_bytes": row["prefix_rfv_event_median_bytes"],
            "prefix_rfv_event_sum_bytes": row["prefix_rfv_event_sum_bytes"],
            "prefix_rfv_sum_is_network_rfv": "false",
            "network_rfv_bytes": network["network_rfv_bytes"],
            "nlsr_control_bytes": network["nlsr_control_bytes"],
            "nlsr_control_rate_bytes_per_s": network["nlsr_control_rate_bytes_per_s"],
            "common_duration_s": network["common_duration_s"],
            "replication_unit": "run",
            "network_overhead_scope": "one-independently-measured-observation-per-run",
        })
    return comparison
