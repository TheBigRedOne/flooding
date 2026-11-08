"""Exp2 deployment record for Shared and Distinct Streams. No Mini-NDN import.

N=2 and N=4 are the supported populations. N=1 remains the completed Solution
experiment and is not an Exp2 population. Absent consumers are not instantiated.
The default demand pattern remains Shared Streams.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

ROUTING_NODES: Tuple[str, ...] = (
    "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
CONSUMER_CATALOGUE: Tuple[str, ...] = ("consumer1", "consumer2", "consumer3", "consumer4")
PRODUCER_HOST = "producer"

CONSUMER_ATTACHMENT = {
    "consumer1": "acc1",
    "consumer2": "acc4",
    "consumer3": "acc3",
    "consumer4": "acc6",
}
POPULATIONS = {
    "n2": ("consumer1", "consumer2"),
    "n4": ("consumer1", "consumer2", "consumer3", "consumer4"),
}
PRODUCER_ATTACHMENTS: Tuple[str, ...] = ("acc2", "acc3", "acc4", "acc5", "acc6")
INITIAL_ATTACHMENT = "acc2"

FULL_HANDOFF_SEQUENCE: Tuple[str, ...] = (
    "acc2", "acc3", "acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2",
)
SMOKE_HANDOFF_SEQUENCE: Tuple[str, ...] = ("acc2", "acc3")

ADVERTISED_PREFIX = "/LiveStream"
STREAM_PREFIX = "/LiveStream/v0"
GUARD_NAME = "/LiveStream/_guard"
FRAME_PERIOD_MS = 20
FULL_RUN_IDS: Tuple[str, ...] = ("r1", "r2", "r3", "r4", "r5")
FULL_INTERVAL_BASE_S = 90.0
FULL_INTERVAL_JITTER_S = 60.0
CAMPAIGN_ID = "shared-n2-n4"
SHARED_CAMPAIGN_ID = CAMPAIGN_ID
DISTINCT_CAMPAIGN_ID = "distinct-n2-n4"
SHARED_RESULT_ROOT = "results/extended/exp2/shared"
DISTINCT_RESULT_ROOT = "results/extended/exp2/distinct"
DEMAND_PATTERNS = ("shared", "distinct")
# Ordinary stream-identifier components. These are not NDN typed Version components.
DISTINCT_STREAM_PREFIX = {
    "consumer1": "/LiveStream/v0",
    "consumer2": "/LiveStream/v1",
    "consumer3": "/LiveStream/v2",
    "consumer4": "/LiveStream/v3",
}
PER_STREAM_GUARD_NAMES = tuple(f"{prefix}/_guard" for prefix in DISTINCT_STREAM_PREFIX.values())
EXPECTED_NODE_COUNT = {"n2": 12, "n4": 14}

# Backbone and producer mobility links match the Solution topology.
BACKBONE_LINKS: Tuple[Tuple[str, str, int, str], ...] = (
    ("core", "agg1", 1000, "1ms"),
    ("core", "agg2", 1000, "1ms"),
    ("agg1", "acc1", 500, "5ms"),
    ("agg1", "acc2", 500, "5ms"),
    ("agg1", "acc3", 500, "5ms"),
    ("agg2", "acc4", 500, "5ms"),
    ("agg2", "acc5", 500, "5ms"),
    ("agg2", "acc6", 500, "5ms"),
)
PRODUCER_LINKS: Tuple[Tuple[str, str, int, str], ...] = tuple(
    ("producer", access, 100, "5ms") for access in PRODUCER_ATTACHMENTS
)
CONSUMER_LINK_BANDWIDTH = 100
CONSUMER_LINK_DELAY = "5ms"

_DATA_LINE = re.compile(r"^\[(\d+)\].*\bDATA: frame=")
_VALIDATE_LINE = re.compile(
    r"^\[(\d+)\] VALIDATE: Data signature verified(?: name=(\S+))?(?: id=(\S+))?"
)
_PRODUCER_INTEREST_LINE = re.compile(
    r"^\[(\d+)\].*\bINTEREST: Received\b.*\bName: (\S+)", re.MULTILINE,
)
_PRODUCER_DATA_LINE = re.compile(
    r"^\[(\d+)\].*\bDATA: Sending response\b.*\bName: (\S+)", re.MULTILINE,
)
_REGISTERED_PREFIX = re.compile(r"Successfully registered prefix: (\S+)")
_GUARD_PREFIX = re.compile(r"registered guard prefix (\S+)")
_GUARD_CONSUMER_NAME = re.compile(r"GUARD-CONSUMER: name=(\S+)")


class Exp2ConfigError(ValueError):
    """Raised when an Exp2-A configuration cannot be run."""


def parse_population(text: str) -> str:
    """Return n2 or n4. Any other population, including N=1 and N=3, is rejected."""
    token = (text or "").strip().lower().replace(" ", "")
    if token in {"2", "n2", "consumer1,consumer2"}:
        return "n2"
    if token in {"4", "n4", "consumer1,consumer2,consumer3,consumer4"}:
        return "n4"
    raise Exp2ConfigError(
        "EXP2_ACTIVE_CONSUMERS must be n2 (consumer1,consumer2) or "
        f"n4 (consumer1,consumer2,consumer3,consumer4); got {text!r}"
    )


def parse_active_consumers(text: str) -> Tuple[str, ...]:
    """Consumers that exist in the selected population and run an application."""
    return POPULATIONS[parse_population(text)]


def population_of(consumers: Sequence[str]) -> str:
    key = tuple(consumers)
    for population, members in POPULATIONS.items():
        if key == members:
            return population
    raise Exp2ConfigError(f"unsupported Exp2 consumer population: {','.join(consumers)}")


def parse_demand_pattern(text: str) -> str:
    """Return shared or distinct. Any other demand pattern is rejected."""
    token = (text or "").strip().lower()
    if token not in DEMAND_PATTERNS:
        raise Exp2ConfigError(
            f"EXP2_DEMAND_PATTERN must be shared or distinct; got {text!r}"
        )
    return token


def campaign_id_for(pattern: str) -> str:
    pattern = parse_demand_pattern(pattern)
    if pattern == "shared":
        return SHARED_CAMPAIGN_ID
    return DISTINCT_CAMPAIGN_ID


def result_root_for(pattern: str) -> str:
    pattern = parse_demand_pattern(pattern)
    if pattern == "shared":
        return SHARED_RESULT_ROOT
    return DISTINCT_RESULT_ROOT


def stream_mapping(pattern: str, consumers: Sequence[str]) -> Dict[str, str]:
    """Map each instantiated consumer to its content stream prefix.

    Shared Streams assigns /LiveStream/v0 to every consumer. Distinct Streams
    assigns v0, v1, v2, and v3 by consumer identity. The Producer still
    advertises only /LiveStream.
    """
    pattern = parse_demand_pattern(pattern)
    population_of(consumers)
    if pattern == "shared":
        return {name: STREAM_PREFIX for name in consumers}
    return {name: DISTINCT_STREAM_PREFIX[name] for name in consumers}


def format_stream_map(mapping: Mapping[str, str]) -> str:
    return ",".join(f"{name}={mapping[name]}" for name in mapping)


def parse_stream_map(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in (text or "").split(","):
        if not item:
            continue
        if "=" not in item:
            raise Exp2ConfigError(f"malformed stream map entry: {item!r}")
        name, prefix = item.split("=", 1)
        result[name.strip()] = prefix.strip()
    return result


def process_environments(
    pattern: str,
    consumers: Sequence[str],
    request_interval_ms: int,
    window_frames: int,
    segments_per_frame: int,
) -> Dict[str, str]:
    """Environment prefixes for the one Producer and each Consumer.

    Shared Streams keeps one EXP_STREAM_PREFIX on every process. Distinct
    Streams sets that variable separately on each Consumer and does not assign
    a stream prefix to the Producer.
    """
    pattern = parse_demand_pattern(pattern)
    population_of(consumers)
    if pattern == "shared":
        app_env = (
            f"EXP_REQUEST_INTERVAL_MS={request_interval_ms}"
            f" EXP_WINDOW_FRAMES={window_frames}"
            f" EXP_SEGMENTS_PER_FRAME={segments_per_frame}"
            f" EXP_STREAM_PREFIX={STREAM_PREFIX}"
            f" EXP_LOG_VALIDATION_NAME=1"
        )
        environments = {PRODUCER_HOST: app_env}
        for name in consumers:
            environments[name] = f"{app_env} EXP_CONSUMER_ID={name}"
        return environments
    app_env = (
        f"EXP_REQUEST_INTERVAL_MS={request_interval_ms}"
        f" EXP_WINDOW_FRAMES={window_frames}"
        f" EXP_SEGMENTS_PER_FRAME={segments_per_frame}"
        f" EXP_LOG_VALIDATION_NAME=1"
    )
    environments = {PRODUCER_HOST: app_env}
    mapping = stream_mapping(pattern, consumers)
    for name in consumers:
        environments[name] = (
            f"{app_env} EXP_STREAM_PREFIX={mapping[name]} EXP_CONSUMER_ID={name}"
        )
    return environments


def physical_hosts(consumers: Sequence[str]) -> Tuple[str, ...]:
    """Routing infrastructure, the producer, and only the selected consumers."""
    population_of(consumers)
    return ROUTING_NODES + (PRODUCER_HOST,) + tuple(consumers)


def nlsr_hosts(consumers: Sequence[str]) -> Tuple[str, ...]:
    return physical_hosts(consumers)


def capture_nodes(consumers: Sequence[str]) -> Tuple[str, ...]:
    return physical_hosts(consumers)


def links(consumers: Sequence[str]) -> Tuple[Tuple[str, str, int, str], ...]:
    population_of(consumers)
    consumer_links = tuple(
        (name, CONSUMER_ATTACHMENT[name], CONSUMER_LINK_BANDWIDTH, CONSUMER_LINK_DELAY)
        for name in consumers
    )
    return BACKBONE_LINKS + consumer_links + PRODUCER_LINKS


def common_links() -> Tuple[Tuple[str, str, int, str], ...]:
    """Links that do not depend on the consumer population."""
    return BACKBONE_LINKS + PRODUCER_LINKS


def smoke_schedule(warmup_s: float, tail_s: float) -> Dict[str, object]:
    """One handoff, acc2 to acc3, with the supplied warm-up and observation intervals."""
    if warmup_s < 0 or tail_s < 0:
        raise Exp2ConfigError("smoke intervals must be non-negative")
    return {
        "mode": "smoke",
        "handoff_count": 1,
        "sequence": SMOKE_HANDOFF_SEQUENCE,
        "intervals_s": (float(warmup_s), float(tail_s)),
        "initial_attachment": INITIAL_ATTACHMENT,
    }


def full_schedule() -> Dict[str, object]:
    """Eight-handoff producer sequence. Intervals are sampled by the driver."""
    return {
        "mode": "full",
        "handoff_count": 8,
        "sequence": FULL_HANDOFF_SEQUENCE,
        "intervals_s": None,
        "initial_attachment": INITIAL_ATTACHMENT,
    }


def schedule_for(mode: str, warmup_s: float, tail_s: float) -> Dict[str, object]:
    if mode == "smoke":
        return smoke_schedule(warmup_s, tail_s)
    if mode == "full":
        return full_schedule()
    raise Exp2ConfigError(f"EXP2_SCHEDULE must be smoke or full; got {mode!r}")


def application_hosts(consumers: Sequence[str]) -> Tuple[str, ...]:
    population_of(consumers)
    return (PRODUCER_HOST,) + tuple(consumers)


def guard_daemon_hosts(consumers: Sequence[str]) -> Tuple[str, ...]:
    """Producer daemon plus one consumer-role daemon on each instantiated consumer."""
    return application_hosts(consumers)


def topology_text(
    consumers: Sequence[str],
    sequence: Sequence[str] = FULL_HANDOFF_SEQUENCE,
    pattern: str = "shared",
) -> str:
    """Record only hosts and links that this population instantiates."""
    pattern = parse_demand_pattern(pattern)
    hosts = physical_hosts(consumers)
    mapping = stream_mapping(pattern, consumers)
    lines = [
        "experiment=exp2-shared" if pattern == "shared" else "experiment=exp2-distinct",
        f"exp2_campaign={campaign_id_for(pattern)}",
        f"demand_pattern={pattern}",
        f"population={population_of(consumers)}",
        f"physical_node_count={len(hosts)}",
        "physical_nodes=" + ",".join(hosts),
        "advertised_prefix=" + ADVERTISED_PREFIX,
        "stream_prefix=" + (STREAM_PREFIX if pattern == "shared" else "per-consumer"),
        "stream_map=" + format_stream_map(mapping),
        "guard_name=" + GUARD_NAME,
        "nlsr_hosts=" + ",".join(nlsr_hosts(consumers)),
        "capture_nodes=" + ",".join(capture_nodes(consumers)),
        "active_consumers=" + ",".join(consumers),
        "application_hosts=" + ",".join(application_hosts(consumers)),
        "guard_daemon_hosts=" + ",".join(guard_daemon_hosts(consumers)),
        "producer_initial_attachment=" + INITIAL_ATTACHMENT,
        "producer_attachments=" + ",".join(PRODUCER_ATTACHMENTS),
        "handoff_sequence=" + ",".join(sequence),
    ]
    for host in consumers:
        lines.append(f"attachment {host} {CONSUMER_ATTACHMENT[host]}")
        lines.append(f"stream {host} {mapping[host]}")
    for left, right, bandwidth, delay in links(consumers):
        lines.append(f"link {left} {right} bw_mbps={bandwidth} delay={delay}")
    return "\n".join(lines) + "\n"


def campaign_text(
    consumers: Sequence[str],
    mode: str,
    run_id: str,
    pattern: str = "shared",
) -> str:
    pattern = parse_demand_pattern(pattern)
    hosts = physical_hosts(consumers)
    mapping = stream_mapping(pattern, consumers)
    return (
        f"exp2_campaign={campaign_id_for(pattern)}\n"
        f"demand_pattern={pattern}\n"
        f"population={population_of(consumers)}\n"
        f"schedule={mode}\n"
        f"run_id={run_id}\n"
        f"physical_node_count={len(hosts)}\n"
        "physical_nodes=" + ",".join(hosts) + "\n"
        f"advertised_prefix={ADVERTISED_PREFIX}\n"
        f"guard_name={GUARD_NAME}\n"
        f"stream_map={format_stream_map(mapping)}\n"
    )


def result_names(consumers: Sequence[str]) -> List[str]:
    """Paths relative to one run directory that a completed run must contain."""
    names = [
        "campaign.txt",
        "params.txt",
        "handoffs.txt",
        "topology.txt",
        "producer.log",
        "optoflood_producer.log",
    ]
    for consumer in consumers:
        names.append(f"{consumer}.log")
        names.append(f"optoflood_{consumer}.log")
    for node in capture_nodes(consumers):
        names.append(f"pcap_nodes/{node}.pcap")
        names.append(f"tcpdump_{node}.log")
        names.append(f"minindn-logs/{node}/nfd.log")
        names.append(f"minindn-logs/{node}/nlsr.log")
    return names


def missing_evidence(run_dir: Path, consumers: Sequence[str]) -> List[str]:
    missing = []
    for name in result_names(consumers):
        if not (run_dir / name).is_file():
            missing.append(name)
    return missing


def recorded_run_id(mode: str, text: str) -> str:
    """Full runs require r1..r5. A smoke run is recorded as smoke."""
    token = (text or "").strip().lower()
    if mode == "full":
        return parse_run_id(token)
    if token in {"", "smoke"}:
        return "smoke"
    raise Exp2ConfigError(f"EXP2_RUN_ID for smoke must be empty or smoke; got {text!r}")


def parse_run_id(text: str) -> str:
    token = (text or "").strip().lower()
    if token not in FULL_RUN_IDS:
        raise Exp2ConfigError(f"EXP2_RUN_ID must be one of {', '.join(FULL_RUN_IDS)}; got {text!r}")
    return token


def _population_name(population: str) -> str:
    token = (population or "").strip().lower()
    if token not in POPULATIONS:
        raise Exp2ConfigError(f"population must be n2 or n4; got {population!r}")
    return token


def full_run_directory(root: str, population: str, run_id: str) -> str:
    """Full-schedule directory. It is not the smoke directory for that population."""
    population = _population_name(population)
    run_id = parse_run_id(run_id)
    return f"{root.rstrip('/')}/{population}/{run_id}"


def smoke_directory(root: str, population: str) -> str:
    population = _population_name(population)
    return f"{root.rstrip('/')}/{population}/smoke"


def directory_has_entries(run_dir: Path) -> bool:
    """True when a directory already holds files and must not be replaced."""
    if not run_dir.is_dir():
        return False
    return any(run_dir.iterdir())


def topology_position(consumer: str, from_node: str, to_node: str) -> str:
    """Classify one handoff relative to that consumer's access router."""
    access = CONSUMER_ATTACHMENT.get(consumer)
    if access is None:
        raise Exp2ConfigError(f"unknown consumer: {consumer}")
    if from_node == access and to_node == access:
        return "resides_at_consumer_access"
    if to_node == access:
        return "moves_onto_consumer_access"
    if from_node == access:
        return "moves_away_from_consumer_access"
    return "other_attachment"


