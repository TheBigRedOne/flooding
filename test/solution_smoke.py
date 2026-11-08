"""One-handoff Solution integration smoke."""

import os
import sys
import time

from mininet.log import info, setLogLevel
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.minindn import Minindn

from smoke_runtime import (
    PREFIX,
    READY_TIMEOUT_S,
    BranchTopo,
    TunableNlsr,
    collect_nfd,
    launch_apps,
    launch_daemons,
    prepare_identity,
    results_dir,
    wait_until,
    write_handoff,
)
from smoke_validate import _DELIVERED, app_events, discover_and_delivery


SOLUTION_NLSR = (
    ("neighbors.result-driven-adj-lsa-build", "on"),
    ("neighbors.event-driven-adjacency-verification", "on"),
    ("neighbors.corridor-prioritised-routing", "on"),
    ("neighbors.corridor-adj-lsa-sync-publish-delay", "1"),
    ("neighbors.event-driven-verification-timeout-ms", "50"),
)


def _delivered_frames(text: str):
    return [int(match.group(1)) for _timestamp, match in app_events(text, _DELIVERED)]


def main() -> None:
    experiment_dir = os.environ["EXPERIMENT_DIR"]
    output_dir = results_dir(experiment_dir)
    ndn = None
    try:
        for name in os.listdir(output_dir):
            path = os.path.join(output_dir, name)
            if os.path.isfile(path):
                os.remove(path)
        Minindn.cleanUp()
        Minindn.verifyDependencies()
        ndn = Minindn(topo=BranchTopo())
        ndn.start()
        info("Starting NFD and full-solution NLSR\n")
        AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
        AppManager(
            ndn, ndn.net.hosts, TunableNlsr, logLevel="DEBUG", infoeditChanges=SOLUTION_NLSR,
        )
        for attachment in ("r3", "r4", "r5"):
            ndn.net.configLinkStatus("producer", attachment, "down")
        producer = ndn.net["producer"]
        consumer = ndn.net["consumer"]
        routers = [ndn.net[name] for name in ("r1", "r2", "r3", "r4", "r5")]
        prepare_identity(producer)
        binary_dir = os.path.dirname(experiment_dir)
        launch_apps(producer, consumer, binary_dir, output_dir)
        launch_daemons(producer, consumer, binary_dir, output_dir)
        consumer_log = os.path.join(output_dir, "consumer.log")
        wait_until(
            consumer_log,
            lambda text: discover_and_delivery(text) is None and _delivered_frames(text),
            READY_TIMEOUT_S,
            "pre-handoff content delivery",
        )
        before = _delivered_frames(open(consumer_log, encoding="utf-8", errors="replace").read())
        last_pre = max(before)
        handoff_ns = time.time_ns()
        write_handoff(output_dir, handoff_ns, "r2", "r3")
        info(f"Handoff producer r2 -> r3 at {handoff_ns} for {PREFIX}\n")
        ndn.net.configLinkStatus("producer", "r2", "down")
        ndn.net.configLinkStatus("producer", "r3", "up")

        def recovered(text: str) -> bool:
            for timestamp, match in app_events(text, _DELIVERED):
                if timestamp > handoff_ns and int(match.group(1)) > last_pre:
                    return True
            return False

        wait_until(
            consumer_log,
            recovered,
            READY_TIMEOUT_S,
            "post-handoff fresh content",
        )
        collect_nfd([producer, consumer, *routers], output_dir)
    finally:
        if ndn is not None:
            ndn.stop()


if __name__ == "__main__":
    setLogLevel("info")
    try:
        main()
    except Exception as exc:
        print(f"solution smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
