// producer.cpp
//
// Baseline live-stream producer. It serves a versioned, segmented live stream
// under /LiveStream: an Interest for a future frame is parked until that frame's
// live edge is reached, then answered; an Interest for an already-produced frame
// is answered immediately (catch-up). Every Data carries the current live-edge
// frame number (TLV_LIVE_EDGE) so consumers track the edge by feedback without a
// shared clock. A bare <stream>/_meta discovery Interest returns the current edge.
//
// This application contains no mobility/OptoFlood logic. The OptoFlood mobility
// solution lives in the separate optoflood-daemon (control plane) and the NFD
// OptoFlood forwarding module (data plane). The same binary is used for both
// baseline and solution runs; the daemon is launched only for solution runs.

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/meta-info.hpp>
#include <ndn-cxx/encoding/block.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>

#include <chrono>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_set>
#include <unistd.h>

namespace ndn {
namespace examples {

// Application-level TLV type carrying the producer's current live-edge frame
// number in Data MetaInfo (application range [128,252]). Consumers read it to
// track the live edge via feedback, with no shared clock. Must match the consumer.
constexpr uint32_t TLV_LIVE_EDGE = 206;

// Generic name component that marks a live-edge discovery Interest
// (<stream>/_meta). Must match the consumer.
constexpr char DISCOVERY_MARKER[] = "_meta";

class Producer : noncopyable
{
public:
  Producer()
    : m_face(m_ioContext)
    , m_scheduler(m_ioContext)
    , m_keyChain()
  {
    // Frame production period: a new frame becomes available every m_interval,
    // supplied by the driver via EXP_REQUEST_INTERVAL_MS (20 ms safety default).
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
  }

  void
  run()
  {
    // Register the prefix; on success advertise it into NLSR.
    m_face.setInterestFilter("/LiveStream",
                             std::bind(&Producer::onInterest, this, _2),
                             std::bind(&Producer::onRegisterSuccess, this, _1),
                             std::bind(&Producer::onRegisterFailed, this, _1, _2));
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

    std::cout << "[" << timestamp << "] PREFIX: Advertising prefix via NLSR" << std::endl;
    int ret = std::system("nlsrc advertise /LiveStream");
    if (ret != 0) {
      std::cerr << "[" << timestamp << "] ERROR: Failed to advertise prefix with nlsrc (exit code: "
                << ret << ")" << std::endl;
      m_face.shutdown();
    }
    else {
      std::cout << "[" << timestamp << "] PREFIX: Successfully advertised prefix via NLSR" << std::endl;
    }
  }

  void
  onRegisterFailed(const Name& prefix, const std::string& reason)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    std::cerr << "[" << timestamp << "] ERROR: Failed to register prefix '" << prefix
              << "' with reason: " << reason << std::endl;
    m_face.shutdown();
  }

  void
  scheduleDataSend()
  {
    m_scheduler.schedule(m_interval, [this] { this->advanceLiveEdgeAndServe(); });
  }

  // Encode and send one Data packet for a requested (frame, segment). Every Data
  // carries the current live edge (TLV_LIVE_EDGE) so consumers track it by feedback.
  void
  serveOne(const Name& name, time::milliseconds freshness = 10_s)
  {
    auto data = make_shared<Data>(name);
    data->setFreshnessPeriod(freshness);
    // FinalBlockId advertises the last segment index (K-1) of the frame.
    data->setFinalBlock(name::Component::fromSegment(m_segmentsPerFrame - 1));
    data->setContent(std::string_view("LiveStream Data"));

    MetaInfo metaInfo = data->getMetaInfo();
    metaInfo.addAppMetaInfo(makeNonNegativeIntegerBlock(TLV_LIVE_EDGE, edgeNow()));
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
  // (frame <= edgeNow()); drop parked Interests whose lifetime has elapsed.
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
        serveOne(it->name);
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
      serveOne(interestName, 0_ms);
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
      serveOne(interestName);
    }
    else if (m_pendingNames.find(interestName) == m_pendingNames.end()) {
      // Future frame: hold the Interest until the live edge reaches it; drop it
      // once its own lifetime elapses.
      auto expiry = time::steady_clock::now() + interest.getInterestLifetime();
      m_pendingInterests.push_back(PendingInterest{interestName, frame, expiry});
      m_pendingNames.insert(interestName);
    }
    else {
      std::cout << "[" << timestamp << "] INTEREST: Duplicate pending Interest ignored Name: "
                << interestName << std::endl;
    }
  }

private:
  struct PendingInterest {
    Name name;
    uint64_t frame = 0;
    time::steady_clock::time_point expiry{};
  };

  boost::asio::io_context m_ioContext;
  Face m_face{m_ioContext};
  Scheduler m_scheduler;
  KeyChain m_keyChain;

  time::milliseconds m_interval{20};
  int m_segmentsPerFrame = 1;
  time::steady_clock::time_point m_startTime;

  std::deque<PendingInterest> m_pendingInterests;
  std::unordered_set<Name> m_pendingNames;

  // Statistics counters for experiment analysis
  uint64_t m_interestCount = 0;
  uint64_t m_dataCount = 0;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  auto startTime = std::chrono::system_clock::now().time_since_epoch().count();

  std::cout << "[" << startTime << "] STARTUP: Producer application starting" << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Process ID: " << getpid() << std::endl;

  // No application flags are required; any extra CLI arguments are ignored so
  // callers that still pass legacy flags continue to work.
  (void)argc;
  (void)argv;

  try {
    ndn::examples::Producer producer;
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
