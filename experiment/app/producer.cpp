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
#include <chrono>
#include <thread>

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
      std::cerr << "Netlink socket error: " << error.message() << std::endl;
      return;
    }

    char buf[8192];
    struct iovec iov = { buf, sizeof(buf) };
    struct sockaddr_nl sa;
    struct msghdr msg = { &sa, sizeof(sa), &iov, 1, nullptr, 0, 0 };

    ssize_t len = recvmsg(m_netlinkSocket.native_handle(), &msg, 0);
    if (len < 0) {
      std::cerr << "Netlink recvmsg failed" << std::endl;
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
                std::cout << "<<<<< MOBILITY EVENT DETECTED: Interface '" << ifname << "' is UP >>>>>" << std::endl;
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
  boost::asio::io_context& m_ioService;
  MobilityCallback m_callback;
  boost::asio::posix::stream_descriptor m_netlinkSocket;
};


class Producer : noncopyable
{
public:
  Producer(const std::string& mode)
    : m_mode(mode)
    , m_hasMoved(false)
    , m_netlinkListener(m_ioCtx, std::bind(&Producer::onMobilityEvent, this))
  {
  }

  void
  run()
  {
    // The order of operations is critical for stability in this environment.
    // 1. First, register the interest filter with the local NFD.
    // This ensures that the local forwarder knows what to do with incoming interests
    // before we announce the prefix to the wider network.
    m_face.setInterestFilter("/example/LiveStream",
                             std::bind(&Producer::onInterest, this, _1, _2),
                             [] (const auto&, const auto& reason) {
                               std::cerr << "ERROR: Failed to register prefix: " << reason << std::endl;
                             });

    // Give the face a moment to process the registration.
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // 2. Second, explicitly advertise the prefix via NLSR.
    // Now that the local NFD is ready, we can safely tell the network to send interests.
    if (std::system("nlsrc advertise /example/LiveStream") != 0) {
        std::cerr << "ERROR: Failed to advertise prefix with nlsrc." << std::endl;
        m_face.shutdown();
        return;
    }

    // In solution mode, start listening for real network events.
    if (m_mode == "solution") {
      try {
        m_netlinkListener.start();
        std::cout << "Netlink listener started for mobility detection." << std::endl;
      }
      catch (const std::exception& e) {
        std::cerr << "ERROR: Failed to start Netlink listener: " << e.what() << std::endl;
      }
    }

    m_ioCtx.run();
  }

private:
  // This callback is triggered by the NetlinkListener
  void
  onMobilityEvent()
  {
    std::cout << "<<<<< MOBILITY EVENT DETECTED via Netlink >>>>>" << std::endl;
    m_hasMoved = true;
  }

  void
  onInterest(const InterestFilter&, const Interest& interest)
  {
    std::cout << ">> I: " << interest << std::endl;

    auto data = make_shared<Data>(interest.getName());
    data->setFreshnessPeriod(10_s);
    data->setContent(std::string_view("OptoFlood Test Data"));

    if (m_mode == "solution" && m_hasMoved) {
      std::cout << "Attaching OptoFlood MetaInfo to Data packet due to mobility event." << std::endl;

      // This is the correct way for this ndn-cxx version, based on compiler feedback.
      // 1. Create a parent Block that will represent the entire MetaInfo
      Block metaBlock(tlv::MetaInfo);

      // 2. Create the specific TLV block for our flag
      Block mobilityFlagBlock(TLV_MOBILITY_FLAG);
      
      // 3. Add our flag block as a child to the parent MetaInfo block
      metaBlock.push_back(mobilityFlagBlock);

      // Here you can add other TLV fields as needed. For example:
      // Block floodIdBlock(TLV_FLOOD_ID);
      // floodIdBlock.assign( ... content ... );
      // metaBlock.push_back(floodIdBlock);
      
      // 4. Construct the final MetaInfo object from our prepared parent Block
      data->setMetaInfo(MetaInfo(metaBlock));
      
      // Reset the flag after processing. This is a simplification.
      m_hasMoved = false; 
    }

    m_keyChain.sign(*data);
    std::cout << "<< D: " << *data << std::endl;
    m_face.put(*data);
  }

private:
  boost::asio::io_context m_ioCtx;
  Face m_face{m_ioCtx};
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
    std::cerr << "ERROR: Exception: " << e.what() << std::endl;
  }
  return 0;
}
