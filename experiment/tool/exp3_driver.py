"""Exp3 Mini-NDN driver. One clock schedules every active producer.

Importing this module loads Mini-NDN. Host-side tests use exp3_config instead.
"""

from time import monotonic, sleep, time as wall_time
import os
import sys
from typing import Dict, List, Optional, Tuple

import exp
import exp3_config as cfg
import exp3_processes as procs

from mininet.log import info, setLogLevel
from mininet.topo import Topo
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.helpers.nfdc import Nfdc
from minindn.minindn import Minindn


class Exp3Topo(Topo):
    """Nine-node backbone plus the producer-consumer pairs selected for this population."""

    population = 1

    def build(self) -> None:
        for name in cfg.physical_hosts(self.population):
            self.addHost(name)
        for left, right, bandwidth, delay in cfg.links(self.population):
            self.addLink(left, right, bw=bandwidth, delay=delay)


def _prepare_faces(ndn: Minindn, producer_name: str) -> None:
    producer = ndn.net[producer_name]
    for access_name in cfg.MOBILITY_ACCESSES:
        access = ndn.net[access_name]
        connections = producer.connectionsTo(access)
        if len(connections) != 1:
            raise RuntimeError(f"{producer_name}--{access_name}: expected one link, found {len(connections)}")
        producer_intf, access_intf = connections[0]
        producer_ip = producer_intf.IP()
        access_ip = access_intf.IP()
        if not producer_ip or not access_ip:
            raise RuntimeError(f"{producer_name}--{access_name}: missing interface address")
        for node, remote, label in (
            (producer, access_ip, f"{producer_name}->{access_name}"),
            (access, producer_ip, f"{access_name}->{producer_name}"),
        ):
            face_id = Nfdc.createFace(node, remote, Nfdc.PROTOCOL_UDP, isPermanent=True, allowExisting=True)
            if face_id == -1:
                raise RuntimeError(f"mobility face preparation failed: {label}")


