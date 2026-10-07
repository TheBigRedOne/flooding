#!/usr/bin/env python3
"""Host-side routing-convergence metrics from existing logs and captures.

This module does not change service recovery, content loss, forwarding cost,
or NLSR control-rate measurement, and it does not start a virtual machine.

The four routing quantities are:

* Complete Mobility-Topology Update Latency: local Adj-LSA build
  after both sides of the move are definitive. Not NLSR Sync publication.
* Service-Path LSA Lead: same-router, same-LSA corridor Data versus NLSR Sync.
* Service-Path FIB Convergence Time: NFD-confirmed /LiveStream install
  on routers whose service-path next hop must change.
* Network-Wide FIB Convergence Time: the same NFD endpoint over every
  affected NLSR router. An unfinished router at the event boundary is right-censored.

TFIB standby is a lifecycle diagnostic. It is not a convergence time.
"""

from __future__ import annotations

import csv
import heapq
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

LOCAL_ADJ_RE = re.compile(r"AdjacencyList\] Adjacent: (?P<name>/ndn/\S+)")
LOCAL_FACE_RE = re.compile(r"Connecting FaceUri: (?P<uri>udp4://[0-9.]+:\d+)")
STATUS_RE = re.compile(r"Old Status: (?P<old>\d+), New Status: (?P<new>\d+)")
NEIGHBOR_RE = re.compile(r"Neighbor: (?P<name>/ndn/\S+)")
VERIFY_RE = re.compile(
    r"HELLO VERIFY RESULT: serial=(?P<serial>\d+) neighbor=(?P<name>/ndn/\S+) .* result=(?P<result>REACHABLE|UNREACHABLE)"
)
VERIFY_START_RE = re.compile(r"MOBILITY VERIFICATION START: serial=(?P<serial>\d+)")
SEQ_RE = re.compile(r"Adj LSA seq no: (?P<seq>\d+)")
SYNC_RE = re.compile(
    r"Update Name: /localhop/ndn/nlsr/LSA/(?P<origin>.+)/ADJACENCY Seq no: (?P<seq>\d+)"
)
FIB_ADD_RE = re.compile(
    r"(?:Registering prefix: /LiveStream faceUri: |Adding )(?P<uri>udp4://[0-9.]+:\d+)(?: to /LiveStream)?"
)
FIB_REGISTER_RE = re.compile(r"Registering prefix: /LiveStream faceUri: (?P<uri>udp4://[0-9.]+:\d+)")
FIB_ADD_FACE_RE = re.compile(r"Adding (?P<uri>udp4://[0-9.]+:\d+) to /LiveStream")
FIB_REMOVE_RE = re.compile(r"Removing (?P<uri>udp4://[0-9.]+:\d+) from /LiveStream")
NLSR_OK_RE = re.compile(
    r"Successful in name registration: (?P<name>\S+) Face Uri: (?P<uri>udp4://[0-9.]+:\d+) faceId: (?P<face>\d+)"
)
LINK_COST_RE = re.compile(r"Link cost: (?P<cost>[0-9.]+)")
# NLSR routers that install a transit /LiveStream next hop.
# The producer originates the prefix locally and does not register a transit next hop.
ROUTING_UNIVERSE = (
    "consumer", "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
INACTIVE_RE = re.compile(r"Neighbor: (?P<name>/ndn/\S+) status changed to INACTIVE")
CALC_RE = re.compile(r"Routing calculation completed serial=(?P<serial>\d+)")
BASE_CALC_RE = re.compile(r"Updating table with newly calculated routes")

NODES = (
    "producer", "consumer", "core", "agg1", "agg2",
    "acc1", "acc2", "acc3", "acc4", "acc5", "acc6",
)
RELAYS = ("core", "agg1", "agg2", "acc1", "acc2", "acc3", "acc4", "acc5", "acc6")
PRODUCER_MARK = "70%72%6F%64%75%63%65%72"


@dataclass
class Handoff:
    index: int
    time: float
    end: float
    old: str
    new: str
    final: bool = False


@dataclass
class LogEvent:
    time: float
    kind: str
    text: str
    neighbor: str = ""
    status: str = ""
    seq: Optional[int] = None
    uri: str = ""
    serial: Optional[int] = None
    face_id: Optional[int] = None


@dataclass
class EventRow:
    values: Dict[str, Any] = field(default_factory=dict)


def short_router(name: str) -> str:
    text = name.rstrip("),")
    if "/cs/" in text:
        return text.rsplit("/cs/", 1)[-1].split("/")[0].rstrip(")")
    return text.rsplit("/", 1)[-1]


def decode_percent(text: str) -> bytes:
    output = bytearray()
    index = 0
    while index < len(text):
        if text[index] == "%" and index + 2 < len(text):
            try:
                output.append(int(text[index + 1:index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        output.append(ord(text[index]))
        index += 1
    return bytes(output)


def corridor_seq(name: str) -> Optional[int]:
    marker = "corridor/ADJACENCY/"
    if marker not in name or PRODUCER_MARK not in name:
        return None
    component = name.split(marker, 1)[1].split("/", 1)[0]
    if "=" in component and component.split("=", 1)[0].isdigit():
        component = component.split("=", 1)[1]
    raw = decode_percent(component)
    if not raw:
        return None
    return int.from_bytes(raw, "big")


def parse_handoffs(path: Path, capture_end: Optional[float] = None) -> List[Handoff]:
    found: List[Tuple[int, float, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            found.append((int(parts[0]), float(parts[1]), parts[3], parts[4]))
    handoffs: List[Handoff] = []
    for position, (index, when, old, new) in enumerate(found):
        final = position + 1 == len(found)
        if final:
            end = capture_end if capture_end is not None else when
        else:
            end = found[position + 1][1]
        handoffs.append(Handoff(index, when, end, old, new, final))
    return handoffs


def _timestamp(line: str) -> Optional[float]:
    parts = line.split()
    if not parts or parts[0].count(".") != 1:
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def parse_nlsr_log(path: Path) -> Tuple[List[LogEvent], Dict[str, str], Dict[str, float], Dict[int, str]]:
    """Return NLSR events, udp URI -> neighbour, neighbour -> link cost, faceId -> URI.

    faceId -> URI comes from NLSR registration callbacks that print both identifiers.
    A faceId that maps to two URIs is omitted; it cannot identify a next hop.
    """
    events: List[LogEvent] = []
    faces: Dict[str, str] = {}
    costs: Dict[str, float] = {}
    face_bindings: Dict[int, Set[str]] = {}
    pending_neighbor = ""
    pending_local = ""
    if not path.exists():
        return events, faces, costs, {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        local_adj = LOCAL_ADJ_RE.search(raw)
        if local_adj:
            pending_local = short_router(local_adj.group("name"))
            continue
        cost_match = LINK_COST_RE.search(raw)
        if cost_match and pending_local:
            costs[pending_local] = float(cost_match.group("cost"))
            continue
        local_face = LOCAL_FACE_RE.search(raw)
        if local_face and pending_local:
            faces[local_face.group("uri")] = pending_local
            continue
        when = _timestamp(raw)
        if when is None:
            continue
        inactive = INACTIVE_RE.search(raw)
        if inactive:
            events.append(LogEvent(when, "inactive", raw, neighbor=short_router(inactive.group("name")), status="INACTIVE"))
            continue
        neighbor = NEIGHBOR_RE.search(raw)
        status = STATUS_RE.search(raw)
        if neighbor and "Old Status" not in raw and "status changed" not in raw:
            pending_neighbor = short_router(neighbor.group("name"))
            continue
        if status and pending_neighbor:
            new_status = "ACTIVE" if status.group("new") == "1" else "INACTIVE"
            events.append(LogEvent(when, "status", raw, neighbor=pending_neighbor, status=new_status))
            pending_neighbor = ""
            continue
        verify = VERIFY_RE.search(raw)
        if verify:
            events.append(LogEvent(
                when, "verify", raw,
                neighbor=short_router(verify.group("name")),
                status=verify.group("result"),
                serial=int(verify.group("serial")),
            ))
            continue
        started = VERIFY_START_RE.search(raw)
        if started:
            events.append(LogEvent(when, "verify-start", raw, serial=int(started.group("serial"))))
            continue
        if "MOBILITY VERIFICATION COMPLETE" in raw:
            events.append(LogEvent(when, "verify-complete", raw))
            continue
        registered_ok = NLSR_OK_RE.search(raw)
        if registered_ok:
            face_id = int(registered_ok.group("face"))
            face_bindings.setdefault(face_id, set()).add(registered_ok.group("uri"))
            events.append(LogEvent(
                when, "nlsr-register-ok", raw,
                uri=registered_ok.group("uri"),
                face_id=face_id,
            ))
            continue
        if "Building and installing own Adj LSA" in raw:
            events.append(LogEvent(when, "build", raw))
            continue
        if "ADJ LSA SETTLE:" in raw:
            events.append(LogEvent(when, "settle", raw))
            continue
        seq = SEQ_RE.search(raw)
        if seq:
            events.append(LogEvent(when, "seq", raw, seq=int(seq.group("seq"))))
            continue
        sync = SYNC_RE.search(raw)
        if sync and "producer" in sync.group("origin"):
            events.append(LogEvent(when, "sync", raw, seq=int(sync.group("seq"))))
            continue
        registered = FIB_REGISTER_RE.search(raw)
        added = FIB_ADD_FACE_RE.search(raw)
        removed = FIB_REMOVE_RE.search(raw)
        if registered:
            events.append(LogEvent(when, "fib-add", raw, uri=registered.group("uri")))
        elif added:
            events.append(LogEvent(when, "fib-add", raw, uri=added.group("uri")))
        elif removed:
            events.append(LogEvent(when, "fib-remove", raw, uri=removed.group("uri")))
        elif CALC_RE.search(raw):
            events.append(LogEvent(when, "calc", raw, serial=int(CALC_RE.search(raw).group("serial"))))
        elif BASE_CALC_RE.search(raw):
            events.append(LogEvent(when, "calc", raw))
    face_ids = {face_id: next(iter(uris)) for face_id, uris in face_bindings.items() if len(uris) == 1}
    return events, faces, costs, face_ids


def _between(events: Sequence[LogEvent], start: float, end: float, kind: str) -> List[LogEvent]:
    return [item for item in events if start < item.time < end and item.kind == kind]


def _seq_after(events: Sequence[LogEvent], when: float, horizon: float) -> Optional[int]:
    for item in events:
        if item.kind == "seq" and when <= item.time <= when + horizon and item.seq is not None:
            return item.seq
    return None


def select_complete_publication(
    events: Sequence[LogEvent],
    handoff: Handoff,
    accelerated: bool,
) -> Dict[str, Any]:
    """Local Adj-LSA build/install for the complete move.

    This is not NLSR Sync publication, remote LSDB installation, or FIB convergence.
    """
    blank: Dict[str, Any] = {
        "verification_start_ms": "",
        "verification_complete_ms": "",
        "old_adjacency_definitive_ms": "",
        "new_adjacency_definitive_ms": "",
        "complete_adj_lsa_seq": "",
        "topology_update_latency_ms": "",
        "nlsr_sync_trigger_latency_ms": "",
        "topology_note": "",
    }
    if accelerated:
        completes = _between(events, handoff.time, handoff.end, "verify-complete")
        if not completes:
            blank["topology_note"] = "no mobility verification completion"
            return blank
        done = completes[0]
        starts = [item for item in events if item.kind == "verify-start" and handoff.time < item.time <= done.time]
        start = starts[-1] if starts else None
        results = [
            item for item in events
            if item.kind == "verify" and start is not None and item.serial == start.serial
            and (start.time - 0.001) <= item.time <= done.time + 0.001
        ]
        by_neighbor = {item.neighbor: item for item in results}
        old = by_neighbor.get(handoff.old)
        new = by_neighbor.get(handoff.new)
        blank["verification_start_ms"] = "" if start is None else (start.time - handoff.time) * 1000.0
        blank["verification_complete_ms"] = (done.time - handoff.time) * 1000.0
        if old is not None:
            blank["old_adjacency_definitive_ms"] = (old.time - handoff.time) * 1000.0
        if new is not None:
            blank["new_adjacency_definitive_ms"] = (new.time - handoff.time) * 1000.0
        if old is None or new is None or old.status != "UNREACHABLE" or new.status != "REACHABLE":
            blank["topology_note"] = "verification did not establish old UNREACHABLE and new REACHABLE"
            return blank
        builds = [
            item for item in events
            if item.kind == "build" and abs(item.time - done.time) <= 0.05
        ]
        if not builds:
            blank["topology_note"] = "no own Adj-LSA build at verification completion"
            return blank
        build = builds[0]
    else:
        status = {node: "INACTIVE" for node in NODES}
        old_time: Optional[float] = None
        new_time: Optional[float] = None
        build = None
        for item in events:
            if item.time <= handoff.time:
                if item.kind in ("status", "inactive"):
                    status[item.neighbor] = item.status
                continue
            if item.time >= handoff.end:
                break
            if item.kind in ("status", "inactive"):
                status[item.neighbor] = item.status
                if item.neighbor == handoff.old and item.status == "INACTIVE" and old_time is None:
                    old_time = item.time
                if item.neighbor == handoff.new and item.status == "ACTIVE" and new_time is None:
                    new_time = item.time
            if item.kind == "build" and old_time is not None and new_time is not None and item.time >= max(old_time, new_time):
                build = item
                break
        if old_time is not None:
            blank["old_adjacency_definitive_ms"] = (old_time - handoff.time) * 1000.0
        if new_time is not None:
            blank["new_adjacency_definitive_ms"] = (new_time - handoff.time) * 1000.0
        if build is None:
            blank["topology_note"] = "no own Adj-LSA build after both PoA facts are definitive"
            return blank
    seq = _seq_after(events, build.time, 1.0)
    blank["complete_adj_lsa_seq"] = "" if seq is None else seq
    blank["topology_update_latency_ms"] = (build.time - handoff.time) * 1000.0
    settles = [item for item in events if item.kind == "settle" and build.time <= item.time < handoff.end]
    if settles:
        blank["nlsr_sync_trigger_latency_ms"] = (settles[0].time - handoff.time) * 1000.0
    if seq is None:
        blank["topology_note"] = "complete build found but sequence was not logged"
        blank["topology_update_latency_ms"] = ""
    return blank


def expected_next_hop(graph: Dict[str, Dict[str, str]], source: str, attachment: str) -> Optional[str]:
    """First hop from source toward the producer's new access router. None if source is that router."""
    if source == attachment:
        return "producer"
    if source not in graph or attachment not in graph:
        return None
    previous: Dict[str, Optional[str]] = {source: None}
    queue = [source]
    while queue:
        current = queue.pop(0)
        if current == attachment:
            break
        for neighbor in graph.get(current, {}):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    if attachment not in previous:
        return None
    hop: Optional[str] = attachment
    while hop is not None and previous.get(hop) != source:
        hop = previous.get(hop)
    return hop


def routers_toward(graph: Dict[str, Dict[str, str]], source: str, attachment: str) -> List[str]:
    """Routers from the hop after source through the new attachment, inclusive."""
    if source not in graph or attachment not in graph:
        return []
    previous: Dict[str, Optional[str]] = {source: None}
    queue = [source]
    while queue:
        current = queue.pop(0)
        if current == attachment:
            break
        for neighbor in graph.get(current, {}):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    if attachment not in previous:
        return []
    path = [attachment]
    while previous[path[-1]] is not None:
        parent = previous[path[-1]]
        if parent is None:
            break
        path.append(parent)
    path.reverse()
    return [node for node in path if node != source and node in RELAYS]


def build_graph(face_maps: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """node -> neighbour short name -> udp URI, from each node's adjacency log."""
    graph: Dict[str, Dict[str, str]] = {node: {} for node in NODES}
    for node, faces in face_maps.items():
        for uri, neighbor in faces.items():
            graph.setdefault(node, {})[neighbor] = uri
            graph.setdefault(neighbor, {})
    return graph


def first_stable_fib(
    events: Sequence[LogEvent],
    handoff: Handoff,
    expected_uri: str,
) -> Optional[float]:
    added: Optional[float] = None
    for item in events:
        if not in_observation_window(item.time, handoff):
            continue
        if item.kind == "fib-add" and item.uri == expected_uri and added is None:
            added = item.time
        elif item.kind == "fib-remove" and item.uri == expected_uri and added is not None and item.time > added:
            return None
    return added


def in_observation_window(when: float, handoff: Handoff) -> bool:
    """Open at the handoff. Final events include the capture-end timestamp."""
    if when <= handoff.time:
        return False
    if handoff.final:
        return when <= handoff.end
    return when < handoff.end


def parse_nfd_livestream_lines(lines: Iterable[str]) -> List[Tuple[float, str, int]]:
    """NFD RIB-update successes for NLSR /LiveStream routes.

    RibManager::registerEntry returns HTTP-style success before FIB installation.
    'RIB update succeeded' is logged only after FibUpdater finishes the FIB nexthop
    command. The record carries the prefix, REGISTER/UNREGISTER, and faceId.
    Other prefixes and non-NLSR origins are not installations of this route.
    """
    found: List[Tuple[float, str, int]] = []
    pending: Optional[float] = None
    name = ""
    action = ""
    face_id: Optional[int] = None
    origin = ""
    for raw in lines:
        if "RIB update succeeded for RibUpdate" in raw:
            pending = _timestamp(raw)
            name = ""
            action = ""
            face_id = None
            origin = ""
            continue
        if pending is None:
            continue
        if raw.startswith("179") or (raw[:1].isdigit() and " DEBUG:" in raw[:40]):
            pending = None
            continue
        if "Name:" in raw:
            name = raw.split("Name:", 1)[1].strip()
        elif "Action:" in raw:
            action = raw.split("Action:", 1)[1].strip()
        elif "faceid:" in raw:
            face_text = raw.split("faceid:", 1)[1].split(",", 1)[0].strip()
            if face_text.isdigit():
                face_id = int(face_text)
            if "origin:" in raw:
                origin = raw.split("origin:", 1)[1].split(",", 1)[0].strip()
        elif raw.strip() == "}":
            if name == "/LiveStream" and origin == "nlsr" and action in ("REGISTER", "UNREGISTER") and face_id is not None:
                found.append((pending, action, face_id))
            pending = None
    return found


def parse_nfd_livestream(path: Path) -> List[Tuple[float, str, int]]:
    if not path.exists():
        return []
    return parse_nfd_livestream_lines(path.open("r", encoding="utf-8", errors="replace"))


def bind_nfd_operations(
    operations: Sequence[Tuple[float, str, int]],
    face_ids: Dict[int, str],
) -> Tuple[List[Tuple[float, str, str]], int]:
    """Map faceId to FaceUri. Unmapped faceIds are counted and dropped, not guessed."""
    bound: List[Tuple[float, str, str]] = []
    unmapped = 0
    for when, action, face_id in operations:
        uri = face_ids.get(face_id)
        if uri is None:
            unmapped += 1
            continue
        bound.append((when, action, uri))
    return bound, unmapped


def first_stable_confirmed(
    operations: Sequence[Tuple[float, str, str]],
    handoff: Handoff,
    expected_uri: str,
) -> Optional[float]:
    """First NFD-confirmed add of expected_uri that is not unregistered before the horizon."""
    added: Optional[float] = None
    for when, action, uri in operations:
        if not in_observation_window(when, handoff) or uri != expected_uri:
            continue
        if action == "REGISTER" and added is None:
            added = when
        elif action == "UNREGISTER" and added is not None and when > added:
            return None
    return added


def build_cost_graph(costs: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    graph: Dict[str, Dict[str, float]] = {node: {} for node in NODES}
    for node, neighbors in costs.items():
        for neighbor, cost in neighbors.items():
            graph.setdefault(node, {})[neighbor] = cost
            graph.setdefault(neighbor, {})
    return graph


def graph_for_attachment(
    base: Dict[str, Dict[str, float]],
    attachment: str,
) -> Dict[str, Dict[str, float]]:
    """Static adjacencies plus only the producer's current PoA link."""
    graph = {node: dict(neighbors) for node, neighbors in base.items()}
    producer_links = dict(base.get("producer", {}))
    for node, neighbors in graph.items():
        neighbors.pop("producer", None)
    graph["producer"] = {}
    if attachment not in producer_links or "producer" not in base.get(attachment, {}):
        return graph
    graph["producer"][attachment] = producer_links[attachment]
    graph.setdefault(attachment, {})["producer"] = base[attachment]["producer"]
    return graph


def distances_from(graph: Dict[str, Dict[str, float]], source: str) -> Dict[str, float]:
    distance = {source: 0.0}
    queue = [(0.0, source)]
    while queue:
        current, node = heapq.heappop(queue)
        if current > distance.get(node, float("inf")):
            continue
        for neighbor, cost in graph.get(node, {}).items():
            updated = current + cost
            if updated < distance.get(neighbor, float("inf")):
                distance[neighbor] = updated
                heapq.heappush(queue, (updated, neighbor))
    return distance


def acceptable_next_hops(
    graph: Dict[str, Dict[str, float]],
    distance: Dict[str, float],
    node: str,
) -> Optional[Set[str]]:
    """Neighbours that lie on a minimum-cost path to the producer.

    NLSR's link-state calculator keeps a single parent and does not add an equal-cost
    alternative. A tie therefore has more than one acceptable next hop, and an
    installation of any non-empty subset is the correct state. This topology
    has a unique path while only one producer adjacency is up, so the set has size 1.
    """
    if node not in distance:
        return None
    hops = {
        neighbor
        for neighbor, cost in graph.get(node, {}).items()
        if neighbor in distance and abs((distance[neighbor] + cost) - distance[node]) <= 1e-6
    }
    return hops


def installed_set_at(
    operations: Sequence[Tuple[float, str, str]],
    until: float,
    inclusive: bool,
) -> Set[str]:
    installed: Set[str] = set()
    for when, action, uri in operations:
        if when > until or (when == until and not inclusive):
            break
        if action == "REGISTER":
            installed.add(uri)
        elif action == "UNREGISTER":
            installed.discard(uri)
    return installed


def first_stable_next_hop_set(
    operations: Sequence[Tuple[float, str, str]],
    handoff: Handoff,
    expected_uris: Set[str],
) -> Optional[float]:
    """First time the installed URI set is a non-empty subset of the acceptable set.

    A later withdrawal that leaves the set incorrect before the observation horizon
    invalidates the router. Operations must be time-ordered.
    """
    if not expected_uris:
        return None
    installed = installed_set_at(operations, handoff.time, True)
    correct_since: Optional[float] = handoff.time if installed and installed <= expected_uris else None
    for when, action, uri in operations:
        if when <= handoff.time:
            continue
        if not in_observation_window(when, handoff):
            break
        if action == "REGISTER":
            installed.add(uri)
        elif action == "UNREGISTER":
            installed.discard(uri)
        correct = bool(installed) and installed <= expected_uris
        if correct and correct_since is None:
            correct_since = when
        elif correct_since is not None and not correct:
            return None
    return correct_since


def scan_tfib(path: Path, handoff: Handoff) -> Dict[str, Any]:
    found: Dict[str, Any] = {"tfib_update_ms": "", "tfib_standby_fib_agrees_ms": "", "tfib_retire_ms": "", "tfib_retire_reason": ""}
    if not path.exists():
        return found
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        when = _timestamp(raw)
        if when is None or when <= handoff.time or when >= handoff.end or "/LiveStream" not in raw:
            continue
        delta = (when - handoff.time) * 1000.0
        if "TFIB update" in raw and found["tfib_update_ms"] == "":
            found["tfib_update_ms"] = delta
        elif "tfib-standby" in raw and "fib-agrees" in raw and found["tfib_standby_fib_agrees_ms"] == "":
            found["tfib_standby_fib_agrees_ms"] = delta
        elif "tfib-retire" in raw and found["tfib_retire_ms"] == "":
            found["tfib_retire_ms"] = delta
            if "reason=" in raw:
                found["tfib_retire_reason"] = raw.split("reason=", 1)[1].strip()
    return found


def blank_row(configuration: str, profile: str, run_id: str, handoff: Handoff) -> Dict[str, Any]:
    return {
        "configuration": configuration,
        "profile": profile,
        "run_id": run_id,
        "handoff_index": handoff.index,
        "from_node": handoff.old,
        "to_node": handoff.new,
        "handoff_time": handoff.time,
        "verification_start_ms": "",
        "verification_complete_ms": "",
        "old_adjacency_definitive_ms": "",
        "new_adjacency_definitive_ms": "",
        "complete_adj_lsa_seq": "",
        "topology_update_latency_ms": "",
        "nlsr_sync_trigger_latency_ms": "",
        "fib_endpoint_evidence_level": "",
        "first_required_router_correct_ms": "",
        "service_path_fib_convergence_ms": "",
        "service_path_fib_registration_ms": "",
        "required_service_path_router_count": "",
        "network_fib_converged": "",
        "network_fib_convergence_ms": "",
        "network_fib_censor_boundary_ms": "",
        "affected_network_router_count": "",
        "affected_router_names": "",
        "network_limiting_router": "",
        "fib_observation_end_time": handoff.end,
        "post_service_path_fib_observation_ms": "",
        "post_network_fib_observation_ms": "",
        "fib_stability_scope": "until-capture-end" if handoff.final else "until-next-handoff",
        "tfib_update_ms": "",
        "tfib_standby_fib_agrees_ms": "",
        "tfib_retire_ms": "",
        "tfib_retire_reason": "",
        "topology_note": "",
        "fib_note": "",
    }


def index_corridor(packet_csv: Path) -> Tuple[Dict[int, List[Tuple[float, str, str, bool]]], Optional[float]]:
    grouped: Dict[int, List[Tuple[float, str, str, bool]]] = {}
    capture_end: Optional[float] = None
    if not packet_csv.exists():
        return grouped, capture_end
    with packet_csv.open("r", encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            try:
                when = float(record["frame.time_epoch"])
            except (KeyError, TypeError, ValueError):
                continue
            capture_end = when if capture_end is None else max(capture_end, when)
            seq = corridor_seq(record.get("ndn.name") or "")
            if seq is None:
                continue
            kind = "corridor-data" if (record.get("ndn.type") or "").lower() == "data" else "corridor-interest"
            outbound = (record.get("sll.pkttype") or "").strip() == "4"
            grouped.setdefault(seq, []).append((when, record.get("node") or "", kind, outbound))
    return grouped, capture_end


def index_tfib(path: Path) -> List[Tuple[float, str]]:
    found: List[Tuple[float, str]] = []
    if not path.exists():
        return found
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "TFIB update" not in raw and "tfib-standby" not in raw and "tfib-retire" not in raw:
            continue
        if "/LiveStream" not in raw:
            continue
        when = _timestamp(raw)
        if when is not None:
            found.append((when, raw))
    return found


def tfib_in_window(lines: Sequence[Tuple[float, str]], handoff: Handoff) -> Dict[str, Any]:
    found: Dict[str, Any] = {"tfib_update_ms": "", "tfib_standby_fib_agrees_ms": "", "tfib_retire_ms": "", "tfib_retire_reason": ""}
    for when, raw in lines:
        if when <= handoff.time or when >= handoff.end:
            continue
        delta = (when - handoff.time) * 1000.0
        if "TFIB update" in raw and found["tfib_update_ms"] == "":
            found["tfib_update_ms"] = delta
        elif "tfib-standby" in raw and "fib-agrees" in raw and found["tfib_standby_fib_agrees_ms"] == "":
            found["tfib_standby_fib_agrees_ms"] = delta
        elif "tfib-retire" in raw and found["tfib_retire_ms"] == "":
            found["tfib_retire_ms"] = delta
            if "reason=" in raw:
                found["tfib_retire_reason"] = raw.split("reason=", 1)[1].strip()
    return found


def priority_from_observations(
    events: Dict[str, List[LogEvent]],
    handoff: Handoff,
    seq: int,
    configuration: str,
    run_id: str,
    observations: Sequence[Tuple[float, str, str, bool]],
) -> List[Dict[str, Any]]:
    per_router: Dict[str, Dict[str, float]] = {}
    for when, node, kind, outbound in observations:
        if outbound or node not in RELAYS:
            continue
        slot = per_router.setdefault(node, {})
        if kind not in slot or when < slot[kind]:
            slot[kind] = when
    earliest: Dict[str, Tuple[float, str]] = {}
    for node, slot in per_router.items():
        if "corridor-data" in slot:
            earliest[node] = (slot["corridor-data"], "corridor-data")
    rows: List[Dict[str, Any]] = []
    for router, (when, _kind) in earliest.items():
        syncs = [
            item for item in events.get(router, [])
            if item.kind == "sync" and item.seq == seq and handoff.time < item.time < handoff.end
        ]
        if not syncs:
            continue
        sync_time = min(item.time for item in syncs)
        rows.append({
            "configuration": configuration,
            "run_id": run_id,
            "handoff_index": handoff.index,
            "router": router,
            "lsa_origin": "producer",
            "lsa_type": "ADJACENCY",
            "lsa_sequence": seq,
            "corridor_data_time": when,
            "nlsr_sync_time": sync_time,
            "lead_ms": (sync_time - when) * 1000.0,
        })
    return rows


def nlsr_route_operations(events: Sequence[LogEvent]) -> List[Tuple[float, str, str]]:
    """NLSR's own /LiveStream FIB add/remove records, in log order.

    'Adding' is recorded before 'Registering prefix'. Both name the same FaceUri.
    This is the NLSR-confirmed endpoint, not NFD's later success callback.
    """
    operations: List[Tuple[float, str, str]] = []
    for item in events:
        if item.kind == "fib-add" and item.uri:
            operations.append((item.time, "REGISTER", item.uri))
        elif item.kind == "fib-remove" and item.uri:
            operations.append((item.time, "UNREGISTER", item.uri))
    return operations


def _nlsr_set_time(
    events: Sequence[LogEvent],
    handoff: Handoff,
    expected_uris: Set[str],
) -> Optional[float]:
    return first_stable_next_hop_set(nlsr_route_operations(events), handoff, expected_uris)


def _manual_audit(
    configuration: str,
    run_id: str,
    handoff: Handoff,
    service_hops: Dict[str, str],
    affected: Sequence[str],
    old_sets: Dict[str, Set[str]],
    new_sets: Dict[str, Set[str]],
    events: Dict[str, List[LogEvent]],
    nfd_ops: Dict[str, Tuple[List[Tuple[float, str, str]], int]],
    graph: Dict[str, Dict[str, str]],
) -> str:
    lines = [
        f"MANUAL {configuration}/{run_id} h{handoff.index} {handoff.old}->{handoff.new} "
        f"scope={'until-capture-end' if handoff.final else 'until-next-handoff'} end={handoff.end:.6f}",
        "affected " + ",".join(affected),
    ]
    for router in affected:
        expected = _uris_for(graph, router, new_sets[router])
        nlsr_when = None if expected is None else _nlsr_set_time(events[router], handoff, expected)
        nfd_when = None if expected is None else first_stable_next_hop_set(nfd_ops[router][0], handoff, expected or set())
        lines.append(
            f"  {router} old={sorted(old_sets[router])} new={sorted(new_sets[router])} "
            f"nlsr_ms={'' if nlsr_when is None else (nlsr_when - handoff.time) * 1000.0:.3f} "
            f"nfd_ms={'' if nfd_when is None else (nfd_when - handoff.time) * 1000.0:.3f} "
            f"evidence=RIB update succeeded faceId->FaceUri"
        )
    service_nlsr = []
    service_nfd = []
    for router, hop in service_hops.items():
        uri = graph.get(router, {}).get(hop, "")
        nlsr_when = first_stable_fib(events[router], handoff, uri)
        nfd_when = first_stable_confirmed(nfd_ops[router][0], handoff, uri)
        nlsr_ms = None if nlsr_when is None else (nlsr_when - handoff.time) * 1000.0
        nfd_ms = None if nfd_when is None else (nfd_when - handoff.time) * 1000.0
        if nlsr_ms is not None:
            service_nlsr.append((nlsr_ms, router))
        if nfd_ms is not None:
            service_nfd.append((nfd_ms, router))
        lines.append(f"  service {router} next={hop} uri={uri} nlsr_ms={nlsr_ms} nfd_ms={nfd_ms}")
    if service_nlsr:
        lines.append(f"  service-path NLSR limiter {max(service_nlsr)}")
    if service_nfd:
        lines.append(f"  service-path NFD limiter {max(service_nfd)}")
    return "\n".join(lines)


def _uris_for(graph: Dict[str, Dict[str, str]], router: str, hops: Set[str]) -> Optional[Set[str]]:
    uris: Set[str] = set()
    for hop in hops:
        if hop == "producer":
            uri = graph.get(router, {}).get("producer")
        else:
            uri = graph.get(router, {}).get(hop)
        if not uri:
            return None
        uris.add(uri)
    return uris


def measure_run(
    run_dir: Path,
    configuration: str,
    profile: str,
    run_id: str,
    accelerated: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    corridor, capture_end = index_corridor(run_dir / "mobility_packets.csv")
    handoff_list = parse_handoffs(run_dir / "handoffs.txt", capture_end)
    parsed = {node: parse_nlsr_log(run_dir / "minindn-logs" / node / "nlsr.log") for node in NODES}
    events = {node: parsed[node][0] for node in NODES}
    graph = build_graph({node: parsed[node][1] for node in NODES})
    base_costs = build_cost_graph({node: parsed[node][2] for node in NODES})
    nfd_ops = {
        node: bind_nfd_operations(
            parse_nfd_livestream(run_dir / "minindn-logs" / node / "nfd.log"),
            parsed[node][3],
        )
        for node in ROUTING_UNIVERSE
    }
    rows: List[Dict[str, Any]] = []
    leads: List[Dict[str, Any]] = []
    notes: List[str] = []
    unmapped = sum(item[1] for item in nfd_ops.values())
    if unmapped:
        notes.append(f"{configuration}/{run_id}: unmapped NLSR /LiveStream RIB faceIds={unmapped}")
    producer = events["producer"]
    tfib_lines = index_tfib(run_dir / "minindn-logs" / "consumer" / "nfd.log") if accelerated else []
    delays: List[Dict[str, Any]] = []
    for handoff in handoff_list:
        row = blank_row(configuration, profile, run_id, handoff)
        publication = select_complete_publication(producer, handoff, accelerated)
        row.update(publication)
        if accelerated:
            row.update(tfib_in_window(tfib_lines, handoff))
        path_routers = routers_toward(graph, "consumer", handoff.new)
        nlsr_times: List[float] = []
        nfd_times: List[float] = []
        unchanged = 0
        missing_nlsr: List[str] = []
        missing_nfd: List[str] = []
        service_hops: Dict[str, str] = {}
        for router in path_routers:
            new_hop = expected_next_hop(graph, router, handoff.new)
            old_hop = expected_next_hop(graph, router, handoff.old)
            if new_hop is None:
                missing_nlsr.append(router)
                missing_nfd.append(router)
                continue
            if new_hop == old_hop:
                unchanged += 1
                continue
            uri = graph.get(router, {}).get(new_hop)
            if not uri:
                missing_nlsr.append(router)
                missing_nfd.append(router)
                continue
            service_hops[router] = new_hop
            nlsr_when = first_stable_fib(events[router], handoff, uri)
            nfd_when = first_stable_confirmed(nfd_ops[router][0], handoff, uri)
            if nlsr_when is None:
                missing_nlsr.append(router)
            else:
                nlsr_times.append((nlsr_when - handoff.time) * 1000.0)
            if nfd_when is None:
                missing_nfd.append(router)
            else:
                nfd_times.append((nfd_when - handoff.time) * 1000.0)
            if nlsr_when is not None and nfd_when is not None:
                delays.append({
                    "configuration": configuration,
                    "run_id": run_id,
                    "handoff_index": handoff.index,
                    "router": router,
                    "nlsr_registration_ms": (nlsr_when - handoff.time) * 1000.0,
                    "nfd_success_ms": (nfd_when - handoff.time) * 1000.0,
                    "nfd_minus_nlsr_ms": (nfd_when - nlsr_when) * 1000.0,
                })
        row["required_service_path_router_count"] = len(service_hops)
        row["_nlsr_service_ms"] = max(nlsr_times) if nlsr_times and not missing_nlsr else ""
        row["_nlsr_first_ms"] = min(nlsr_times) if nlsr_times and not missing_nlsr else ""
        row["_nfd_service_ms"] = max(nfd_times) if nfd_times and not missing_nfd else ""
        row["_nfd_first_ms"] = min(nfd_times) if nfd_times and not missing_nfd else ""
        if not path_routers:
            row["fib_note"] = "no path from consumer to the new attachment"
        elif missing_nlsr:
            row["fib_note"] = f"FIB change missing or reverted on {missing_nlsr}; unchanged routers={unchanged}"

        old_distance = distances_from(graph_for_attachment(base_costs, handoff.old), "producer")
        new_distance = distances_from(graph_for_attachment(base_costs, handoff.new), "producer")
        affected: List[str] = []
        old_sets: Dict[str, Set[str]] = {}
        new_sets: Dict[str, Set[str]] = {}
        network_missing: List[str] = []
        nlsr_network: List[Tuple[str, float]] = []
        nfd_network: List[Tuple[str, float]] = []
        ecmp = False
        for router in ROUTING_UNIVERSE:
            old_hops = acceptable_next_hops(graph_for_attachment(base_costs, handoff.old), old_distance, router)
            new_hops = acceptable_next_hops(graph_for_attachment(base_costs, handoff.new), new_distance, router)
            if old_hops is None or new_hops is None or not new_hops:
                network_missing.append(router)
                continue
            if len(old_hops) > 1 or len(new_hops) > 1:
                ecmp = True
            if old_hops == new_hops:
                continue
            affected.append(router)
            old_sets[router] = old_hops
            new_sets[router] = new_hops
            expected_uris = _uris_for(graph, router, new_hops)
            if expected_uris is None:
                network_missing.append(router)
                continue
            nlsr_router = _nlsr_set_time(events[router], handoff, expected_uris)
            nfd_router = first_stable_next_hop_set(nfd_ops[router][0], handoff, expected_uris)
            if nlsr_router is None:
                network_missing.append(f"{router}:nlsr")
            else:
                nlsr_network.append((router, (nlsr_router - handoff.time) * 1000.0))
            if nfd_router is None:
                network_missing.append(f"{router}:nfd")
            else:
                nfd_network.append((router, (nfd_router - handoff.time) * 1000.0))
        row["affected_network_router_count"] = len(affected)
        row["affected_router_names"] = ";".join(affected)
        row["_nlsr_network_ms"] = ""
        row["_nfd_network_ms"] = ""
        row["_nlsr_network_limiter"] = ""
        row["_nfd_network_limiter"] = ""
        if affected and len(nlsr_network) == len(affected):
            nlsr_limit = max(nlsr_network, key=lambda item: item[1])
            row["_nlsr_network_ms"] = nlsr_limit[1]
            row["_nlsr_network_limiter"] = nlsr_limit[0]
        if affected and len(nfd_network) == len(affected):
            nfd_limit = max(nfd_network, key=lambda item: item[1])
            row["_nfd_network_ms"] = nfd_limit[1]
            row["_nfd_network_limiter"] = nfd_limit[0]
        nfd_gaps = [item for item in network_missing if item.endswith(":nfd") or ":" not in item]
        nlsr_gaps = [item for item in network_missing if item.endswith(":nlsr")]
        censor_routers = [item for item in nfd_gaps if item.endswith(":nfd")]
        row["_network_censored"] = bool(affected) and bool(censor_routers) and len(censor_routers) == len(nfd_gaps)
        row["_network_censor_boundary_ms"] = (
            (handoff.end - handoff.time) * 1000.0 if row["_network_censored"] else ""
        )
        if row["_network_censored"]:
            notes.append(
                f"{configuration}/{run_id} h{handoff.index}: network FIB right-censored at capture/event boundary; "
                f"unfinished routers {censor_routers}; boundary_ms={row['_network_censor_boundary_ms']:.3f}. "
                "The boundary is not a convergence time."
            )
        elif nfd_gaps:
            notes.append(
                f"{configuration}/{run_id} h{handoff.index}: network FIB not evaluable: {nfd_gaps}"
            )
        if nlsr_gaps and not nfd_gaps:
            notes.append(
                f"{configuration}/{run_id} h{handoff.index}: NLSR add/remove trace did not reach a stable correct set "
                f"({nlsr_gaps}); formal network time still uses NFD confirmation"
            )
        row["_ecmp"] = ecmp
        outside = [router for router in service_hops if router not in affected]
        if outside:
            notes.append(f"{configuration}/{run_id} h{handoff.index}: service routers outside affected set {outside}")
        if configuration in ("OptoFlood", "G0") and run_id == "r1" and handoff.index in (1, 8):
            notes.append(_manual_audit(
                configuration, run_id, handoff, service_hops, affected, old_sets, new_sets,
                events, nfd_ops, graph,
            ))
        seq = row["complete_adj_lsa_seq"]
        if seq != "":
            observations = [
                item for item in corridor.get(int(seq), [])
                if handoff.time < item[0] < handoff.end
            ]
            leads.extend(priority_from_observations(events, handoff, int(seq), configuration, run_id, observations))
        if row["topology_note"]:
            notes.append(f"{configuration}/{run_id} h{handoff.index}: {row['topology_note']}")
        if row["fib_note"]:
            notes.append(f"{configuration}/{run_id} h{handoff.index}: {row['fib_note']}")
        rows.append(row)
    return rows, leads, notes, delays


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def numeric(rows: Sequence[Dict[str, Any]], field_name: str) -> List[float]:
    values: List[float] = []
    for row in rows:
        value = row.get(field_name, "")
        if value == "" or value is None:
            continue
        values.append(float(value))
    return values


def quantiles(values: Sequence[float]) -> Tuple[float, float, float]:
    ordered = sorted(values)
    def q(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        weight = position - low
        return ordered[low] * (1.0 - weight) + ordered[high] * weight
    return q(0.25), q(0.5), q(0.75)


def tukey_outlier_count(values: Sequence[float]) -> int:
    if len(values) < 4:
        return 0
    q1, _median, q3 = quantiles(values)
    span = 1.5 * (q3 - q1)
    return sum(1 for value in values if value < q1 - span or value > q3 + span)


def summarise(label: str, values: Sequence[float]) -> str:
    if not values:
        return f"{label}: n=0"
    ordered = sorted(values)
    q1, median, q3 = quantiles(ordered)
    return (
        f"{label}: n={len(ordered)} median={median:.4g} Q1={q1:.4g} Q3={q3:.4g} "
        f"mean={statistics.fmean(ordered):.4g} min={ordered[0]:.4g} max={ordered[-1]:.4g} "
        f"tukey_outliers={tukey_outlier_count(ordered)}"
    )


def per_handoff_leads(pairs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One formal observation per handoff: the median of that handoff's router leads."""
    grouped: Dict[Tuple[str, int], List[float]] = {}
    for pair in pairs:
        key = (str(pair["run_id"]), int(pair["handoff_index"]))
        grouped.setdefault(key, []).append(float(pair["lead_ms"]))
    rows: List[Dict[str, Any]] = []
    for (run_id, index), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered = sorted(values)
        q1, median, q3 = quantiles(ordered)
        rows.append({
            "run_id": run_id,
            "handoff_index": index,
            "paired_router_count": len(ordered),
            "median_lead_ms": median,
            "q1_router_lead_ms": q1,
            "q3_router_lead_ms": q3,
            "min_router_lead_ms": ordered[0],
            "max_router_lead_ms": ordered[-1],
        })
    return rows


def plot_boxes(path: Path, groups: Sequence[Tuple[str, Sequence[float]]], ylabel: str, log_y: bool = False) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    usable = [(label, list(values)) for label, values in groups if values]
    if not usable:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(6.4, 4.2))
    axis.boxplot(
        [values for _label, values in usable],
        tick_labels=[f"{label}\nn={len(values)}" for label, values in usable],
        whis=1.5,
        showfliers=True,
        showmeans=True,
        meanprops={"marker": "D", "markerfacecolor": "black", "markeredgecolor": "black", "markersize": 4.5},
    )
    axis.set_ylabel(ylabel)
    if log_y:
        positive = [value for _label, values in usable for value in values if value > 0]
        low = min(positive)
        high = max(positive)
        import math
        pad = max((math.log10(high) - math.log10(low)) * 0.08, 0.15)
        axis.set_yscale("log")
        axis.set_ylim(10 ** (math.log10(low) - pad), 10 ** (math.log10(high) + pad))
    axis.grid(True, axis="y", linestyle="--", alpha=0.6)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def srt_sanity(results: Path, rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Compare service recovery with routing times. Descriptive only."""
    lines = ["SRT versus routing medians (descriptive; not an ablation):"]
    sources = {
        "G0": results / "baseline" / "mobility_events.csv",
        "OptoFlood": results / "solution" / "mobility_events.csv",
    }
    for configuration, path in sources.items():
        if not path.exists():
            lines.append(f"{configuration} SRT: production event table missing")
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            selected = [row for row in csv.DictReader(handle) if row["configuration"] == configuration]
        lines.append(summarise(f"{configuration} SRT", numeric(selected, "service_recovery_time_ms")))
        selected_routing = [row for row in rows if row["configuration"] == configuration]
        lines.append(summarise(f"{configuration} topology update", numeric(selected_routing, "topology_update_latency_ms")))
        lines.append(summarise(f"{configuration} service-path FIB", numeric(selected_routing, "service_path_fib_convergence_ms")))
    return lines


def apply_evidence_level(rows: Sequence[Dict[str, Any]], level: str) -> None:
    """Copy one evidence level into the formal columns. Do not mix levels."""
    private = (
        "_nlsr_service_ms", "_nlsr_first_ms", "_nfd_service_ms", "_nfd_first_ms",
        "_nlsr_network_ms", "_nfd_network_ms", "_nlsr_network_limiter", "_nfd_network_limiter",
        "_network_censored", "_network_censor_boundary_ms", "_ecmp",
    )
    for row in rows:
        row["fib_endpoint_evidence_level"] = level
        censored = bool(row.get("_network_censored"))
        if level == "NFD_CONFIRMED":
            row["service_path_fib_convergence_ms"] = row["_nfd_service_ms"]
            row["first_required_router_correct_ms"] = row["_nfd_first_ms"]
            row["service_path_fib_registration_ms"] = row["_nlsr_service_ms"]
            if censored:
                row["network_fib_converged"] = "false"
                row["network_fib_convergence_ms"] = ""
                row["network_fib_censor_boundary_ms"] = row["_network_censor_boundary_ms"]
                row["network_limiting_router"] = ""
            else:
                row["network_fib_converged"] = "true" if row["_nfd_network_ms"] != "" else "false"
                row["network_fib_convergence_ms"] = row["_nfd_network_ms"]
                row["network_fib_censor_boundary_ms"] = ""
                row["network_limiting_router"] = row["_nfd_network_limiter"]
        else:
            row["service_path_fib_convergence_ms"] = row["_nlsr_service_ms"]
            row["first_required_router_correct_ms"] = row["_nlsr_first_ms"]
            row["service_path_fib_registration_ms"] = ""
            row["network_fib_converged"] = "true" if row["_nlsr_network_ms"] != "" else "false"
            row["network_fib_convergence_ms"] = row["_nlsr_network_ms"]
            row["network_fib_censor_boundary_ms"] = ""
            row["network_limiting_router"] = row["_nlsr_network_limiter"]
        service = row["service_path_fib_convergence_ms"]
        network = row["network_fib_convergence_ms"]
        horizon = (float(row["fib_observation_end_time"]) - float(row["handoff_time"])) * 1000.0
        if service != "":
            row["post_service_path_fib_observation_ms"] = horizon - float(service)
        if network != "":
            row["post_network_fib_observation_ms"] = horizon - float(network)
        for key in private:
            row.pop(key, None)


def horizon_summary(rows: Sequence[Dict[str, Any]]) -> List[str]:
    observed = [row for row in rows if row.get("post_service_path_fib_observation_ms") != ""]
    values = [float(row["post_service_path_fib_observation_ms"]) for row in observed]
    lines = [
        "Final handoffs use capture end, not a following handoff. "
        "post_service_path_fib_observation_ms is remaining evidence after service-path FIB correctness, not a performance metric. "
        "A directly observed service-path installation is not right-censored.",
    ]
    for limit in (100.0, 500.0, 1000.0):
        selected = [row for row in observed if float(row["post_service_path_fib_observation_ms"]) < limit]
        lines.append(f"post_service_path_fib_observation_ms < {limit:.0f}: {len(selected)}")
        for row in selected:
            lines.append(
                f"  {row['configuration']}/{row['run_id']} h{row['handoff_index']} "
                f"{row['fib_stability_scope']} remaining={float(row['post_service_path_fib_observation_ms']):.3f} ms "
                f"service_fib={row['service_path_fib_convergence_ms']}"
            )
    if values:
        lines.append(summarise("post-service-FIB observation", values))
    return lines


def endpoint_shift_summary(rows: Sequence[Dict[str, Any]], delays: Sequence[Dict[str, Any]]) -> List[str]:
    lines = ["NLSR registration to NFD RIB-success delay on service-path required routers:"]
    delta = numeric(delays, "nfd_minus_nlsr_ms")
    lines.append(summarise("router update NFD minus NLSR", delta))
    lines.append("Per-configuration change of service_path_fib_convergence_ms if the formal endpoint is NFD success:")
    for configuration in ("G0", "G1", "G2", "G3", "G4", "OptoFlood"):
        selected = [row for row in rows if row["configuration"] == configuration and row["_nlsr_service_ms"] != "" and row["_nfd_service_ms"] != ""]
        if not selected:
            lines.append(f"{configuration}: no paired service-path endpoints")
            continue
        change = [abs(float(row["_nfd_service_ms"]) - float(row["_nlsr_service_ms"])) for row in selected]
        changed = sum(1 for value in change if value > 0.05)
        lines.append(
            f"{configuration}: paired={len(selected)} changed={changed} "
            f"median_abs={statistics.median(change):.6g} max_abs={max(change):.6g} "
            f"old_median={statistics.median(float(row['_nlsr_service_ms']) for row in selected):.6g} "
            f"new_median={statistics.median(float(row['_nfd_service_ms']) for row in selected):.6g}"
        )
    return lines


def write_summary(
    path_csv: Path,
    path_txt: Path,
    rows: Sequence[Dict[str, Any]],
    handoff_leads: Sequence[Dict[str, Any]],
    raw_pairs: Sequence[Dict[str, Any]],
) -> None:
    """Numeric summaries. Right-censored network rows stay in total_n and out of the quartiles."""
    records: List[Dict[str, Any]] = []
    labels = ("G0", "G1", "G2", "G3", "G4", "OptoFlood")

    def add(metric: str, configuration: str, selected: Sequence[Dict[str, Any]], field_name: str, censored: int) -> None:
        values = numeric(selected, field_name)
        if values:
            q1, median, q3 = quantiles(values)
            record = {
                "metric": metric,
                "configuration": configuration,
                "total_n": len(selected) if metric != "service_path_lsa_lead_raw_pairs" else len(selected),
                "numeric_n": len(values),
                "censored_n": censored,
                "median": median,
                "q1": q1,
                "q3": q3,
                "mean": statistics.fmean(values),
                "min": min(values),
                "max": max(values),
            }
        else:
            record = {
                "metric": metric, "configuration": configuration, "total_n": len(selected),
                "numeric_n": 0, "censored_n": censored, "median": "", "q1": "", "q3": "",
                "mean": "", "min": "", "max": "",
            }
        records.append(record)

    for configuration in labels:
        selected = [row for row in rows if row["configuration"] == configuration]
        add("topology_update_latency_ms", configuration, selected, "topology_update_latency_ms", 0)
        add("service_path_fib_convergence_ms", configuration, selected, "service_path_fib_convergence_ms", 0)
        censored = sum(1 for row in selected if row.get("network_fib_converged") == "false")
        add("network_fib_convergence_ms", configuration, selected, "network_fib_convergence_ms", censored)
    add("service_path_lsa_lead_ms", "OptoFlood", handoff_leads, "median_lead_ms", 0)
    add("service_path_lsa_lead_raw_pairs", "OptoFlood", raw_pairs, "lead_ms", 0)
    write_csv(path_csv, records)
    lines = []
    for record in records:
        lines.append(
            f"{record['metric']} {record['configuration']}: total_n={record['total_n']} "
            f"numeric_n={record['numeric_n']} censored_n={record['censored_n']} "
            f"median={record['median']} q1={record['q1']} q3={record['q3']} "
            f"mean={record['mean']} min={record['min']} max={record['max']}"
        )
    path_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


# The three Section IV-C panels share one row at about 0.31\textwidth.
# Width follows the old 7.2 in / 0.72\textwidth scale so type stays readable.
# A little extra height holds the two-line OptoFlood label.
ROUTING_ROW_FIGSIZE = (7.2 * 0.31 / 0.72, 4.4 * 0.31 / 0.72 + 0.28)


def _draw_log_boxes(axis, labels, data, totals, censor_marks, ylabel: str, compact: bool = False) -> None:
    from matplotlib.cbook import boxplot_stats
    from plot_mobility_event_metrics import MEANPROPS, WHIS, positive_log_bounds

    axis.boxplot(
        [list(values) for values in data],
        positions=list(range(len(labels))),
        whis=WHIS,
        showfliers=True,
        showmeans=True,
        meanprops=MEANPROPS,
    )
    tick_labels = []
    visible: List[float] = []
    labeled = False
    for index, (label, values) in enumerate(zip(labels, data)):
        text = label if compact else f"{label}\nn={totals[index]}"
        marks = censor_marks[index]
        if marks and not compact:
            text += f"\n{len(marks)} right-censored"
        if marks:
            axis.scatter(
                [index] * len(marks), marks, marker="v", s=36, color="crimson", zorder=5,
                label=None if labeled else "right-censored",
            )
            labeled = True
            visible.extend(marks)
        visible.extend(values)
        tick_labels.append(text)
        stats = boxplot_stats(list(values), whis=WHIS)[0]
        print(
            f"{label} {ylabel}: total_events={totals[index]} numeric={len(values)} censored={len(marks)} "
            f"median={float(stats['med']):.6g}"
        )
    axis.set_xticks(list(range(len(labels))))
    if compact:
        # OptoFlood is wider than one category slot. A line break keeps every
        # label horizontal at the existing canvas width.
        shown = ["Opto-\nFlood" if label == "OptoFlood" else label for label in tick_labels]
        axis.set_xticklabels(shown, rotation=0)
    else:
        axis.set_xticklabels(tick_labels)
    axis.set_ylabel(ylabel)
    low, high = positive_log_bounds(visible)
    axis.set_yscale("log")
    axis.set_ylim(low, high)
    axis.grid(True, axis="y", linestyle="--", alpha=0.6)
    # The column panel's caption identifies the censor marker. An in-axes
    # legend covers the boxes at this canvas size.
    if labeled and not compact:
        axis.legend(loc="best")


def plot_production_figures(results: Path, rows: Sequence[Dict[str, Any]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["G0", "G1", "G2", "G3", "G4", "OptoFlood"]
    topology = []
    for label in labels:
        selected = [row for row in rows if row["configuration"] == label]
        topology.append(numeric(selected, "topology_update_latency_ms"))
    _save_routing_column_panel(
        results / "routing_topology_update_latency.pdf",
        labels, topology, [[] for _ in labels],
        "Topology update latency (ms)",
    )

    service_data = []
    network_data = []
    network_marks = []
    for label in labels:
        selected = [row for row in rows if row["configuration"] == label]
        service_data.append(numeric(selected, "service_path_fib_convergence_ms"))
        network_data.append(numeric(selected, "network_fib_convergence_ms"))
        network_marks.append([
            float(row["network_fib_censor_boundary_ms"])
            for row in selected
            if row.get("network_fib_converged") == "false" and row.get("network_fib_censor_boundary_ms") != ""
        ])
    figure, axes = plt.subplots(2, 1, figsize=(7.2, 8.6))
    _draw_log_boxes(
        axes[0], labels, service_data, [40] * 6, [[] for _ in labels],
        "Service-path FIB convergence time (ms)",
    )
    axes[0].set_title("(a) Service-path FIB convergence")
    _draw_log_boxes(
        axes[1], labels, network_data, [40] * 6, network_marks,
        "Network-wide FIB convergence time (ms)",
    )
    axes[1].set_title("(b) Network-wide FIB convergence")
    figure.tight_layout()
    figure.savefig(results / "routing_fib_convergence.pdf")
    plt.close(figure)

    # Paper panels. The stacked PDF above remains a diagnostic output.
    _save_routing_column_panel(
        results / "routing_service_path_fib_convergence.pdf",
        labels, service_data, [[] for _ in labels],
        "FIB convergence (ms)",
    )
    _save_routing_column_panel(
        results / "routing_network_fib_convergence.pdf",
        labels, network_data, network_marks,
        "FIB convergence (ms)",
    )


def _save_routing_column_panel(path: Path, labels, data, censor_marks, ylabel: str) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=ROUTING_ROW_FIGSIZE)
    _draw_log_boxes(
        axis, labels, data, [40] * len(labels), censor_marks,
        ylabel, compact=True,
    )
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def require_routing_evidence(results: Path) -> bool:
    """Fail before measurement when logs or handoff records are absent."""
    profiles = (
        "g0-h60-a10-r15-s60",
        "g1-h54-a9-r14-s54",
        "g2-h48-a8-r12-s48",
        "g3-h42-a7-r10-s42",
        "g4-h36-a6-r9-s36",
    )
    required: List[Path] = []
    run_dirs = [results / "baseline" / profile / run_id for profile in profiles for run_id in ("r1", "r2", "r3", "r4", "r5")]
    run_dirs.extend(results / "solution" / run_id for run_id in ("r1", "r2", "r3", "r4", "r5"))
    for run_dir in run_dirs:
        required.append(run_dir / "handoffs.txt")
        required.append(run_dir / "mobility_packets.csv")
        for node in NODES:
            required.append(run_dir / "minindn-logs" / node / "nlsr.log")
        for node in ROUTING_UNIVERSE:
            required.append(run_dir / "minindn-logs" / node / "nfd.log")
    missing = [path for path in required if not path.is_file()]
    for path in missing:
        print(f"required routing evidence missing: {path}", file=sys.stderr)
    return not missing


def main(diagnostic: bool = False) -> int:
    root = Path(__file__).resolve().parents[2]
    results = root / "results"
    output = results / "routing"
    profiles = [
        ("G0", "g0-h60-a10-r15-s60", False),
        ("G1", "g1-h54-a9-r14-s54", False),
        ("G2", "g2-h48-a8-r12-s48", False),
        ("G3", "g3-h42-a7-r10-s42", False),
        ("G4", "g4-h36-a6-r9-s36", False),
    ]
    rows: List[Dict[str, Any]] = []
    leads: List[Dict[str, Any]] = []
    delays: List[Dict[str, Any]] = []
    if not require_routing_evidence(results):
        return 1
    notes: List[str] = [
        "TFIB standby requires fibAgrees to remain true for TFIB_FIB_STABLE_WINDOW = 5000 ms "
        "before Active becomes Standby. It is not the first instant the FIB is correct.",
        "Prioritised timestamps are inbound corridor Adj-LSA Data, not availability Interests and not LSDB insertion.",
        "topology_update_latency_ms is the local Adj-LSA build/install. It is not NLSR Sync publication.",
        "TFIB_FIB_STABLE_WINDOW is 5000 ms in daemon/fw/forwarder.cpp. Standby is not FIB convergence.",
    ]
    for configuration, profile, _accelerated in profiles:
        for run_id in ("r1", "r2", "r3", "r4", "r5"):
            run_rows, run_leads, run_notes, run_delays = measure_run(
                results / "baseline" / profile / run_id, configuration, profile, run_id, False,
            )
            rows.extend(run_rows)
            leads.extend(run_leads)
            notes.extend(run_notes)
            delays.extend(run_delays)
    for run_id in ("r1", "r2", "r3", "r4", "r5"):
        run_rows, run_leads, run_notes, run_delays = measure_run(
            results / "solution" / run_id, "OptoFlood", "solution", run_id, True,
        )
        rows.extend(run_rows)
        leads.extend(run_leads)
        notes.extend(run_notes)
        delays.extend(run_delays)
    formal = per_handoff_leads(leads)
    covered = {(str(row["run_id"]), int(row["handoff_index"])) for row in formal}
    for row in rows:
        if row["configuration"] != "OptoFlood":
            continue
        key = (str(row["run_id"]), int(row["handoff_index"]))
        if key not in covered:
            notes.append(f"OptoFlood/{row['run_id']} h{row['handoff_index']}: no same-router corridor-Data/Sync pair")
    nfd_service_complete = all(row.get("_nfd_service_ms", "") != "" for row in rows)
    if not nfd_service_complete:
        print("NFD_CONFIRMED service-path coverage is incomplete; refusing a mixed FIB endpoint", file=sys.stderr)
        return 1
    level = "NFD_CONFIRMED"
    shift_lines = endpoint_shift_summary(rows, delays)
    ecmp_rows = sum(1 for row in rows if row.get("_ecmp"))
    apply_evidence_level(rows, level)
    endpoint_lines = [
        "Formal FIB endpoint: "
        + (
            "NFD_CONFIRMED. Timestamp is NFD 'RIB update succeeded' for Name=/LiveStream, "
            "Action=REGISTER, origin=nlsr, after FibUpdater's FIB nexthop command succeeds. "
            "faceId is bound to FaceUri by NLSR lines that print both identifiers. "
            "Unrelated prefixes, non-NLSR origins, and unbound faceIds are ignored."
            if level == "NFD_CONFIRMED"
            else
            "NLSR_CONFIRMED. NFD success could not be tied to the correct next hop for every "
            "required service-path router, so the formal time remains the NLSR /LiveStream add."
        ),
        f"Evidence level is uniform: {level}.",
        "Router universe for network-wide convergence: "
        + ", ".join(ROUTING_UNIVERSE)
        + ". Producer is excluded because it does not register a transit /LiveStream next hop.",
        "A router is affected when its minimum-cost next-hop set toward the producer changes. "
        "Unchanged routers are not convergence blockers.",
        "Equal-cost next hops are retained as a set. NLSR installs one parent on a tie; "
        "a non-empty installed subset of the minimum-cost set is correct. "
        f"Events whose acceptable set had size > 1: {ecmp_rows}.",
        "Network-wide time is the latest affected router at NFD_CONFIRMED. "
        "If an affected router has not installed the new next hop by the event boundary, "
        "the handoff stays in the sample as right-censored: network_fib_converged=false, "
        "network_fib_convergence_ms is blank, and network_fib_censor_boundary_ms is the "
        "observation duration. That boundary is not a convergence time and is excluded from box statistics.",
        "Service-path installation that is directly observed is not censored, even when little time remains before capture end.",
        "TFIB standby uses TFIB_FIB_STABLE_WINDOW = 5000 ms and is not FIB convergence.",
        "No ablation is implied by differences among these times.",
    ]
    write_csv(output / "routing_events.csv", rows)
    write_csv(output / "service_path_priority_lead_pairs.csv", leads)
    write_csv(output / "service_path_lsa_lead.csv", formal)
    labels = ("G0", "G1", "G2", "G3", "G4", "OptoFlood")
    summary = []
    for configuration in labels:
        selected = [row for row in rows if row["configuration"] == configuration]
        summary.append(summarise(f"{configuration} topology update", numeric(selected, "topology_update_latency_ms")))
        summary.append(summarise(f"{configuration} service-path FIB", numeric(selected, "service_path_fib_convergence_ms")))
        summary.append(summarise(f"{configuration} first required router", numeric(selected, "first_required_router_correct_ms")))
        numeric_network = numeric(selected, "network_fib_convergence_ms")
        censored = sum(1 for row in selected if row.get("network_fib_converged") == "false")
        summary.append(summarise(f"{configuration} network FIB", numeric_network))
        summary.append(f"{configuration} network total={len(selected)} numeric={len(numeric_network)} right_censored={censored}")
        deltas = [
            float(row["network_fib_convergence_ms"]) - float(row["service_path_fib_convergence_ms"])
            for row in selected
            if row["network_fib_convergence_ms"] != "" and row["service_path_fib_convergence_ms"] != ""
        ]
        summary.append(summarise(f"{configuration} network minus service (descriptive)", deltas))
    opto = [row for row in rows if row["configuration"] == "OptoFlood"]
    summary.append(summarise("OptoFlood NLSR Sync trigger", numeric(opto, "nlsr_sync_trigger_latency_ms")))
    summary.append(summarise("OptoFlood TFIB standby", numeric(opto, "tfib_standby_fib_agrees_ms")))
    summary.append(summarise("raw router-handoff LSA lead", numeric(leads, "lead_ms")))
    summary.append(summarise("per-handoff LSA lead", numeric(formal, "median_lead_ms")))
    srt_lines = srt_sanity(results, rows)
    horizons = horizon_summary(rows)
    audit_lines = endpoint_lines + [""] + shift_lines + [""] + summary + [""] + srt_lines + [""] + horizons + [""] + notes
    (output / "routing_audit.txt").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")
    write_summary(output / "routing_summary.csv", output / "routing_summary.txt", rows, formal, leads)
    plot_production_figures(results, rows)
    if diagnostic:
        plot_boxes(
            output / "routing_service_path_lsa_lead.pdf",
            [("OptoFlood", numeric(formal, "median_lead_ms"))],
            "Service-path LSA lead (ms)",
        )
        plot_boxes(
            output / "routing_service_vs_network_fib.pdf",
            [
                (configuration, [
                    float(row["network_fib_convergence_ms"]) - float(row["service_path_fib_convergence_ms"])
                    for row in rows
                    if row["configuration"] == configuration
                    and row["network_fib_convergence_ms"] != ""
                    and row["service_path_fib_convergence_ms"] != ""
                ])
                for configuration in labels
            ],
            "Network-wide minus service-path FIB time (ms)",
        )
        plot_boxes(
            output / "routing_stage_decomposition.pdf",
            [
                ("verify", numeric(opto, "verification_complete_ms")),
                ("topology update", numeric(opto, "topology_update_latency_ms")),
                ("first router", numeric(opto, "first_required_router_correct_ms")),
                ("path FIB", numeric(opto, "service_path_fib_convergence_ms")),
                ("NLSR Sync trigger", numeric(opto, "nlsr_sync_trigger_latency_ms")),
            ],
            "Time after handoff (ms)",
            log_y=True,
        )
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
