// consumer.cpp

#include "common.hpp"

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/validator-config.hpp>

#include <iostream>
#include <queue>

namespace ndn {
namespace examples {

class Consumer : noncopyable
{
public:
  void
  run()
  {
    // Load the trust schema for validation
    // This is crucial for security and is based on the provided trust-schema.conf
    try {
      m_validator.load("trust-schema.conf");
    }
    catch (const security::v2::ValidationError& e) {
      NDN_LOG_ERROR("Failed to load trust schema: " << e.what());
      return;
    }

    // Schedule the first Interest request
    sendInterest();

    m_face.processEvents();
  }

private:
  void
  sendInterest()
  {
    // If there's a failed request, prioritize retransmitting it.
    if (!m_retransmissionQueue.empty()) {
      auto name = m_retransmissionQueue.front();
      m_retransmissionQueue.pop();

      NDN_LOG_INFO("Retransmitting interest for: " << name);
      expressInterest(name);
      
      // Schedule the next retransmission check
      m_scheduler.schedule(1_s, [this] { this->sendInterest(); });
      return;
    }
    
    // Otherwise, send a new Interest for the next sequence number.
    Name interestName("/example/LiveStream");
    interestName.appendVersion(m_sequenceNo);

    expressInterest(interestName);
    
    // Increment sequence number for the next new interest
    m_sequenceNo++;
  }

  void
  expressInterest(const Name& name)
  {
    NDN_LOG_INFO(">> I: " << name);

    Interest interest(name);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(6_s); // As per .tex description

    m_face.expressInterest(interest,
                           bind(&Consumer::onData, this, _1, _2),
                           bind(&Consumer::onNack, this, _1, _2),
                           bind(&Consumer::onTimeout, this, _1));
  }
  
  void
  onData(const Interest&, const Data& data)
  {
    NDN_LOG_INFO("<< D: " << data);

    // Validate the received data packet
    m_validator.validate(data,
                       [this] (const Data&) {
                         NDN_LOG_INFO("Data validated successfully");
                         // Schedule the next interest immediately after successful validation
                         // This maintains the 33ms request interval.
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       },
                       [this] (const Data&, const security::v2::ValidationError& error) {
                         NDN_LOG_ERROR("Data validation failed: " << error);
                         // Even on validation failure, we continue to request the next packet.
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       });
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    NDN_LOG_ERROR("Received Nack for " << interest.getName() << " with reason " << nack.getReason());
    
    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());

    // Immediately schedule the next interest cycle. The retransmission will be handled
    // by the check at the beginning of sendInterest.
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
  }

  void
  onTimeout(const Interest& interest)
  {
    NDN_LOG_ERROR("Timeout for " << interest.getName());

    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());

    // Immediately schedule the next interest cycle.
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
  }

private:
  Face m_face;
  ValidatorConfig m_validator{m_face};
  Scheduler m_scheduler{m_face.getIoService()};

  uint64_t m_sequenceNo = 0;
  std::queue<Name> m_retransmissionQueue;
};

} // namespace examples
} // namespace ndn

int
main(int argc, char** argv)
{
  try {
    ndn::examples::Consumer consumer;
    consumer.run();
  }
  catch (const std::exception& e) {
    NDN_LOG_ERROR("Exception: " << e.what());
  }
  return 0;
}
