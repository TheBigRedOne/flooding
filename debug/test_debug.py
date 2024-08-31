from time import sleep, time
from mininet.log import setLogLevel, info
from minindn.minindn import Minindn
from minindn.util import MiniNDNCLI
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from mininet.topo import Topo

class SimpleTopo(Topo):
    def build(self):
        # 添加主机: producer, consumer
        producer = self.addHost('producer')
        consumer = self.addHost('consumer')

        # 连接 consumer 和 producer
        self.addLink(consumer, producer, delay='10ms')

if __name__ == '__main__':
    # 设置日志级别为 debug
    setLogLevel('debug')

    Minindn.cleanUp()
    Minindn.verifyDependencies()

    # 使用自定义的拓扑
    ndn = Minindn(topo=SimpleTopo())
    ndn.start()

    # 添加输出间隔符
    print("\n" + "="*50 + " NFD 启动 " + "="*50 + "\n")

    # 启动 NFD
    info('Starting NFD on nodes\n')
    start_time_nfd = time()
    nfds = AppManager(ndn, ndn.net.hosts, Nfd)
    end_time_nfd = time()
    info(f'NFD started in {end_time_nfd - start_time_nfd:.2f} seconds\n')

    # 添加输出间隔符
    print("\n" + "="*50 + " NLSR 启动 " + "="*50 + "\n")

    # 启动 NLSR
    info('Starting NLSR on nodes\n')
    start_time_nlsr = time()
    nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)
    end_time_nlsr = time()
    info(f'NLSR started in {end_time_nlsr - start_time_nlsr:.2f} seconds\n')

    sleep(30)  # 等待NLSR启动并稳定

    # 添加输出间隔符
    print("\n" + "="*50 + " 应用程序启动 " + "="*50 + "\n")

    # 获取生产者和消费者
    producer = ndn.net['producer']
    consumer = ndn.net['consumer']

    # 启动生产者和消费者应用程序
    producer.cmd("/home/vagrant/mini-ndn/flooding/producer &> /home/vagrant/mini-ndn/flooding/producer.log &")
    consumer.cmd("/home/vagrant/mini-ndn/flooding/consumer &> /home/vagrant/mini-ndn/flooding/consumer.log &")

    # 运行 CLI
    MiniNDNCLI(ndn.net)

    # 停止网络
    ndn.stop()
