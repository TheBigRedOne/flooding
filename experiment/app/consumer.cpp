// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/encoding/tlv.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
#include <iostream>
#include <map>
#include <chrono>
#include <cstdlib>
#include <unistd.h>

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
    // Request interval (frame period) is supplied by the driver via the
    // EXP_REQUEST_INTERVAL_MS environment variable; 20 ms is a safety-net
    // default for direct runs.
    const char* rawInterval = std::getenv("EXP_REQUEST_INTERVAL_MS");
    int intervalMs = rawInterval ? std::atoi(rawInterval) : 20;
    if (intervalMs <= 0) {
      intervalMs = 20;
    }
    m_interval = time::milliseconds(intervalMs);
  }

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

    std::cout << "[" << std::chrono::system_clock::now().time_since_epoch().count()
              << "] STARTUP: request interval " << m_interval.count() << " ms" << std::endl;

    // Schedule the first Interest request
    sendInterest();

    m_ioContext.run();
  }

private:
  void
  sendInterest()
  {
    // Request the frame for the current sequence number, then advance the
    // sequence number.
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();

    Name interestName("/example/LiveStream");
    interestName.appendVersion(m_sequenceNo);

    std::cout << "[" << timestamp << "] INTEREST: Sending Interest #" << m_sequenceNo << std::endl;
    expressInterest(interestName);
    m_sequenceNo++;

    m_scheduler.schedule(m_interval, [this] { this->sendInterest(); });
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

    m_validator.validate(data,
                       [this, recvTimestamp] (const Data&) {
                         std::cout << "[" << recvTimestamp << "] VALIDATE: Data signature verified" << std::endl;
                       },
                       [this, recvTimestamp] (const Data&, const security::ValidationError& error) {
                         std::cerr << "[" << recvTimestamp << "] ERROR: Data validation failed: " << error << std::endl;
                       });
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_nacksReceived++;

    std::cerr << "[" << timestamp << "] NACK: Received NACK #" << m_nacksReceived
              << " Name: " << interest.getName()
              << " Reason: " << nack.getReason() << std::endl;

    m_sendTimeMap.erase(interest.getName());
  }

  void
  onTimeout(const Interest& interest)
  {
    auto timestamp = std::chrono::system_clock::now().time_since_epoch().count();
    m_timeouts++;

    std::cerr << "[" << timestamp << "] TIMEOUT: Interest timeout #" << m_timeouts
              << " Name: " << interest.getName() << std::endl;

    m_sendTimeMap.erase(interest.getName());

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

private:
  boost::asio::io_context m_ioContext;
  Face m_face;
  ValidatorConfig m_validator;
  Scheduler m_scheduler;

  time::milliseconds m_interval{20};

  uint64_t m_sequenceNo = 0;

  // Statistics for experiment analysis
  uint64_t m_interestsSent = 0;
  uint64_t m_dataReceived = 0;
  uint64_t m_nacksReceived = 0;
  uint64_t m_timeouts = 0;

  // Map to track RTT for each Interest
  std::map<Name, uint64_t> m_sendTimeMap;
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
