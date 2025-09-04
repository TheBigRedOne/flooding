#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/security/signing-helpers.hpp>
#include <iostream>
#include <cstdlib> // for std::system

namespace ndn {
	namespace examples {

		class Producer
		{
		public:
			void run()
			{
				m_face.setInterestFilter("/example/LiveStream",
					std::bind(&Producer::onInterest, this, std::placeholders::_2),
					std::bind(&Producer::onRegisterSuccess, this, std::placeholders::_1),
					std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

				std::cout << "Producer running, waiting for Interests...\n";
				m_face.processEvents();
			}

		private:
			void onInterest(const Interest& interest)
			{
				std::cout << ">> I: " << interest << std::endl;

				auto data = std::make_shared<Data>();
				data->setName(interest.getName());
				data->setFreshnessPeriod(10_s);

				// Set content
				const std::string content = "Hello, world!";
				data->setContent(makeStringBlock(tlv::Content, content));

				// Sign the data using default key
				m_keyChain.sign(*data);

				std::cout << "<< D: " << *data << std::endl;
				m_face.put(*data);
			}

			void onRegisterSuccess(const Name& prefix)
			{
				std::cout << "Successfully registered prefix " << prefix << std::endl;
				std::string command = "nlsrc advertise " + prefix.toUri();
				int res = std::system(command.c_str());
				if (res == 0) {
					std::cout << "Successfully advertised prefix " << prefix << std::endl;
				}
				else {
					std::cerr << "ERROR: failed to advertise prefix " << prefix << std::endl;
				}
			}

			void onRegisterFailed(const Name& prefix, const std::string& reason)
			{
				std::cerr << "ERROR: Failed to register prefix '" << prefix
					<< "' with the local forwarder (" << reason << ")\n";
				m_face.shutdown();
			}

		private:
			Face m_face;
			KeyChain m_keyChain; // Add KeyChain for signing
		};

	} // namespace examples
} // namespace ndn

int main(int argc, char** argv)
{
	try {
		ndn::examples::Producer producer;
		producer.run();
		return 0;
	}
	catch (const std::exception& e) {
		std::cerr << "ERROR: " << e.what() << std::endl;
		return 1;
	}
}