def read_active_consumers(params_path: Path) -> Tuple[str, ...]:
    text = ""
    for line in params_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("exp2_active_consumers="):
            text = line.split("=", 1)[1]
    if not text:
        raise Exp2ConfigError(f"{params_path} has no exp2_active_consumers")
    return parse_active_consumers(text)


def _read_assignments(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.startswith("attachment ") or line.startswith("link "):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip()
    return values


def _log_seconds(raw: int) -> float:
    if raw > 10**14:
        return raw / 1e9
    if raw > 10**11:
        return raw / 1e6
    return float(raw)


def _handoff_rows(path: Path) -> List[Tuple[str, str, str, str]]:
    rows: List[Tuple[str, str, str, str]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.startswith("index"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        rows.append((parts[0], parts[1], parts[3], parts[4]))
    return rows


def _file_problem(path: Path, label: str, nonempty: bool) -> str:
    if not path.is_file():
        return f"missing {label}: {path}"
    if nonempty and path.stat().st_size <= 0:
        return f"empty {label}: {path}"
    return ""


def _pcap_problem(path: Path) -> str:
    if not path.is_file():
        return f"missing pcap: {path}"
    size = path.stat().st_size
    if size <= 24:
        return f"pcap has no packets: {path} ({size} bytes)"
    return ""


def _pattern_vote(source: Mapping[str, str]) -> Optional[str]:
    token = (source.get("exp2_demand_pattern") or source.get("demand_pattern") or "").strip()
    campaign_name = (source.get("exp2_campaign") or "").strip()
    label = (source.get("exp2_experiment") or source.get("experiment") or "").strip()
    votes = []
    if token:
        votes.append(parse_demand_pattern(token))
    if campaign_name == SHARED_CAMPAIGN_ID:
        votes.append("shared")
    elif campaign_name == DISTINCT_CAMPAIGN_ID:
        votes.append("distinct")
    if label in {"shared", "exp2-shared"}:
        votes.append("shared")
    elif label in {"distinct", "exp2-distinct"}:
        votes.append("distinct")
    elif label:
        raise Exp2ConfigError(f"unknown Exp2 experiment label {label!r}")
    if not votes:
        return None
    if len(set(votes)) != 1:
        raise Exp2ConfigError("demand pattern records disagree: " + ",".join(votes))
    return votes[0]


def recorded_demand_pattern(
    params: Mapping[str, str],
    campaign: Mapping[str, str],
    topology: Mapping[str, str],
) -> str:
    """Infer one demand pattern. Shared and Distinct records must not be mixed."""
    votes = []
    for source in (params, campaign, topology):
        vote = _pattern_vote(source)
        if vote is not None:
            votes.append(vote)
    if not votes:
        raise Exp2ConfigError("demand pattern is not recorded")
    if len(set(votes)) != 1:
        raise Exp2ConfigError("Shared and Distinct records disagree: " + ",".join(votes))
    return votes[0]


def _content_name(name: str, prefix: str) -> bool:
    """True when name is content under prefix, not that stream's discovery name."""
    if not name.startswith(prefix + "/"):
        return False
    remainder = name[len(prefix) + 1:]
    return remainder != "_meta" and not remainder.startswith("_meta/")


def _log_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _smoke_reception_problems(run_dir: Path, consumers: Sequence[str], handoff_time: float) -> List[str]:
    problems = []
    for consumer in consumers:
        log_path = run_dir / f"{consumer}.log"
        if not log_path.is_file():
            problems.append(f"missing consumer log for smoke reception check: {log_path}")
            continue
        data_after = False
        validate_after = False
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            data_match = _DATA_LINE.match(line.strip())
            if data_match and _log_seconds(int(data_match.group(1))) > handoff_time:
                data_after = True
            validate_match = _VALIDATE_LINE.match(line.strip())
            if not validate_match:
                continue
            if _log_seconds(int(validate_match.group(1))) <= handoff_time:
                continue
            identity = validate_match.group(3) or ""
            name = validate_match.group(2) or ""
            if identity == consumer and "/LiveStream/" in name:
                validate_after = True
        if not data_after:
            problems.append(f"{consumer} has no content Data after the smoke handoff")
        if not validate_after:
            problems.append(f"{consumer} has no successful content validation after the smoke handoff")
    return problems


def _map_problems(label: str, text: str, expected: Mapping[str, str], required: bool) -> List[str]:
    if not text:
        if required:
            return [f"{label} has no stream_map"]
        return []
    try:
        recorded = parse_stream_map(text)
    except Exp2ConfigError as error:
        return [f"{label} {error}"]
    if recorded != dict(expected):
        return [f"{label} stream_map must be {format_stream_map(expected)}; got {text!r}"]
    return []


def _distinct_metadata_problems(
    params: Mapping[str, str],
    campaign: Mapping[str, str],
    topology: Mapping[str, str],
    topology_body: str,
    consumers: Sequence[str],
) -> List[str]:
    problems = []
    expected = stream_mapping("distinct", consumers)
    problems.extend(_map_problems("params.txt", params.get("exp2_stream_map", ""), expected, True))
    problems.extend(_map_problems("campaign.txt", campaign.get("stream_map", ""), expected, True))
    problems.extend(_map_problems("topology.txt", topology.get("stream_map", ""), expected, True))
    for consumer, prefix in expected.items():
        if f"stream {consumer} {prefix}" not in topology_body.splitlines():
            problems.append(f"missing stream {consumer} {prefix}")
    single = params.get("exp2_stream_prefix", "")
    if single and single != "per-consumer":
        problems.append(
            f"distinct run must not record one stream prefix; got exp2_stream_prefix={single!r}"
        )
    if params.get("exp2_advertised_prefix") != ADVERTISED_PREFIX or topology.get("advertised_prefix") != ADVERTISED_PREFIX:
        problems.append(f"advertised prefix must be {ADVERTISED_PREFIX}")
    if params.get("exp2_guard_name") != GUARD_NAME or topology.get("guard_name") != GUARD_NAME:
        problems.append(f"guard name must be {GUARD_NAME}")
    if campaign.get("advertised_prefix") not in {"", ADVERTISED_PREFIX}:
        problems.append(f"campaign advertised prefix must be {ADVERTISED_PREFIX}")
    if campaign.get("guard_name") not in {"", GUARD_NAME}:
        problems.append(f"campaign guard name must be {GUARD_NAME}")
    for forbidden in PER_STREAM_GUARD_NAMES:
        if forbidden in topology_body:
            problems.append(f"topology records per-stream guard {forbidden}")
    required_settings = {
        "window_frames": "4",
        "guard_interval_ms": "1000",
        "neighbors.result-driven-adj-lsa-build": "on",
        "neighbors.event-driven-adjacency-verification": "on",
        "neighbors.corridor-prioritised-routing": "on",
        "neighbors.corridor-adj-lsa-sync-publish-delay": "1",
        "neighbors.event-driven-verification-timeout-ms": "50",
    }
    for key, expected_value in required_settings.items():
        if params.get(key) != expected_value:
            problems.append(f"{key} must be {expected_value}; got {params.get(key)!r}")
    return problems


def _smoke_distinct_problems(run_dir: Path, consumers: Sequence[str], handoff_time: float) -> List[str]:
    """Smoke evidence that each active consumer used its own stream after the handoff."""
    problems = []
    mapping = stream_mapping("distinct", consumers)
    for consumer, prefix in mapping.items():
        log_path = run_dir / f"{consumer}.log"
        text = _log_text(log_path)
        if not text:
            problems.append(f"missing consumer log for smoke reception check: {log_path}")
            continue
        data_after = False
        assigned_after = False
        for line in text.splitlines():
            data_match = _DATA_LINE.match(line.strip())
            if data_match and _log_seconds(int(data_match.group(1))) > handoff_time:
                data_after = True
            validate_match = _VALIDATE_LINE.match(line.strip())
            if not validate_match or _log_seconds(int(validate_match.group(1))) <= handoff_time:
                continue
            identity = validate_match.group(3) or ""
            name = validate_match.group(2) or ""
            if identity != consumer:
                continue
            if _content_name(name, prefix):
                assigned_after = True
            elif name.startswith("/LiveStream/"):
                problems.append(
                    f"{consumer} validated {name}, which is not its assigned stream {prefix}"
                )
        if not data_after:
            problems.append(f"{consumer} has no content Data after the smoke handoff")
        if not assigned_after:
            problems.append(
                f"{consumer} has no successful validation of {prefix} after the smoke handoff"
            )
    producer_text = _log_text(run_dir / "producer.log")
    if not producer_text:
        problems.append(f"missing producer log: {run_dir / 'producer.log'}")
    else:
        registered = _REGISTERED_PREFIX.findall(producer_text)
        if not registered or any(name != ADVERTISED_PREFIX for name in registered):
            problems.append(
                f"producer must register only {ADVERTISED_PREFIX}; got {registered or ['none']}"
            )
        interests = {
            name for stamp, name in _PRODUCER_INTEREST_LINE.findall(producer_text)
            if _log_seconds(int(stamp)) > handoff_time and _content_name_any(name, mapping)
        }
        sent = {
            name for stamp, name in _PRODUCER_DATA_LINE.findall(producer_text)
            if _log_seconds(int(stamp)) > handoff_time and _content_name_any(name, mapping)
        }
        for prefix in mapping.values():
            if not any(_content_name(name, prefix) for name in interests):
                problems.append(f"producer log has no post-handoff content Interest for {prefix}")
            if not any(_content_name(name, prefix) for name in sent):
                problems.append(f"producer log has no post-handoff content Data for {prefix}")
    problems.extend(_guard_namespace_problems(run_dir, consumers))
    return problems


def _content_name_any(name: str, mapping: Mapping[str, str]) -> bool:
    return any(_content_name(name, prefix) for prefix in mapping.values())


def _guard_namespace_problems(run_dir: Path, consumers: Sequence[str]) -> List[str]:
    problems = []
    logs = [run_dir / "optoflood_producer.log"]
    logs.extend(run_dir / f"optoflood_{consumer}.log" for consumer in consumers)
    logs.append(run_dir / "producer.log")
    for path in logs:
        text = _log_text(path)
        for forbidden in PER_STREAM_GUARD_NAMES:
            if forbidden in text:
                problems.append(f"{path.name} records per-stream guard {forbidden}")
    producer_daemon = _log_text(run_dir / "optoflood_producer.log")
    registered = _GUARD_PREFIX.findall(producer_daemon)
    if not registered or any(name != GUARD_NAME for name in registered):
        problems.append(
            f"producer daemon must register only {GUARD_NAME}; got {registered or ['none']}"
        )
    if "prefix=/LiveStream " not in producer_daemon:
        problems.append("producer daemon startup prefix must be /LiveStream")
    for consumer in consumers:
        text = _log_text(run_dir / f"optoflood_{consumer}.log")
        names = _GUARD_CONSUMER_NAME.findall(text)
        if not names or any(name != GUARD_NAME for name in names):
            problems.append(
                f"{consumer} daemon must request only {GUARD_NAME}; got {names or ['none']}"
            )
        if "prefix=/LiveStream " not in text:
            problems.append(f"{consumer} daemon startup prefix must be /LiveStream")
    return problems


def inspect_run(run_dir: Path, expected_pattern: Optional[str] = None) -> List[str]:
    """Return evidence problems. An empty list means the run directory is consistent."""
    problems: List[str] = []
    params = _read_assignments(run_dir / "params.txt")
    campaign = _read_assignments(run_dir / "campaign.txt")
    topology_fields = _read_assignments(run_dir / "topology.txt")
    if not params:
        problems.append(f"missing or unreadable params.txt: {run_dir / 'params.txt'}")
        return problems
    try:
        consumers = parse_active_consumers(params.get("exp2_active_consumers", ""))
    except Exp2ConfigError as error:
        problems.append(str(error))
        return problems
    population = population_of(consumers)
    hosts = physical_hosts(consumers)
    mode = params.get("exp2_schedule", "")
    if mode not in {"smoke", "full"}:
        problems.append(f"exp2_schedule must be smoke or full; got {mode!r}")
    try:
        pattern = recorded_demand_pattern(params, campaign, topology_fields)
    except Exp2ConfigError as error:
        problems.append(str(error))
        return problems
    if expected_pattern is not None:
        try:
            demanded = parse_demand_pattern(expected_pattern)
        except Exp2ConfigError as error:
            problems.append(str(error))
            return problems
        if pattern != demanded:
            problems.append(f"demand pattern must be {demanded}; recorded {pattern}")
            return problems
    expected_campaign = campaign_id_for(pattern)
    if params.get("exp2_campaign") != expected_campaign or campaign.get("exp2_campaign") != expected_campaign:
        problems.append(
            f"campaign id must be {expected_campaign}; params={params.get('exp2_campaign')!r} "
            f"campaign.txt={campaign.get('exp2_campaign')!r}"
        )
    if campaign.get("population") != population or topology_fields.get("population") != population:
        problems.append(
            f"population mismatch: expected {population}, "
            f"campaign.txt={campaign.get('population')!r}, topology={topology_fields.get('population')!r}"
        )
    recorded_hosts = tuple(item for item in campaign.get("physical_nodes", "").split(",") if item)
    topology_hosts = tuple(item for item in topology_fields.get("physical_nodes", "").split(",") if item)
    if recorded_hosts != hosts or topology_hosts != hosts:
        problems.append(
            f"physical nodes must be {','.join(hosts)}; "
            f"campaign={','.join(recorded_hosts)}; topology={','.join(topology_hosts)}"
        )
    if str(len(hosts)) != campaign.get("physical_node_count") or str(len(hosts)) != topology_fields.get("physical_node_count"):
        problems.append(f"physical node count must be {len(hosts)}")
    if population == "n2":
        for forbidden in ("consumer3", "consumer4"):
            if forbidden in hosts or forbidden in topology_fields.get("physical_nodes", ""):
                problems.append(f"N=2 must not instantiate {forbidden}")
            if (run_dir / "pcap_nodes" / f"{forbidden}.pcap").exists():
                problems.append(f"N=2 contains unexpected {forbidden} capture")
            if (run_dir / f"{forbidden}.log").exists():
                problems.append(f"N=2 contains unexpected {forbidden} application log")
    topology_text_body = (run_dir / "topology.txt").read_text(encoding="utf-8", errors="replace") if (run_dir / "topology.txt").is_file() else ""
    for consumer in consumers:
        expected = f"attachment {consumer} {CONSUMER_ATTACHMENT[consumer]}"
        if expected not in topology_text_body.splitlines():
            problems.append(f"missing {expected}")
    for absent in CONSUMER_CATALOGUE:
        if absent in consumers:
            continue
        if f"attachment {absent} " in topology_text_body:
            problems.append(f"{population} topology lists absent consumer {absent}")
    expected_count = 1 if mode == "smoke" else 8 if mode == "full" else -1
    expected_sequence = SMOKE_HANDOFF_SEQUENCE if mode == "smoke" else FULL_HANDOFF_SEQUENCE
    if params.get("handoff_sequence") != ",".join(expected_sequence):
        problems.append(
            f"handoff_sequence must be {','.join(expected_sequence)}; got {params.get('handoff_sequence')!r}"
        )
    if params.get("handoff_count") != str(expected_count):
        problems.append(f"handoff_count must be {expected_count}; got {params.get('handoff_count')!r}")
    rows = _handoff_rows(run_dir / "handoffs.txt")
    if expected_count >= 0 and len(rows) != expected_count:
        problems.append(f"handoffs.txt has {len(rows)} rows; expected {expected_count}")
    for index, (_number, _stamp, source, destination) in enumerate(rows):
        if index + 1 >= len(expected_sequence):
            break
        if source != expected_sequence[index] or destination != expected_sequence[index + 1]:
            problems.append(
                f"handoff {index + 1} is {source}->{destination}; "
                f"expected {expected_sequence[index]}->{expected_sequence[index + 1]}"
            )
    realized = [item for item in params.get("exp2_realized_intervals_s", "").split(",") if item]
    if expected_count >= 0 and len(realized) != expected_count + 1:
        problems.append(
            f"expected {expected_count + 1} realised intervals including the final observation; got {len(realized)}"
        )
    if mode == "full":
        if params.get("exp2_interval_source") != "sampled":
            problems.append("full run must record sampled intervals")
        if params.get("handoff_interval_base_s") not in {"90", "90.0", "90.000"}:
            problems.append(f"full-run base interval must be 90; got {params.get('handoff_interval_base_s')!r}")
        if params.get("handoff_interval_jitter_s") not in {"60", "60.0", "60.000"}:
            problems.append(f"full-run jitter must be 60; got {params.get('handoff_interval_jitter_s')!r}")
    if params.get("request_interval_ms") != "20":
        problems.append(f"request_interval_ms must be 20; got {params.get('request_interval_ms')!r}")
    if params.get("segments_per_frame") != "1":
        problems.append(f"segments_per_frame must be 1; got {params.get('segments_per_frame')!r}")
    if pattern == "shared":
        if params.get("exp2_stream_prefix") != STREAM_PREFIX or params.get("exp2_advertised_prefix") != ADVERTISED_PREFIX:
            problems.append("stream or advertised prefix does not match the shared LiveStream configuration")
        if params.get("exp2_guard_name") != GUARD_NAME:
            problems.append(f"guard name must be {GUARD_NAME}; got {params.get('exp2_guard_name')!r}")
        shared_map = stream_mapping("shared", consumers)
        problems.extend(_map_problems("params.txt", params.get("exp2_stream_map", ""), shared_map, False))
        problems.extend(_map_problems("campaign.txt", campaign.get("stream_map", ""), shared_map, False))
        problems.extend(_map_problems("topology.txt", topology_fields.get("stream_map", ""), shared_map, False))
    else:
        problems.extend(_distinct_metadata_problems(
            params, campaign, topology_fields, topology_text_body, consumers,
        ))
    for name in result_names(consumers):
        path = run_dir / name
        if name.endswith(".pcap"):
            problem = _pcap_problem(path)
        elif name.startswith("tcpdump_"):
            problem = _file_problem(path, name, nonempty=False)
        else:
            problem = _file_problem(path, name, nonempty=True)
        if problem:
            problems.append(problem)
    if mode == "smoke" and rows:
        try:
            handoff_time = float(rows[0][1])
        except ValueError:
            problems.append(f"smoke handoff timestamp is not numeric: {rows[0][1]!r}")
        else:
            if pattern == "distinct":
                problems.extend(_smoke_distinct_problems(run_dir, consumers, handoff_time))
            else:
                problems.extend(_smoke_reception_problems(run_dir, consumers, handoff_time))
    return problems
