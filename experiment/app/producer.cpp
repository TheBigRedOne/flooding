// producer.cpp

#include "common.hpp"

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>

#include <boost/asio/posix/stream_descriptor.hpp>

#include <iostream>
#include <string>

// Linux headers for Netlink
#include <asm/types.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <unistd.h>


// Custom TLV type numbers for OptoFlood.
const uint32_t TLV_MOBILITY_FLAG = 201;
const uint32_t TLV_FLOOD_ID = 202;
const uint32_t TLV_NEW_FACE_SEQ = 203;
const uint32_t TLV_TRACE_HINT = 204;

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

  NetlinkListener(boost::asio::io_service& io, MobilityCallback callback)
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

    // Assign the raw socket to the asio descriptor
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
      NDN_LOG_ERROR("Netlink socket error: " << error.message());
      return;
    }

    char buf[8192];
    struct iovec iov = { buf, sizeof(buf) };
    struct sockaddr_nl sa;
    struct msghdr msg = { &sa, sizeof(sa), &iov, 1, nullptr, 0, 0 };

    ssize_t len = recvmsg(m_netlinkSocket.native_handle(), &msg, 0);
    if (len < 0) {
      NDN_LOG_ERROR("Netlink recvmsg failed");
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
                NDN_LOG_INFO("<<<<< MOBILITY EVENT DETECTED: Interface '" << ifname << "' is UP >>>>>");
                m_callback(); // Trigger the producer's mobility logic
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
  boost::asio::io_service& m_ioService;
  MobilityCallback m_callback;
  boost::asio::posix::stream_descriptor m_netlinkSocket;
};


class Producer : noncopyable
{
public:
  Producer(const std::string& mode)
    : m_mode(mode)
    , m_hasMoved(false)
    , m_netlinkListener(m_face.getIoService(), bind(&Producer::onMobilityEvent, this))
  {
  }

  void
  run()
  {
    m_face.setInterestFilter("/example/LiveStream",
                             bind(&Producer::onInterest, this, _1),
                             [] (const auto&, const auto& reason) {
                               NDN_LOG_ERROR("Failed to register prefix: " << reason);
                             });

    // In solution mode, start listening for real network events.
    if (m_mode == "solution") {
      try {
        m_netlinkListener.start();
        NDN_LOG_INFO("Netlink listener started for mobility detection.");
      }
      catch (const std::exception& e) {
        NDN_LOG_ERROR("Failed to start Netlink listener: " << e.what());
      }
    }

    m_face.processEvents();
  }

private:
  // This callback is triggered by the NetlinkListener
  void
  onMobilityEvent()
  {
    m_hasMoved = true;
  }

  void
  onInterest(const Interest& interest)
  {
    NDN_LOG_INFO(">> I: " << interest);

    auto data = make_shared<Data>(interest.getName());
    data->setFreshnessPeriod(10_s);
    data->setContent(reinterpret_cast<const uint8_t*>("OptoFlood Test Data"), 19);

    if (m_mode == "solution" && m_hasMoved) {
      NDN_LOG_INFO("Attaching OptoFlood MetaInfo to Data packet due to mobility event.");

      auto& metaInfo = data->getMetaInfo();
      metaInfo.push_back(make_shared<Block>(TLV_MOBILITY_FLAG));
      // ... (add other fields as before)
      
      // Reset the flag after processing. This is a simplification.
      m_hasMoved = false; 
    }

    m_keyChain.sign(*data);
    NDN_LOG_INFO("<< D: " << *data);
    m_face.put(*data);
  }

private:
  Face m_face;
  KeyChain m_keyChain;
  bool m_hasMoved;
  std::string m_mode;
  NetlinkListener m_netlinkListener;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  std::string mode = "baseline"; // Default to baseline mode
  if (argc == 3 && std::string(argv[1]) == "--mode") {
    mode = argv[2];
    if (mode != "baseline" && mode != "solution") {
      std::cerr << "ERROR: mode must be 'baseline' or 'solution'" << std::endl;
      return 1;
    }
  }

  std::cout << "Running Producer in '" << mode << "' mode." << std::endl;

  try {
    ndn::examples::Producer producer(mode);
    producer.run();
  }
  catch (const std::exception& e) {
    NDN_LOG_ERROR("Exception: " << e.what());
  }
  return 0;
}
