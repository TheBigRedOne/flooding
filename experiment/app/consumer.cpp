// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <unistd.h>

namespace ndn {
namespace examples {

// Application-level TLV type carrying the producer's current live-edge frame
// number in Data MetaInfo. Must match the producer (TLV_LIVE_EDGE / 206).
constexpr uint32_t TLV_LIVE_EDGE = 206;

// Generic name component marking a live-edge discovery Interest (<stream>/_meta).
// Must match the producer.
constexpr char DISCOVERY_MARKER[] = "_meta";

/**
 * @brief Pull-based live-stream consumer that tracks the producer live edge via
 *        Data feedback (no shared clock).
 *
 * On join the consumer discovers the current edge with a MustBeFresh
 * "<stream>/_meta" Interest. It then keeps a lookahead of EXP_WINDOW_FRAMES
 * frames ahead of the edge, fetching each frame as a versioned, segmented object
 * (/<stream>/<version=frame>/<segment>): segment 0 first, its FinalBlockId
 * reveals the segment count K, then the remaining segments. Every received Data
 * reports the current edge, so the consumer slides its window forward; after a
 * disruption it jumps to the latest edge (skipping stale frames), which is the
 * live-streaming "skip to live" behaviour. The frames requested ahead of the
 * edge are the producer-parked Interests that OptoFlood floods on a hand-off.
 */
class Consumer : noncopyable
{
public:
  Consumer()
    : m_face(m_ioContext)
    , m_validator(m_face)
    , m_scheduler(m_ioContext)
  {
    const char* rawStreamPrefix = std::getenv("EXP_STREAM_PREFIX");
    m_streamPrefix = Name(rawStreamPrefix && rawStreamPrefix[0] != '\0'
                          ? rawStreamPrefix : "/LiveStream/v0");

    const char* rawWindow = std::getenv("EXP_WINDOW_FRAMES");
    m_windowFrames = rawWindow ? std::atoi(rawWindow) : 4;
    if (m_windowFrames <= 0) {
      m_windowFrames = 4;
    }

    // Frame production period (ms): used only to size the per-frame timeout so
    // that legitimately parked frames are not declared lost before they can be
    // produced and delivered.
    const char* rawInterval = std::getenv("EXP_REQUEST_INTERVAL_MS");
    int framePeriodMs = rawInterval ? std::atoi(rawInterval) : 20;
    if (framePeriodMs <= 0) {
      framePeriodMs = 20;
    }

    // Per-frame timeout = lookahead (m_windowFrames * framePeriod) plus a reclaim
    // margin. It is the Interest lifetime and the slot-reclaim deadline, not a
    // playout/QoE deadline: it is kept well above any playout deadline evaluated
    // in post-processing (currently <= 1000 ms) so that late-but-delivered frames
    // stay observable instead of being dropped here.
    static constexpr int kReclaimMarginMs = 2000;
    int timeoutMs = m_windowFrames * framePeriodMs + kReclaimMarginMs;
    m_frameTimeout = time::milliseconds(timeoutMs);
  }

  void
  run()
  {
    try {
      m_validator.load("/home/vagrant/flooding/experiment/app/trust-schema.conf");
    }
    catch (const std::exception& e) {
      std::cerr << "ERROR: Failed to load trust schema: " << e.what() << std::endl;
      return;
    }

    std::cout << "[" << nowNs() << "] STARTUP: window " << m_windowFrames
              << " frames, frame timeout " << m_frameTimeout.count() << " ms" << std::endl;

    sendDiscovery();
    m_ioContext.run();
  }

private:
  struct FrameState {
    int expectedSegments = 0;   // known once segment 0 (FinalBlockId) is received
    bool finalKnown = false;
    std::set<uint64_t> received;
    uint64_t startTimeNs = 0;
    scheduler::ScopedEventId deadlineEvent;
  };

  static uint64_t
  nowNs()
  {
    return std::chrono::system_clock::now().time_since_epoch().count();
  }

  // Extract the producer live edge reported in a Data's MetaInfo, if present.
  static std::optional<uint64_t>
  readEdge(const Data& data)
  {
    const Block* block = data.getMetaInfo().findAppMetaInfo(TLV_LIVE_EDGE);
    if (block == nullptr) {
      return std::nullopt;
    }
    try {
      return readNonNegativeInteger(*block);
    }
    catch (const tlv::Error&) {
      return std::nullopt;
    }
  }

