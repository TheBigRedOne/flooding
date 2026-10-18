"""Exp3 Mini-NDN driver. One clock schedules every active producer.

Importing this module loads Mini-NDN. Host-side tests use exp3_config instead.
"""

from time import sleep, time as wall_time
import os
import sys
from typing import Dict

import exp
import exp3_config as cfg

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
    daemon_exec = os.path.join(experiment_dir, cfg_daemon())
    event_driven = (os.getenv("NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION") or "").strip().lower() == "on"
    for pair in selected:
        producer = ndn.net[pair.producer]
        producer_env = f"{app_common} EXP_ADVERTISED_PREFIX={pair.prefix}"
        producer.cmd(
            f"{producer_env} {os.path.join(experiment_dir, 'producer')} &> "
            f"{os.path.join(results_dir, pair.producer + '.log')} &"
        )
        consumer_env = (
            f"{app_common} EXP_STREAM_PREFIX={pair.prefix} EXP_CONSUMER_ID={pair.consumer} "
            f"EXP_TRUST_SCHEMA={schema_path}"
        )
        ndn.net[pair.consumer].cmd(
            f"{consumer_env} {os.path.join(experiment_dir, 'consumer')} &> "
            f"{os.path.join(results_dir, pair.consumer + '.log')} &"
        )
        if os.path.exists(daemon_exec):
            consumer_daemon_env = (
                f"GUARD_PREFIX={pair.prefix} EXP_GUARD_INTERVAL_MS={guard_interval_ms}"
            )
            producer_daemon_env = (
                f"{consumer_daemon_env} OPTOFLOOD_PRODUCER_INDEX={pair.index}"
                + (" OPTOFLOOD_NLSR_VERIFY_NOW=1" if event_driven else "")
            )
            producer.cmd(
                f"{producer_daemon_env} {daemon_exec} producer &> "
                f"{os.path.join(results_dir, 'optoflood_' + pair.producer + '.log')} &"
            )
            ndn.net[pair.consumer].cmd(
                f"{consumer_daemon_env} {daemon_exec} consumer &> "
                f"{os.path.join(results_dir, 'optoflood_' + pair.consumer + '.log')} &"
            )

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
    cursor = 0.0
    handoff_path = os.path.join(results_dir, "handoffs.txt")
    by_index = {pair.index: pair for pair in selected}
    for when, producer_index, index, source, destination, interval_s in cfg.plan_events(selected, schedules, mode):
        pair = by_index[producer_index]
        sleep(max(0.0, when - cursor))
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
    sleep(max(0.0, common_end - cursor))
    for node_name in cfg.physical_hosts(population):
        pcap_path = os.path.join(results_dir, "pcap_nodes", f"{node_name}.pcap")
        ndn.net[node_name].cmd(f"pkill -f '{pcap_path}' || true")
    sleep(1)
    ndn.stop()
    return 0


def cfg_daemon() -> str:
    return "optoflood-daemon"


if __name__ == "__main__":
    sys.exit(main())
