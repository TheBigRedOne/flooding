// producer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/meta-info.hpp>
#include <ndn-cxx/encoding/block.hpp>
#include <ndn-cxx/encoding/tlv.hpp>

#include <boost/asio/io_context.hpp>
#include <boost/asio/posix/stream_descriptor.hpp>

#include <iostream>
#include <string>
#include <string_view>
#include <cstdlib> // For std::system
#include <cstring> // For strerror
#include <cerrno>  // For errno
#include <chrono>
#include <thread>
#include <iomanip>

// Only available in solution build
#ifdef SOLUTION_ENABLED
#include <ndn-cxx/optoflood.hpp>
#endif
// Linux headers for Netlink
#include <asm/types.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <unistd.h>

// OptoFlood TLV types are now defined in ndn-cxx/optoflood.hpp

namespace ndn {
namespace examples {

/**
 * @brief A helper class to listen for network interface changes using Netlink.
 * This class encapsulates the logic for creating a Netlink socket and integrating
 * it with the ndn-cxx/boost::asio event loop.
 */
class NetlinkListener : noncopyable
{
public:
  // The callback will be invoked when a mobility event is detected.
  using MobilityCallback = std::function<void()>;

  NetlinkListener(boost::asio::io_context& io, MobilityCallback callback)
    : m_ioService(io)
    , m_callback(callback)
    , m_netlinkSocket(io)
  {
  }

  void
  start()
  {
    int sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (sock < 0) {
      throw std::runtime_error("Failed to create Netlink socket");
    }

    struct sockaddr_nl sa;
    memset(&sa, 0, sizeof(sa));
    sa.nl_family = AF_NETLINK;
    sa.nl_groups = RTMGRP_LINK;

    if (bind(sock, (struct sockaddr*)&sa, sizeof(sa)) < 0) {
      close(sock);
      throw std::runtime_error("Failed to bind Netlink socket");
    }

    m_netlinkSocket.assign(sock);
    waitForEvent();
  }

private:
  void
  waitForEvent()
  {
    // Asynchronously wait until the socket is ready to read.
    m_netlinkSocket.async_wait(boost::asio::posix::stream_descriptor::wait_read,
                              bind(&NetlinkListener::handleEvent, this, _1));
  }

  void
  handleEvent(const boost::system::error_code& error)
  {
    if (error) {
      std::cerr << "[" << std::chrono::system_clock::now().time_since_epoch().count() 
                << "] ERROR: Netlink socket error: " << error.message() 
                << " (code: " << error.value() << ")" << std::endl;
      
      if (error == boost::asio::error::operation_aborted) {
        std::cerr << "[" << std::chrono::system_clock::now().time_since_epoch().count() 
                  << "] INFO: Netlink listener shutting down gracefully" << std::endl;
        return;
      }
      
      // For other errors, try to restart monitoring after a delay
      std::cerr << "[" << std::chrono::system_clock::now().time_since_epoch().count() 
                << "] INFO: Attempting to restart Netlink monitoring in 1 second" << std::endl;
      std::this_thread::sleep_for(std::chrono::seconds(1));
      waitForEvent();
      return;
    }

    char buf[8192];
    struct iovec iov = { buf, sizeof(buf) };
    struct sockaddr_nl sa;
    struct msghdr msg = { &sa, sizeof(sa), &iov, 1, nullptr, 0, 0 };

    ssize_t len = recvmsg(m_netlinkSocket.native_handle(), &msg, 0);
    if (len < 0) {
      int err = errno;
      std::cerr << "[" << std::chrono::system_clock::now().time_since_epoch().count() 
                << "] ERROR: Netlink recvmsg failed: " << strerror(err) 
                << " (errno: " << err << ")" << std::endl;
      
      // Handle specific error cases
      if (err == EAGAIN || err == EWOULDBLOCK) {
        // No data available, continue waiting
        waitForEvent();
      } else if (err == ENOBUFS) {
        // Buffer overflow, log and continue
        std::cerr << "[" << std::chrono::system_clock::now().time_since_epoch().count() 
                  << "] WARNING: Netlink buffer overflow, some events may be lost" << std::endl;
        waitForEvent();
      }
      return;
    }

    for (struct nlmsghdr* nlh = (struct nlmsghdr*)buf; NLMSG_OK(nlh, len); nlh = NLMSG_NEXT(nlh, len)) {
      if (nlh->nlmsg_type == RTM_NEWLINK) {
        struct ifinfomsg* ifi = (struct ifinfomsg*)NLMSG_DATA(nlh);
        // Check if the interface is up and running. This is our mobility trigger.
        if ((ifi->ifi_flags & IFF_UP) && (ifi->ifi_flags & IFF_RUNNING)) {
          struct rtattr* rta = IFLA_RTA(ifi);
          int rta_len = nlh->nlmsg_len - NLMSG_LENGTH(sizeof(*ifi));
          for (; RTA_OK(rta, rta_len); rta = RTA_NEXT(rta, rta_len)) {
            if (rta->rta_type == IFLA_IFNAME) {
                std::string ifname(static_cast<char*>(RTA_DATA(rta)));
                auto now = std::chrono::system_clock::now();
                auto timestamp = now.time_since_epoch().count();
                
                std::cout << "[" << timestamp << "] MOBILITY: Interface state change detected" << std::endl;
                std::cout << "[" << timestamp << "] MOBILITY: Interface '" << ifname 
                          << "' is UP (flags: 0x" << std::hex << ifi->ifi_flags << std::dec << ")" << std::endl;
                std::cout << "[" << timestamp << "] MOBILITY: Triggering mobility event handler" << std::endl;
                
                m_callback();
                break;
            }
          }
        }
      }
    }
    // Reschedule the wait for the next event
    waitForEvent();
  }

private:
  boost::asio::io_context& m_ioService;
  MobilityCallback m_callback;
  boost::asio::posix::stream_descriptor m_netlinkSocket;
};


class Producer : noncopyable
{
public:
  Producer()
    : m_face(m_ioContext)
    , m_keyChain()
  {
    // Default to disabled; enable automatically in solution builds
#ifdef SOLUTION_ENABLED
    m_enableOptoFlood = true;
#endif
  }

