// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <map>
#include <optional>
#include <random>
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

// Generic name component marking a guard Interest
// (<stream>/_guard/<clientId>/<seq>). Solution-only keep-alive; must match the
// producer.
constexpr char GUARD_MARKER[] = "_guard";

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

    // Initial lookahead; refined adaptively once the RTT is observed (see
    // updateRttWindow). Serves as the fallback before the first measurement.
    const char* rawWindow = std::getenv("EXP_WINDOW_FRAMES");
    m_windowFrames = rawWindow ? std::atoi(rawWindow) : 4;
    if (m_windowFrames <= 0) {
      m_windowFrames = 4;
    }

    // Target number of Interests kept requested ahead of the producer live edge
    // (producer-parked Interests that OptoFlood floods on a hand-off). The
    // effective window is target + ceil(RTT / framePeriod), so the parked count
    // stays near this target independent of path RTT (topology). This replaces a
    // topology-dependent fixed window with a topology-independent target.
    const char* rawParked = std::getenv("EXP_TARGET_PARKED");
    m_targetParked = rawParked ? std::atoi(rawParked) : 4;
    if (m_targetParked <= 0) {
      m_targetParked = 4;
    }

    // Frame production period (ms): sizes the per-frame timeout and converts the
    // measured RTT into a number of frames for the effective window.
    const char* rawInterval = std::getenv("EXP_REQUEST_INTERVAL_MS");
    m_framePeriodMs = rawInterval ? std::atoi(rawInterval) : 20;
    if (m_framePeriodMs <= 0) {
      m_framePeriodMs = 20;
    }

    // Per-frame timeout = effective lookahead (frames * framePeriod) plus a
    // reclaim margin. It is the Interest lifetime and the slot-reclaim deadline,
    // not a playout/QoE deadline: it is kept well above any playout deadline
    // evaluated in post-processing (currently <= 1000 ms) so that late-but-
    // delivered frames stay observable instead of being dropped here.
    m_effectiveWindow = m_windowFrames;
    m_frameTimeout = time::milliseconds(m_effectiveWindow * m_framePeriodMs + kReclaimMarginMs);

#ifdef SOLUTION_ENABLED
    // Guard keep-alive interval (solution-only). The guard loop keeps a floodable
    // pending Interest at the producer, decoupled from the content window.
    const char* rawGuardInterval = std::getenv("EXP_GUARD_INTERVAL_MS");
    int guardIntervalMs = rawGuardInterval ? std::atoi(rawGuardInterval) : 1000;
    if (guardIntervalMs <= 0) {
      guardIntervalMs = 1000;
    }
    m_guardInterval = time::milliseconds(guardIntervalMs);
#endif
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

    std::cout << "[" << nowNs() << "] STARTUP: target parked " << m_targetParked
              << " frames, initial window " << m_effectiveWindow
              << " frames, frame timeout " << m_frameTimeout.count() << " ms (RTT-adaptive)" << std::endl;

    sendDiscovery();

#ifdef SOLUTION_ENABLED
    // Assign a random per-consumer id so guard names never collide across
    // consumers sharing a stream, then start the keep-alive loop.
    std::random_device rd;
    std::mt19937_64 gen(rd());
    m_clientId = gen();
    std::cout << "[" << nowNs() << "] GUARD: enabled clientId=" << m_clientId
              << " interval_ms=" << m_guardInterval.count() << std::endl;
    sendGuard();
