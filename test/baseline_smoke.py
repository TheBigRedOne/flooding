"""Stationary Baseline integration smoke."""

import os
import sys

from mininet.log import info, setLogLevel
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from minindn.minindn import Minindn

from smoke_runtime import (
    READY_TIMEOUT_S,
    StationaryTopo,
    launch_apps,
    prepare_identity,
    results_dir,
    wait_until,
)
from smoke_validate import discover_and_delivery


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
        ndn = Minindn(topo=StationaryTopo())
        ndn.start()
        info("Starting NFD and NLSR\n")
        AppManager(ndn, ndn.net.hosts, Nfd, logLevel="INFO")
        AppManager(ndn, ndn.net.hosts, Nlsr, logLevel="INFO")
        producer = ndn.net["producer"]
        consumer = ndn.net["consumer"]
        prepare_identity(producer)
        launch_apps(producer, consumer, os.path.dirname(experiment_dir), output_dir)
        consumer_log = os.path.join(output_dir, "consumer.log")
        wait_until(
            consumer_log,
            lambda text: discover_and_delivery(text) is None,
            READY_TIMEOUT_S,
            "baseline discovery and content delivery",
        )
    finally:
        if ndn is not None:
            ndn.stop()


if __name__ == "__main__":
    setLogLevel("info")
    try:
        main()
    except Exception as exc:
        print(f"baseline smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