  void enableOptoFlood(bool enable = true) { m_enableOptoFlood = enable; }
  void forceMobilityOnce() { m_enableOptoFlood = true; m_hasMoved = true; m_forceMobilityOnceFlag = true; }

  void
  run()
  {
    // Register prefix with a success callback to advertise it via NLSR
    m_face.setInterestFilter("/example/LiveStream",
                             std::bind(&Producer::onInterest, this, _2),
                             std::bind(&Producer::onRegisterSuccess, this, _1),
                             std::bind(&Producer::onRegisterFailed, this, _1, _2));
    if (m_enableOptoFlood) {
      try {
        if (!m_netlinkListener) {
          m_netlinkListener = std::make_unique<NetlinkListener>(
            m_ioContext, [this] { this->onMobilityEvent(); }
          );
        }
        m_netlinkListener->start();
        std::cout << "Netlink listener started for mobility detection." << std::endl;
      }
      catch (const std::exception& e) {
        std::cerr << "ERROR: Failed to start Netlink listener: " << e.what() << std::endl;
      }
    }
    m_ioContext.run();
  }

private:
  void
  onRegisterSuccess(const Name& prefix)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    std::cout << "[" << timestamp << "] PREFIX: Successfully registered prefix: " << prefix << std::endl;
    
    // Now that the local filter is confirmed, advertise the prefix to the network.
    std::cout << "[" << timestamp << "] PREFIX: Advertising prefix via NLSR" << std::endl;
    int ret = std::system("nlsrc advertise /example/LiveStream");
    if (ret != 0) {
      std::cerr << "[" << timestamp << "] ERROR: Failed to advertise prefix with nlsrc (exit code: " 
                << ret << ")" << std::endl;
      m_face.shutdown();
    } else {
      std::cout << "[" << timestamp << "] PREFIX: Successfully advertised prefix via NLSR" << std::endl;
    }
  }

  void
  onRegisterFailed(const Name& prefix, const std::string& reason)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    std::cerr << "[" << timestamp << "] ERROR: Failed to register prefix '" << prefix 
              << "' with reason: " << reason << std::endl;
    std::cerr << "[" << timestamp << "] ERROR: Shutting down face due to registration failure" << std::endl;
    m_face.shutdown();
  }

