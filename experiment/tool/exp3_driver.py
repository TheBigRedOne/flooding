"""Exp3 Mini-NDN driver. One clock schedules every active producer.

Importing this module loads Mini-NDN. Host-side tests use exp3_config instead.
"""

from time import monotonic, sleep, time as wall_time
import os
import sys
from typing import Dict, List

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
        if mode == "full" and run_id not in cfg.RUN_IDS:
            raise cfg.Exp3ConfigError(f"EXP3_RUN_ID must be r1..r5; got {run_id!r}")
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
        handle.write("producer\tindex\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n")
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

    for node_name in cfg.physical_hosts(population):
        node = ndn.net[node_name]
        pcap_path = os.path.join(results_dir, "pcap_nodes", f"{node_name}.pcap")
        log_path = os.path.join(results_dir, f"tcpdump_{node_name}.log")
        node.cmd(f"tcpdump -i any -U -w {pcap_path} udp port 6363 &> {log_path} &")

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
    cursor = 0.0
    handoff_path = os.path.join(results_dir, "handoffs.txt")
    by_index = {pair.index: pair for pair in selected}
    for when, producer_index, index, source, destination, interval_s in cfg.plan_events(selected, schedules, mode):
        pair = by_index[producer_index]
        _wait(max(0.0, when - cursor), ndn, managed, health_path, started)
        cursor = when
        info(f"Handoff {pair.producer} #{index}: {source} -> {destination}\n")
        absolute = wall_time()
        ndn.net.configLinkStatus(pair.producer, source, "down")
        ndn.net.configLinkStatus(pair.producer, destination, "up")
        with open(handoff_path, "a", encoding="utf-8") as handle:
            handle.write(
                f"{pair.producer}\t{index}\t{absolute:.6f}\t{absolute - started:.6f}\t"
                f"{source}\t{destination}\t{interval_s:.6f}\n"
            )
    _wait(max(0.0, common_end - cursor), ndn, managed, health_path, started)
    for node_name in cfg.physical_hosts(population):
        pcap_path = os.path.join(results_dir, "pcap_nodes", f"{node_name}.pcap")
        ndn.net[node_name].cmd(f"pkill -f '{pcap_path}' || true")
    _wait(1.0, ndn, managed, health_path, started, "absent-before-shutdown")
    _stop_managed(ndn, managed, health_path, started)
    ndn.stop()
    return 0


def cfg_daemon() -> str:
    return "optoflood-daemon"


def _pid_alive(node, pid: int) -> bool:
    output = node.cmd(f"kill -0 {pid} >/dev/null 2>&1; echo $?")
    return procs.trailing_status(output) == "0"


def _cmdline(node, pid: int) -> str:
    return node.cmd(f"tr '\\0' ' ' < /proc/{pid}/cmdline 2>/dev/null || true").strip()


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


def _wait(seconds: float, ndn: Minindn, managed: List[procs.ManagedProcess],
          health_path: str, origin: float, detail: str = "absent-during-observation") -> None:
    deadline = monotonic() + max(0.0, seconds)
    while True:
        _poll(ndn, managed, health_path, origin, detail)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(1.0, remaining))


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
