from time import sleep
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo
import os
from typing import Dict, List, Optional, Tuple


NLSR_INTERVAL_ENV_TO_KEY = {
    'NLSR_HELLO_INTERVAL': 'neighbors.hello-interval',
    'NLSR_ADJ_LSA_BUILD_INTERVAL': 'neighbors.adj-lsa-build-interval',
    'NLSR_ROUTING_CALC_INTERVAL': 'fib.routing-calc-interval',
}


def _load_nlsr_interval_overrides() -> Tuple[Optional[List[Tuple[str, str]]], Optional[Dict[str, str]]]:
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
        return None, None

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


def _write_nlsr_params_file(results_dir: str, applied_params: Optional[Dict[str, str]]) -> None:
    """Persist the effective NLSR tuning parameters for later aggregation."""
    if not applied_params:
        return

    output_path = os.path.join(results_dir, 'params.txt')
    with open(output_path, 'w', encoding='utf-8') as output_file:
        for key in sorted(applied_params):
            output_file.write(f'{key}={applied_params[key]}\n')

class CustomTopo(Topo):
    def build(self):
        # add core switch
        core = self.addHost('core')

        # add aggregation switches
        agg1 = self.addHost('agg1')
        agg2 = self.addHost('agg2')

        # add access switches
        acc1 = self.addHost('acc1')
        acc2 = self.addHost('acc2')
        acc3 = self.addHost('acc3')
        acc4 = self.addHost('acc4')
        acc5 = self.addHost('acc5')
        acc6 = self.addHost('acc6')

        # add producer and consumer
        producer = self.addHost('producer')
        consumer = self.addHost('consumer')

        # set links
        self.addLink(core, agg1, bw=1000, delay='1ms')
        self.addLink(core, agg2, bw=1000, delay='1ms')

        self.addLink(agg1, acc1, bw=500, delay='5ms')
        self.addLink(agg1, acc2, bw=500, delay='5ms')
        self.addLink(agg1, acc3, bw=500, delay='5ms')

        self.addLink(agg2, acc4, bw=500, delay='5ms')
        self.addLink(agg2, acc5, bw=500, delay='5ms')
        self.addLink(agg2, acc6, bw=500, delay='5ms')

        # connect consumer and producer to switches
        self.addLink(consumer, acc1, bw=100, delay='5ms')
        self.addLink(producer, acc2, bw=100, delay='5ms')  # acc2 is the initial connection
        self.addLink(producer, acc3, bw=100, delay='5ms')  # pre-build producer-acc3
        self.addLink(producer, acc4, bw=100, delay='5ms')  # pre-build producer-acc4

if __name__ == '__main__':
    setLogLevel('info')

    # read experiment directory from environment variable
    experiment_dir = os.getenv('EXPERIMENT_DIR')
    if not experiment_dir:
        print("Error: EXPERIMENT_DIR environment variable is not set")
        exit(1)
    results_dir = os.path.join(experiment_dir, "results")
    pcap_nodes_dir = os.path.join(results_dir, "pcap_nodes")
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(pcap_nodes_dir, exist_ok=True)
    try:
        nlsr_infoedit_changes, nlsr_applied_params = _load_nlsr_interval_overrides()
    except ValueError as error:
        print(f"Error: {error}")
        exit(1)
    _write_nlsr_params_file(results_dir, nlsr_applied_params)

    Minindn.cleanUp()
    Minindn.verifyDependencies()

    # use custom topology
    ndn = Minindn(topo=CustomTopo())
    ndn.start()

    info('Starting NFD on nodes\n')
    nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel='DEBUG')
    info('Starting NLSR on nodes\n')
    nlsr_kwargs = {'logLevel': 'DEBUG'}
    if nlsr_infoedit_changes:
        nlsr_kwargs['infoeditChanges'] = nlsr_infoedit_changes
        info(f"Applying NLSR interval overrides: {nlsr_applied_params}\n")
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr, **nlsr_kwargs)
    sleep(30)  # wait for NLSR

    # disable producer-acc3&4 at beginning
    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'down')

    # deploy producer and consumer
    producer = ndn.net['producer']
    consumer = ndn.net['consumer']

    # enable tcpdump listening on consumer
    consumer_pcap = os.path.join(results_dir, "consumer_capture.pcap")
    tcpdump_log = os.path.join(results_dir, "tcpdump.log")
    consumer.cmd(f"tcpdump -i consumer-eth0 -w {consumer_pcap} &> {tcpdump_log} &")

    # Capture app-plane traffic (UDP/6363) on all nodes for network overhead analysis.
    overhead_nodes = ['core', 'agg1', 'agg2', 'acc1', 'acc2', 'acc3', 'acc4', 'acc5', 'acc6', 'producer', 'consumer']
    for node_name in overhead_nodes:
        node = ndn.net[node_name]
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        log_path = os.path.join(results_dir, f"tcpdump_{node_name}.log")
        node.cmd(f"tcpdump -i any -U -w {pcap_path} udp port 6363 &> {log_path} &")

    # enbale applications
    producer_exec = os.path.join(experiment_dir, "producer")
    consumer_exec = os.path.join(experiment_dir, "consumer")
    producer_log = os.path.join(experiment_dir, "results", "producer.log")
    consumer_log = os.path.join(experiment_dir, "results", "consumer.log")

    producer.cmd(f"{producer_exec} &> {producer_log} &")
    consumer.cmd(f"{consumer_exec} &> {consumer_log} &")
    sleep(120)

    # link state changes to emulate producer movement
    info('Switching producer to acc3\n')
    ndn.net.configLinkStatus('producer', 'acc2', 'down')
    ndn.net.configLinkStatus('producer', 'acc3', 'up')
    sleep(120)

    info('Switching producer to acc4\n')
    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'up')
    sleep(120)  # keep listening

    # terminate tcpdump and flush pcap files
    consumer.cmd(f"pkill -f '{consumer_pcap}' || true")
    for node_name in overhead_nodes:
        pcap_path = os.path.join(pcap_nodes_dir, f"{node_name}.pcap")
        ndn.net[node_name].cmd(f"pkill -f '{pcap_path}' || true")
    sleep(1)

    ndn.stop()
