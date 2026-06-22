"""
Mini-NDN experiment driver for the baseline / solution mobility study.

Topology: six access points (acc1..acc6) connected via two aggregation switches
(agg1/agg2) to a core; consumer is fixed on acc1 and producer owns pre-built
producer-acc{2..6} links so that handoffs can be emulated by toggling link
status. acc2 is the initial active producer attachment; acc3..acc6 start down.

Behaviour is parameterised through environment variables (see _load_handoff_config
and _load_nlsr_interval_overrides) so the same driver supports the legacy
two-handoff baseline (default) and the K-handoff random-interval campaign
introduced for the disruption-vs-parameter study.
"""

from time import sleep, time as wall_time
import os
import random
from shlex import quote
from typing import Any, Dict, List, Optional, Tuple

from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI  # noqa: F401 (kept for interactive use)
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo


# Map NLSR-override env variables to nlsr.conf keys edited via infoedit.
NLSR_INTERVAL_ENV_TO_KEY = {
    'NLSR_HELLO_INTERVAL': 'neighbors.hello-interval',
    'NLSR_ADJ_LSA_BUILD_INTERVAL': 'neighbors.adj-lsa-build-interval',
    'NLSR_ROUTING_CALC_INTERVAL': 'fib.routing-calc-interval',
}

# Defaults preserve the legacy two-handoff baseline so unchanged callers keep
# their previous behaviour.
DEFAULT_HANDOFF_SEQUENCE: Tuple[str, ...] = ('acc2', 'acc3', 'acc4')
DEFAULT_HANDOFF_COUNT = 2
DEFAULT_HANDOFF_INTERVAL_BASE = 120.0
DEFAULT_HANDOFF_INTERVAL_JITTER = 0.0

# Access points that must start down so the experiment begins with the producer
# attached only via acc2.
NON_INITIAL_ACCESS_POINTS: Tuple[str, ...] = ('acc3', 'acc4', 'acc5', 'acc6')

# Per-node packet capture nodes used for downstream overhead analysis.
OVERHEAD_NODES: Tuple[str, ...] = (
    'core', 'agg1', 'agg2',
    'acc1', 'acc2', 'acc3', 'acc4', 'acc5', 'acc6',
    'producer', 'consumer',
)


def _load_nlsr_interval_overrides() -> Tuple[Optional[List[Tuple[str, str]]], Dict[str, str]]:
    """
    Read optional NLSR interval overrides from the environment.

    The three interval variables must either be provided together or omitted
    together. When present, values are validated as non-negative integers and
    converted into Mini-NDN infoeditChanges entries.
    """
    raw_values = {
        env_name: (os.getenv(env_name) or '').strip()
        for env_name in NLSR_INTERVAL_ENV_TO_KEY
    }
    provided = {env_name: value for env_name, value in raw_values.items() if value}
    if not provided:
        return None, {}

    missing = [env_name for env_name, value in raw_values.items() if not value]
    if missing:
        raise ValueError(
            'Incomplete NLSR interval override set. Missing: ' + ', '.join(sorted(missing))
        )

    infoedit_changes: List[Tuple[str, str]] = []
    applied_params: Dict[str, str] = {}
    for env_name, config_key in NLSR_INTERVAL_ENV_TO_KEY.items():
        value = raw_values[env_name]
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f'Invalid integer for {env_name}: {value}') from exc
        if parsed < 0:
            raise ValueError(f'Negative interval is not allowed for {env_name}: {value}')
        infoedit_changes.append((config_key, str(parsed)))
        applied_params[config_key] = str(parsed)

    profile_name = (os.getenv('NLSR_TUNING_PROFILE') or '').strip()
    if profile_name:
        applied_params['profile'] = profile_name

    return infoedit_changes, applied_params


