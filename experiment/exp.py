from time import sleep
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo

class CustomTopo(Topo):
    def build(self):
        # 添加核心主机（模拟核心交换机）add core switch
        core = self.addHost('core')

        # 添加汇聚主机（模拟汇聚交换机）add aggregation switch
        agg1 = self.addHost('agg1')
        agg2 = self.addHost('agg2')

        # 添加接入主机（模拟接入交换机）add access switch
        acc1 = self.addHost('acc1')
        acc2 = self.addHost('acc2')
        acc3 = self.addHost('acc3')
        acc4 = self.addHost('acc4')
        acc5 = self.addHost('acc5')
        acc6 = self.addHost('acc6')

        # 添加主机: producer 和 consumer add hosts producer and consumer
        producer = self.addHost('producer')
        consumer = self.addHost('consumer')

        # 连接主机，设置带宽和延迟 set links
        self.addLink(core, agg1, bw=1000, delay='1ms')
        self.addLink(core, agg2, bw=1000, delay='1ms')
        
        self.addLink(agg1, acc1, bw=1000, delay='1ms')
        self.addLink(agg1, acc2, bw=1000, delay='1ms')
        self.addLink(agg1, acc3, bw=1000, delay='1ms')
        
        self.addLink(agg2, acc4, bw=1000, delay='1ms')
        self.addLink(agg2, acc5, bw=1000, delay='1ms')
        self.addLink(agg2, acc6, bw=1000, delay='1ms')

        # 连接主机到接入主机 connect consumer and producer to switches
        self.addLink(consumer, acc1, bw=100, delay='10ms')
        self.addLink(producer, acc2, bw=100, delay='10ms')  # 初始连接到acc2
        self.addLink(producer, acc3, bw=100, delay='10ms')  # 预先创建到acc3的连接 pre-build producer-acc3
        self.addLink(producer, acc4, bw=100, delay='10ms')  # 预先创建到acc4的连接 pre-build producer-acc4

if __name__ == '__main__':
    setLogLevel('info')

    Minindn.cleanUp()
    Minindn.verifyDependencies()

    # 使用自定义拓扑 use custom topology
    ndn = Minindn(topo=CustomTopo())
    ndn.start()

    info('Starting NFD on nodes\n')
    nfds = AppManager(ndn, ndn.net.hosts, Nfd)
    info('Starting NLSR on nodes\n')
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)
    sleep(30)  # 等待NLSR启动并稳定 wait for NLSR

    # 禁用额外的连接，确保初始状态下只有到acc2的连接是启用的 disable producer-acc3&4 at beginning
    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'down')

    # 获取生产者和消费者 deploy producer and consumer
    producer = ndn.net['producer']
    consumer = ndn.net['consumer']

    # 在consumer节点上启动tcpdump监听 enable tcpdump listening on consumer
    consumer.cmd("tcpdump -i consumer-eth0 -w /home/vagrant/mini-ndn/flooding/experiment/consumer_capture.pcap &")
    
    # 启动生产者和消费者应用程序 enbale applications
    producer.cmd("/home/vagrant/mini-ndn/flooding/experiment/producer &> /home/vagrant/mini-ndn/flooding/experiment/producer.log &")
    consumer.cmd("/home/vagrant/mini-ndn/flooding/experiment/consumer &> /home/vagrant/mini-ndn/flooding/experiment/consumer.log &")

    # 调度生产者切换连接 link state changes to emulate producer movement
    sleep(30)
    info('Switching producer to acc3\n')
    ndn.net.configLinkStatus('producer', 'acc2', 'down')
    ndn.net.configLinkStatus('producer', 'acc3', 'up')

    sleep(30)
    info('Switching producer to acc4\n')
    ndn.net.configLinkStatus('producer', 'acc3', 'down')
    ndn.net.configLinkStatus('producer', 'acc4', 'up')
    
    sleep(30)  # 保持监听状态 keep listening
    consumer.cmd("kill %tcpdump")  # 终止tcpdump terminate tcpdump
    
    ndn.stop()