def main() -> int:
    setLogLevel("info")
    experiment_dir = os.getenv("EXPERIMENT_DIR")
    if not experiment_dir:
        print("Error: EXPERIMENT_DIR environment variable is not set")
        return 1
    results_dir = os.path.join(experiment_dir, "results")
    os.makedirs(os.path.join(results_dir, "pcap_nodes"), exist_ok=True)
    os.makedirs(os.path.join(results_dir, "certs"), exist_ok=True)
    try:
        population = cfg.parse_population(os.getenv("EXP3_POPULATION") or "")
        mode = (os.getenv("EXP3_SCHEDULE") or "smoke").strip()
        if mode not in {"smoke", "full"}:
            raise cfg.Exp3ConfigError(f"EXP3_SCHEDULE must be smoke or full; got {mode!r}")
        run_id = "smoke" if mode == "smoke" else (os.getenv("EXP3_RUN_ID") or "").strip()
        if mode == "full" and run_id not in cfg.RUN_IDS and run_id != cfg.PILOT_RUN_ID:
            raise cfg.Exp3ConfigError(f"EXP3_RUN_ID must be r1..r5 or pilot; got {run_id!r}")
        run_seed = cfg.run_seed_for(run_id, os.getenv("EXP3_RUN_SEED") or "")
        selected = cfg.pairs_for(population)
        if mode == "smoke":
            schedules = {pair.index: cfg.smoke_intervals() for pair in selected}
        else:
            schedules = {pair.index: cfg.sample_intervals(run_seed, pair.index) for pair in selected}
        ends = {pair.index: cfg.schedule_end(schedules[pair.index]) for pair in selected}
        common_end = max(ends.values())
        interval_changes, nlsr_applied = exp._load_nlsr_interval_overrides()
        feature_changes, feature_params = exp._load_nlsr_feature_overrides()
        scalar_changes, scalar_params = exp._load_nlsr_scalar_overrides()
        request_interval_ms = exp._load_request_interval_ms()
        window_frames = exp._load_positive_int_env("EXP_WINDOW_FRAMES", 4)
        segments_per_frame = exp._load_positive_int_env("EXP_SEGMENTS_PER_FRAME", 1)
        guard_interval_ms = exp._load_positive_int_env("EXP_GUARD_INTERVAL_MS", 1000)
    except (ValueError, cfg.Exp3ConfigError) as error:
        print(f"Error: {error}")
        return 1

    with open(os.path.join(results_dir, "campaign.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            f"exp3_campaign={cfg.CAMPAIGN_ID}\n"
            f"exp3_population=p{population}\n"
            f"exp3_schedule={mode}\n"
            f"exp3_run_id={run_id}\n"
            f"exp3_run_seed={run_seed}\n"
            f"common_end_s={common_end:.6f}\n"
        )
    with open(os.path.join(results_dir, "topology.txt"), "w", encoding="utf-8") as handle:
        handle.write(cfg.topology_text(population))
    with open(os.path.join(results_dir, "schedules.txt"), "w", encoding="utf-8") as handle:
        handle.write("producer\tindex\tseed\tintervals_s\tplanned_end_s\tfinal_observation_end_s\n")
        for pair in selected:
            intervals = schedules[pair.index]
            handle.write(
                f"{pair.producer}\t{pair.index}\t{cfg.producer_seed(run_seed, pair.index)}\t"
                + ",".join(f"{value:.6f}" for value in intervals)
                + f"\t{ends[pair.index]:.6f}\t{ends[pair.index]:.6f}\n"
            )
    with open(os.path.join(results_dir, "handoffs.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            "producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s"
            "\tplanned_rel_s\tlateness_s\n"
        )
    exp._write_nlsr_params_file(
        results_dir, {**nlsr_applied, **feature_params, **scalar_params},
        8 if mode == "full" else 1,
        cfg.INTERVAL_BASE_S, cfg.INTERVAL_JITTER_S,
        list(selected[0].sequence[:2] if mode == "smoke" else selected[0].sequence), request_interval_ms, window_frames, segments_per_frame,
        guard_interval_ms, None,
    )
    with open(os.path.join(results_dir, "params.txt"), "a", encoding="utf-8") as handle:
        handle.write(f"exp3_campaign={cfg.CAMPAIGN_ID}\n")
        handle.write(f"exp3_population=p{population}\n")
        handle.write(f"exp3_schedule={mode}\n")
        handle.write(f"exp3_run_id={run_id}\n")
        handle.write(f"exp3_run_seed={run_seed}\n")
        handle.write(f"common_end_s={common_end:.6f}\n")
        handle.write("exp3_interval_source=" + ("configured" if mode == "smoke" else "sampled") + "\n")
        for pair in selected:
            handle.write(
                f"producer{pair.index}_prefix={pair.prefix}\n"
                f"producer{pair.index}_guard={pair.guard}\n"
                f"producer{pair.index}_identity={pair.identity}\n"
                f"producer{pair.index}_sequence={','.join(pair.sequence if mode == 'full' else pair.sequence[:2])}\n"
                f"producer{pair.index}_planned_end_s={ends[pair.index]:.6f}\n"
                f"producer{pair.index}_final_observation_end_s={ends[pair.index]:.6f}\n"
            )

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    Exp3Topo.population = population
    ndn = Minindn(topo=Exp3Topo())
    ndn.start()
    info("Starting NFD on nodes\n")
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
    for pair in selected:
        _prepare_faces(ndn, pair.producer)
        for access_name in cfg.MOBILITY_ACCESSES:
            if access_name != pair.initial:
                ndn.net.configLinkStatus(pair.producer, access_name, "down")
    info("Starting NLSR on nodes\n")
    nlsr_infoedit = (interval_changes or []) + feature_changes + scalar_changes
    nlsr_kwargs: Dict[str, object] = {"logLevel": "DEBUG"}
    if nlsr_infoedit:
        nlsr_kwargs["infoeditChanges"] = nlsr_infoedit
    AppManager(ndn, ndn.net.hosts, exp.TunableNlsr, **nlsr_kwargs)
    sleep(30)

    cert_paths = []
    for pair in selected:
        node = ndn.net[pair.producer]
        cert_path = os.path.join(results_dir, "certs", f"{pair.producer}.cert")
        node.cmd(f"ndnsec key-gen {pair.identity} >/dev/null 2>&1")
        node.cmd(f"ndnsec cert-dump -i {pair.identity} > {cert_path}")
        node.cmd(f"ndnsec key-gen -n {cfg.MGMT_IDENTITY} >/dev/null 2>&1")
        cert_paths.append(cert_path)
    schema_path = os.path.join(results_dir, "trust-schema.conf")
    with open(schema_path, "w", encoding="utf-8") as handle:
        handle.write(cfg.trust_schema_text(cert_paths))

    captures: List[procs.Capture] = []
    inflight: Optional[procs.Capture] = None
    try:
        for node_name in cfg.physical_hosts(population):
            node = ndn.net[node_name]
            pcap_path = os.path.join(results_dir, "pcap_nodes", f"{node_name}.pcap")
            log_path = os.path.join(results_dir, f"tcpdump_{node_name}.log")
            pid = _launch(
                node, "", "tcpdump", f"-i any -U -w {pcap_path} udp port 6363", log_path,
            )
            inflight = procs.Capture(node_name, pid, pcap_path, log_path)
            _await_capture(node, node_name, pid, pcap_path, log_path)
            captures.append(inflight)
            inflight = None
    except procs.ProcessError as error:
        print(f"Error: {error}")
        if inflight is not None:
            captures.append(inflight)
        _stop_owned_captures(ndn, captures)
        ndn.stop()
        return 1

    app_common = (
        f"EXP_REQUEST_INTERVAL_MS={request_interval_ms}"
        f" EXP_WINDOW_FRAMES={window_frames}"
        f" EXP_SEGMENTS_PER_FRAME={segments_per_frame}"
        f" EXP_LOG_VALIDATION_NAME=1"
    )
    producer_exec = os.path.join(experiment_dir, "producer")
    consumer_exec = os.path.join(experiment_dir, "consumer")
    daemon_exec = os.path.join(experiment_dir, cfg_daemon())
    if not os.path.exists(daemon_exec):
        print(f"Error: Exp3 requires {daemon_exec}")
        return 1
    event_driven = (os.getenv("NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION") or "").strip().lower() == "on"
    managed: List[procs.ManagedProcess] = []
    try:
        for pair in selected:
            producer = ndn.net[pair.producer]
            producer_env = f"{app_common} EXP_ADVERTISED_PREFIX={pair.prefix}"
            producer_log = os.path.join(results_dir, pair.producer + ".log")
            managed.append(procs.ManagedProcess(
                pair.producer, "producer-app",
                _launch(producer, producer_env, producer_exec, "", producer_log),
                producer_exec, ""))
            consumer_env = (
                f"{app_common} EXP_STREAM_PREFIX={pair.prefix} EXP_CONSUMER_ID={pair.consumer} "
                f"EXP_TRUST_SCHEMA={schema_path}"
            )
            consumer_log = os.path.join(results_dir, pair.consumer + ".log")
            managed.append(procs.ManagedProcess(
                pair.consumer, "consumer-app",
                _launch(ndn.net[pair.consumer], consumer_env, consumer_exec, "", consumer_log),
                consumer_exec, ""))
            consumer_daemon_env = (
                f"GUARD_PREFIX={pair.prefix} EXP_GUARD_INTERVAL_MS={guard_interval_ms}"
            )
            producer_daemon_env = (
                f"{consumer_daemon_env} OPTOFLOOD_PRODUCER_INDEX={pair.index}"
                + (" OPTOFLOOD_NLSR_VERIFY_NOW=1" if event_driven else "")
            )
            producer_daemon_log = os.path.join(results_dir, "optoflood_" + pair.producer + ".log")
            managed.append(procs.ManagedProcess(
                pair.producer, "producer-daemon",
                _launch(producer, producer_daemon_env, daemon_exec, "producer", producer_daemon_log),
                daemon_exec, "producer"))
            consumer_daemon_log = os.path.join(results_dir, "optoflood_" + pair.consumer + ".log")
            managed.append(procs.ManagedProcess(
                pair.consumer, "consumer-daemon",
                _launch(ndn.net[pair.consumer], consumer_daemon_env, daemon_exec, "consumer",
                        consumer_daemon_log),
                daemon_exec, "consumer"))
    except procs.ProcessError as error:
        print(f"Error: {error}")
        if managed:
            failed_health = os.path.join(results_dir, "process-health.txt")
            with open(failed_health, "w", encoding="utf-8") as handle:
                handle.write(procs.HEALTH_HEADER)
            _stop_managed(ndn, managed, failed_health, wall_time())
        ndn.stop()
        return 1

    started = wall_time()
    mono_origin = monotonic()
    with open(os.path.join(results_dir, "observation_ends.txt"), "w", encoding="utf-8") as handle:
        handle.write("producer\tindex\trel_end_s\tabs_end\n")
        for pair in selected:
            handle.write(
                f"{pair.producer}\t{pair.index}\t{ends[pair.index]:.6f}\t"
                f"{started + ends[pair.index]:.6f}\n"
            )
    with open(os.path.join(results_dir, "params.txt"), "a", encoding="utf-8") as handle:
        handle.write(f"mobility_clock_origin_abs={started:.6f}\n")
        for pair in selected:
            handle.write(
                f"producer{pair.index}_final_observation_abs={started + ends[pair.index]:.6f}\n"
            )
    health_path = os.path.join(results_dir, "process-health.txt")
    with open(health_path, "w", encoding="utf-8") as handle:
        handle.write(procs.HEALTH_HEADER)
    capture_path = os.path.join(results_dir, "capture-health.txt")
    with open(capture_path, "w", encoding="utf-8") as handle:
        handle.write("host\tpid\tevent\trel_s\tdetail\n")
    for capture in captures:
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\tstarted\t0.000000\ttcpdump\n"
        ))
    handoff_path = os.path.join(results_dir, "handoffs.txt")
    by_index = {pair.index: pair for pair in selected}
    lateness_by_producer: Dict[str, List[float]] = {pair.producer: [] for pair in selected}
    for when, producer_index, index, source, destination, interval_s in cfg.plan_events(selected, schedules, mode):
        pair = by_index[producer_index]
        _wait_until(mono_origin + when, ndn, managed, captures, health_path, capture_path, started)
        absolute = wall_time()
        actual_rel = absolute - started
        late = cfg.scheduling_lateness(actual_rel, when)
        lateness_by_producer[pair.producer].append(late)
        info(f"Handoff {pair.producer} #{index}: {source} -> {destination}\n")
        ndn.net.configLinkStatus(pair.producer, source, "down")
        ndn.net.configLinkStatus(pair.producer, destination, "up")
        with open(handoff_path, "a", encoding="utf-8") as handle:
            handle.write(
                f"{pair.producer}\t{index}\t{absolute:.6f}\t{actual_rel:.6f}\t"
                f"{source}\t{destination}\t{interval_s:.6f}\t{when:.6f}\t{late:.6f}\n"
            )
    _wait_until(mono_origin + common_end, ndn, managed, captures, health_path, capture_path, started)
    _finish_captures(ndn, captures, capture_path, started, common_end)
    _stop_managed(ndn, managed, health_path, started)
    _write_timing_summary(os.path.join(results_dir, "timing-summary.txt"), lateness_by_producer)
    ndn.stop()
    return 0


