#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <iostream>

namespace ndn {
	namespace examples {

		class Consumer
		{
		public:
			Consumer()
				: m_scheduler(m_face.getIoContext())
			{
				m_validator.load("/home/vagrant/mini-ndn/flooding/experiments/baseline/trust-schema.conf");
			}

			void run()
			{
				sendInterest();
				m_face.processEvents();
			}

		private:
			void sendInterest()
			{
				Name interestName("/example/LiveStream");
				interestName.appendVersion();
				Interest interest(interestName);
				interest.setMustBeFresh(true);
				interest.setInterestLifetime(6_s);

				std::cout << "Sending Interest " << interest << std::endl;
				m_face.expressInterest(interest,
					std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
					std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
					std::bind(&Consumer::onTimeout, this, std::placeholders::_1));

				// Schedule the next interest
				m_scheduler.schedule(ndn::time::milliseconds(20), [this] { sendInterest(); });
			}

			void onData(const Interest&, const Data& data)
			{
				std::cout << "Received Data " << data << std::endl;
				m_validator.validate(data,
					[](const Data&) {
						std::cout << "Data conforms to trust schema" << std::endl;
					},
					[](const Data&, const security::ValidationError& error) {
						std::cout << "Error authenticating data: " << error << std::endl;
					});
			}

			void onNack(const Interest&, const lp::Nack& nack) const
			{
				std::cout << "Received Nack with reason " << nack.getReason() << std::endl;
			}

			void onTimeout(const Interest& interest) const
			{
				std::cout << "Timeout for " << interest << std::endl;
			}

		private:
			Face m_face;
			ValidatorConfig m_validator{ m_face };
			Scheduler m_scheduler;
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
