#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/security/signing-helpers.hpp>
#include <iostream>
#include <cstdlib> // for std::system
#include <thread>
#include <atomic>
#include <queue>
#include <mutex>
#include <condition_variable>
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

  void run()
  {
    // Automatically advertise prefix using system call
    std::system("nlsrc advertise /example/testApp");

    // Start the Netlink listener thread
    netlinkListenerThread = std::thread(&Producer::listenToNetlink, this);

    // Register Interest filter
    m_face.setInterestFilter("/example/testApp/randomData",
                             std::bind(&Producer::onInterestReceived, this, std::placeholders::_2),
                             nullptr,
                             std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

    std::cout << "Producer running, waiting for Interests...\n";

    // Start the worker thread for processing Interest queue
    interestProcessingThread = std::thread(&Producer::processInterestQueue, this);

    m_face.processEvents();

    // Shutdown
    keepRunning.store(false);
    if (netlinkListenerThread.joinable()) {
      netlinkListenerThread.join();
    }
    if (interestProcessingThread.joinable()) {
      interestProcessingThread.join();
    }
  }

private:
  // Listener for Netlink messages to monitor mobility
  void listenToNetlink()
  {
    int nlSock = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (nlSock < 0) {
      std::cerr << "ERROR: Failed to create Netlink socket\n";
      return;
    }

    sockaddr_nl sa;
    std::memset(&sa, 0, sizeof(sa));
    sa.nl_family = AF_NETLINK;
    sa.nl_groups = RTMGRP_LINK;

    if (bind(nlSock, (sockaddr*)&sa, sizeof(sa)) < 0) {
      std::cerr << "ERROR: Failed to bind Netlink socket\n";
      close(nlSock);
      return;
    }

    while (keepRunning.load()) {
      char buffer[4096];
      int len = recv(nlSock, buffer, sizeof(buffer), 0);
      if (len < 0) {
        continue;
      }

      for (nlmsghdr* nlh = (nlmsghdr*)buffer; NLMSG_OK(nlh, (unsigned int)len); nlh = NLMSG_NEXT(nlh, len)) {
        if (nlh->nlmsg_type == RTM_NEWLINK || nlh->nlmsg_type == RTM_DELLINK) {
          bool mobilityDetected = detectMobility();
          if (mobilityDetected != isMobile) {
            isMobile = mobilityDetected;
            std::cout << (isMobile ? "Mobility detected: now in mobile state.\n" : "Producer is now stationary.\n");
          }
        }
      }
    }

    close(nlSock);
  }

  // Detect mobility by checking network interface status
  bool detectMobility()
  {
    struct ifaddrs *ifap, *ifa;
    getifaddrs(&ifap);

    for (ifa = ifap; ifa != nullptr; ifa = ifa->ifa_next) {
      if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET) {
        std::string iface(ifa->ifa_name);
        if (iface == "eth0" && !(ifa->ifa_flags & IFF_UP)) {
          freeifaddrs(ifap);
          return true;
        }
      }
    }

    freeifaddrs(ifap);
    return false;
  }

  // Add Interest to processing queue
  void onInterestReceived(const Interest& interest)
  {
    std::unique_lock<std::mutex> lock(interestQueueMutex);
    interestQueue.push(interest);
    lock.unlock();
    interestQueueCondition.notify_one();
  }

  // Process Interests from the queue
  void processInterestQueue()
  {
    while (keepRunning.load()) {
      std::unique_lock<std::mutex> lock(interestQueueMutex);
      interestQueueCondition.wait(lock, [this] { return !interestQueue.empty() || !keepRunning.load(); });

      if (!keepRunning.load() && interestQueue.empty()) {
        return;
      }

      Interest interest = interestQueue.front();
      interestQueue.pop();
      lock.unlock();

      processInterest(interest);
    }
  }

  // Process a single Interest
  void processInterest(const Interest& interest)
  {
    std::cout << ">> I: " << interest << std::endl;

    // Create data
    auto data = std::make_shared<Data>();
    data->setName(interest.getName());
    data->setFreshnessPeriod(10_s);

    // Set content
    const std::string content = "Hello, world! (Producer Response)";
    data->setContent(makeStringBlock(tlv::Content, content));

    // Mark data with mobility flag if producer is in mobile state
    if (isMobile.load()) {
      data->getMetaInfo().setMobilityFlag(true);
      data->getMetaInfo().setHopLimit(5);
      data->getMetaInfo().setTimeStamp(time::steady_clock::now());
    }

    // Sign data
    m_keyChain.sign(*data);

    std::cout << "<< D: " << *data << std::endl;
    m_face.put(*data);
  }

  // Handle registration failure
  void onRegisterFailed(const Name& prefix, const std::string& reason)
  {
    std::cerr << "ERROR: Failed to register prefix '" << prefix << "' with the local forwarder (" << reason << ")\n";
    m_face.shutdown();
  }

private:
  Face m_face;
  KeyChain m_keyChain;

  std::atomic<bool> isMobile;
  std::atomic<bool> keepRunning;

  std::queue<Interest> interestQueue;
  std::mutex interestQueueMutex;
  std::condition_variable interestQueueCondition;

  std::thread netlinkListenerThread;
  std::thread interestProcessingThread;
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
