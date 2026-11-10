"""Mini-NDN helpers for the two integration smokes."""

from __future__ import annotations

import os
import time
from shlex import quote

from mininet.log import info
from mininet.topo import Topo
from minindn.apps.nlsr import Nlsr


READY_TIMEOUT_S = 180
POLL_S = 0.5
PREFIX = "/LiveStream"


class TunableNlsr(Nlsr):
    """Apply infoedit after Mini-NDN writes nlsr.conf and before NLSR starts."""

    def __init__(self, node, infoeditChanges=None, **kwargs):
        super().__init__(node, **kwargs)
        if not infoeditChanges:
            return
        conf_dir = getattr(self, "homeDir", node.params["params"]["homeDir"])
        conf_file = getattr(self, "confFile", os.path.join(conf_dir, "nlsr.conf"))
        for key, value in infoeditChanges:
            node.cmd(
                f"cd {quote(conf_dir)} && "
                f"infoedit -f {quote(os.path.basename(conf_file))} "
                f"-s {quote(str(key))} -v {quote(str(value))}"
            )


class StationaryTopo(Topo):
    """Consumer and producer stay on one path. No second attachment."""

    def build(self):
        r1 = self.addHost("r1")
        r2 = self.addHost("r2")
        consumer = self.addHost("consumer")
        producer = self.addHost("producer")
        self.addLink(r1, r2, bw=1000, delay="1ms")
        self.addLink(consumer, r1, bw=100, delay="5ms")
        self.addLink(producer, r2, bw=100, delay="5ms")


class BranchTopo(Topo):
    """Linear chain r1–r4 with an r3–r5 branch. Producer starts on r2."""

    def build(self):
        r1 = self.addHost("r1")
        r2 = self.addHost("r2")
        r3 = self.addHost("r3")
        r4 = self.addHost("r4")
        r5 = self.addHost("r5")
        consumer = self.addHost("consumer")
        producer = self.addHost("producer")
        self.addLink(r1, r2, bw=1000, delay="1ms")
        self.addLink(r2, r3, bw=1000, delay="1ms")
        self.addLink(r3, r4, bw=1000, delay="1ms")
        self.addLink(r3, r5, bw=1000, delay="1ms")
        self.addLink(consumer, r1, bw=100, delay="5ms")
        self.addLink(producer, r2, bw=100, delay="5ms")
        self.addLink(producer, r3, bw=100, delay="5ms")
        self.addLink(producer, r4, bw=100, delay="5ms")
        self.addLink(producer, r5, bw=100, delay="5ms")


def results_dir(experiment_dir: str) -> str:
    path = os.path.join(experiment_dir, "results")
    os.makedirs(path, exist_ok=True)
    return path


def prepare_identity(producer) -> None:
    producer.cmd("ndnsec key-gen /LiveStream >/dev/null 2>&1")
    producer.cmd(
        "ndnsec cert-dump -i /LiveStream > "
        "/home/vagrant/flooding/experiment/app/livestream-trust-anchor.cert"
    )
    producer.cmd("ndnsec key-gen -n /localhost/optoflood >/dev/null 2>&1")


def launch_apps(producer, consumer, experiment_dir: str, output_dir: str) -> None:
    producer_log = os.path.join(output_dir, "producer.log")
    consumer_log = os.path.join(output_dir, "consumer.log")
    producer.cmd(f"{os.path.join(experiment_dir, 'producer')} &> {producer_log} &")
    consumer.cmd(f"{os.path.join(experiment_dir, 'consumer')} &> {consumer_log} &")


def launch_daemons(producer, consumer, experiment_dir: str, output_dir: str) -> None:
    daemon = os.path.join(experiment_dir, "optoflood-daemon")
    common = "GUARD_PREFIX=/LiveStream EXP_GUARD_INTERVAL_MS=1000"
    producer.cmd(
        f"{common} OPTOFLOOD_NLSR_VERIFY_NOW=1 {daemon} producer "
        f"&> {os.path.join(output_dir, 'optoflood_producer.log')} &"
    )
    consumer.cmd(
        f"{common} {daemon} consumer "
        f"&> {os.path.join(output_dir, 'optoflood_consumer.log')} &"
    )


def wait_until(path: str, ready, timeout_s: int, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                last = handle.read()
            if ready(last):
                info(f"smoke ready: {label}\n")
                return
        time.sleep(POLL_S)
    raise TimeoutError(f"timed out waiting for {label}; log bytes={len(last)}")


def collect_nfd(nodes, output_dir: str) -> None:
    for node in nodes:
        home = node.params["params"]["homeDir"]
        destination = os.path.join(output_dir, f"{node.name}_nfd.log")
        node.cmd(
            f"grep -E 'OptoFlood' {home}/log/nfd.log > {destination} 2>/dev/null || true"
        )


# Producer attachments in the smoke topology. Faces are created while every
# link is up; r3–r5 are then disabled before NLSR starts. r2 stays active.
SMOKE_PRODUCER_ATTACHMENTS = ("r2", "r3", "r4", "r5")
SMOKE_INACTIVE_ATTACHMENTS = ("r3", "r4", "r5")
# Formal exp.py sleeps 30 s after NLSR starts, then at least 90 s before the
# first handoff. The formal interval is 90 + Uniform(0, 60); smoke uses the
# lower bound so the wait is deterministic.
NLSR_INITIAL_WAIT_S = 30
PRE_HANDOFF_WARMUP_S = 90


def _attachment_ips(ndn, attachment: str):
    producer = ndn.net["producer"]
    access = ndn.net[attachment]
    connections = producer.connectionsTo(access)
    if len(connections) != 1:
        raise RuntimeError(
            f"producer--{attachment}: expected one link, found {len(connections)}"
        )
    producer_intf, access_intf = connections[0]
    producer_ip = producer_intf.IP()
    access_ip = access_intf.IP()
    if not producer_ip or not access_ip:
        raise RuntimeError(f"producer--{attachment}: missing interface address")
    return producer_ip, access_ip


def prepare_producer_mobility_faces(ndn, attachments=SMOKE_PRODUCER_ATTACHMENTS) -> None:
    """Create permanent UDP faces before inactive producer links are taken down."""
    from minindn.helpers.nfdc import Nfdc

    producer = ndn.net["producer"]
    for attachment in attachments:
        access = ndn.net[attachment]
        producer_ip, access_ip = _attachment_ips(ndn, attachment)
        for node, remote_ip, label in (
            (producer, access_ip, f"producer->{attachment}"),
            (access, producer_ip, f"{attachment}->producer"),
        ):
            face_id = Nfdc.createFace(
                node,
                remote_ip,
                Nfdc.PROTOCOL_UDP,
                isPermanent=True,
                allowExisting=True,
            )
            if face_id == -1:
                raise RuntimeError(
                    f"mobility face preparation failed: {label} udp://{remote_ip}"
                )


def producer_face_list(ndn) -> str:
    return ndn.net["producer"].cmd("nfdc face list")


def missing_producer_attachment_faces(ndn, attachments=SMOKE_PRODUCER_ATTACHMENTS):
    """Return attachment names whose remote IP is absent from the producer face list."""
    listing = producer_face_list(ndn)
    missing = []
    for attachment in attachments:
        _producer_ip, access_ip = _attachment_ips(ndn, attachment)
        if access_ip not in listing:
            missing.append(f"{attachment} {access_ip}")
    return missing, listing


def write_handoff(output_dir: str, handoff_ns: int, source: str, target: str) -> None:
    path = os.path.join(output_dir, "handoff.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            f"handoff_ns={handoff_ns}\nprefix={PREFIX}\nfrom={source}\nto={target}\n"
        )
