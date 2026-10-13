"""Exp2 Mini-NDN driver for Shared and Distinct Streams.

The selected N=2 or N=4 population is the whole topology. EXP2_DEMAND_PATTERN
selects the consumer stream map; an unset value remains Shared Streams.
Importing this module loads Mini-NDN. Host-side tests use exp2_shared_config instead.
"""

from time import sleep, time as wall_time
import os
import random
import sys
from typing import Dict

import exp
import exp2_shared_config as cfg
import handoff_schedule

from mininet.log import info, setLogLevel
from mininet.topo import Topo
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.minindn import Minindn


class Exp2SharedTopo(Topo):
    """Solution routing graph plus the consumers selected for this population."""

    consumers = cfg.POPULATIONS["n2"]

    def build(self):
        for name in cfg.physical_hosts(self.consumers):
            self.addHost(name)
        for left, right, bandwidth, delay in cfg.links(self.consumers):
            self.addLink(left, right, bw=bandwidth, delay=delay)


def _positive_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {raw}") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative: {value}")
    return value


def _append_exp2_params(
    results_dir: str,
    active: tuple,
    mode: str,
    run_id: str,
    interval_source: str,
    realized_intervals: list,
    pattern: str,
    mapping: Dict[str, str],
) -> None:
    path = os.path.join(results_dir, "params.txt")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"exp2_experiment={pattern}\n")
        handle.write(f"exp2_demand_pattern={pattern}\n")
        handle.write(f"exp2_active_consumers={','.join(active)}\n")
        handle.write(f"exp2_schedule={mode}\n")
        handle.write(f"exp2_run_id={run_id}\n")
        handle.write(f"exp2_interval_source={interval_source}\n")
        handle.write(
            "exp2_realized_intervals_s="
            + ",".join(f"{float(value):.6f}" for value in realized_intervals)
            + "\n"
        )
        if pattern == "shared":
            handle.write(f"exp2_stream_prefix={cfg.STREAM_PREFIX}\n")
        handle.write(f"exp2_stream_map={cfg.format_stream_map(mapping)}\n")
        handle.write(f"exp2_advertised_prefix={cfg.ADVERTISED_PREFIX}\n")
        handle.write(f"exp2_guard_name={cfg.GUARD_NAME}\n")
        handle.write(f"exp2_campaign={cfg.campaign_id_for(pattern)}\n")
        handle.write(f"exp2_population={cfg.population_of(active)}\n")
        hosts = cfg.physical_hosts(active)
        handle.write(f"exp2_physical_node_count={len(hosts)}\n")
        handle.write("exp2_physical_nodes=" + ",".join(hosts) + "\n")
        handle.write("exp2_nlsr_hosts=" + ",".join(cfg.nlsr_hosts(active)) + "\n")
        handle.write("exp2_capture_nodes=" + ",".join(cfg.capture_nodes(active)) + "\n")
        handle.write("exp2_application_hosts=" + ",".join(cfg.application_hosts(active)) + "\n")
        handle.write("exp2_guard_daemon_hosts=" + ",".join(cfg.guard_daemon_hosts(active)) + "\n")


