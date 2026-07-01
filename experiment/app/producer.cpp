// producer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/meta-info.hpp>
#include <ndn-cxx/encoding/block.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/util/scheduler.hpp>

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
#include <deque>
#include <unordered_set>

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

// Application-level TLV type carrying the producer's current live-edge frame
// number in Data MetaInfo (application range [128,252]; distinct from the
// OptoFlood tlv::optoflood::* types 201-205). Consumers read it to track the
// live edge via feedback, with no shared clock. Must match the consumer.
constexpr uint32_t TLV_LIVE_EDGE = 206;

// Generic name component that marks a live-edge discovery Interest
// (<stream>/_meta). Must match the consumer.
constexpr char DISCOVERY_MARKER[] = "_meta";

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
    , m_scheduler(m_ioContext)
    , m_keyChain()
  {
    // Frame production period: a new frame becomes available every m_interval,
    // supplied by the driver via EXP_REQUEST_INTERVAL_MS (20 ms safety-net default).
    const char* rawInterval = std::getenv("EXP_REQUEST_INTERVAL_MS");
    int intervalMs = rawInterval ? std::atoi(rawInterval) : 20;
    if (intervalMs <= 0) {
      intervalMs = 20;
    }
    m_interval = time::milliseconds(intervalMs);

    // Segments per frame (K). FinalBlockId on every segment advertises K-1 so the
    // consumer can fetch all segments. Supplied via EXP_SEGMENTS_PER_FRAME (default 1).
    const char* rawSegments = std::getenv("EXP_SEGMENTS_PER_FRAME");
    m_segmentsPerFrame = rawSegments ? std::atoi(rawSegments) : 1;
    if (m_segmentsPerFrame <= 0) {
      m_segmentsPerFrame = 1;
    }

    // Default to disabled; enable automatically in solution builds
#ifdef SOLUTION_ENABLED
    m_enableOptoFlood = true;
#endif
  }

  void enableOptoFlood(bool enable = true) { m_enableOptoFlood = enable; }
  void forceMobilityOnce() { m_enableOptoFlood = true; m_forceMobilityOnceFlag = true; }

  void
  run()
  {
    // Register prefix with a success callback to advertise it via NLSR
    m_face.setInterestFilter("/LiveStream",
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
    m_startTime = time::steady_clock::now();
    scheduleDataSend();
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
    int ret = std::system("nlsrc advertise /LiveStream");
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
    m_mobilityEventCount++;
    for (auto& pending : m_pendingInterests) {
      pending.markMobility = true;
      pending.mobilitySeq = m_mobilityEventCount;
    }
    std::cout << "[" << timestamp << "] MOBILITY: Total mobility events: " << m_mobilityEventCount << std::endl;
    std::cout << "[" << timestamp << "] MOBILITY: Pending Interests marked: " << m_pendingInterests.size() << std::endl;
  }

  void
  scheduleDataSend()
  {
    m_scheduler.schedule(m_interval, [this] { this->advanceLiveEdgeAndServe(); });
  }

  // Encode and send one Data packet for a requested (frame, segment). Every Data
  // carries the current live edge (TLV_LIVE_EDGE) so consumers track it via
  // feedback. Mobility-marked Data additionally carry OptoFlood markers so the
  // modified forwarder floods them along the FIB to refresh the path.
  void
  serveOne(const Name& name, bool markMobility, uint32_t mobilitySeq,
           time::milliseconds freshness = 10_s)
  {
    auto data = make_shared<Data>(name);
    data->setFreshnessPeriod(freshness);
    // FinalBlockId advertises the last segment index (K-1) of the frame.
    data->setFinalBlock(name::Component::fromSegment(m_segmentsPerFrame - 1));
    data->setContent(std::string_view("OptoFlood Test Data"));

    MetaInfo metaInfo = data->getMetaInfo();
    metaInfo.addAppMetaInfo(makeNonNegativeIntegerBlock(TLV_LIVE_EDGE, edgeNow()));
#ifdef SOLUTION_ENABLED
    if (m_enableOptoFlood && markMobility) {
      uint64_t floodId = ++m_floodIdSeq;
      metaInfo.addAppMetaInfo(optoflood::makeFloodIdBlock(floodId));
      metaInfo.addAppMetaInfo(optoflood::makeNewFaceSeqBlock(mobilitySeq));
      std::cout << "[" << std::chrono::system_clock::now().time_since_epoch().count()
                << "] DATA: Attaching OptoFlood mobility markers"
                << " NewFaceSeq: " << mobilitySeq
                << " FloodId: " << floodId << std::endl;
    }
#endif
    data->setMetaInfo(metaInfo);

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

  // The live edge advances by the producer's own wall-clock: frame N becomes
  // available at m_startTime + N*framePeriod. Computed on demand, independent of
  // per-tick processing time, and requires no cross-node clock synchronisation.
  uint64_t
  edgeNow() const
  {
    auto elapsed = time::steady_clock::now() - m_startTime;
    if (elapsed.count() <= 0) {
      return 0;
    }
    return static_cast<uint64_t>(elapsed / m_interval);
  }

  // Periodic tick: serve every parked Interest whose frame has now been produced
  // (frame <= edgeNow()). Mobility-marked Interests carry OptoFlood markers.
  void
  advanceLiveEdgeAndServe()
  {
    uint64_t edge = edgeNow();

    auto now = time::steady_clock::now();

    // Drop parked Interests whose lifetime has elapsed: the network PIT entry is
    // gone, so any Data produced now would be unsolicited.
    for (auto it = m_pendingInterests.begin(); it != m_pendingInterests.end(); ) {
      if (now > it->expiry) {
        m_pendingNames.erase(it->name);
        it = m_pendingInterests.erase(it);
      }
      else {
        ++it;
      }
    }

    // Serve every parked Interest whose frame has now been produced.
    for (auto it = m_pendingInterests.begin(); it != m_pendingInterests.end(); ) {
      if (it->frame <= edge) {
        serveOne(it->name, it->markMobility, it->mobilitySeq);
        m_pendingNames.erase(it->name);
        it = m_pendingInterests.erase(it);
      }
      else {
        ++it;
      }
    }

    scheduleDataSend();
  }

  void
  onInterest(const Interest& interest)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_interestCount++;
    
    const Name& interestName = interest.getName();
    std::cout << "[" << timestamp << "] INTEREST: Received #" << m_interestCount
              << " Name: " << interestName
              << " CanBePrefix: " << interest.getCanBePrefix()
              << " MustBeFresh: " << interest.getMustBeFresh() << std::endl;

    // Discovery: a bare "<stream>/_meta" Interest asks for the current live edge.
    // Reply with a zero-freshness Data carrying the edge stamp, so a MustBeFresh
    // discovery always reaches the producer instead of a cached copy.
    if (!interestName.empty() && interestName.get(-1) == name::Component(DISCOVERY_MARKER)) {
      serveOne(interestName, false, 0, 0_ms);
      return;
    }

    // Content names follow /<stream>/<version=frame>/<segment>; the frame index
    // gates production against the live edge.
    uint64_t frame = 0;
    try {
      if (interestName.size() >= 2 && interestName.get(-1).isSegment() &&
          interestName.get(-2).isVersion()) {
        frame = interestName.get(-2).toVersion();
      }
      else {
        std::cerr << "[" << timestamp << "] INTEREST: Unrecognized name, ignored Name: "
                  << interestName << std::endl;
        return;
      }
    }
    catch (const tlv::Error& e) {
      std::cerr << "[" << timestamp << "] INTEREST: Failed to parse frame index: "
                << e.what() << std::endl;
      return;
    }

    if (frame <= edgeNow()) {
      // The frame has already been produced: serve immediately (catch-up).
      serveOne(interestName, false, 0);
    }
    else if (m_pendingNames.find(interestName) == m_pendingNames.end()) {
      // Future frame: hold the Interest until the live edge reaches it; drop it
      // once its own lifetime elapses.
      auto expiry = time::steady_clock::now() + interest.getInterestLifetime();
      m_pendingInterests.push_back(PendingInterest{interestName, frame, false, 0, expiry});
      m_pendingNames.insert(interestName);
    }
    else {
      std::cout << "[" << timestamp << "] INTEREST: Duplicate pending Interest ignored Name: "
                << interestName << std::endl;
    }

    if (m_forceMobilityOnceFlag) {
      m_forceMobilityOnceFlag = false;
      onMobilityEvent();
    }
  }

private:
  struct PendingInterest {
    Name name;
    uint64_t frame = 0;
    bool markMobility = false;
    uint32_t mobilitySeq = 0;
    time::steady_clock::time_point expiry{};
  };

  boost::asio::io_context m_ioContext;
  Face m_face{m_ioContext};
  Scheduler m_scheduler;
  KeyChain m_keyChain;

  time::milliseconds m_interval{20};
  int m_segmentsPerFrame = 1;
  time::steady_clock::time_point m_startTime;

  std::unique_ptr<NetlinkListener> m_netlinkListener;
  bool m_enableOptoFlood = false;
  bool m_forceMobilityOnceFlag = false;
  std::deque<PendingInterest> m_pendingInterests;
  std::unordered_set<Name> m_pendingNames;
  uint64_t m_floodIdSeq = 0;
  
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
