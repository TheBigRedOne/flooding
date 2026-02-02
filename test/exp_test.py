from time import sleep
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo
import os
import shutil


class BranchTopo(Topo):
    """
    Purpose: Build R1–R2–R3–R4 linear chain with a branch at R3 to R5.
    Interface: consumer attaches to R1; producer initially attaches to R2, then moves to R3 for validation.
    Nodes: r1, r2, r3, r4, r5, consumer, producer.
    Links: r1-r2-r3-r4 chain; r3-r5 branch; consumer–r1; producer–r2 active; producer–r3/r4/r5 pre-created for mobility events.
    """

    def build(self):
        r1 = self.addHost('r1')
        r2 = self.addHost('r2')
        r3 = self.addHost('r3')
        r4 = self.addHost('r4')
        r5 = self.addHost('r5')

        consumer = self.addHost('consumer')
        producer = self.addHost('producer')

        # Backbone and branch
        self.addLink(r1, r2, bw=1000, delay='1ms')
        self.addLink(r2, r3, bw=1000, delay='1ms')
        self.addLink(r3, r4, bw=1000, delay='1ms')
        self.addLink(r3, r5, bw=1000, delay='1ms')

        # Edge attachments
        self.addLink(consumer, r1, bw=100, delay='5ms')
        self.addLink(producer, r2, bw=100, delay='5ms')  # initial active
        # Pre-create alternative attachments for mobility events
        self.addLink(producer, r3, bw=100, delay='5ms')
        self.addLink(producer, r4, bw=100, delay='5ms')
        self.addLink(producer, r5, bw=100, delay='5ms')


