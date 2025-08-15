// consumer.cpp

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include <boost/asio/io_context.hpp>
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
    try {
      m_validator.load("/home/vagrant/mini-ndn/flooding/trust-schema.conf");
    }
    catch (const security::ValidationError& e) {
      std::cerr << "ERROR: Failed to load trust schema: " << e << std::endl;
      return;
    }

    // Schedule the first Interest request
    sendInterest();

    m_ioCtx.run();
  }

private:
  void
  sendInterest()
  {
    // Prioritize retransmitting failed requests
    if (!m_retransmissionQueue.empty()) {
      auto name = m_retransmissionQueue.front();
      m_retransmissionQueue.pop();

      std::cout << "Retransmitting interest for: " << name << std::endl;
      expressInterest(name);
      
      // Schedule the next retransmission check
      m_scheduler.schedule(1_s, [this] { this->sendInterest(); });
      return;
    }
    
    // Otherwise, send a new Interest for the next sequence number
    Name interestName("/example/LiveStream");
    interestName.appendVersion(m_sequenceNo);

    expressInterest(interestName);
    
    // Increment sequence number for the next new interest
    m_sequenceNo++;
  }

  void
  expressInterest(const Name& name)
  {
    std::cout << ">> I: " << name << std::endl;

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
    std::cout << "<< D: " << data << std::endl;

    m_validator.validate(data,
                       [this] (const Data&) {
                         std::cout << "Data validated successfully" << std::endl;
                         // Schedule the next interest to maintain the request interval
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       },
                       [this] (const Data&, const security::ValidationError& error) {
                         std::cerr << "ERROR: Data validation failed: " << error << std::endl;
                         // Also schedule the next interest on validation failure
                         m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
                       });
  }

  void
  onNack(const Interest& interest, const lp::Nack& nack)
  {
    std::cerr << "ERROR: Received Nack for " << interest.getName() 
              << " with reason " << nack.getReason() << std::endl;
    
    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());

    // Schedule the next interest cycle
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
  }

  void
  onTimeout(const Interest& interest)
  {
    std::cerr << "ERROR: Timeout for " << interest.getName() << std::endl;

    // Add the failed interest to the retransmission queue
    m_retransmissionQueue.push(interest.getName());

    // Schedule the next interest cycle
    m_scheduler.schedule(33_ms, [this] { this->sendInterest(); });
  }

private:
  boost::asio::io_context m_ioCtx;
  Face m_face{m_ioCtx};
  ValidatorConfig m_validator{m_face};
  Scheduler m_scheduler{m_ioCtx};

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
    std::cerr << "ERROR: Exception: " << e.what() << std::endl;
  }
  return 0;
}
