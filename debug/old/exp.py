from time import sleep, time
import os
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo

class CustomTopo(Topo):
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

        self.addLink(core, agg1, bw=100, delay='10ms')
        self.addLink(core, agg2, bw=100, delay='10ms')

        self.addLink(agg1, acc1, bw=100, delay='5ms')
        self.addLink(agg1, acc2, bw=100, delay='5ms')
        self.addLink(agg1, acc3, bw=100, delay='5ms')

        self.addLink(agg2, acc4, bw=100, delay='5ms')
        self.addLink(agg2, acc5, bw=100, delay='5ms')
        self.addLink(agg2, acc6, bw=100, delay='5ms')

        self.addLink(consumer, acc1, bw=100, delay='2ms')
        self.addLink(producer, acc2, bw=100, delay='2ms')
        self.addLink(producer, acc3, bw=100, delay='2ms')
        self.addLink(producer, acc4, bw=100, delay='2ms')

if __name__ == '__main__':
    setLogLevel('info')

    Minindn.cleanUp()
    Minindn.verifyDependencies()

    ndn = Minindn(topo=CustomTopo())
    ndn.start()

    info('Starting NFD on nodes\n')
    start_time_nfd = time()
    nfds = AppManager(ndn, ndn.net.hosts, Nfd)
    end_time_nfd = time()
    info(f'NFD started in {end_time_nfd - start_time_nfd:.2f} seconds\n')

    info('Starting NLSR on nodes\n')
    start_time_nlsr = time()
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)
    end_time_nlsr = time()
    info(f'NLSR started in {end_time_nlsr - start_time_nlsr:.2f} seconds\n')

    sleep(30)  # 等待NLSR启动并稳定

    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'down')

    consumer = ndn.net['consumer']
    producer = ndn.net['producer']

    # Get the current directory (should be /home/vagrant/mini-ndn/flooding)
    base_dir = os.getcwd()

    consumer.cmd(f"tcpdump -i consumer-eth0 -w {base_dir}/consumer_capture.pcap &")
    producer.cmd(f"tcpdump -i producer-eth0 -w {base_dir}/producer_capture_1.pcap &")

    consumer.cmd(f"{base_dir}/consumer &> {base_dir}/consumer.log &")
    producer.cmd(f"{base_dir}/producer &> {base_dir}/producer.log &")
    sleep(120)

    info('Switching producer to acc3\n')
    ndn.net.configLinkStatus('producer', 'acc2', 'down')
    ndn.net.configLinkStatus('producer', 'acc3', 'up')
    producer.cmd(f"tcpdump -i producer-eth0 -w {base_dir}/producer_capture_2.pcap &")
    sleep(120)

    info('Switching producer to acc4\n')
    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'up')
    producer.cmd(f"tcpdump -i producer-eth0 -w {base_dir}/producer_capture_3.pcap &")
    sleep(120)

    consumer.cmd("kill %tcpdump")
    producer.cmd("kill %tcpdump")

    ndn.stop()