"""Exp2-A shared-stream deployment record. No Mini-NDN import.

Later extended scenarios can add their own records beside this module.
This file describes the one shared-stream scenario that is implemented now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROUTING_NODES: Tuple[str, ...] = (
    "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
CONSUMER_HOSTS: Tuple[str, ...] = ("consumer1", "consumer2")
PRODUCER_HOST = "producer"
NLSR_HOSTS: Tuple[str, ...] = ROUTING_NODES + (PRODUCER_HOST,) + CONSUMER_HOSTS
CAPTURE_NODES: Tuple[str, ...] = NLSR_HOSTS

CONSUMER_ATTACHMENT = {
    "consumer1": "acc1",
    "consumer2": "acc4",
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

# (left, right, bandwidth Mbps, delay)
LINKS: Tuple[Tuple[str, str, int, str], ...] = (
    ("core", "agg1", 1000, "1ms"),
    ("core", "agg2", 1000, "1ms"),
    ("agg1", "acc1", 500, "5ms"),
    ("agg1", "acc2", 500, "5ms"),
    ("agg1", "acc3", 500, "5ms"),
    ("agg2", "acc4", 500, "5ms"),
    ("agg2", "acc5", 500, "5ms"),
    ("agg2", "acc6", 500, "5ms"),
    ("consumer1", "acc1", 100, "5ms"),
    ("consumer2", "acc4", 100, "5ms"),
    ("producer", "acc2", 100, "5ms"),
    ("producer", "acc3", 100, "5ms"),
    ("producer", "acc4", 100, "5ms"),
    ("producer", "acc5", 100, "5ms"),
    ("producer", "acc6", 100, "5ms"),
)


class Exp2ConfigError(ValueError):
    """Raised when an Exp2-A configuration cannot be run."""


def parse_active_consumers(text: str) -> Tuple[str, ...]:
    """Return the consumers that run an application and a guard daemon.

    N=1 is consumer1 only. N=2 is both hosts. The physical topology always
    contains both hosts.
    """
    token = (text or "").strip().lower()
    if token in {"1", "n1", "consumer1"}:
        return ("consumer1",)
    if token in {"2", "n2", "consumer1,consumer2"}:
        return ("consumer1", "consumer2")
    raise Exp2ConfigError(
        "EXP2_ACTIVE_CONSUMERS must be consumer1 (N=1) or consumer1,consumer2 (N=2); "
        f"got {text!r}"
    )


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
    """Eight-handoff producer sequence. Intervals are supplied by the caller."""
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


def application_hosts(active_consumers: Sequence[str]) -> Tuple[str, ...]:
    return (PRODUCER_HOST,) + tuple(active_consumers)


def guard_daemon_hosts(active_consumers: Sequence[str]) -> Tuple[str, ...]:
    """Producer daemon plus one consumer-role daemon on each active consumer."""
    return application_hosts(active_consumers)


def topology_text(active_consumers: Sequence[str]) -> str:
    """Placement record. Both consumer hosts are listed whether or not they run an application."""
    lines = [
        "experiment=exp2-shared",
        "advertised_prefix=" + ADVERTISED_PREFIX,
        "stream_prefix=" + STREAM_PREFIX,
        "guard_name=" + GUARD_NAME,
        "nlsr_hosts=" + ",".join(NLSR_HOSTS),
        "active_consumers=" + ",".join(active_consumers),
        "inactive_consumers=" + ",".join(
            host for host in CONSUMER_HOSTS if host not in active_consumers
        ),
        "producer_initial_attachment=" + INITIAL_ATTACHMENT,
        "producer_attachments=" + ",".join(PRODUCER_ATTACHMENTS),
    ]
    for host, access in CONSUMER_ATTACHMENT.items():
        lines.append(f"attachment {host} {access}")
    for left, right, bandwidth, delay in LINKS:
        lines.append(f"link {left} {right} bw_mbps={bandwidth} delay={delay}")
    return "\n".join(lines) + "\n"


def result_names(active_consumers: Sequence[str]) -> List[str]:
    """Paths relative to the run directory that a completed run must contain."""
    names = [
        "params.txt",
        "handoffs.txt",
        "topology.txt",
        "producer.log",
        "optoflood_producer.log",
    ]
    for consumer in active_consumers:
        names.append(f"{consumer}.log")
        names.append(f"optoflood_{consumer}.log")
    for node in CAPTURE_NODES:
        names.append(f"pcap_nodes/{node}.pcap")
    for node in NLSR_HOSTS:
        names.append(f"minindn-logs/{node}/nfd.log")
        names.append(f"minindn-logs/{node}/nlsr.log")
    return names


def missing_evidence(run_dir: Path, active_consumers: Sequence[str]) -> List[str]:
    missing = []
    for name in result_names(active_consumers):
        if not (run_dir / name).is_file():
            missing.append(name)
    return missing


def recorded_run_id(mode: str, text: str) -> str:
    """Full runs require r1..r5. Smoke may omit the id."""
    token = (text or "").strip().lower()
    if mode == "full":
        return parse_run_id(token)
    if token and token not in FULL_RUN_IDS:
        raise Exp2ConfigError(f"EXP2_RUN_ID must be empty or one of {', '.join(FULL_RUN_IDS)}; got {text!r}")
    return token


def parse_run_id(text: str) -> str:
    token = (text or "").strip().lower()
    if token not in FULL_RUN_IDS:
        raise Exp2ConfigError(f"EXP2_RUN_ID must be one of {', '.join(FULL_RUN_IDS)}; got {text!r}")
    return token


def full_run_directory(root: str, population: str, run_id: str) -> str:
    """Full-schedule directory. It is not the smoke directory for that population."""
    if population not in {"n1", "n2"}:
        raise Exp2ConfigError(f"population must be n1 or n2; got {population!r}")
    run_id = parse_run_id(run_id)
    return f"{root.rstrip('/')}/{population}/{run_id}"


def smoke_directory(root: str, population: str) -> str:
    if population not in {"n1", "n2"}:
        raise Exp2ConfigError(f"population must be n1 or n2; got {population!r}")
    return f"{root.rstrip('/')}/{population}"


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
