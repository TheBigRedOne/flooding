from time import sleep, time
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo

class PatchedNlsr(Nlsr):
    def __init__(self, node, **kwargs):
        super(PatchedNlsr, self).__init__(node, **kwargs)
        self.isRouter = kwargs.get('isRouter',
            node.name.startswith('agg') or node.name.startswith('core'))

    def start(self):
        config_path = f'/tmp/minindn/{self.node.name}/nlsr.conf'
        self.node.cmd(f'mkdir -p /tmp/minindn/{self.node.name}/log')
        self.node.cmd(f'cp /usr/local/etc/ndn/nlsr.conf.sample {config_path}')

        # general section
        self.node.cmd(f'infoedit -f {config_path} -s general.network -v /ndn/')
        self.node.cmd(f'infoedit -f {config_path} -s general.site -v /{self.node.name}-site')
        self.node.cmd(f'infoedit -f {config_path} -s general.router -v /%C1.Router/cs/{self.node.name}')
        self.node.cmd(f'infoedit -f {config_path} -s general.state-dir -v /tmp/minindn/{self.node.name}/log')
        self.node.cmd(f'infoedit -f {config_path} -s general.sync-protocol -v psync')

        # neighbors section
        self.node.cmd(f'infoedit -f {config_path} -d neighbors.neighbor')

        for intf in self.node.intfList():
            if intf.link:
                other_intf = intf.link.intf1 if intf is intf.link.intf2 else intf.link.intf2
                other_node = other_intf.node
                ip = other_node.IP(intf=other_intf)
                cost = intf.params.get('cost', intf.params.get('bw', 1))
                self.node.cmd(f"""infoedit -f {config_path} -a neighbors.neighbor \\
                           <<<'name /ndn/{other_node.name}-site/%C1.Router/cs/{other_node.name} face-uri udp://{ip}\\n link-cost {int(cost)}'""")

        # hyperbolic section
        self.node.cmd(f'infoedit -f {config_path} -s hyperbolic.state -v off')
        self.node.cmd(f'infoedit -f {config_path} -s hyperbolic.radius -v 0.0')
        self.node.cmd(f'infoedit -f {config_path} -s hyperbolic.angle -v 0.0')

        # fib section
        self.node.cmd(f'infoedit -f {config_path} -s fib.max-faces-per-prefix  -v 3')

        # advertising section
        self.node.cmd(f'infoedit -f {config_path} -d advertising.prefix')
        if not self.isRouter:
            self.node.cmd(f'infoedit -f {config_path} -a advertising.prefix '
                     f'-v "/ndn/{self.node.name}-site/{self.node.name} 0"')
        else:
            self.node.cmd(f'infoedit -f {config_path} -a advertising.prefix '
                     f'-v "/ndn/{self.node.name}-site 0"')

        # security section
        self.node.cmd(f'infoedit -f {config_path} -d security.cert-to-publish')
        self.node.cmd(f'infoedit -f {config_path} -s security.validator.trust-anchor.type -v any')
        self.node.cmd(f'infoedit -f {config_path} -d security.validator.trust-anchor.file-name')
        self.node.cmd(f'infoedit -f {config_path} -s security.prefix-update-validator.trust-anchor.type -v any')
        self.node.cmd(f'infoedit -f {config_path} -d security.prefix-update-validator.trust-anchor.file-name')

        # Create faces for neighbors
        for intf in self.node.intfList():
            if intf.link:
                other_intf = intf.link.intf1 if intf is intf.link.intf2 else intf.link.intf2
                other_node = other_intf.node
                ip = other_node.IP(intf=other_intf)
                self.node.cmd(f'nfdc face create udp://{ip} persistency permanent')

        self.daemon = self.node.cmd(f'nlsr -f {config_path} &')


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
    nlsrs = AppManager(ndn, ndn.net.hosts, PatchedNlsr)
    end_time_nlsr = time()
    info(f'NLSR started in {end_time_nlsr - start_time_nlsr:.2f} seconds\n')

    sleep(30)  # 等待NLSR启动并稳定

    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'down')

    consumer = ndn.net['consumer']
    producer = ndn.net['producer']

    info('Creating and setting default identity for producer\n')
    producer.cmd('ndnsec-key-gen /ndn/producer-site/producer | ndnsec-cert-install -')
    producer.cmd('ndnsec-set-default /ndn/producer-site/producer')
    sleep(1) # Allow a moment for identity commands to process

    consumer.cmd("tcpdump -i consumer-eth0 -w /home/vagrant/mini-ndn/flooding/consumer_capture.pcap &")

    consumer.cmd("/home/vagrant/mini-ndn/flooding/consumer &> /home/vagrant/mini-ndn/flooding/consumer.log &")
    producer.cmd("/home/vagrant/mini-ndn/flooding/producer &> /home/vagrant/mini-ndn/flooding/producer.log &")
    sleep(120)

 #   info('Switching producer to acc3\n')
 #   ndn.net.configLinkStatus('producer', 'acc2', 'down')
 #   ndn.net.configLinkStatus('producer', 'acc3', 'up')
 #   sleep(120)

 #   info('Switching producer to acc4\n')
 #   ndn.net.configLinkStatus('producer', 'acc3', 'down')
 #   ndn.net.configLinkStatus('producer', 'acc4', 'up')
 #   sleep(120)

    consumer.cmd("kill %tcpdump")
    producer.cmd("kill %tcpdump")

    ndn.stop()