def _load_handoff_config() -> Tuple[int, float, float, List[str]]:
    """
    Read handoff loop configuration from the environment.

    Returned tuple is (count, base_seconds, jitter_seconds, sequence). sequence
    has length = count + 1; sequence[0] is the initial access point and
    sequence[i] is the target of handoff i (1 <= i <= count).
    """
    raw_count = (os.getenv('NLSR_HANDOFF_COUNT') or '').strip()
    raw_base = (os.getenv('NLSR_HANDOFF_INTERVAL_BASE') or '').strip()
    raw_jitter = (os.getenv('NLSR_HANDOFF_INTERVAL_JITTER') or '').strip()
    raw_sequence = (os.getenv('NLSR_HANDOFF_SEQUENCE') or '').strip()

    try:
        count = int(raw_count) if raw_count else DEFAULT_HANDOFF_COUNT
        base_seconds = float(raw_base) if raw_base else DEFAULT_HANDOFF_INTERVAL_BASE
        jitter_seconds = float(raw_jitter) if raw_jitter else DEFAULT_HANDOFF_INTERVAL_JITTER
    except ValueError as exc:
        raise ValueError(f'Invalid NLSR_HANDOFF_* value: {exc}') from exc

    if count < 0:
        raise ValueError(f'NLSR_HANDOFF_COUNT must be non-negative: {count}')
    if base_seconds < 0:
        raise ValueError(f'NLSR_HANDOFF_INTERVAL_BASE must be non-negative: {base_seconds}')
    if jitter_seconds < 0:
        raise ValueError(f'NLSR_HANDOFF_INTERVAL_JITTER must be non-negative: {jitter_seconds}')

    if raw_sequence:
        sequence = [token.strip() for token in raw_sequence.split(',') if token.strip()]
    else:
        sequence = list(DEFAULT_HANDOFF_SEQUENCE)

    if len(sequence) < count + 1:
        raise ValueError(
            f'NLSR_HANDOFF_SEQUENCE has {len(sequence)} node(s), '
            f'requires at least {count + 1} for {count} handoff(s).'
        )
    return count, base_seconds, jitter_seconds, sequence[: count + 1]


def _load_request_interval_ms() -> int:
    """
    Read the consumer/producer request interval (frame period) in milliseconds.

    The value is supplied by the driver via EXP_REQUEST_INTERVAL_MS. 
    A 20 ms default keeps direct runs functional. 
    The consumer request cadence and the producer frame-generation cadence both use this value.
    """
    raw_value = (os.getenv('EXP_REQUEST_INTERVAL_MS') or '').strip()
    if not raw_value:
        return 20
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f'Invalid EXP_REQUEST_INTERVAL_MS: {raw_value}') from exc
    if value <= 0:
        raise ValueError(f'EXP_REQUEST_INTERVAL_MS must be positive: {value}')
    return value


def _write_nlsr_params_file(
    results_dir: str,
    nlsr_params: Dict[str, str],
    handoff_count: int,
    handoff_base: float,
    handoff_jitter: float,
    handoff_sequence: List[str],
    request_interval_ms: int,
) -> None:
    """Persist NLSR tuning parameters and handoff configuration to params.txt."""
    output_path = os.path.join(results_dir, 'params.txt')
    combined: Dict[str, str] = dict(nlsr_params)
    combined['handoff_count'] = str(handoff_count)
    combined['handoff_interval_base_s'] = f'{handoff_base:.3f}'
    combined['handoff_interval_jitter_s'] = f'{handoff_jitter:.3f}'
    combined['handoff_sequence'] = ','.join(handoff_sequence)
    combined['request_interval_ms'] = str(request_interval_ms)
    with open(output_path, 'w', encoding='utf-8') as output_file:
        for key in sorted(combined):
            output_file.write(f'{key}={combined[key]}\n')


def _init_handoffs_file(path: str) -> None:
    """Truncate handoffs.txt and write the header row."""
    with open(path, 'w', encoding='utf-8') as output_file:
        output_file.write('index\tabs_time\trel_time\tfrom_node\tto_node\tinterval_s\n')


def _append_handoff_row(
    path: str,
    index: int,
    abs_time: float,
    rel_time: float,
    from_node: str,
    to_node: str,
    interval_s: float,
) -> None:
    """Append one handoff record to handoffs.txt in tab-separated format."""
    with open(path, 'a', encoding='utf-8') as output_file:
        output_file.write(
            f'{index}\t{abs_time:.6f}\t{rel_time:.6f}\t'
            f'{from_node}\t{to_node}\t{interval_s:.6f}\n'
        )


