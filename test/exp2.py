from time import sleep, time
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo
import os

# --- Configuration ---
# Use a variable for the experiment directory to make it easily configurable.
EXP_DIR = "/home/vagrant/mini-ndn/flooding"

class SimplifiedTopo(Topo):
    """
    A simplified but still representative 3-layer topology.
    This makes the experiment setup cleaner and easier to reason about.
    """
    def build(self):
        # Core Layer
        core = self.addHost('core')
        # Aggregation Layer
        agg1 = self.addHost('agg1')
        # Access Layer (Points of Attachment)
        acc1 = self.addHost('acc1')
        acc2 = self.addHost('acc2')
        acc3 = self.addHost('acc3')
        # End Hosts
        producer = self.addHost('producer')
        consumer = self.addHost('consumer')

        # Inter-layer links
        self.addLink(core, agg1, bw=100, delay='10ms')
        self.addLink(agg1, acc1, bw=100, delay='5ms')
        self.addLink(agg1, acc2, bw=100, delay='5ms')
        self.addLink(agg1, acc3, bw=100, delay='5ms')

        # Links for end hosts
        self.addLink(consumer, acc1, bw=100, delay='2ms')
        # Producer has links to all potential access points
        self.addLink(producer, acc1, bw=100, delay='2ms')
        self.addLink(producer, acc2, bw=100, delay='2ms')
        self.addLink(producer, acc3, bw=100, delay='2ms')

if __name__ == '__main__':
    setLogLevel('info')

    # Ensure clean slate
    Minindn.cleanUp()
    Minindn.verifyDependencies()

    # Start Mini-NDN with the simplified topology
    ndn = Minindn(topo=SimplifiedTopo())
    ndn.start()

    info('Starting NFD on all nodes...\n')
    nfds = AppManager(ndn, ndn.net.hosts, Nfd)

    info("Giving NFD 3 seconds to start up before starting NLSR...\n")
    sleep(3)

    info('Starting NLSR on all nodes...\n')
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)
    
    info("Waiting 30 seconds for NLSR to converge...\n")
    sleep(30)

    # --- Initial Network State ---
    # At the beginning, producer is only connected to acc1
    info("Setting initial link status: producer is only connected to acc1.\n")
    ndn.net.configLinkStatus('producer', 'acc2', 'down')
    ndn.net.configLinkStatus('producer', 'acc3', 'down')

    # Get host objects
    consumer = ndn.net['consumer']
    producer = ndn.net['producer']

    # CRITICAL: Wait for a few more seconds after NLSR convergence before
    # starting the applications. This ensures that when the producer app calls
    # 'nlsrc advertise', the NLSR daemon is fully ready to accept commands.
    info("Giving NLSR an extra 5 seconds to be fully ready for control commands...\n")
    sleep(5)

    # --- Start Data Collection ---
    info("Starting tcpdump on consumer and producer...\n")
    consumer_pcap_path = os.path.join(EXP_DIR, "consumer_capture.pcap")
    producer_pcap_path = os.path.join(EXP_DIR, "producer_capture.pcap")
    consumer.cmd(f"tcpdump -i any -w {consumer_pcap_path} &")
    producer.cmd(f"tcpdump -i any -w {producer_pcap_path} &")

    # --- Start Applications ---
    info("Starting producer and consumer applications in 'baseline' mode...\n")
    consumer_log = os.path.join(EXP_DIR, "consumer.log")
    producer_log = os.path.join(EXP_DIR, "producer.log")
    # IMPORTANT: Pass the --mode baseline argument to the applications
    consumer.cmd(f"{EXP_DIR}/consumer &> {consumer_log} &")
    producer.cmd(f"{EXP_DIR}/producer --mode baseline &> {producer_log} &")
    
    info("Experiment running for 60 seconds before first handoff...\n")
    sleep(60)

    # --- Simulate First Mobility Event ---
    info('Switching producer from acc1 to acc2...\n')
    ndn.net.configLinkStatus('producer', 'acc1', 'down')
    ndn.net.configLinkStatus('producer', 'acc2', 'up')
    
    info("Experiment running for 60 seconds before second handoff...\n")
    sleep(60)

    # --- Simulate Second Mobility Event ---
    info('Switching producer from acc2 to acc3...\n')
    ndn.net.configLinkStatus('producer', 'acc2', 'down')
    ndn.net.configLinkStatus('producer', 'acc3', 'up')
    
    info("Experiment running for a final 60 seconds...\n")
    sleep(60)

    # --- Stop Data Collection and Cleanup ---
    info("Stopping tcpdump...\n")
    consumer.cmd("kill %tcpdump")
    producer.cmd("kill %tcpdump")
    
    info("Stopping Mini-NDN...\n")
    ndn.stop()