#endif

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
    uint64_t sentNs = nowNs();
    std::cout << "[" << sentNs << "] DISCOVER: " << name << std::endl;

    // Capture the send time to measure a park-free round-trip on the response.
    m_face.expressInterest(interest,
                           [this, sentNs] (const Interest&, const Data& d) { onDiscoveryData(d, sentNs); },
                           [this] (const Interest&, const lp::Nack&) { scheduleDiscoveryRetry(); },
                           [this] (const Interest&) { scheduleDiscoveryRetry(); });
  }

  void
  scheduleDiscoveryRetry()
  {
    m_scheduler.schedule(200_ms, [this] { sendDiscovery(); });
  }

  void
  onDiscoveryData(const Data& data, uint64_t sentNs)
  {
    // Discovery is a pure network round-trip (no producer parking), so it yields
    // a clean RTT estimate for sizing the adaptive lookahead window.
    updateRttWindow(static_cast<double>(nowNs() - sentNs) / 1000000.0);

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

  // Refine the effective lookahead from an observed discovery round-trip so that
  // the number of Interests parked ahead of the live edge stays near
  // m_targetParked regardless of path RTT. Discovery RTT is used (not frame
  // delivery latency) because a parked frame's latency includes producer hold
  // time, which would otherwise create a window/latency feedback loop.
  void
  updateRttWindow(double rttMs)
  {
    if (rttMs <= 0.0 || rttMs > kMaxPlausibleRttMs) {
      return;
    }
    m_rttEwmaMs = (m_rttEwmaMs <= 0.0) ? rttMs
                                       : kRttAlpha * rttMs + (1.0 - kRttAlpha) * m_rttEwmaMs;

    int rttFrames = static_cast<int>(std::ceil(m_rttEwmaMs / m_framePeriodMs));
    int target = m_targetParked + rttFrames;
    int minWindow = m_targetParked + 1;
    target = std::max(minWindow, std::min(target, kMaxWindowFrames));

    if (target != m_effectiveWindow) {
      m_effectiveWindow = target;
      m_frameTimeout = time::milliseconds(m_effectiveWindow * m_framePeriodMs + kReclaimMarginMs);
      std::cout << "[" << nowNs() << "] WINDOW: L=" << m_effectiveWindow
                << " targetParked=" << m_targetParked
                << " rttEwma_ms=" << m_rttEwmaMs << std::endl;
      ensureWindow();
    }
  }

  // Keep the lookahead window filled: request every frame in (edge, edge + L]
  // that has not yet been requested, where L is the effective (RTT-adaptive)
  // window. Frames that fell behind the edge (after a disruption) are skipped
  // and counted as lost (live "skip to latest").
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
    while (m_requestedUpTo < m_edge + static_cast<uint64_t>(m_effectiveWindow)) {
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

#ifdef SOLUTION_ENABLED
  // Guard keep-alive loop: periodically express /<stream>/_guard/<clientId>/<seq>
  // with a fresh seq. The producer parks these and floods one on each hand-off;
  // here only the reported live edge is consumed and loss is ignored (the timer
  // keeps the loop running). Independent of the content window.
  void
  sendGuard()
  {
    Name name(m_streamPrefix);
    name.append(name::Component(GUARD_MARKER));
    name.appendNumber(m_clientId);
    name.appendNumber(m_guardSeq++);

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    // InterestLifetime left at the ndn-cxx default (4 s): a guard is normally
    // answered well before expiry; the lifetime is only the PIT reclaim fallback.

    m_face.expressInterest(interest,
                           [this] (const Interest&, const Data& d) { onGuardData(d); },
                           [] (const Interest&, const lp::Nack&) {},
                           [] (const Interest&) {});

    m_guardTimer = m_scheduler.schedule(m_guardInterval, [this] { this->sendGuard(); });
  }

  void
  onGuardData(const Data& data)
  {
    // Guard replies carry no payload; use only the reported live edge, if present.
    if (auto edge = readEdge(data)) {
      updateEdge(*edge);
    }
  }
#endif

private:
  boost::asio::io_context m_ioContext;
  Face m_face;
  ValidatorConfig m_validator;
  Scheduler m_scheduler;

  // Adaptive lookahead tuning constants.
  static constexpr int kReclaimMarginMs = 2000;
  static constexpr double kRttAlpha = 0.25;         // EWMA weight for new RTT samples
  static constexpr double kMaxPlausibleRttMs = 5000.0;  // reject implausible RTT samples
  static constexpr int kMaxWindowFrames = 64;       // upper bound on effective window

  Name m_streamPrefix;
  int m_windowFrames = 4;          // configured initial lookahead (fallback)
  int m_targetParked = 4;          // desired Interests parked ahead of the live edge
  int m_framePeriodMs = 20;        // frame period; RTT -> frames conversion
  int m_effectiveWindow = 4;       // current lookahead = targetParked + RTT/framePeriod
  double m_rttEwmaMs = 0.0;        // smoothed discovery round-trip time
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

  // Guard keep-alive state (solution-only; unused in baseline builds).
  uint64_t m_clientId = 0;
  uint64_t m_guardSeq = 0;
  time::milliseconds m_guardInterval{1000};
  scheduler::ScopedEventId m_guardTimer;
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