def _sample_interval(base_seconds: float, jitter_seconds: float, rng: random.SystemRandom) -> float:
    """Draw a single handoff interval from base + Uniform(0, jitter)."""
    if jitter_seconds <= 0:
        return base_seconds
    return base_seconds + rng.uniform(0.0, jitter_seconds)


class TunableNlsr(Nlsr):
    """
    Nlsr wrapper for the Mini-NDN release used in the experiment VM.

    The baseline tuning study targets the installed 2024-08 Mini-NDN release,
    where NLSR is created first and then adjusted through infoedit against the
    generated nlsr.conf before the process starts.
    """

    def __init__(self, node, infoeditChanges=None, **kwargs):
        super().__init__(node, **kwargs)
        self._apply_manual_infoedit_changes(infoeditChanges)

    def _apply_manual_infoedit_changes(self, infoedit_changes):
        if not infoedit_changes:
            return

        conf_dir = getattr(self, 'homeDir', self.node.params['params']['homeDir'])
        conf_file = getattr(self, 'confFile', os.path.join(conf_dir, 'nlsr.conf'))
        for change in infoedit_changes:
            if len(change) < 2:
                continue
            key, value = change[0], change[1]
            operation = change[2] if len(change) > 2 else 'section'

            if operation == 'delete':
                command = f'cd {quote(conf_dir)} && infoedit -f {quote(os.path.basename(conf_file))} -d {quote(key)}'
            else:
                option = '-p' if operation == 'put' else '-s'
                command = (
                    f'cd {quote(conf_dir)} && '
                    f'infoedit -f {quote(os.path.basename(conf_file))} {option} {quote(key)} -v {quote(value)}'
                )
            self.node.cmd(command)


class CustomTopo(Topo):
    """
    Topology with one core, two aggregation switches and six access points.

    consumer is fixed on acc1. The producer owns pre-built producer-acc{2..6}
    links so that mobility events are emulated by toggling link status at
    runtime. acc2 is the initial active attachment; acc3..acc6 are taken down
    before the application traffic starts.
    """

    def build(self):
        core = self.addHost('core')

        agg1 = self.addHost('agg1')
        agg2 = self.addHost('agg2')

        acc1 = self.addHost('acc1')
        acc2 = self.addHost('acc2')
        acc3 = self.addHost('acc3')
        acc4 = self.addHost('acc4')
        acc5 = self.addHost('acc5')
        acc6 = self.addHost('acc6')

        producer = self.addHost('producer')
        consumer = self.addHost('consumer')

        self.addLink(core, agg1, bw=1000, delay='1ms')
        self.addLink(core, agg2, bw=1000, delay='1ms')

        self.addLink(agg1, acc1, bw=500, delay='5ms')
        self.addLink(agg1, acc2, bw=500, delay='5ms')
        self.addLink(agg1, acc3, bw=500, delay='5ms')

        self.addLink(agg2, acc4, bw=500, delay='5ms')
        self.addLink(agg2, acc5, bw=500, delay='5ms')
        self.addLink(agg2, acc6, bw=500, delay='5ms')

        self.addLink(consumer, acc1, bw=100, delay='5ms')
        self.addLink(producer, acc2, bw=100, delay='5ms')  # initial active link
        # Pre-built alternative producer attachments (initially down) for handoffs.
        self.addLink(producer, acc3, bw=100, delay='5ms')
        self.addLink(producer, acc4, bw=100, delay='5ms')
        self.addLink(producer, acc5, bw=100, delay='5ms')
        self.addLink(producer, acc6, bw=100, delay='5ms')


