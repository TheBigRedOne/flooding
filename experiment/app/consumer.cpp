// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
#include <iostream>
#include <queue>
#include <map>
#include <chrono>
#include <unistd.h>

#ifdef SOLUTION_ENABLED
#include <ndn-cxx/optoflood.hpp>
#include <optional>
// Defines the fixed hop limit for controlled Interest flooding.
static constexpr uint8_t DEFAULT_FLOOD_HOP_LIMIT = 3;
#endif

namespace ndn {
namespace examples {

class Consumer : noncopyable
{
public:
  Consumer()
    : m_face(m_ioContext)
    , m_validator(m_face)
    , m_scheduler(m_ioContext)
  {
#ifdef SOLUTION_ENABLED
    // Default enable OptoFlood behavior in solution builds
    m_enableOptoFlood = true;
#endif
  }

  void enableOptoFlood(bool enable = false) { m_enableOptoFlood = enable; }
  void setFloodThreshold(uint32_t threshold) { m_floodThreshold = threshold; }
  void forceFloodOnce() { m_forceFloodInitially = true; m_enableOptoFlood = true; }

  void
  run()
  {
    // Load the trust schema for validation
    try {
      m_validator.load("/home/vagrant/flooding/experiment/app/trust-schema.conf");
    }
    catch (const security::ValidationError& e) {
      std::cerr << "ERROR: Failed to load trust schema: " << e << std::endl;
      return;
    }

    // Schedule the first Interest request
    sendInterest();

    m_ioContext.run();
  }

private:
  void
  sendInterest()
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    
    // Prioritize retransmitting failed requests
    if (!m_retransmissionQueue.empty()) {
      auto name = m_retransmissionQueue.front();
      m_retransmissionQueue.pop();

      std::cout << "[" << timestamp << "] RETRANS: Retransmitting Interest"
                << " Name: " << name 
                << " Queue size: " << m_retransmissionQueue.size() << std::endl;
      expressInterest(name);
      
      // Schedule the next retransmission check
      m_scheduler.schedule(1_s, [this] { this->sendInterest(); });
      return;
    }
    
    // Otherwise, send a new Interest for the next sequence number
    Name interestName("/example/LiveStream");
    interestName.appendVersion(m_sequenceNo);

    std::cout << "[" << timestamp << "] INTEREST: Sending new Interest #" << m_sequenceNo << std::endl;
    expressInterest(interestName);
    
    // Increment sequence number for the next new interest
    m_sequenceNo++;
  }

  void
  expressInterest(const Name& name)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_interestsSent++;
    
    std::cout << "[" << timestamp << "] SEND: Interest #" << m_interestsSent 
              << " Name: " << name << std::endl;

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(6_s); // As per .tex description
    
    // Check if we should enable Interest flooding (OptoFlood solution mode)
    if (shouldEnableFlooding()) {
      auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
      std::cout << "[" << timestamp << "] OPTOFLOOD: Enabling Interest flooding due to consecutive failures" << std::endl;
      
      // Enable ApplicationParameters
#ifdef SOLUTION_ENABLED
      try {
        std::cout << "[" << timestamp << "] AP: build begin" << std::endl;
        // Encode InterestFloodRequest with hopLimit
        ndn::Block inner = ndn::optoflood::makeInterestFloodingParameters(std::optional<uint8_t>(DEFAULT_FLOOD_HOP_LIMIT));
        interest.setApplicationParameters(inner);
        std::cout << "[" << timestamp << "] AP: set ok, valueLen="
                  << interest.getApplicationParameters().value_size() << std::endl;
      }
      catch (const std::exception& ex) {
        std::cerr << "[" << timestamp << "] ERROR: Failed to set ApplicationParameters: " << ex.what() << std::endl;
      }
#endif
#ifdef SOLUTION_ENABLED
      // Set native HopLimit (TLV 34) to control propagation range
      interest.setHopLimit(DEFAULT_FLOOD_HOP_LIMIT);
#endif
      
      // Reset failure counter after triggering flooding
      m_consecutiveFailures = 0;
    }
    else {
      // Not flooding: ensure Interest has no ApplicationParameters and no params-sha256
      interest.unsetApplicationParameters();
    }
    
    // Record send time for latency calculation
    m_sendTimeMap[name] = std::chrono::system_clock::now().time_since_epoch().count();

    m_face.expressInterest(interest,
                           bind(&Consumer::onData, this, _1, _2),
                           bind(&Consumer::onNack, this, _1, _2),
                           bind(&Consumer::onTimeout, this, _1));
  }
  
