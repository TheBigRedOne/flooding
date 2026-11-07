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
 * @brief Pull-based live-stream consumer with fixed-rate Interest pacing.
 *
 * Join and long-outage recovery use a MustBeFresh "<stream>/_meta" Interest.
 * The Producer live edge in that reply is authoritative. The consumer then
 * requests the next L frame versions immediately and continues one new frame
 * per configured period from a local timer. Content Data may move the edge
 * forward, but it is not the scheduler for ordinary requests. Segment 0 still
 * reveals FinalBlockId. Frame deadlines only release application state.
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
    // at join and after a forward resynchronisation. The effective window is
    // target + ceil(RTT / framePeriod). It is not a cap on later paced requests.
    const char* rawParked = std::getenv("EXP_TARGET_PARKED");
    m_targetParked = rawParked ? std::atoi(rawParked) : 4;
    if (m_targetParked <= 0) {
      m_targetParked = 4;
    }

    // Frame production period (ms). Also the fixed Content Interest pacing interval.
    const char* rawInterval = std::getenv("EXP_REQUEST_INTERVAL_MS");
    m_framePeriodMs = rawInterval ? std::atoi(rawInterval) : 20;
    if (m_framePeriodMs <= 0) {
      m_framePeriodMs = 20;
    }

    const char* rawStall = std::getenv("EXP_STALL_MS");
    m_stallMs = rawStall ? std::atoi(rawStall) : 2000;
    if (m_stallMs <= 0) {
      m_stallMs = 2000;
    }

    const char* rawProbe = std::getenv("EXP_PROBE_INTERVAL_MS");
    m_probeIntervalMs = rawProbe ? std::atoi(rawProbe) : 1000;
    if (m_probeIntervalMs <= 0) {
      m_probeIntervalMs = 1000;
    }

    // Exp2 associates each validation result with the Data Name. Unset leaves
    // the historical log lines unchanged.
    const char* rawValidationLog = std::getenv("EXP_LOG_VALIDATION_NAME");
    m_logValidationName = rawValidationLog && std::string(rawValidationLog) == "1";
    const char* rawConsumerId = std::getenv("EXP_CONSUMER_ID");
    if (rawConsumerId && rawConsumerId[0] != '\0') {
      m_consumerId = rawConsumerId;
    }

    // Per-frame timeout = effective lookahead (frames * framePeriod) plus a
    // reclaim margin. It is the Interest lifetime and the slot-reclaim deadline,
    // not a playout/QoE deadline and not the stall threshold.
    m_effectiveWindow = m_windowFrames;
    m_frameTimeout = time::milliseconds(m_effectiveWindow * m_framePeriodMs + kReclaimMarginMs);
  }

  void
  run()
  {
    try {
      const char* schema = std::getenv("EXP_TRUST_SCHEMA");
      const std::string schemaPath =
        (schema != nullptr && schema[0] != '\0')
          ? schema
          : "/home/vagrant/flooding/experiment/app/trust-schema.conf";
      m_validator.load(schemaPath);
      std::cout << "[" << nowNs() << "] TRUST_SCHEMA: " << schemaPath << std::endl;
    }
    catch (const std::exception& e) {
      std::cerr << "ERROR: Failed to load trust schema: " << e.what() << std::endl;
      return;
    }

    std::cout << "[" << nowNs() << "] STARTUP: target parked " << m_targetParked
              << " frames, initial window " << m_effectiveWindow
              << " frames, pace " << m_framePeriodMs
              << " ms, stall " << m_stallMs
              << " ms, probe " << m_probeIntervalMs
              << " ms, frame timeout " << m_frameTimeout.count()
              << " ms (RTT-adaptive)" << std::endl;

    sendDiscovery();

    m_ioContext.run();
  }

