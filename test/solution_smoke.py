"""One-handoff Solution integration smoke."""

import os
import sys
import time

from mininet.log import info, setLogLevel
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.minindn import Minindn

from smoke_runtime import (
    NLSR_INITIAL_WAIT_S,
    POLL_S,
    PRE_HANDOFF_WARMUP_S,
    PREFIX,
    READY_TIMEOUT_S,
    SMOKE_INACTIVE_ATTACHMENTS,
    SMOKE_PRODUCER_ATTACHMENTS,
    BranchTopo,
    TunableNlsr,
    collect_nfd,
    launch_apps,
    launch_daemons,
    missing_producer_attachment_faces,
    prepare_identity,
    prepare_producer_mobility_faces,
    results_dir,
    wait_until,
    write_handoff,
)
from smoke_validate import (
    fresh_post_handoff_delivery,
    pre_handoff_status,
)


SOLUTION_NLSR = (
    ("neighbors.result-driven-adj-lsa-build", "on"),
    ("neighbors.event-driven-adjacency-verification", "on"),
    ("neighbors.corridor-prioritised-routing", "on"),
    ("neighbors.corridor-adj-lsa-sync-publish-delay", "1"),
    ("neighbors.event-driven-verification-timeout-ms", "50"),
)


def _read(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _wait_pre_handoff(consumer_log: str, daemon_log: str, r3) -> None:
    """After the formal minimum wait, require business, guard, and r3 FIB separately."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    business = guard = fib_ready = False
    fib_text = ""
    while time.monotonic() < deadline:
        fib_text = r3.cmd("nfdc fib list")
        business, guard, fib_ready = pre_handoff_status(
            _read(consumer_log), _read(daemon_log), fib_text,
        )
        if business and guard and fib_ready:
            info(
                "smoke ready: business delivery, held guard, and r3 /LiveStream FIB\n"
            )
            return
        time.sleep(POLL_S)
    diag = os.path.join(os.path.dirname(consumer_log), "r3_fib_before_handoff.txt")
    with open(diag, "w", encoding="utf-8") as handle:
        handle.write(fib_text)
    raise TimeoutError(
        "pre-handoff readiness failed "
        f"business={business} guard={guard} fib={fib_ready}; saved {diag}"
    )


def main() -> None:
    experiment_dir = os.environ["EXPERIMENT_DIR"]
    output_dir = results_dir(experiment_dir)
    ndn = None
    nfd_nodes = None
    try:
        for name in os.listdir(output_dir):
            path = os.path.join(output_dir, name)
            if os.path.isfile(path):
                os.remove(path)
        Minindn.cleanUp()
        Minindn.verifyDependencies()
        ndn = Minindn(topo=BranchTopo())
        ndn.start()
        info("Starting NFD\n")
        AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
        producer = ndn.net["producer"]
        consumer = ndn.net["consumer"]
        routers = [ndn.net[name] for name in ("r1", "r2", "r3", "r4", "r5")]
        nfd_nodes = [producer, consumer, *routers]
        prepare_producer_mobility_faces(ndn, SMOKE_PRODUCER_ATTACHMENTS)
        for attachment in SMOKE_INACTIVE_ATTACHMENTS:
            ndn.net.configLinkStatus("producer", attachment, "down")
        missing, face_list = missing_producer_attachment_faces(ndn)
        face_path = os.path.join(output_dir, "producer_faces_after_inactive_down.txt")
        with open(face_path, "w", encoding="utf-8") as handle:
            handle.write(face_list)
        if missing:
            raise RuntimeError(
                "permanent mobility faces missing after inactive links were disabled: "
                + ", ".join(missing)
            )
        info("Starting full-solution NLSR\n")
        AppManager(
            ndn, ndn.net.hosts, TunableNlsr, logLevel="DEBUG", infoeditChanges=SOLUTION_NLSR,
        )
        info(f"Waiting {NLSR_INITIAL_WAIT_S}s for NLSR initial convergence\n")
        time.sleep(NLSR_INITIAL_WAIT_S)
        prepare_identity(producer)
        binary_dir = os.path.dirname(experiment_dir)
        launch_apps(producer, consumer, binary_dir, output_dir)
        launch_daemons(producer, consumer, binary_dir, output_dir)
        info(f"Waiting {PRE_HANDOFF_WARMUP_S}s before the first handoff\n")
        time.sleep(PRE_HANDOFF_WARMUP_S)
        consumer_log = os.path.join(output_dir, "consumer.log")
        daemon_log = os.path.join(output_dir, "optoflood_producer.log")
        _wait_pre_handoff(consumer_log, daemon_log, ndn.net["r3"])
        handoff_ns = time.time_ns()
        write_handoff(output_dir, handoff_ns, "r2", "r3")
        info(f"Handoff producer r2 -> r3 at {handoff_ns} for {PREFIX}\n")
        ndn.net.configLinkStatus("producer", "r2", "down")
        ndn.net.configLinkStatus("producer", "r3", "up")

        def recovered(text: str) -> bool:
            return fresh_post_handoff_delivery(text, handoff_ns)

        wait_until(
            consumer_log,
            recovered,
            READY_TIMEOUT_S,
            "post-handoff fresh content",
        )
        collect_nfd(nfd_nodes, output_dir)
    except Exception:
        if nfd_nodes is not None:
            try:
                collect_nfd(nfd_nodes, output_dir)
            except Exception as collect_error:
                print(
                    f"solution smoke could not collect NFD logs: {collect_error}",
                    file=sys.stderr,
                )
        raise
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