if __name__ == '__main__':
    setLogLevel('info')

    # Read experiment directory from environment variable
    experiment_dir = os.getenv('EXPERIMENT_DIR')
    if not experiment_dir:
        print("Error: EXPERIMENT_DIR environment variable is not set")
        exit(1)

    # Prepare output paths
    results_dir = os.getenv('RESULTS_DIR')
    if not results_dir:
        results_dir = os.path.join(experiment_dir, 'results')
    results_dir = os.path.abspath(results_dir)
    pcap_dir = os.path.join(results_dir, 'pcap')
    log_dir = os.path.join(results_dir, 'logs')
    os.makedirs(pcap_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    # Timing parameters (seconds)
    converge_wait = 30
    app_warmup = 20
    t1_samples = 5
    t1_interval = 0.5
    t2_wait = 6

    # Clean and verify Mini-NDN
    Minindn.cleanUp()
    Minindn.verifyDependencies()

    # Start Mini-NDN with the branch topology
    ndn = Minindn(topo=BranchTopo())
    ndn.start()

    info('Starting NFD on all nodes\n')
    nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel='DEBUG')
    info('Starting NLSR on all nodes\n')
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)

    # Allow routing to converge
    sleep(converge_wait)

    # Ensure only producer–r2 is initially active (simulate initial attachment)
    ndn.net.configLinkStatus('producer', 'r3', 'down')
    ndn.net.configLinkStatus('producer', 'r4', 'down')
    ndn.net.configLinkStatus('producer', 'r5', 'down')

    # Get node handles
    consumer = ndn.net['consumer']
    producer = ndn.net['producer']
    r1 = ndn.net['r1']
    r2 = ndn.net['r2']
    r3 = ndn.net['r3']
    r4 = ndn.net['r4']
    r5 = ndn.net['r5']

    # Helper to take nfdc snapshots per node
    def snap(node, label: str):
        base = os.path.join(results_dir, f"{node.name}_{label}")
        node.cmd(f"nfdc status report text > {base}_status.txt 2>/dev/null || true")
        node.cmd(f"nfdc face list > {base}_face.txt 2>/dev/null || true")
        node.cmd(f"nfdc fib list > {base}_fib.txt 2>/dev/null || true")
        node.cmd(f"nfdc route list > {base}_rib.txt 2>/dev/null || true")

    # Start tcpdump on multiple nodes (use -i any within each namespace)
    consumer_pcap = os.path.join(pcap_dir, 'consumer.pcap')
    producer_pcap = os.path.join(pcap_dir, 'producer.pcap')
    r1_pcap = os.path.join(pcap_dir, 'r1.pcap')
    r2_pcap = os.path.join(pcap_dir, 'r2.pcap')
    r3_pcap = os.path.join(pcap_dir, 'r3.pcap')
    r4_pcap = os.path.join(pcap_dir, 'r4.pcap')
    r5_pcap = os.path.join(pcap_dir, 'r5.pcap')

    consumer.cmd(f"tcpdump -i any -U -w {consumer_pcap} &> {os.path.join(results_dir, 'tcpdump_consumer.log')} &")
    producer.cmd(f"tcpdump -i any -U -w {producer_pcap} &> {os.path.join(results_dir, 'tcpdump_producer.log')} &")
    r1.cmd(f"tcpdump -i any -U -w {r1_pcap} &> {os.path.join(results_dir, 'tcpdump_r1.log')} &")
    r2.cmd(f"tcpdump -i any -U -w {r2_pcap} &> {os.path.join(results_dir, 'tcpdump_r2.log')} &")
    r3.cmd(f"tcpdump -i any -U -w {r3_pcap} &> {os.path.join(results_dir, 'tcpdump_r3.log')} &")
    r4.cmd(f"tcpdump -i any -U -w {r4_pcap} &> {os.path.join(results_dir, 'tcpdump_r4.log')} &")
    r5.cmd(f"tcpdump -i any -U -w {r5_pcap} &> {os.path.join(results_dir, 'tcpdump_r5.log')} &")

    # Launch producer and consumer apps (built under test/ by Makefile prep)
    producer_exec = os.path.join(experiment_dir, 'producer')
    consumer_exec = os.path.join(experiment_dir, 'consumer')
    producer_log = os.path.join(results_dir, 'producer.log')
    consumer_log = os.path.join(results_dir, 'consumer.log')

    producer.cmd(f"{producer_exec} --solution &> {producer_log} &")
    consumer.cmd(f"{consumer_exec} &> {consumer_log} &")

    # Warm-up period, then take T0 snapshot
    sleep(app_warmup)
    for n in (r1, r2, r3, r4, r5):
        snap(n, 'T0')

    # Mobility event #1: move producer to r3 (fast snapshot window for S3/S5)
    info('Mobility #1: producer attaches to r3\n')
    ndn.net.configLinkStatus('producer', 'r2', 'down')
    ndn.net.configLinkStatus('producer', 'r3', 'up')
    for idx in range(t1_samples):
        sleep(t1_interval)
        for n in (r1, r2, r3, r4, r5):
            snap(n, f"T1_{idx}")

    # Post-Fast-LSA snapshot window (after short-lived routes expire)
    sleep(t2_wait)
    for n in (r1, r2, r3, r4, r5):
        snap(n, 'T2')

    # Stop tcpdump
    consumer.cmd("pkill -f 'tcpdump -i any' || true")
    producer.cmd("pkill -f 'tcpdump -i any' || true")
    r1.cmd("pkill -f 'tcpdump -i any' || true")
    r2.cmd("pkill -f 'tcpdump -i any' || true")
    r3.cmd("pkill -f 'tcpdump -i any' || true")
    r4.cmd("pkill -f 'tcpdump -i any' || true")
    r5.cmd("pkill -f 'tcpdump -i any' || true")

    # Collect NFD/NLSR logs for validation
    for node in (consumer, producer, r1, r2, r3, r4, r5):
        for log_name in ('nfd.log', 'nlsr.log'):
            src = f"/tmp/minindn/{node.name}/log/{log_name}"
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(log_dir, f"{node.name}-{log_name}"))

    ndn.stop()