  // Discover (or re-acquire) the current live edge. Retried until the producer
  // responds, which also covers start-up and recovery from a long outage.
  void
  sendDiscovery()
  {
    Name name(m_streamPrefix);
    name.append(name::Component(DISCOVERY_MARKER));

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(1_s);

    m_discoveries++;
    std::cout << "[" << nowNs() << "] DISCOVER: " << name << std::endl;

    m_face.expressInterest(interest,
                           [this] (const Interest&, const Data& d) { onDiscoveryData(d); },
                           [this] (const Interest&, const lp::Nack&) { scheduleDiscoveryRetry(); },
                           [this] (const Interest&) { scheduleDiscoveryRetry(); });
  }

  void
  scheduleDiscoveryRetry()
  {
    m_scheduler.schedule(200_ms, [this] { sendDiscovery(); });
  }

  void
  onDiscoveryData(const Data& data)
  {
    auto edge = readEdge(data);
    if (!edge) {
      scheduleDiscoveryRetry();
      return;
    }
    std::cout << "[" << nowNs() << "] DISCOVER: live edge = " << *edge << std::endl;
    m_edgeKnown = true;
    if (*edge > m_edge) {
      m_edge = *edge;
    }
    if (m_requestedUpTo < m_edge) {
      m_requestedUpTo = m_edge;   // start requesting from the live edge
    }
    ensureWindow();
  }

  // Keep the lookahead window filled: request every frame in (edge, edge + L]
  // that has not yet been requested. Frames that fell behind the edge (after a
  // disruption) are skipped and counted as lost (live "skip to latest").
  void
  ensureWindow()
  {
    if (!m_edgeKnown) {
      return;
    }
    if (m_requestedUpTo < m_edge) {
      m_framesSkipped += (m_edge - m_requestedUpTo);
      m_requestedUpTo = m_edge;
    }
    while (m_requestedUpTo < m_edge + static_cast<uint64_t>(m_windowFrames)) {
      startFrame(++m_requestedUpTo);
    }
  }

  void
  updateEdge(uint64_t edge)
  {
    if (edge > m_edge) {
      m_edge = edge;
      ensureWindow();
    }
  }

  void
  startFrame(uint64_t frame)
  {
    m_framesRequested++;
    FrameState& st = m_frames[frame];
    st.startTimeNs = nowNs();
    st.deadlineEvent = m_scheduler.schedule(m_frameTimeout, [this, frame] { onFrameDeadline(frame); });

    std::cout << "[" << nowNs() << "] FRAME: start frame=" << frame << std::endl;
    requestSegment(frame, 0);
  }

  void
  requestSegment(uint64_t frame, uint64_t segment)
  {
    Name name(m_streamPrefix);
    name.appendVersion(frame);
    name.appendSegment(segment);

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(m_frameTimeout);

    m_interestsSent++;
    std::cout << "[" << nowNs() << "] SEND: frame=" << frame << " seg=" << segment
              << " Name: " << name << std::endl;

    m_face.expressInterest(interest,
                           [this] (const Interest& i, const Data& d) { onData(i, d); },
                           [this] (const Interest& i, const lp::Nack& n) { onNack(i, n); },
                           [this] (const Interest& i) { onTimeout(i); });
  }

  void
  onData(const Interest&, const Data& data)
  {
    auto recvTimestamp = nowNs();
    m_segmentsReceived++;

    // Track the live edge reported by the producer (feedback), regardless of
    // whether this Data belongs to a frame still in the window.
    if (auto edge = readEdge(data)) {
      updateEdge(*edge);
    }

    const Name& name = data.getName();
    uint64_t frame = 0;
    uint64_t segment = 0;
    try {
      if (name.size() < 2 || !name.get(-1).isSegment() || !name.get(-2).isVersion()) {
        return;  // discovery or unexpected name; edge already consumed above
      }
      frame = name.get(-2).toVersion();
      segment = name.get(-1).toSegment();
    }
    catch (const tlv::Error& e) {
      std::cerr << "[" << recvTimestamp << "] ERROR: Failed to parse Data name: " << e.what() << std::endl;
      return;
    }

    std::cout << "[" << recvTimestamp << "] DATA: frame=" << frame << " seg=" << segment
              << " Size: " << data.wireEncode().size() << " bytes" << std::endl;

    // Validate the signature against the trust schema. Reception accounting does
    // not gate on validation; the result is logged for trust verification.
    m_validator.validate(data,
      [recvTimestamp] (const Data&) {
        std::cout << "[" << recvTimestamp << "] VALIDATE: Data signature verified" << std::endl;
      },
      [recvTimestamp] (const Data&, const security::ValidationError& error) {
        std::cerr << "[" << recvTimestamp << "] ERROR: Data validation failed: " << error << std::endl;
      });

    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      return;  // frame already completed, lost, or skipped
    }
    FrameState& st = it->second;
    st.received.insert(segment);