def cfg_daemon() -> str:
    return "optoflood-daemon"


def _process_state(node, pid: int) -> str:
    return procs.process_state(node.cmd(f"cat /proc/{pid}/stat 2>/dev/null || true"))


def _pid_alive(node, pid: int) -> bool:
    """A zombie is not a running capture. kill -0 succeeds on a zombie."""
    return procs.pid_state_is_running(_process_state(node, pid))


def _cmdline(node, pid: int) -> str:
    return node.cmd(f"tr '\\0' ' ' < /proc/{pid}/cmdline 2>/dev/null || true").strip()


def _capture_snapshot(node, pid: int) -> Tuple[str, str]:
    output = node.cmd(
        "echo __STATE__; cat /proc/{0}/stat 2>/dev/null || true; "
        "echo __CMDLINE__; tr '\\0' ' ' < /proc/{0}/cmdline 2>/dev/null || true".format(pid)
    )
    return procs.split_capture_observation(output)


def _await_capture(node, host: str, pid: int, pcap_path: str, log_path: str) -> None:
    """Poll until tcpdump owns this PCAP, or fail on exit, mismatch, or deadline."""
    deadline = monotonic() + procs.CAPTURE_STARTUP_TIMEOUT_S
    while True:
        state, cmdline = _capture_snapshot(node, pid)
        status = procs.capture_startup_status(state, cmdline, pcap_path)
        if status == "ready":
            return
        if status == "wait" and monotonic() < deadline:
            sleep(procs.CAPTURE_STARTUP_POLL_S)
            continue
        if status == "wait":
            status = "timeout"
        try:
            log_text = open(log_path, encoding="utf-8", errors="replace").read()
        except OSError:
            log_text = ""
        raise procs.ProcessError(procs.capture_failure_message(
            host, pid, status, state, cmdline, log_text))