def main() -> int:
    setLogLevel("info")
    experiment_dir = os.getenv("EXPERIMENT_DIR")
    if not experiment_dir:
        print("Error: EXPERIMENT_DIR environment variable is not set")
        return 1
    results_dir = os.path.join(experiment_dir, "results")
    pcap_nodes_dir = os.path.join(results_dir, "pcap_nodes")
    handoffs_path = os.path.join(results_dir, "handoffs.txt")
    os.makedirs(pcap_nodes_dir, exist_ok=True)

    try:
        pattern = cfg.parse_demand_pattern(os.getenv("EXP2_DEMAND_PATTERN") or "shared")
        active = cfg.parse_active_consumers(os.getenv("EXP2_ACTIVE_CONSUMERS") or "")
        mapping = cfg.stream_mapping(pattern, active)
        mode = (os.getenv("EXP2_SCHEDULE") or "smoke").strip()
        warmup_s = _positive_float_env("EXP2_WARMUP_S", 20.0)
        tail_s = _positive_float_env("EXP2_TAIL_S", 30.0)
        plan = cfg.schedule_for(mode, warmup_s, tail_s)
        run_id = cfg.recorded_run_id(str(plan["mode"]), os.getenv("EXP2_RUN_ID") or "")
        interval_changes, nlsr_applied = exp._load_nlsr_interval_overrides()
        feature_changes, feature_params = exp._load_nlsr_feature_overrides()
        scalar_changes, scalar_params = exp._load_nlsr_scalar_overrides()
        request_interval_ms = exp._load_request_interval_ms()
        window_frames = exp._load_positive_int_env("EXP_WINDOW_FRAMES", 4)
        segments_per_frame = exp._load_positive_int_env("EXP_SEGMENTS_PER_FRAME", 1)
        guard_interval_ms = exp._load_positive_int_env("EXP_GUARD_INTERVAL_MS", 1000)
    except (ValueError, cfg.Exp2ConfigError) as error:
        print(f"Error: {error}")
        return 1

    sequence = list(plan["sequence"])
    handoff_count = int(plan["handoff_count"])
    interval_source = "configured"
    if plan["intervals_s"] is None:
        try:
            explicit_intervals = handoff_schedule.intervals_from_env(
                os.getenv("NLSR_HANDOFF_INTERVALS"), handoff_count,
            )
        except ValueError as error:
            print(f"Error: {error}")
            return 1
        handoff_base = float(os.getenv("NLSR_HANDOFF_INTERVAL_BASE") or cfg.FULL_INTERVAL_BASE_S)
        handoff_jitter = float(os.getenv("NLSR_HANDOFF_INTERVAL_JITTER") or cfg.FULL_INTERVAL_JITTER_S)
        if explicit_intervals is None:
            interval_source = "sampled"
            interval_rng = random.SystemRandom()
            explicit_intervals = [
                exp._sample_interval(handoff_base, handoff_jitter, interval_rng)
                for _ in range(handoff_count + 1)
            ]
    else:
        explicit_intervals = list(plan["intervals_s"])
        handoff_base = explicit_intervals[0]
        handoff_jitter = 0.0

    nlsr_infoedit = (interval_changes or []) + feature_changes + scalar_changes
    nlsr_applied.update(feature_params)
    nlsr_applied.update(scalar_params)
    exp._write_nlsr_params_file(
        results_dir, nlsr_applied, handoff_count, handoff_base, handoff_jitter,
        sequence, request_interval_ms, window_frames, segments_per_frame,
        guard_interval_ms, explicit_intervals,
    )
    _append_exp2_params(
        results_dir, active, str(plan["mode"]), run_id, interval_source, explicit_intervals,
        pattern, mapping,
    )
    with open(os.path.join(results_dir, "campaign.txt"), "w", encoding="utf-8") as handle:
        handle.write(cfg.campaign_text(active, str(plan["mode"]), run_id, pattern))
    with open(os.path.join(results_dir, "topology.txt"), "w", encoding="utf-8") as handle:
        handle.write(cfg.topology_text(active, sequence, pattern))
    exp._init_handoffs_file(handoffs_path)

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    Exp2SharedTopo.consumers = active
    ndn = Minindn(topo=Exp2SharedTopo())
    ndn.start()

    info("Starting NFD on nodes\n")
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
    exp._prepare_producer_mobility_faces(ndn)
    for access_name in cfg.PRODUCER_ATTACHMENTS:
        if access_name != cfg.INITIAL_ATTACHMENT:
            ndn.net.configLinkStatus("producer", access_name, "down")

    info("Starting NLSR on nodes\n")
    nlsr_kwargs: Dict[str, object] = {"logLevel": "DEBUG"}
    if nlsr_infoedit:
        nlsr_kwargs["infoeditChanges"] = nlsr_infoedit
        info(f"Applying NLSR overrides: {nlsr_applied}\n")
    AppManager(ndn, ndn.net.hosts, exp.TunableNlsr, **nlsr_kwargs)
    sleep(30)

    producer = ndn.net[cfg.PRODUCER_HOST]
    producer.cmd("ndnsec key-gen {} >/dev/null 2>&1".format(exp.PRODUCER_IDENTITY))
    producer.cmd("ndnsec cert-dump -i {} > {}".format(exp.PRODUCER_IDENTITY, exp.TRUST_ANCHOR_FILE))
    daemon_exec = os.path.join(experiment_dir, exp.OPTOFLOOD_DAEMON)
    if os.path.exists(daemon_exec):
        producer.cmd("ndnsec key-gen -n {} >/dev/null 2>&1".format(exp.OPTOFLOOD_MGMT_IDENTITY))

    for node_name in cfg.capture_nodes(active):
        node = ndn.net[node_name]
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        log_path = os.path.join(results_dir, f"tcpdump_{node_name}.log")
        node.cmd(f"tcpdump -i any -U -w {pcap_path} udp port 6363 &> {log_path} &")

    producer_exec = os.path.join(experiment_dir, "producer")
    consumer_exec = os.path.join(experiment_dir, "consumer")
    environments = cfg.process_environments(
        pattern, active, request_interval_ms, window_frames, segments_per_frame,
    )
    producer.cmd(
        f"{environments[cfg.PRODUCER_HOST]} {producer_exec} &> "
        f"{os.path.join(results_dir, 'producer.log')} &"
    )
    for consumer_name in active:
        log_path = os.path.join(results_dir, f"{consumer_name}.log")
        ndn.net[consumer_name].cmd(
            f"{environments[consumer_name]} {consumer_exec} &> {log_path} &"
        )

    if os.path.exists(daemon_exec):
        daemon_env = (
            f"GUARD_PREFIX={cfg.ADVERTISED_PREFIX} EXP_GUARD_INTERVAL_MS={guard_interval_ms}"
        )
        producer_daemon_env = daemon_env
        event_driven = (os.getenv("NLSR_EVENT_DRIVEN_ADJACENCY_VERIFICATION") or "").strip().lower()
        if event_driven == "on":
            producer_daemon_env += " OPTOFLOOD_NLSR_VERIFY_NOW=1"
        producer.cmd(
            f"{producer_daemon_env} {daemon_exec} producer &> "
            f"{os.path.join(results_dir, 'optoflood_producer.log')} &"
        )
        for consumer_name in active:
            ndn.net[consumer_name].cmd(
                f"{daemon_env} {daemon_exec} consumer &> "
                f"{os.path.join(results_dir, f'optoflood_{consumer_name}.log')} &"
            )

    sequence_start = wall_time()
    current_node = sequence[0]
    for index in range(1, handoff_count + 1):
        interval_s = explicit_intervals[index - 1]
        sleep(interval_s)
        next_node = sequence[index]
        info(f"Handoff #{index}: producer detaches from {current_node}, attaches to {next_node}\n")
        abs_time = wall_time()
        ndn.net.configLinkStatus("producer", current_node, "down")
        ndn.net.configLinkStatus("producer", next_node, "up")
        exp._append_handoff_row(
            handoffs_path, index, abs_time, abs_time - sequence_start,
            current_node, next_node, interval_s,
        )
        current_node = next_node
    sleep(explicit_intervals[handoff_count])

    for node_name in cfg.capture_nodes(active):
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        ndn.net[node_name].cmd(f"pkill -f '{pcap_path}' || true")
    sleep(1)
    ndn.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
