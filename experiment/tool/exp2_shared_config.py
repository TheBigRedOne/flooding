"""Exp2-A shared-stream deployment record. No Mini-NDN import.

N=2 and N=4 are the supported populations. N=1 remains the completed Solution
experiment and is not an Exp2 population. Absent consumers are not instantiated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

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


def topology_text(consumers: Sequence[str], sequence: Sequence[str] = FULL_HANDOFF_SEQUENCE) -> str:
    """Record only hosts and links that this population instantiates."""
    hosts = physical_hosts(consumers)
    lines = [
        "experiment=exp2-shared",
        f"exp2_campaign={CAMPAIGN_ID}",
        f"population={population_of(consumers)}",
        f"physical_node_count={len(hosts)}",
        "physical_nodes=" + ",".join(hosts),
        "advertised_prefix=" + ADVERTISED_PREFIX,
        "stream_prefix=" + STREAM_PREFIX,
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
    for left, right, bandwidth, delay in links(consumers):
        lines.append(f"link {left} {right} bw_mbps={bandwidth} delay={delay}")
    return "\n".join(lines) + "\n"


def campaign_text(consumers: Sequence[str], mode: str, run_id: str) -> str:
    hosts = physical_hosts(consumers)
    return (
        f"exp2_campaign={CAMPAIGN_ID}\n"
        f"population={population_of(consumers)}\n"
        f"schedule={mode}\n"
        f"run_id={run_id}\n"
        f"physical_node_count={len(hosts)}\n"
        "physical_nodes=" + ",".join(hosts) + "\n"
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


def inspect_run(run_dir: Path) -> List[str]:
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
    if params.get("exp2_campaign") != CAMPAIGN_ID or campaign.get("exp2_campaign") != CAMPAIGN_ID:
        problems.append(
            f"campaign id must be {CAMPAIGN_ID}; params={params.get('exp2_campaign')!r} "
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
    if params.get("exp2_stream_prefix") != STREAM_PREFIX or params.get("exp2_advertised_prefix") != ADVERTISED_PREFIX:
        problems.append("stream or advertised prefix does not match the shared LiveStream configuration")
    if params.get("exp2_guard_name") != GUARD_NAME:
        problems.append(f"guard name must be {GUARD_NAME}; got {params.get('exp2_guard_name')!r}")
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
            problems.extend(_smoke_reception_problems(run_dir, consumers, handoff_time))
    return problems