def _stop_owned_captures(ndn: Minindn, captures: List[procs.Capture]) -> None:
    for capture in captures:
        node = ndn.net[capture.host]
        if procs.capture_stop_allowed(_cmdline(node, capture.pid), capture.pcap):
            node.cmd(f"kill -TERM {capture.pid} >/dev/null 2>&1 || true")


def _launch(node, env: str, executable: str, argument: str, log_path: str) -> int:
    output = node.cmd(procs.background_launch(env, executable, argument, log_path))
    return procs.parse_background_pid(output)


def _record(path: str, row: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(row)


def _poll(ndn: Minindn, managed: List[procs.ManagedProcess], health_path: str,
          origin: float, detail: str) -> None:
    rel_s = wall_time() - origin
    for proc in managed:
        if proc.premature or _pid_alive(ndn.net[proc.host], proc.pid):
            continue
        proc.premature = True
        _record(health_path, procs.health_row(
            proc.host, proc.kind, proc.pid, "premature-exit", rel_s, detail))


def _poll_captures(ndn: Minindn, captures: List[procs.Capture], capture_path: str, origin: float) -> None:
    rel_s = wall_time() - origin
    for capture in captures:
        if capture.dead:
            continue
        node = ndn.net[capture.host]
        if _pid_alive(node, capture.pid) and procs.command_owns_capture(
                _cmdline(node, capture.pid), capture.pcap):
            continue
        capture.dead = True
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\terror\t{rel_s:.6f}\tdied-during-observation\n"
        ))