  void
  onData(const Interest& interest, const Data& data)
  {
    auto recvTimestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_dataReceived++;
    
    // Calculate round-trip time
    auto sendTime = m_sendTimeMap.find(interest.getName());
    if (sendTime != m_sendTimeMap.end()) {
      auto rtt = recvTimestamp - sendTime->second;
      std::cout << "[" << recvTimestamp << "] DATA: Received #" << m_dataReceived 
                << " Name: " << data.getName()
                << " Size: " << data.wireEncode().size() << " bytes"
                << " RTT: " << rtt << " ns (" << rtt/1000000.0 << " ms)" << std::endl;
      m_sendTimeMap.erase(sendTime);
    } else {
      std::cout << "[" << recvTimestamp << "] DATA: Received #" << m_dataReceived 
                << " Name: " << data.getName()
                << " Size: " << data.wireEncode().size() << " bytes"
                << " (RTT unavailable)" << std::endl;
    }

    // Reset consecutive failures on successful data reception
    m_consecutiveFailures = 0;

    m_validator.validate(data,
                       [this, recvTimestamp] (const Data&) {
                         std::cout << "[" << recvTimestamp << "] VALIDATE: Data signature verified" << std::endl;
                         // Schedule the next interest to maintain the request interval
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       },
                       [this, recvTimestamp] (const Data&, const security::ValidationError& error) {
                         std::cerr << "[" << recvTimestamp << "] ERROR: Data validation failed: " << error << std::endl;
                         // Also schedule the next interest on validation failure
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       });
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_nacksReceived++;
    m_consecutiveFailures++;
    
    std::cerr << "[" << timestamp << "] NACK: Received NACK #" << m_nacksReceived
              << " Name: " << interest.getName() 
              << " Reason: " << nack.getReason()
              << " Consecutive failures: " << m_consecutiveFailures
              << std::endl;
    
    // Remove from send time map
    m_sendTimeMap.erase(interest.getName());
    
    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());
    std::cout << "[" << timestamp << "] NACK: Added to retransmission queue"
              << " Queue size: " << m_retransmissionQueue.size() + 1 << std::endl;

    // Schedule the next interest cycle
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
  }

  void
  onTimeout(const Interest& interest)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_timeouts++;
    m_consecutiveFailures++;
    
    std::cerr << "[" << timestamp << "] TIMEOUT: Interest timeout #" << m_timeouts
              << " Name: " << interest.getName()
              << " Consecutive failures: " << m_consecutiveFailures
              << std::endl;
    
    // Remove from send time map
    m_sendTimeMap.erase(interest.getName());

    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());
    std::cout << "[" << timestamp << "] TIMEOUT: Added to retransmission queue"
              << " Queue size: " << m_retransmissionQueue.size() + 1 << std::endl;

    // Schedule the next interest cycle
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
    
    // Log statistics periodically
    if (m_timeouts % 10 == 0) {
      std::cout << "[" << timestamp << "] STATS:"
                << " Sent: " << m_interestsSent
                << " Received: " << m_dataReceived
                << " NACKs: " << m_nacksReceived
                << " Timeouts: " << m_timeouts
                << " Success rate: " << (m_dataReceived * 100.0 / m_interestsSent) << "%"
                << std::endl;
    }
  }
  
  bool
  shouldEnableFlooding()
  {
    if (!m_enableOptoFlood) {
      return false;
    }
    if (m_forceFloodInitially && !m_forceFloodConsumed) {
      m_forceFloodConsumed = true;
      return true;
    }
    return m_consecutiveFailures >= m_floodThreshold;
  }

private:
  boost::asio::io_context m_ioContext;
  Face m_face;
  ValidatorConfig m_validator;
  Scheduler m_scheduler;

  uint64_t m_sequenceNo = 0;
  std::queue<Name> m_retransmissionQueue;
  
  // Statistics for experiment analysis
  uint64_t m_interestsSent = 0;
  uint64_t m_dataReceived = 0;
  uint64_t m_nacksReceived = 0;
  uint64_t m_timeouts = 0;
  
  // Map to track RTT for each Interest
  std::map<Name, uint64_t> m_sendTimeMap;
  
  // OptoFlood support (runtime-configurable)
  bool m_enableOptoFlood = false;
  uint32_t m_consecutiveFailures = 0;
  uint32_t m_floodThreshold = 3;
  bool m_forceFloodInitially = false;
  bool m_forceFloodConsumed = false;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  auto startTime = std::chrono::system_clock::now().time_since_epoch().count();
  
  std::cout << "[" << startTime << "] STARTUP: Consumer application starting" << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Process ID: " << getpid() << std::endl;
  std::cout << "[" << startTime << "] STARTUP: Video stream simulation: 30 fps (33ms intervals)" << std::endl;
  
  try {
    ndn::examples::Consumer consumer;

    // Parse simple CLI flags to control OptoFlood behavior
    // --solution                Enable OptoFlood features
    // --flood-threshold=N       Set consecutive-failure threshold (default 3)
    // --force-flood             Force flooding for the next Interest immediately
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      if (arg == "--solution" || arg == "--mode=solution") {
        consumer.enableOptoFlood(true);
      }
      else if (arg.rfind("--flood-threshold=", 0) == 0) {
        auto value = arg.substr(std::string("--flood-threshold=").size());
        try {
          uint32_t t = static_cast<uint32_t>(std::stoul(value));
          consumer.setFloodThreshold(t);
        }
        catch (...) {}
      }
      else if (arg == "--force-flood") {
        consumer.forceFloodOnce();
      }
    }
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