  // This callback is triggered by the NetlinkListener
  void
  onMobilityEvent()
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    std::cout << "[" << timestamp << "] MOBILITY: Producer mobility event triggered" << std::endl;
    std::cout << "[" << timestamp << "] MOBILITY: Setting mobility flag for subsequent Data packets" << std::endl;
    m_hasMoved = true;
    m_mobilityEventCount++;
    std::cout << "[" << timestamp << "] MOBILITY: Total mobility events: " << m_mobilityEventCount << std::endl;
  }

  void
  onInterest(const Interest& interest)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_interestCount++;
    
    std::cout << "[" << timestamp << "] INTEREST: Received #" << m_interestCount 
              << " Name: " << interest.getName() 
              << " CanBePrefix: " << interest.getCanBePrefix()
              << " MustBeFresh: " << interest.getMustBeFresh() << std::endl;

    auto data = make_shared<Data>(interest.getName());
    data->setFreshnessPeriod(10_s);
    data->setContent(std::string_view("OptoFlood Test Data"));

    if (m_hasMoved) {
      std::cout << "[" << timestamp << "] DATA: Attaching OptoFlood mobility markers" << std::endl;

      // Use OptoFlood API to create mobility-related blocks
      MetaInfo metaInfo = data->getMetaInfo();
      
#ifdef SOLUTION_ENABLED
      // Add MobilityFlag
      metaInfo.addAppMetaInfo(optoflood::makeMobilityFlagBlock());
      
      // Add FloodID (using timestamp as unique ID)
      uint64_t floodId = static_cast<uint64_t>(timestamp);
      metaInfo.addAppMetaInfo(optoflood::makeFloodIdBlock(floodId));
      
      // Add NewFaceSeq (using mobility event count as sequence)
      metaInfo.addAppMetaInfo(optoflood::makeNewFaceSeqBlock(m_mobilityEventCount));
      
      // Add a placeholder TraceHint. In a full implementation, this would carry meaningful PoA info.
      std::vector<uint8_t> traceHint = {0x01, 0x02};
      metaInfo.addAppMetaInfo(optoflood::makeTraceHintBlock(traceHint));
#endif
      
      data->setMetaInfo(metaInfo);
      
      // Log additional OptoFlood fields
      std::cout << "[" << timestamp << "] DATA: Mobility packet marked"
                << " NewFaceSeq: " << m_mobilityEventCount << std::endl;

      // Reset the flag after processing
      m_hasMoved = false; 
      m_forceMobilityOnceFlag = false;
      std::cout << "[" << timestamp << "] DATA: Mobility flag cleared for producer" << std::endl;
    }

    m_keyChain.sign(*data);
    
    auto sendTimestamp = std::chrono::system_clock::now().time_since_epoch().count();
    std::cout << "[" << sendTimestamp << "] DATA: Sending response"
              << " Size: " << data->wireEncode().size() << " bytes"
              << " Name: " << data->getName() << std::endl;
              
    m_face.put(*data);
    m_dataCount++;
    
    std::cout << "[" << sendTimestamp << "] STATS: Total Interests: " << m_interestCount 
              << " Total Data sent: " << m_dataCount << std::endl;
  }

private:
  boost::asio::io_context m_ioContext;
  Face m_face{m_ioContext};
  KeyChain m_keyChain;

  std::atomic<bool> m_hasMoved{false};
  std::unique_ptr<NetlinkListener> m_netlinkListener;
  bool m_enableOptoFlood = false;
  bool m_forceMobilityOnceFlag = false;
  
  // Statistics counters for experiment analysis
  uint64_t m_interestCount = 0;
  uint64_t m_dataCount = 0;
  uint64_t m_mobilityEventCount = 0;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  auto startTime = std::chrono::system_clock::now().time_since_epoch().count();
  
  std::cout << "[" << startTime << "] STARTUP: Producer application starting" << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Process ID: " << getpid() << std::endl;

  try {
    ndn::examples::Producer producer;
    // CLI flags retained but not required under solution build
    // --solution / --mode=solution: no-op in solution build (already enabled)
    // --force-mobility: Force one mobility event
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      if (arg == "--force-mobility") {
        producer.forceMobilityOnce();
      }
      else if (arg == "--solution" || arg == "--mode=solution") {
        producer.enableOptoFlood(true);
      }
    }
    std::cout << "[" << startTime << "] STARTUP: Producer initialized, starting event loop" << std::endl;
    producer.run();
  }
  catch (const std::exception& e) {
    auto errorTime = std::chrono::system_clock::now().time_since_epoch().count();
    std::cerr << "[" << errorTime << "] FATAL: Exception in producer: " << e.what() << std::endl;
    return 1;
  }
  
  auto endTime = std::chrono::system_clock::now().time_since_epoch().count();
  std::cout << "[" << endTime << "] SHUTDOWN: Producer application terminated" << std::endl;
  return 0;
}
