// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <map>
#include <set>
#include <unistd.h>

namespace ndn {
namespace examples {

/**
 * @brief Pull-based live-stream consumer with a fixed lookahead window.
 *
 * The consumer keeps at most EXP_WINDOW_FRAMES frames in flight (one slot per
 * frame). Each frame is a versioned, segmented object
 * (/<stream>/<version=frame>/<segment>): segment 0 is requested first, its
 * FinalBlockId reveals the segment count K, and the remaining segments are then
 * requested. A frame that is not fully received within the per-frame timeout is
 * declared lost. On either completion or loss the window slides forward by one
 * frame, so the number of outstanding (and producer-parked) Interests stays
 * bounded by the window regardless of the production rate.
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

    // Frame production period (ms): used to size the per-frame timeout so that
    // legitimately parked frames are not declared lost before they can be
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

    // Prime the lookahead window.
    for (int i = 0; i < m_windowFrames; ++i) {
      startFrame(m_nextFrame++);
    }

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

    const Name& name = data.getName();
    uint64_t frame = 0;
    uint64_t segment = 0;
    try {
      if (name.size() < 2 || !name.get(-1).isSegment() || !name.get(-2).isVersion()) {
        std::cerr << "[" << recvTimestamp << "] ERROR: Unexpected Data name: " << name << std::endl;
        return;
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
      return;  // frame already completed or lost (late or duplicate segment)
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
              << " (delivered " << m_framesDelivered << ", lost " << m_framesLost << ")" << std::endl;

    m_frames.erase(it);          // cancels the per-frame deadline event
    startFrame(m_nextFrame++);   // slide the window forward
  }

  void
  onFrameDeadline(uint64_t frame)
  {
    auto it = m_frames.find(frame);
    if (it == m_frames.end()) {
      return;                    // already completed
    }
    m_framesLost++;

    std::cerr << "[" << nowNs() << "] FRAME: lost frame=" << frame
              << " (timeout; delivered " << m_framesDelivered << ", lost " << m_framesLost << ")" << std::endl;

    m_frames.erase(it);
    startFrame(m_nextFrame++);   // slide the window forward
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
  time::milliseconds m_frameTimeout{200};

  uint64_t m_nextFrame = 0;
  std::map<uint64_t, FrameState> m_frames;

  // Statistics for experiment analysis
  uint64_t m_framesRequested = 0;
  uint64_t m_framesDelivered = 0;
  uint64_t m_framesLost = 0;
  uint64_t m_interestsSent = 0;
  uint64_t m_segmentsReceived = 0;
  uint64_t m_nacks = 0;
  uint64_t m_timeouts = 0;
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
