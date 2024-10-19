#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/security/signing-helpers.hpp>
#include <iostream>
#include <cstdlib> // for std::system
#include <thread>
#include <atomic>
#include <cstring>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <unistd.h>

namespace ndn {
namespace examples {

class Producer
{
public:
  Producer()
    : isMobile(false), keepRunning(true) {}

  // 启动生产者
  void run()
  {
    // Automatically advertise prefix using system call
    std::system("nlsrc advertise /example/testApp");

    // 使用一个线程来监听网络接口状态
    netlinkListenerThread = std::thread(&Producer::listenToNetlink, this);

    // 设置监听转发器的路由更新通知
    m_face.setInterestFilter("/local/ndn/forwarder/globalRoutingUpdate",
                             std::bind(&Producer::onRoutingUpdateNotification, this, std::placeholders::_2),
                             nullptr,
                             std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

    m_face.setInterestFilter("/example/testApp/randomData",
                             std::bind(&Producer::onInterest, this, std::placeholders::_2),
                             nullptr,
                             std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

    std::cout << "Producer running, waiting for Interests...\n";
    m_face.processEvents(); // 主线程处理事件

    // 退出时停止监听线程
    keepRunning.store(false);
    if (netlinkListenerThread.joinable()) {
      netlinkListenerThread.join();
    }
  }

private:
  // 处理转发器发送的路由更新通知
  void onRoutingUpdateNotification(const Interest& interest)
  {
    std::cout << "Received global routing update notification." << std::endl;

    // 收到通知后，取消移动性标记
    globalRoutingUpdated = true;
    isMobile = false;
    std::cout << "Stopped marking MobilityFlag after routing update." << std::endl;
  }

  // 使用 Netlink 监听网络接口状态变化
  void listenToNetlink()
  {
    // 创建 Netlink 套接字
    int nlSock = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (nlSock < 0) {
      std::cerr << "ERROR: Failed to create Netlink socket\n";
      return;
    }

    // 绑定到 Netlink 套接字
    struct sockaddr_nl sa;
    std::memset(&sa, 0, sizeof(sa));
    sa.nl_family = AF_NETLINK;
    sa.nl_groups = RTMGRP_LINK; // 监听网络接口状态变化

    if (bind(nlSock, (struct sockaddr*)&sa, sizeof(sa)) < 0) {
      std::cerr << "ERROR: Failed to bind Netlink socket\n";
      close(nlSock);
      return;
    }

    // 开始监听网络接口状态变化
    while (keepRunning.load()) {
      char buffer[4096];
      int len = recv(nlSock, buffer, sizeof(buffer), 0);
      if (len < 0) {
        continue; // 收到无效消息，继续
      }

      for (struct nlmsghdr* nlh = (struct nlmsghdr*)buffer;
           NLMSG_OK(nlh, (unsigned int)len);
           nlh = NLMSG_NEXT(nlh, len)) {

        // 判断是否是网络接口的变化
        if (nlh->nlmsg_type == RTM_NEWLINK || nlh->nlmsg_type == RTM_DELLINK) {
          bool mobilityDetected = detectMobility();
          if (mobilityDetected != isMobile) {
            isMobile = mobilityDetected;
            std::cout << (isMobile ? "Mobility detected: now in mobile state.\n" : "Producer is now stationary.\n");
          }
        }
      }
    }

    // 关闭 Netlink 套接字
    close(nlSock);
  }

  // 检测接口状态的实际逻辑
  bool detectMobility()
  {
    // 这里假设 eth0 是我们要检测的接口
    struct ifaddrs *ifap, *ifa;
    getifaddrs(&ifap);

    for (ifa = ifap; ifa != nullptr; ifa = ifa->ifa_next) {
      if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET) {
        std::string iface(ifa->ifa_name);
        if (iface == "eth0" && !(ifa->ifa_flags & IFF_UP)) {
          freeifaddrs(ifap);
          return true;  // 生产者检测到移动 (eth0 断开)
        }
      }
    }

    freeifaddrs(ifap);
    return false;  // 没有检测到移动
  }

// 处理 Interest 的函数
void onInterest(const Interest& interest)
{
  std::cout << ">> I: " << interest << std::endl;

  // 创建数据包
  auto data = std::make_shared<Data>();
  data->setName(interest.getName());
  data->setFreshnessPeriod(10_s);

  // 设置内容，附加移动状态信息
  const std::string content = "Hello, world! " + std::string(isMobile ? "(Mobile Producer)" : "(Fixed Producer)");
  data->setContent(makeStringBlock(tlv::Content, content));

  // 如果生产者处于移动状态，设置 MobilityFlag 和 HopLimit
  if (isMobile) {
    data->getMetaInfo().setMobilityFlag(true);  // 标记数据包为移动生产者发出的
    data->getMetaInfo().setHopLimit(5);         // 设置初始 HopLimit 为 5，表示最多转发 5 次
    data->getMetaInfo().setTimeStamp(time::steady_clock::now());  // 设置时间戳为当前时间
  }

  // 使用默认密钥签名数据
  m_keyChain.sign(*data);

  std::cout << "<< D: " << *data << std::endl;
  m_face.put(*data);
}

  // 注册失败时的处理函数
  void onRegisterFailed(const Name& prefix, const std::string& reason)
  {
    std::cerr << "ERROR: Failed to register prefix '" << prefix
              << "' with the local forwarder (" << reason << ")\n";
    m_face.shutdown();
  }

private:
  Face m_face;
  KeyChain m_keyChain; // 用于签名
  std::atomic<bool> isMobile; // 生产者是否在移动状态
  std::thread netlinkListenerThread; // 用于监听网络接口的线程
  std::atomic<bool> keepRunning; // 控制线程运行状态
  std::atomic<bool> globalRoutingUpdated; // 标记全局路由是否已更新
};

} // namespace examples
} // namespace ndn

int main(int argc, char** argv)
{
  try {
    ndn::examples::Producer producer;
    producer.run();
    return 0;
  }
  catch (const std::exception& e) {
    std::cerr << "ERROR: " << e.what() << std::endl;
    return 1;
  }
}