def _wait_until(deadline: float, ndn: Minindn, managed: List[procs.ManagedProcess],
                captures: List[procs.Capture], health_path: str, capture_path: str, origin: float) -> None:
    """Sleep until an absolute monotonic deadline. A passed deadline does not wait."""
    while True:
        _poll(ndn, managed, health_path, origin, "absent-during-observation")
        _poll_captures(ndn, captures, capture_path, origin)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(1.0, remaining))


def _finish_captures(ndn: Minindn, captures: List[procs.Capture], capture_path: str,
                     origin: float, common_end: float) -> None:
    """Stop tcpdump after the common endpoint and while NFD is still up."""
    for capture in captures:
        node = ndn.net[capture.host]
        rel_s = wall_time() - origin
        if capture.dead or not _pid_alive(node, capture.pid):
            capture.dead = True
            _record(capture_path, (
                f"{capture.host}\t{capture.pid}\trunning-at-common-end\t{rel_s:.6f}\tdead\n"
            ))
            continue
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\trunning-at-common-end\t{common_end:.6f}\talive\n"
        ))
        if not procs.command_owns_capture(_cmdline(node, capture.pid), capture.pcap):
            _record(capture_path, (
                f"{capture.host}\t{capture.pid}\tshutdown-refused\t{rel_s:.6f}\tcmdline-mismatch\n"
            ))
            continue
        node.cmd(f"kill -TERM {capture.pid} >/dev/null 2>&1 || true")
        deadline = monotonic() + 3.0
        while monotonic() < deadline and _pid_alive(node, capture.pid):
            sleep(0.1)
        if _pid_alive(node, capture.pid) and procs.command_owns_capture(
                _cmdline(node, capture.pid), capture.pcap):
            node.cmd(f"kill -KILL {capture.pid} >/dev/null 2>&1 || true")
            sleep(0.1)
        stopped = wall_time() - origin
        if _pid_alive(node, capture.pid):
            _record(capture_path, (
                f"{capture.host}\t{capture.pid}\tfinalized\t{stopped:.6f}\tstill-alive\n"
            ))
            continue
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\tstopped\t{stopped:.6f}\tsigterm-after-common-end\n"
        ))
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\tfinalized\t{stopped:.6f}\texited\n"
        ))
        try:
            log_text = open(capture.log, encoding="utf-8", errors="replace").read()
        except OSError:
            log_text = ""
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\tdrops\t{stopped:.6f}\t"
            f"{procs.tcpdump_drop_detail(log_text)}\n"
        ))
        try:
            payload = open(capture.pcap, "rb").read()
        except OSError:
            payload = b""
        status, count = procs.inspect_pcap(payload)
        _record(capture_path, (
            f"{capture.host}\t{capture.pid}\tdecode\t{stopped:.6f}\t{status} packets={count}\n"
        ))


