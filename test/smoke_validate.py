"""Parse integration-smoke logs. No Mini-NDN import."""

from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence, Tuple

PREFIX = "/LiveStream"
ARM_NAME = "/localhost/nfd/optoflood/arm/LiveStream"

_APP_LINE = re.compile(r"^\[(\d+)\]\s+(.*)$")
_NFD_LINE = re.compile(r"^(\d+\.\d+)\s+.*$")
_DELIVERED = re.compile(r"FRAME: delivered frame=(\d+)\b")
_DISCOVER = re.compile(r"DISCOVER: live edge = (\d+)\b")
_ARMED = re.compile(r"MOBILITY: armed NFD (\S+)")
_NFD_ARM = re.compile(r"OptoFlood arm prefix=(\S+)")
_NFD_FORWARD = re.compile(r"OptoFlood forward data=(\S+)")
_TFIB_UPDATE = re.compile(r"OptoFlood TFIB update prefix=(\S+)")
_TFIB_FORWARD = re.compile(r"OptoFlood tfib-forward interest=(\S+)")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def app_events(text: str, pattern: re.Pattern) -> List[Tuple[int, re.Match]]:
    found = []
    for line in text.splitlines():
        header = _APP_LINE.match(line.strip())
        if header is None:
            continue
        body = pattern.search(header.group(2))
        if body is not None:
            found.append((int(header.group(1)), body))
    return found


def nfd_events(text: str, pattern: re.Pattern) -> List[Tuple[float, re.Match]]:
    """NFD lines begin with a Unix timestamp in seconds."""
    found = []
    for line in text.splitlines():
        header = _NFD_LINE.match(line.strip())
        if header is None:
            continue
        body = pattern.search(line)
        if body is not None:
            found.append((float(header.group(1)), body))
    return found


def is_business_name(name: str) -> bool:
    return (
        name == PREFIX or name.startswith(PREFIX + "/")
    ) and "/_guard" not in name and "/_meta" not in name


def is_live_prefix(prefix: str) -> bool:
    return prefix == PREFIX or prefix.startswith(PREFIX + "/")


def load_handoff_ns(results_dir: str) -> int:
    path = os.path.join(results_dir, "handoff.txt")
    text = read_text(path)
    for line in text.splitlines():
        if line.startswith("handoff_ns="):
            return int(line.split("=", 1)[1].strip())
    raise ValueError("handoff.txt has no handoff_ns")


def discover_and_delivery(consumer_log: str) -> Optional[str]:
    discoveries = app_events(consumer_log, _DISCOVER)
    deliveries = app_events(consumer_log, _DELIVERED)
    if not discoveries:
        return "consumer log has no _meta live edge"
    if not deliveries:
        return "consumer log has no delivered Content frame"
    discover_ns = discoveries[0][0]
    if not any(timestamp >= discover_ns for timestamp, _match in deliveries):
        return "Content delivery is not after _meta discovery"
    return None


def check_baseline(results_dir: str) -> List[str]:
    errors = []
    consumer_path = os.path.join(results_dir, "consumer.log")
    producer_path = os.path.join(results_dir, "producer.log")
    if not os.path.isfile(consumer_path) or not os.path.isfile(producer_path):
        return ["baseline smoke is missing producer.log or consumer.log"]
    consumer_log = read_text(consumer_path)
    producer_log = read_text(producer_path)
    problem = discover_and_delivery(consumer_log)
    if problem is not None:
        errors.append(problem)
    if "PREFIX: Successfully advertised prefix via NLSR" not in producer_log:
        errors.append("producer did not advertise its prefix through NLSR")
    return errors


def _earliest(events: Sequence[Tuple[float, re.Match]], accept) -> Optional[Tuple[float, str]]:
    for timestamp, match in events:
        value = match.group(1)
        if accept(value):
            return timestamp, value
    return None


def check_solution(results_dir: str) -> List[str]:
    errors = []
    consumer_path = os.path.join(results_dir, "consumer.log")
    daemon_path = os.path.join(results_dir, "optoflood_producer.log")
    nfd_dir_files = [
        os.path.join(results_dir, name)
        for name in os.listdir(results_dir)
        if name.endswith("_nfd.log")
    ] if os.path.isdir(results_dir) else []
    if not os.path.isfile(consumer_path) or not os.path.isfile(daemon_path):
        return ["solution smoke is missing consumer.log or optoflood_producer.log"]
    try:
        handoff_ns = load_handoff_ns(results_dir)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    handoff_s = handoff_ns / 1_000_000_000.0
    consumer_log = read_text(consumer_path)
    daemon_log = read_text(daemon_path)
    deliveries = app_events(consumer_log, _DELIVERED)
    pre = [(timestamp, int(match.group(1))) for timestamp, match in deliveries if timestamp < handoff_ns]
    post = [(timestamp, int(match.group(1))) for timestamp, match in deliveries if timestamp > handoff_ns]
    if not pre:
        errors.append("no Content delivery before the handoff")
    else:
        last_pre = max(frame for _timestamp, frame in pre)
        fresh = [item for item in post if item[1] > last_pre]
        if not fresh:
            errors.append("no fresh Content frame delivered after the handoff")
    arms = [
        (timestamp, match.group(1))
        for timestamp, match in app_events(daemon_log, _ARMED)
        if timestamp >= handoff_ns and ARM_NAME in match.group(1)
    ]
    if not arms:
        errors.append("producer daemon did not arm /LiveStream at or after the handoff")
    nfd_text = "\n".join(read_text(path) for path in nfd_dir_files)
    nfd_arms = [
        item for item in nfd_events(nfd_text, _NFD_ARM)
        if item[0] >= handoff_s and is_live_prefix(item[1].group(1))
    ]
    forwards = [
        item for item in nfd_events(nfd_text, _NFD_FORWARD)
        if item[0] >= handoff_s and is_business_name(item[1].group(1))
    ]
    updates = [
        item for item in nfd_events(nfd_text, _TFIB_UPDATE)
        if item[0] >= handoff_s and is_live_prefix(item[1].group(1))
    ]
    uses = [
        item for item in nfd_events(nfd_text, _TFIB_FORWARD)
        if is_business_name(item[1].group(1))
    ]
    if not nfd_arms:
        errors.append("NFD did not record an OptoFlood arm for /LiveStream after the handoff")
    if not forwards:
        errors.append("NFD did not forward recovery Data for /LiveStream after the handoff")
    elif nfd_arms and min(item[0] for item in forwards) < min(item[0] for item in nfd_arms):
        errors.append("recovery Data forwarding precedes the NFD arm")
    if not updates:
        errors.append("NFD did not install a /LiveStream TFIB entry after the handoff")
    else:
        update_s = min(item[0] for item in updates)
        later_uses = [item for item in uses if item[0] >= update_s]
        if not later_uses:
            errors.append("no business Interest was forwarded by TFIB after the entry was installed")
    return errors