    if (segment == 0 && !st.finalKnown) {
      auto finalBlock = data.getFinalBlock();
      if (finalBlock && finalBlock->isSegment()) {
        st.expectedSegments = static_cast<int>(finalBlock->toSegment()) + 1;
      }
      else {
        st.expectedSegments = 1;
      }
      st.finalKnown = true;

      for (uint64_t s = 1; s < static_cast<uint64_t>(st.expectedSegments); ++s) {
        requestSegment(frame, s);
      }
    }

    if (st.finalKnown && static_cast<int>(st.received.size()) >= st.expectedSegments) {
      completeFrame(frame);
    }
  }

  void
  completeFrame(uint64_t frame)
  {
    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      return;
    }
    auto latencyNs = nowNs() - it->second.startTimeNs;
    m_framesDelivered++;

    std::cout << "[" << nowNs() << "] FRAME: delivered frame=" << frame
              << " latency_ms=" << latencyNs / 1000000.0
              << " (delivered " << m_framesDelivered << ", lost " << m_framesLost
              << ", skipped " << m_framesSkipped << ")" << std::endl;

    m_frames.erase(it);   // cancels the per-frame deadline event
    ensureWindow();
  }

  void
  onFrameDeadline(uint64_t frame)
  {
    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      return;   // already completed
    }
    m_framesLost++;

    std::cerr << "[" << nowNs() << "] FRAME: lost frame=" << frame
              << " (timeout; delivered " << m_framesDelivered << ", lost " << m_framesLost
              << ", skipped " << m_framesSkipped << ")" << std::endl;

    m_frames.erase(it);
    if (m_frames.empty()) {
      // Lost the whole window with no feedback source: re-acquire the live edge.
      sendDiscovery();
    }
    else {
      ensureWindow();
    }
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    m_nacks++;
    std::cerr << "[" << nowNs() << "] NACK: " << interest.getName()
              << " Reason: " << nack.getReason() << std::endl;
    // Loss is resolved by the per-frame deadline.
  }

  void
  onTimeout(const Interest& interest)
  {
    m_timeouts++;
    std::cerr << "[" << nowNs() << "] TIMEOUT: " << interest.getName() << std::endl;
    // Loss is resolved by the per-frame deadline.
  }

private:
  boost::asio::io_context m_ioContext;
  Face m_face;
  ValidatorConfig m_validator;
  Scheduler m_scheduler;

  Name m_streamPrefix;
  int m_windowFrames = 4;
  time::milliseconds m_frameTimeout{2000};

  uint64_t m_edge = 0;
  bool m_edgeKnown = false;
  uint64_t m_requestedUpTo = 0;
  std::map<uint64_t, FrameState> m_frames;

  // Statistics for experiment analysis
  uint64_t m_framesRequested = 0;
  uint64_t m_framesDelivered = 0;
  uint64_t m_framesLost = 0;
  uint64_t m_framesSkipped = 0;
  uint64_t m_interestsSent = 0;
  uint64_t m_segmentsReceived = 0;
  uint64_t m_nacks = 0;
  uint64_t m_timeouts = 0;
  uint64_t m_discoveries = 0;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  auto startTime = std::chrono::system_clock::now().time_since_epoch().count();

  std::cout << "[" << startTime << "] STARTUP: Consumer application starting" << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Process ID: " << getpid() << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Live stream consumer (pull-based)" << std::endl;

  try {
    ndn::examples::Consumer consumer;

    std::cout << "[" << startTime << "] STARTUP: Consumer initialized, starting Interest generation" << std::endl;
    consumer.run();
  }
  catch (const std::exception& e) {
    auto errorTime = std::chrono::system_clock::now().time_since_epoch().count();
    std::cerr << "[" << errorTime << "] FATAL: Exception in consumer: " << e.what() << std::endl;
    return 1;
  }

  auto endTime = std::chrono::system_clock::now().time_since_epoch().count();
  std::cout << "[" << endTime << "] SHUTDOWN: Consumer application terminated" << std::endl;
  return 0;
}
