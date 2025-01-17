#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <iostream>
#include <atomic>

namespace ndn {
	namespace examples {

		class Consumer
		{
		public:
			Consumer()
				: m_scheduler(m_face.getIoContext()), frameNumber(0)
			{
				m_validator.load("/home/vagrant/mini-ndn/flooding/experiments/tools/trust-schema.conf");
			}

			void run()
			{
				sendInterest();
				m_face.processEvents();
			}

		private:
			void sendInterest()
			{
				// Construct Interest for the current frame
				Name interestName("/example/LiveStream");
				interestName.append(std::to_string(frameNumber)); // Request Frame-<frameNumber>
				Interest interest(interestName);
				interest.setMustBeFresh(true);
				interest.setInterestLifetime(6_s);

				std::cout << "Sending Interest " << interest << std::endl;

				m_face.expressInterest(interest,
					std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
					std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
					std::bind(&Consumer::onTimeout, this, std::placeholders::_1));

				// Increment frame number for the next Interest
				frameNumber++;

				// Schedule the next Interest at a fixed interval
				m_scheduler.schedule(ndn::time::milliseconds(20), [this] { sendInterest(); });
			}

			void onData(const Interest& interest, const Data& data)
			{
				std::cout << "Received Data " << data << std::endl;

				// Extract content
				std::string content(reinterpret_cast<const char*>(data.getContent().value()),
					data.getContent().value_size());
				std::cout << "Frame Content: " << content << std::endl;

				// Validate data
				m_validator.validate(data,
					[](const Data&) {
						std::cout << "Data conforms to trust schema" << std::endl;
					},
					[](const Data&, const security::ValidationError& error) {
						std::cout << "Error authenticating data: " << error << std::endl;
					});
			}

			void onNack(const Interest& interest, const lp::Nack& nack) const
			{
				std::cout << "Received Nack for Interest " << interest << " with reason " << nack.getReason() << std::endl;
			}

			void onTimeout(const Interest& interest) const
			{
				std::cout << "Timeout for Interest " << interest << std::endl;
			}

		private:
			Face m_face;
			ValidatorConfig m_validator{ m_face };
			Scheduler m_scheduler;
			std::atomic<int> frameNumber; // Frame counter
		};

	} // namespace examples
} // namespace ndn

int main(int argc, char** argv)
{
	try {
		ndn::examples::Consumer consumer;
		consumer.run();
		return 0;
	}
	catch (const std::exception& e) {
		std::cerr << "ERROR: " << e.what() << std::endl;
		return 1;
	}
}
