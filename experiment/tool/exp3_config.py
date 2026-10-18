"""Exp3 multi-producer deployment record. No Mini-NDN import.

P=1, P=2, and P=4 each instantiate that many Producer-Consumer pairs.
Schedules for one producer depend only on the run seed and that producer index.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import List, Mapping, Sequence, Tuple

ROUTING_NODES: Tuple[str, ...] = (
    "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
MOBILITY_ACCESSES: Tuple[str, ...] = ("acc2", "acc3", "acc4", "acc5", "acc6")
CONSUMER_ATTACHMENT = {
    "consumer1": "acc1",
    "consumer2": "acc4",
    "consumer3": "acc3",
    "consumer4": "acc6",
}
SEQUENCES = {
    1: ("acc2", "acc3", "acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2"),
    2: ("acc5", "acc6", "acc5", "acc4", "acc3", "acc2", "acc3", "acc4", "acc5"),
    3: ("acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2", "acc3", "acc4"),
    4: ("acc3", "acc4", "acc5", "acc6", "acc5", "acc4", "acc3", "acc2", "acc3"),
}
PREFIXES = {
    1: "/LiveStream/v0",
    2: "/LiveStream/v1",
    3: "/LiveStream/v2",
    4: "/LiveStream/v3",
}
RUN_IDS = ("r1", "r2", "r3", "r4", "r5")
INTERVAL_BASE_S = 90.0
INTERVAL_JITTER_S = 60.0
FRAME_PERIOD_MS = 20
MGMT_IDENTITY = "/localhost/optoflood"
LEGACY_TRUST_ANCHOR = "/home/vagrant/flooding/experiment/app/livestream-trust-anchor.cert"
LEGACY_TRUST_SCHEMA = "/home/vagrant/flooding/experiment/app/trust-schema.conf"
CAMPAIGN_ID = "exp3-independent"
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
EDGE_BANDWIDTH = 100
EDGE_DELAY = "5ms"
SHARED_FORWARDERS = ("core", "agg1", "agg2")
SMOKE_WARMUP_S = 20.0
SMOKE_TAIL_S = 30.0


class Exp3ConfigError(ValueError):
    """Raised when an Exp3 configuration cannot be run or checked."""


class Pair:
    def __init__(self, index: int) -> None:
        if index not in SEQUENCES:
            raise Exp3ConfigError(f"producer index must be 1..4; got {index}")
        self.index = index
        self.producer = f"producer{index}"
        self.consumer = f"consumer{index}"
        self.prefix = PREFIXES[index]
        self.guard = f"{self.prefix}/_guard"
        self.identity = self.prefix
        self.attachment = CONSUMER_ATTACHMENT[self.consumer]
        self.sequence = SEQUENCES[index]
        self.initial = self.sequence[0]

    def smoke_handoff(self) -> Tuple[str, str]:
        return self.sequence[0], self.sequence[1]


def parse_population(text: str) -> int:
    token = (text or "").strip().lower()
    if token in {"1", "p1"}:
        return 1
    if token in {"2", "p2"}:
        return 2
    if token in {"4", "p4"}:
        return 4
    raise Exp3ConfigError(f"EXP3_POPULATION must be p1, p2, or p4; got {text!r}")


def pairs_for(population: int) -> Tuple[Pair, ...]:
    if population not in {1, 2, 4}:
        raise Exp3ConfigError(f"population must be 1, 2, or 4; got {population}")
    return tuple(Pair(index) for index in range(1, population + 1))


def physical_hosts(population: int) -> Tuple[str, ...]:
    selected = pairs_for(population)
    return ROUTING_NODES + tuple(pair.producer for pair in selected) + tuple(pair.consumer for pair in selected)


def expected_node_count(population: int) -> int:
    return {1: 11, 2: 13, 4: 17}[population]


def links(population: int) -> Tuple[Tuple[str, str, int, str], ...]:
    selected = pairs_for(population)
    consumer_links = tuple(
        (pair.consumer, pair.attachment, EDGE_BANDWIDTH, EDGE_DELAY) for pair in selected
    )
    producer_links = tuple(
        (pair.producer, access, EDGE_BANDWIDTH, EDGE_DELAY)
        for pair in selected
        for access in MOBILITY_ACCESSES
    )
    return BACKBONE_LINKS + consumer_links + producer_links


def run_seed_for(run_id: str, explicit: str = "") -> int:
    if explicit.strip():
        try:
            seed = int(explicit, 10)
        except ValueError as error:
            raise Exp3ConfigError(f"EXP3_RUN_SEED must be an integer; got {explicit!r}") from error
        if seed < 0:
            raise Exp3ConfigError("EXP3_RUN_SEED must be non-negative")
        return seed
    if run_id in RUN_IDS:
        return RUN_IDS.index(run_id) + 1
    if run_id == "smoke":
        return 0
    raise Exp3ConfigError(f"EXP3_RUN_ID must be smoke or r1..r5; got {run_id!r}")


def producer_seed(run_seed: int, producer_index: int) -> int:
    """Seed for one producer. It does not depend on which other producers exist."""
    mixed = (run_seed + 0x9E3779B9) & 0xFFFFFFFF
    mixed ^= (producer_index * 0x85EBCA6B) & 0xFFFFFFFF
    mixed = (mixed * 0x7FEB352D) & 0xFFFFFFFF
    mixed ^= mixed >> 15
    return mixed & 0xFFFFFFFF


def sample_intervals(run_seed: int, producer_index: int, count: int = 9) -> Tuple[float, ...]:
    if count != 9:
        raise Exp3ConfigError("a full producer schedule has nine intervals")
    generator = random.Random(producer_seed(run_seed, producer_index))
    return tuple(INTERVAL_BASE_S + generator.uniform(0.0, INTERVAL_JITTER_S) for _ in range(count))


def smoke_intervals() -> Tuple[float, ...]:
    return (SMOKE_WARMUP_S, SMOKE_TAIL_S)


def schedule_end(intervals: Sequence[float]) -> float:
    return float(sum(intervals))


def plan_events(
    selected: Sequence[Pair],
    schedules: Mapping[int, Sequence[float]],
    mode: str,
) -> Tuple[Tuple[float, int, int, str, str, float], ...]:
    """One timeline of mobility events for the active producers.

    Each event is (relative_time, producer_index, transition_index, old, new, interval).
    The last interval is the final observation tail and is not itself a handoff.
    Ordering depends only on time, then producer index, not on input order.
    """
    if mode not in {"smoke", "full"}:
        raise Exp3ConfigError(f"schedule mode must be smoke or full; got {mode!r}")
    planned = []
    for pair in selected:
        intervals = tuple(schedules[pair.index])
        sequence = pair.sequence[:2] if mode == "smoke" else pair.sequence
        expected = 2 if mode == "smoke" else 9
        if len(intervals) != expected or len(sequence) != expected:
            raise Exp3ConfigError(
                f"{pair.producer} {mode} schedule needs {expected} positions"
            )
        cursor = 0.0
        current = sequence[0]
        for index in range(1, len(sequence)):
            cursor += intervals[index - 1]
            nxt = sequence[index]
            planned.append((cursor, pair.index, index, current, nxt, intervals[index - 1]))
            current = nxt
    planned.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(planned)


def guard_flood_id(producer_index: int, sequence: int) -> int:
    if producer_index < 1 or producer_index > 4:
        raise Exp3ConfigError("producer index must be 1..4")
    if sequence < 1 or sequence > 0xFFFFFFFF:
        raise Exp3ConfigError("FloodId sequence must fit in 32 bits")
    return (producer_index << 32) | sequence


def identity_may_sign(identity: str, data_name: str) -> bool:
    """Mirror the trust-schema hyper-relation for one identity and Data name.

    The key name must be a prefix of the Data name with its last component removed.
    """
    parts = [part for part in data_name.split("/") if part]
    if len(parts) < 2:
        return False
    stripped = "/" + "/".join(parts[:-1])
    return stripped == identity or stripped.startswith(identity + "/")


def trust_schema_text(certificate_paths: Sequence[str]) -> str:
    if not certificate_paths:
        raise Exp3ConfigError("Exp3 trust schema requires at least one certificate")
    anchors = []
    for path in certificate_paths:
        if path == LEGACY_TRUST_ANCHOR:
            raise Exp3ConfigError("Exp3 must not use the legacy trust-anchor path")
        anchors.append(
            "trust-anchor\n{\n    type file\n    file-name \"" + path + "\"\n}\n"
        )
    return (
        "rule\n{\n"
        "    id \"Exp3 producer data\"\n"
        "    for data\n"
        "    filter\n"
        "    {\n"
        "        type name\n"
        "        name /LiveStream\n"
        "        relation is-prefix-of\n"
        "    }\n"
        "    checker\n"
        "    {\n"
        "        type customized\n"
        "        sig-type ecdsa-sha256\n"
        "        key-locator\n"
        "        {\n"
        "            type name\n"
        "            hyper-relation\n"
        "            {\n"
        "                k-regex ^(<>*)<KEY><><>?<>?$\n"
        "                k-expand \\\\1\n"
        "                h-relation is-prefix-of\n"
        "                p-regex ^(<>*)<>*$\n"
        "                p-expand \\\\1\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        + "\n".join(anchors)
    )


def topology_text(population: int) -> str:
    selected = pairs_for(population)
    hosts = physical_hosts(population)
    lines = [
        "experiment=exp3",
        f"exp3_campaign={CAMPAIGN_ID}",
        f"population=p{population}",
        f"physical_node_count={len(hosts)}",
        "physical_nodes=" + ",".join(hosts),
        "routing_nodes=" + ",".join(ROUTING_NODES),
    ]
    for pair in selected:
        lines.append(
            f"pair index={pair.index} producer={pair.producer} consumer={pair.consumer} "
            f"prefix={pair.prefix} guard={pair.guard} identity={pair.identity} "
            f"consumer_attachment={pair.attachment} initial={pair.initial} "
            f"sequence={','.join(pair.sequence)}"
        )
    for left, right, bandwidth, delay in links(population):
        lines.append(f"link {left} {right} bw_mbps={bandwidth} delay={delay}")
    return "\n".join(lines) + "\n"


def result_names(population: int) -> List[str]:
    names = [
        "campaign.txt",
        "params.txt",
        "handoffs.txt",
        "topology.txt",
        "schedules.txt",
        "observation_ends.txt",
        "process-health.txt",
        "trust-schema.conf",
    ]
    for pair in pairs_for(population):
        names.extend([
            f"{pair.producer}.log",
            f"{pair.consumer}.log",
            f"optoflood_{pair.producer}.log",
            f"optoflood_{pair.consumer}.log",
            f"certs/{pair.producer}.cert",
        ])
    for node in physical_hosts(population):
        names.extend([
            f"pcap_nodes/{node}.pcap",
            f"tcpdump_{node}.log",
            f"minindn-logs/{node}/nfd.log",
            f"minindn-logs/{node}/nlsr.log",
        ])
    return names
