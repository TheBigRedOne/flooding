// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
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
  }

  void
  run()
  {
    // Load the trust schema for validation
    try {
      m_validator.load("/home/vagrant/mini-ndn/flooding/trust-schema.conf");
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
    
#ifdef SOLUTION_ENABLED
    // Check if we should enable Interest flooding (OptoFlood solution mode)
    if (shouldEnableFlooding()) {
      auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
      std::cout << "[" << timestamp << "] OPTOFLOOD: Enabling Interest flooding due to consecutive failures" << std::endl;
      
      // Add OptoFlood parameters for controlled flooding
      auto params = optoflood::makeInterestFloodingParameters(std::nullopt, DEFAULT_FLOOD_HOP_LIMIT);
      interest.setApplicationParameters(params);
      
      // Reset failure counter after triggering flooding
      m_consecutiveFailures = 0;
    }
#endif
    
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
#ifdef SOLUTION_ENABLED
    m_consecutiveFailures = 0;
#endif

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
#ifdef SOLUTION_ENABLED
    m_consecutiveFailures++;
#endif
    
    std::cerr << "[" << timestamp << "] NACK: Received NACK #" << m_nacksReceived
              << " Name: " << interest.getName() 
              << " Reason: " << nack.getReason()
#ifdef SOLUTION_ENABLED
              << " Consecutive failures: " << m_consecutiveFailures
#endif
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
#ifdef SOLUTION_ENABLED
    m_consecutiveFailures++;
#endif
    
    std::cerr << "[" << timestamp << "] TIMEOUT: Interest timeout #" << m_timeouts
              << " Name: " << interest.getName()
#ifdef SOLUTION_ENABLED
              << " Consecutive failures: " << m_consecutiveFailures
#endif
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
  
#ifdef SOLUTION_ENABLED
  bool
  shouldEnableFlooding() const
  {
    // Enable flooding after 3 consecutive failures (timeout or NACK)
    return m_consecutiveFailures >= 3;
  }
#endif

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
  
#ifdef SOLUTION_ENABLED
  // OptoFlood support
  uint32_t m_consecutiveFailures = 0;
#endif
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