def _write_timing_summary(path: str, lateness_by_producer: Dict[str, List[float]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("scope\tn\tmax_lateness_s\tmedian_lateness_s\tp90_lateness_s\n")
        combined: List[float] = []
        for producer in sorted(lateness_by_producer):
            values = lateness_by_producer[producer]
            combined.extend(values)
            if not values:
                continue
            maximum, median, upper = cfg.lateness_summary(values)
            handle.write(
                f"{producer}\t{len(values)}\t{maximum:.6f}\t{median:.6f}\t{upper:.6f}\n"
            )
        if combined:
            maximum, median, upper = cfg.lateness_summary(combined)
            handle.write(f"run\t{len(combined)}\t{maximum:.6f}\t{median:.6f}\t{upper:.6f}\n")
        handle.write("review\tlateness-recorded-not-thresholded\n")


def _stop_managed(ndn: Minindn, managed: List[procs.ManagedProcess],
                  health_path: str, origin: float) -> None:
    """Signal only the processes this driver started, while NFD is still up."""
    for proc in managed:
        node = ndn.net[proc.host]
        if proc.premature:
            continue
        if not _pid_alive(node, proc.pid):
            proc.premature = True
            _record(health_path, procs.health_row(
                proc.host, proc.kind, proc.pid, "premature-exit",
                wall_time() - origin, "absent-before-shutdown"))
            continue
        cmdline = _cmdline(node, proc.pid)
        if not procs.command_owns_pid(cmdline, proc.executable, proc.role):
            _record(health_path, procs.health_row(
                proc.host, proc.kind, proc.pid, "shutdown-refused",
                wall_time() - origin, "cmdline-mismatch"))
            continue
        node.cmd(f"kill -TERM {proc.pid} >/dev/null 2>&1 || true")
        deadline = monotonic() + 2.0
        while monotonic() < deadline and _pid_alive(node, proc.pid):
            sleep(0.1)
        if _pid_alive(node, proc.pid) and procs.command_owns_pid(
                _cmdline(node, proc.pid), proc.executable, proc.role):
            node.cmd(f"kill -KILL {proc.pid} >/dev/null 2>&1 || true")
            sleep(0.1)
        rel_s = wall_time() - origin
        if _pid_alive(node, proc.pid):
            _record(health_path, procs.health_row(
                proc.host, proc.kind, proc.pid, "shutdown-refused", rel_s, "still-alive"))
        else:
            _record(health_path, procs.health_row(
                proc.host, proc.kind, proc.pid, "intentional-shutdown",
                rel_s, "sigterm-before-nfd-stop"))


if __name__ == "__main__":
    sys.exit(main())