private:
  enum class Mode {
    STARTUP,    // existing join discovery; not a recovery state
    STREAMING,
    PROBING,
  };

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

  // Discover (or re-acquire) the current live edge. At most one Interest is
  // in flight. Startup retries stay at 200 ms; PROBING uses the probe interval.
  void
  sendDiscovery()
  {
    if (m_discoveryInFlight) {
      return;
    }
    m_discoveryInFlight = true;
    const uint64_t generation = ++m_discoveryGeneration;

    Name name(m_streamPrefix);
    name.append(name::Component(DISCOVERY_MARKER));

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(1_s);

    m_discoveries++;
    uint64_t sentNs = nowNs();
    std::cout << "[" << sentNs << "] DISCOVER: " << name << std::endl;

    m_face.expressInterest(interest,
                           [this, generation, sentNs] (const Interest&, const Data& d) {
                             onDiscoveryData(d, sentNs, generation);
                           },
                           [this, generation] (const Interest&, const lp::Nack&) {
                             onDiscoveryFailure(generation);
                           },
                           [this, generation] (const Interest&) {
                             onDiscoveryFailure(generation);
                           });
  }

  void
  onDiscoveryFailure(uint64_t generation)
  {
    if (generation != m_discoveryGeneration || m_mode == Mode::STREAMING) {
      return;
    }
    m_discoveryInFlight = false;
    auto delay = m_mode == Mode::PROBING ? time::milliseconds(m_probeIntervalMs) : 200_ms;
    m_discoveryRetry = m_scheduler.schedule(delay, [this, generation] {
      if (generation != m_discoveryGeneration || m_mode == Mode::STREAMING) {
        return;
      }
      sendDiscovery();
    });
  }

  void
  onDiscoveryData(const Data& data, uint64_t sentNs, uint64_t generation)
  {
    if (generation != m_discoveryGeneration || m_mode == Mode::STREAMING) {
      return;
    }
    m_discoveryInFlight = false;
    m_discoveryRetry.cancel();

    // Discovery is a pure network round-trip (no producer parking), so it yields
    // a clean RTT estimate for sizing the initial lookahead.
    updateRttWindow(static_cast<double>(nowNs() - sentNs) / 1000000.0);

    auto edge = readEdge(data);
    if (!edge) {
      onDiscoveryFailure(generation);
      return;
    }
    std::cout << "[" << nowNs() << "] DISCOVER: live edge = " << *edge << std::endl;
    beginStreaming(*edge);
  }

  // Refine the lookahead used by the next prime. Does not emit Content Interests.
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
    }
  }

  void
  beginStreaming(uint64_t edge)
  {
    m_frames.clear();
    ++m_session;
    m_mode = Mode::STREAMING;
    m_edge = edge;
    // _meta is a new session anchor, not a Content-Data correction.
    m_requestedUpTo = edge;
    primeLookahead();
    // The pace timeline starts after the initial burst, so priming does not consume a slot.
    m_paceEpoch = time::steady_clock::now();
    m_paceSlot = 1;
    armPace();
    armStall();
    std::cout << "[" << nowNs() << "] MODE: STREAMING edge=" << m_edge
              << " requestedUpTo=" << m_requestedUpTo
              << " L=" << m_effectiveWindow << std::endl;
  }

  // Request every not-yet-requested frame in (m_requestedUpTo, m_edge + L].
  // Used at join and when Producer feedback shows the cursor fell behind.
  void
  primeLookahead()
  {
    uint64_t lead = m_edge + static_cast<uint64_t>(m_effectiveWindow);
    while (m_requestedUpTo < lead) {
      startFrame(++m_requestedUpTo);
    }
  }

  // Next callback is epoch + m_paceSlot periods. A late callback shortens the
  // following wait. Slots already in the past are skipped and do not send Interests.
  void
  armPace()
  {
    if (m_mode != Mode::STREAMING) {
      return;
    }
    const auto period = time::milliseconds(m_framePeriodMs);
    auto now = time::steady_clock::now();
    auto deadline = m_paceEpoch + period * m_paceSlot;
    while (deadline <= now) {
      ++m_paceSlot;
      deadline = m_paceEpoch + period * m_paceSlot;
    }
    auto delay = time::duration_cast<time::nanoseconds>(deadline - now);
    if (delay <= time::nanoseconds::zero()) {
      delay = time::nanoseconds(1);
    }
    const uint64_t session = m_session;
    m_paceEvent = m_scheduler.schedule(delay, [this, session] {
      if (session != m_session || m_mode != Mode::STREAMING) {
        return;
      }
      onPaceTick();
    });
  }

  // One new frame version per interval. Not gated on m_edge or on Data arrival.
  void
  onPaceTick()
  {
    startFrame(++m_requestedUpTo);
    ++m_paceSlot;
    armPace();
  }

  void
  armStall()
  {
    m_stallEvent = m_scheduler.schedule(time::milliseconds(m_stallMs), [this] {
      onStall();
    });
  }

  void
  noteProgress()
  {
    if (m_mode == Mode::STREAMING) {
      armStall();
    }
  }

  void
  onStall()
  {
    if (m_mode != Mode::STREAMING) {
      return;
    }
    enterProbing();
  }

  void
  enterProbing()
  {
    m_mode = Mode::PROBING;
    ++m_session;
    m_paceEvent.cancel();
    m_stallEvent.cancel();
    m_framesLost += m_frames.size();
    m_frames.clear();
    std::cout << "[" << nowNs() << "] MODE: PROBING" << std::endl;
    sendDiscovery();
  }

  // Content feedback may only move the live edge forward. A cursor already
  // ahead of that edge is left to the pacing timer.
  void
  applyForwardEdge(uint64_t edge)
  {
    if (edge <= m_edge) {
      return;
    }
    m_edge = edge;
    if (m_requestedUpTo < m_edge) {
      m_framesSkipped += (m_edge - m_requestedUpTo);
      m_requestedUpTo = m_edge;
      primeLookahead();
    }
  }

  void
  startFrame(uint64_t frame)
  {
    if (m_frames.find(frame) != m_frames.end()) {
      return;
    }
    m_framesRequested++;
    FrameState& st = m_frames[frame];
    st.startTimeNs = nowNs();
    const uint64_t session = m_session;
    st.deadlineEvent = m_scheduler.schedule(m_frameTimeout, [this, frame, session] {
      onFrameDeadline(frame, session);
    });

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
    if (m_mode != Mode::STREAMING) {
      return;
    }
    auto recvTimestamp = nowNs();
    m_segmentsReceived++;

    bool progressed = false;
    // The live-edge value is metadata. It is not the frame version of this Data.
    if (auto edge = readEdge(data)) {
      if (*edge > m_edge) {
        applyForwardEdge(*edge);
        progressed = true;
      }
    }

    const Name& name = data.getName();
    uint64_t frame = 0;
    uint64_t segment = 0;
    try {
      if (name.size() < 2 || !name.get(-1).isSegment() || !name.get(-2).isVersion()) {
        if (progressed) {
          noteProgress();
        }
        return;
      }
      frame = name.get(-2).toVersion();
      segment = name.get(-1).toSegment();
    }
    catch (const tlv::Error& e) {
      std::cerr << "[" << recvTimestamp << "] ERROR: Failed to parse Data name: " << e.what() << std::endl;
      if (progressed) {
        noteProgress();
      }
      return;
    }

    std::cout << "[" << recvTimestamp << "] DATA: frame=" << frame << " seg=" << segment
              << " Size: " << data.wireEncode().size() << " bytes" << std::endl;

    // Validate the signature against the trust schema. Reception accounting does
    // not gate on validation; the result is logged for trust verification.
    if (m_logValidationName) {
      Name loggedName = name;
      std::string loggedId = m_consumerId;
      m_validator.validate(data,
        [recvTimestamp, loggedName, loggedId] (const Data&) {
          std::cout << "[" << recvTimestamp << "] VALIDATE: Data signature verified"
                    << " name=" << loggedName;
          if (!loggedId.empty()) {
            std::cout << " id=" << loggedId;
          }
          std::cout << std::endl;
        },
        [recvTimestamp, loggedName, loggedId] (const Data&, const security::ValidationError& error) {
          std::cerr << "[" << recvTimestamp << "] ERROR: Data validation failed: " << error
                    << " name=" << loggedName;
          if (!loggedId.empty()) {
            std::cerr << " id=" << loggedId;
          }
          std::cerr << std::endl;
        });
    }
    else {
      m_validator.validate(data,
        [recvTimestamp] (const Data&) {
          std::cout << "[" << recvTimestamp << "] VALIDATE: Data signature verified" << std::endl;
        },
        [recvTimestamp] (const Data&, const security::ValidationError& error) {
          std::cerr << "[" << recvTimestamp << "] ERROR: Data validation failed: " << error << std::endl;
        });
    }

    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      if (progressed) {
        noteProgress();
      }
      return;  // frame already completed, lost, or skipped
    }
    FrameState& st = it->second;
    if (!st.received.insert(segment).second) {
      if (progressed) {
        noteProgress();
      }
      return;  // duplicate segment does not by itself extend the stall timer
    }
    noteProgress();

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
  }

  void
  onFrameDeadline(uint64_t frame, uint64_t session)
  {
    if (session != m_session) {
      return;
    }
    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      return;   // already completed
    }
    m_framesLost++;

    std::cerr << "[" << nowNs() << "] FRAME: lost frame=" << frame
              << " (timeout; delivered " << m_framesDelivered << ", lost " << m_framesLost
              << ", skipped " << m_framesSkipped << ")" << std::endl;

    m_frames.erase(it);
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    m_nacks++;
    std::cerr << "[" << nowNs() << "] NACK: " << interest.getName()
              << " Reason: " << nack.getReason() << std::endl;
    // Loss is resolved by the per-frame deadline. Pacing is independent.
  }

  void
  onTimeout(const Interest& interest)
  {
    m_timeouts++;
    std::cerr << "[" << nowNs() << "] TIMEOUT: " << interest.getName() << std::endl;
    // Loss is resolved by the per-frame deadline. Pacing is independent.
  }

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
  bool m_logValidationName = false;
  std::string m_consumerId;
  int m_windowFrames = 4;          // configured initial lookahead (fallback)
  int m_targetParked = 4;          // desired Interests parked ahead of the live edge
  int m_framePeriodMs = 20;        // frame period and pacing interval
  int m_stallMs = 2000;
  int m_probeIntervalMs = 1000;
  int m_effectiveWindow = 4;       // lookahead lead = targetParked + RTT/framePeriod
  double m_rttEwmaMs = 0.0;        // smoothed discovery round-trip time
  time::milliseconds m_frameTimeout{2000};

  Mode m_mode = Mode::STARTUP;
  uint64_t m_session = 0;
  bool m_discoveryInFlight = false;
  uint64_t m_discoveryGeneration = 0;
  scheduler::ScopedEventId m_discoveryRetry;
  scheduler::ScopedEventId m_paceEvent;
  scheduler::ScopedEventId m_stallEvent;
  time::steady_clock::time_point m_paceEpoch;
  uint64_t m_paceSlot = 1;

  uint64_t m_edge = 0;
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