if __name__ == '__main__':
    setLogLevel('info')

    experiment_dir = os.getenv('EXPERIMENT_DIR')
    if not experiment_dir:
        print("Error: EXPERIMENT_DIR environment variable is not set")
        exit(1)
    results_dir = os.path.join(experiment_dir, "results")
    pcap_nodes_dir = os.path.join(results_dir, "pcap_nodes")
    handoffs_path = os.path.join(results_dir, "handoffs.txt")
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(pcap_nodes_dir, exist_ok=True)

    try:
        nlsr_infoedit_changes, nlsr_applied_params = _load_nlsr_interval_overrides()
    except ValueError as error:
        print(f"Error: {error}")
        exit(1)

    try:
        handoff_count, handoff_base, handoff_jitter, handoff_sequence = _load_handoff_config()
    except ValueError as error:
        print(f"Error: {error}")
        exit(1)

    try:
        request_interval_ms = _load_request_interval_ms()
    except ValueError as error:
        print(f"Error: {error}")
        exit(1)

    _write_nlsr_params_file(
        results_dir,
        nlsr_applied_params,
        handoff_count,
        handoff_base,
        handoff_jitter,
        handoff_sequence,
        request_interval_ms,
    )
    _init_handoffs_file(handoffs_path)

    Minindn.cleanUp()
    Minindn.verifyDependencies()

    ndn = Minindn(topo=CustomTopo())
    ndn.start()

    info('Starting NFD on nodes\n')
    nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel='DEBUG')
    info('Starting NLSR on nodes\n')
    nlsr_kwargs: Dict[str, Any] = {'logLevel': 'DEBUG'}
    if nlsr_infoedit_changes:
        nlsr_kwargs['infoeditChanges'] = nlsr_infoedit_changes
        info(f"Applying NLSR interval overrides: {nlsr_applied_params}\n")
    nlsrs = AppManager(ndn, ndn.net.hosts, TunableNlsr, **nlsr_kwargs)
    sleep(30)  # allow NLSR initial convergence

    # Leave only producer-acc2 active before the experiment starts.
    for ap in NON_INITIAL_ACCESS_POINTS:
        ndn.net.configLinkStatus('producer', ap, 'down')

    producer = ndn.net['producer']
    consumer = ndn.net['consumer']

    consumer_pcap = os.path.join(results_dir, "consumer_capture.pcap")
    tcpdump_log = os.path.join(results_dir, "tcpdump.log")
    consumer.cmd(f"tcpdump -i consumer-eth0 -w {consumer_pcap} &> {tcpdump_log} &")

    for node_name in OVERHEAD_NODES:
        node = ndn.net[node_name]
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        log_path = os.path.join(results_dir, f"tcpdump_{node_name}.log")
        node.cmd(f"tcpdump -i any -U -w {pcap_path} udp port 6363 &> {log_path} &")

    producer_exec = os.path.join(experiment_dir, "producer")
    consumer_exec = os.path.join(experiment_dir, "consumer")
    producer_log = os.path.join(experiment_dir, "results", "producer.log")
    consumer_log = os.path.join(experiment_dir, "results", "consumer.log")

    app_env = f"EXP_REQUEST_INTERVAL_MS={request_interval_ms}"
    producer.cmd(f"{app_env} {producer_exec} &> {producer_log} &")
    consumer.cmd(f"{app_env} {consumer_exec} &> {consumer_log} &")

    # The handoff loop runs K randomly-spaced toggles along handoff_sequence.
    # The first interval doubles as application warm-up before handoff #1.
    rng = random.SystemRandom()
    sequence_start_time = wall_time()
    current_node = handoff_sequence[0]
    for index in range(1, handoff_count + 1):
        interval_s = _sample_interval(handoff_base, handoff_jitter, rng)
        sleep(interval_s)
        next_node = handoff_sequence[index]
        info(f"Handoff #{index}: producer detaches from {current_node}, attaches to {next_node}\n")
        ndn.net.configLinkStatus('producer', current_node, 'down')
        ndn.net.configLinkStatus('producer', next_node, 'up')
        abs_time = wall_time()
        rel_time = abs_time - sequence_start_time
        _append_handoff_row(
            handoffs_path,
            index,
            abs_time,
            rel_time,
            current_node,
            next_node,
            interval_s,
        )
        current_node = next_node

    # Tail interval drawn from the same distribution to leave the last handoff
    # a full recovery window before tcpdump termination.
    sleep(_sample_interval(handoff_base, handoff_jitter, rng))

    consumer.cmd(f"pkill -f '{consumer_pcap}' || true")
    for node_name in OVERHEAD_NODES:
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        ndn.net[node_name].cmd(f"pkill -f '{pcap_path}' || true")
    sleep(1)

    ndn.stop()
