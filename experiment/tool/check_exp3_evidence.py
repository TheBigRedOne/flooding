#!/usr/bin/env python3
"""Host-side Exp3 smoke evidence check. Does not start a VM."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import exp3_config as config
import exp3_processes as procs

_STARTUP = re.compile(r"STARTUP: OptoFlood daemon")
_REGISTERED = re.compile(r"Successfully registered prefix: (\S+)")
_ADVERTISED = re.compile(r"Advertising prefix via NLSR: (\S+)")
_GUARD_REGISTERED = re.compile(r"registered guard prefix (\S+)")
_FLOOD = re.compile(r"FloodId=(\d+)")
_VALIDATE = re.compile(
    r"^\[(\d+)\] VALIDATE: Data signature verified(?: name=(\S+))?(?: id=(\S+))?"
)
_DATA = re.compile(r"^\[(\d+)\].*\bDATA: frame=")
_TFIB = re.compile(r"TFIB update prefix=(\S+).*floodId=(\d+)")
_DEDUP = re.compile(r"dedup drop data=\S+ floodId=(\d+)")


def _assignments(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.startswith("link ") or line.startswith("pair "):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip()
    return values


def _seconds(raw: int) -> float:
    if raw > 10**14:
        return raw / 1e9
    if raw > 10**11:
        return raw / 1e6
    return float(raw)


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _handoffs(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.split("\t", 1)[0] == "producer":
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append({
            "producer": parts[0],
            "index": parts[1],
            "abs_time": parts[2],
            "rel_time": parts[3],
            "from_node": parts[4],
            "to_node": parts[5],
            "interval_s": parts[6],
        })
    return rows


def _daemon_alive(text: str, label: str) -> List[str]:
    problems = []
    startups = len(_STARTUP.findall(text))
    if startups != 1:
        problems.append(f"{label} has {startups} daemon STARTUP records; a restart is not a valid run")
    if "FATAL:" in text:
        problems.append(f"{label} contains a daemon FATAL record")
    return problems


def _app_fatal(text: str, label: str) -> List[str]:
    if "FATAL:" in text:
        return [f"{label} contains an application FATAL record"]
    return []


def _consumer_validated(log_text: str, consumer: str, prefix: str, handoff_time: float) -> bool:
    for line in log_text.splitlines():
        match = _VALIDATE.match(line.strip())
        if not match or _seconds(int(match.group(1))) <= handoff_time:
            continue
        name = match.group(2) or ""
        identity = match.group(3) or ""
        if identity == consumer and name.startswith(prefix + "/"):
            return True
    return False


def _foreign_validations(log_text: str, identity: str) -> List[str]:
    foreign = []
    for line in log_text.splitlines():
        match = _VALIDATE.match(line.strip())
        if not match:
            continue
        name = match.group(2) or ""
        if name and not config.identity_may_sign(identity, name):
            foreign.append(name)
    return foreign


def _shared_forwarding(run_dir: Path, prefix: str, flood_id: int, destination: str) -> List[str]:
    problems = []
    shared_hits = []
    destination_hits = []
    dedup_without_install = False
    installed = False
    for node in config.physical_hosts(4):
        text = _read(run_dir / "minindn-logs" / node / "nfd.log")
        if not text:
            continue
        updates = [
            (matched_prefix, int(matched_id))
            for matched_prefix, matched_id in _TFIB.findall(text)
        ]
        own_updates = [item for item in updates if item[0] == prefix and item[1] == flood_id]
        if own_updates:
            installed = True
            if node in config.SHARED_FORWARDERS:
                shared_hits.append(node)
            if node == destination:
                destination_hits.append(node)
        dropped = [int(item) for item in _DEDUP.findall(text)]
        if flood_id in dropped and not own_updates and node in config.SHARED_FORWARDERS:
            dedup_without_install = True
    if not installed:
        problems.append(f"no TFIB update for {prefix} floodId={flood_id}")
    if not shared_hits:
        problems.append(f"{prefix} guard flood was not installed on core or an aggregation router")
    if not destination_hits:
        problems.append(f"{prefix} guard flood was not installed on the new attachment {destination}")
    if dedup_without_install:
        problems.append(f"floodId={flood_id} was deduplicated on shared infrastructure before any TFIB update")
    return problems


def inspect_run(run_dir: Path) -> List[str]:
    problems: List[str] = []
    params = _assignments(run_dir / "params.txt")
    if not params:
        return [f"missing params.txt: {run_dir / 'params.txt'}"]
    try:
        population = config.parse_population(params.get("exp3_population", ""))
    except config.Exp3ConfigError as error:
        return [str(error)]
    if params.get("exp3_campaign") != config.CAMPAIGN_ID:
        problems.append(f"campaign must be {config.CAMPAIGN_ID}")
    selected = config.pairs_for(population)
    if len(config.physical_hosts(population)) != config.expected_node_count(population):
        problems.append("physical node count does not match the approved population")
    mode = params.get("exp3_schedule", "")
    rows = _handoffs(run_dir / "handoffs.txt")
    expected_handoffs = 1 if mode == "smoke" else 8 if mode == "full" else -1
    if expected_handoffs < 0:
        problems.append(f"exp3_schedule must be smoke or full; got {mode!r}")
    for pair in selected:
        own = [row for row in rows if row["producer"] == pair.producer]
        if expected_handoffs >= 0 and len(own) != expected_handoffs:
            problems.append(f"{pair.producer} has {len(own)} handoffs; expected {expected_handoffs}")
        for offset, row in enumerate(own):
            if offset + 1 >= len(pair.sequence):
                problems.append(f"{pair.producer} handoff {offset + 1} is outside its sequence")
                continue
            source = pair.sequence[offset]
            destination = pair.sequence[offset + 1]
            if row["from_node"] != source or row["to_node"] != destination:
                problems.append(
                    f"{pair.producer} handoff {offset + 1} is {row['from_node']}->{row['to_node']}; "
                    f"expected {source}->{destination}"
                )
        producer_log = _read(run_dir / f"{pair.producer}.log")
        registered = _REGISTERED.findall(producer_log)
        advertised = _ADVERTISED.findall(producer_log)
        if registered != [pair.prefix]:
            problems.append(f"{pair.producer} registered {registered or ['none']}; expected {pair.prefix}")
        if advertised != [pair.prefix]:
            problems.append(f"{pair.producer} advertised {advertised or ['none']}; expected {pair.prefix}")
        consumer_log = _read(run_dir / f"{pair.consumer}.log")
        daemon_log = _read(run_dir / f"optoflood_{pair.producer}.log")
        problems.extend(_daemon_alive(daemon_log, f"{pair.producer} daemon"))
        problems.extend(_app_fatal(producer_log, pair.producer))
        consumer_daemon_log = _read(run_dir / f"optoflood_{pair.consumer}.log")
        problems.extend(_daemon_alive(consumer_daemon_log, f"{pair.consumer} daemon"))
        problems.extend(_app_fatal(consumer_log, pair.consumer))
        guards = _GUARD_REGISTERED.findall(daemon_log)
        if guards != [pair.guard]:
            problems.append(f"{pair.producer} guard registration {guards or ['none']}; expected {pair.guard}")
        for foreign in _foreign_validations(consumer_log, pair.identity):
            problems.append(
                f"{pair.consumer} validated {foreign}, which {pair.identity} cannot sign"
            )
        if mode == "smoke":
            expected_id = config.guard_flood_id(pair.index, 1)
            seen_ids = [int(item) for item in _FLOOD.findall(daemon_log)]
            if expected_id not in seen_ids:
                problems.append(f"{pair.producer} did not emit Guard FloodId {expected_id}")
            if seen_ids and seen_ids[0] != expected_id:
                problems.append(f"{pair.producer} first Guard FloodId is {seen_ids[0]}; expected {expected_id}")
            if own:
                try:
                    handoff_time = float(own[0]["abs_time"])
                except ValueError:
                    problems.append(f"{pair.producer} handoff time is not numeric")
                else:
                    if not _consumer_validated(consumer_log, pair.consumer, pair.prefix, handoff_time):
                        problems.append(
                            f"{pair.consumer} did not validate {pair.prefix} after the smoke handoff"
                        )
                    problems.extend(_shared_forwarding(run_dir, pair.prefix, expected_id, own[0]["to_node"]))
    for name in config.result_names(population):
        path = run_dir / name
        if not path.is_file():
            problems.append(f"missing {name}")
        elif name.endswith(".pcap") and path.stat().st_size <= 24:
            problems.append(f"pcap has no packets: {name}")
        elif not name.startswith("tcpdump_") and path.stat().st_size <= 0:
            problems.append(f"empty {name}")
    schema = _read(run_dir / "trust-schema.conf")
    if config.LEGACY_TRUST_ANCHOR in schema:
        problems.append("Exp3 trust schema references the legacy trust anchor")
    problems.extend(_schema_relation(schema))
    for pair in selected:
        if f"certs/{pair.producer}.cert" not in schema:
            problems.append(f"trust schema does not include {pair.producer}.cert")
    problems.extend(_observation_ends(run_dir / "observation_ends.txt", selected, mode))
    try:
        common_end = float(params.get("common_end_s", ""))
    except ValueError:
        common_end = -1.0
    if common_end <= 0:
        problems.append("common_end_s is missing")
    else:
        problems.extend(_process_health(run_dir / "process-health.txt", selected, common_end))
    return problems


def _process_health(path: Path, selected: Sequence[config.Pair], common_end: float) -> List[str]:
    problems = []
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.split("\t", 1)[0] == "host":
                continue
            parts = line.split("\t")
            if len(parts) != 6:
                problems.append("process-health.txt row does not have six columns")
                continue
            rows.append(parts)
    expected = procs.expected_processes(
        tuple(pair.producer for pair in selected),
        tuple(pair.consumer for pair in selected),
    )
    for host, kind in expected:
        own = [row for row in rows if row[0] == host and row[1] == kind]
        premature = [row for row in own if row[3] == "premature-exit"]
        refused = [row for row in own if row[3] == "shutdown-refused"]
        shutdowns = [row for row in own if row[3] == "intentional-shutdown"]
        if premature:
            problems.append(f"{host} {kind} exited during observation at {premature[0][4]}")
        if refused:
            problems.append(f"{host} {kind} shutdown was refused: {refused[0][5]}")
        if len(shutdowns) != 1:
            problems.append(f"{host} {kind} has {len(shutdowns)} intentional shutdown records")
            continue
        try:
            rel_s = float(shutdowns[0][4])
        except ValueError:
            problems.append(f"{host} {kind} shutdown time is not numeric")
            continue
        if rel_s + 0.05 < common_end:
            problems.append(
                f"{host} {kind} shut down at {rel_s:.3f}s before the common end {common_end:.3f}s"
            )
    return problems


def _schema_relation(schema: str) -> List[str]:
    legacy_path = Path(__file__).resolve().parents[1] / "app" / "trust-schema.conf"
    if not legacy_path.is_file():
        return [f"missing legacy trust schema: {legacy_path}"]
    legacy = legacy_path.read_text(encoding="utf-8")
    problems = []
    for marker in ("k-regex", "k-expand", "h-relation", "p-regex", "p-expand"):
        legacy_line = next((line.strip() for line in legacy.splitlines() if marker in line), "")
        generated_line = next((line.strip() for line in schema.splitlines() if marker in line), "")
        if not generated_line or generated_line != legacy_line:
            problems.append(f"trust schema {marker} does not match the legacy name relation")
    return problems


def _observation_ends(path: Path, selected: Sequence[config.Pair], mode: str) -> List[str]:
    problems: List[str] = []
    rows: Dict[str, List[str]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.split("\t", 1)[0] == "producer":
                continue
            fields = line.split("\t")
            if len(fields) != 4:
                problems.append("observation_ends.txt row does not have four columns")
                continue
            rows[fields[0]] = fields
    if len(rows) != len(selected):
        problems.append(
            f"observation_ends.txt has {len(rows)} producers; expected {len(selected)}"
        )
    for pair in selected:
        fields = rows.get(pair.producer)
        if fields is None:
            problems.append(f"observation_ends.txt has no endpoint for {pair.producer}")
            continue
        if fields[1] != str(pair.index):
            problems.append(f"{pair.producer} observation index is {fields[1]}")
        try:
            relative = float(fields[2])
            absolute = float(fields[3])
        except ValueError:
            problems.append(f"{pair.producer} observation endpoint is not numeric")
            continue
        if relative <= 0 or absolute <= relative:
            problems.append(f"{pair.producer} observation endpoint is not after the mobility clock origin")
        if mode == "smoke" and abs(relative - (config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S)) > 1e-6:
            problems.append(
                f"{pair.producer} smoke observation end is {relative}; "
                f"expected {config.SMOKE_WARMUP_S + config.SMOKE_TAIL_S}"
            )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_exp3_evidence.py <run-directory>", file=sys.stderr)
        return 2
    run_dir = Path(arguments[0])
    problems = inspect_run(run_dir)
    if problems:
        print(f"Exp3 evidence check failed: {run_dir}")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"Exp3 evidence check passed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
