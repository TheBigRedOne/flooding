#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <iostream>
#include <atomic>
#include <map> // For pendingInterests
#include <mutex> // For thread safety if needed (though scheduler callbacks run sequentially)
#include <chrono> // For timestamps

namespace ndn {
	namespace examples {

		// Define constants for request window, intervals, and timeouts.
		const int REQUEST_WINDOW = 10;
		const time::milliseconds SEND_INTERVAL = 25_ms;
		const time::milliseconds INTEREST_LIFETIME = 4_s;
		const time::milliseconds RETRY_DELAY = 500_ms;

		class Consumer
		{
		public:
			Consumer()
				: m_scheduler(m_face.getIoContext()),
				nextFrameToRequest(0),
				lowestFailedFrame(-1),
				outstandingRetries(0)
			{
				m_validator.load("/home/vagrant/mini-ndn/flooding/trust-schema.conf");
			}

			void run()
			{
				trySendInterests();
				m_face.processEvents();
			}

		private:
			// Attempts to send new interests respecting the window size and failure state.
			void trySendInterests()
			{
				// Only send new interests if no failure has occurred and the window has space.
				while (lowestFailedFrame == -1 && pendingInterests.size() < REQUEST_WINDOW) {
					Name interestName("/example/liveStream");
					interestName.append(std::to_string(nextFrameToRequest));
					Interest interest(interestName);
					interest.setMustBeFresh(true);
					interest.setInterestLifetime(INTEREST_LIFETIME);

					std::cout << "Sending Interest " << interest << " (Pending: " << pendingInterests.size() << ")" << std::endl;

					// Track the pending interest with its send time.
					pendingInterests[nextFrameToRequest] = std::chrono::steady_clock::now();

					m_face.expressInterest(interest,
						std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
						std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
						std::bind(&Consumer::onTimeout, this, std::placeholders::_1));

					nextFrameToRequest++;
				}

				// Schedule the next attempt to send interests.
				m_scheduler.schedule(SEND_INTERVAL, [this] { trySendInterests(); });
			}

			void onData(const Interest& interest, const Data& data)
			{
				int receivedFrame = parseFrameNumber(interest.getName());
				if (receivedFrame < 0) return;

				bool wasPending = pendingInterests.count(receivedFrame) > 0;

				if (wasPending) {
					std::cout << "Received Data " << data.getName() << " for Frame-" << receivedFrame << std::endl;
					pendingInterests.erase(receivedFrame);

					// If this received frame was the one blocking progress, allow sending new interests again.
					if (receivedFrame == lowestFailedFrame.load()) {
						std::cout << "INFO: Received blocking frame " << receivedFrame << ". Resuming sending new interests." << std::endl;
						lowestFailedFrame = -1;
						trySendInterests();
					}
					else if (lowestFailedFrame == -1) {
						// If not blocked, receiving data means we can potentially send more.
						trySendInterests();
					}
				}
				else {
					std::cout << "WARN: Received data for non-pending interest: " << interest.getName() << std::endl;
				}

				// Validate data.
				m_validator.validate(data,
					[](const Data&) { /* Valid */ },
					[](const Data&, const security::ValidationError& error) {
						std::cout << "Error authenticating data: " << error << std::endl;
					});
			}

			void onNack(const Interest& interest, const lp::Nack& nack)
			{
				int nackedFrame = parseFrameNumber(interest.getName());
				std::cout << "Received Nack for Interest " << interest << " (Frame-" << nackedFrame << ") with reason " << nack.getReason() << std::endl;
				handleFailure(interest, nackedFrame);
			}

			void onTimeout(const Interest& interest)
			{
				int timedOutFrame = parseFrameNumber(interest.getName());
				if (pendingInterests.count(timedOutFrame)) {
					std::cout << "Timeout for Interest " << interest << " (Frame-" << timedOutFrame << ")" << std::endl;
					handleFailure(interest, timedOutFrame);
				}
				else {
					std::cout << "WARN: Late Timeout for non-pending interest: " << interest.getName() << std::endl;
				}
			}

			// Helper function to handle Timeout and Nack.
			void handleFailure(const Interest& interest, int failedFrame)
			{
				if (failedFrame < 0) return;

				// Check if it's actually pending.
				if (pendingInterests.count(failedFrame)) {
					// If this is the first failure or an earlier frame failed, update the blocking frame.
					if (lowestFailedFrame == -1 || failedFrame < lowestFailedFrame.load()) {
						std::cout << "INFO: Stopping new interest sending due to failure on Frame-" << failedFrame << std::endl;
						lowestFailedFrame = failedFrame;
					}
					else {
						std::cout << "INFO: Failure for Frame-" << failedFrame << ", but already blocked by Frame-" << lowestFailedFrame.load() << std::endl;
					}

					// Schedule a retry for this specific frame after a delay, if retry limit not reached.
					if (outstandingRetries < REQUEST_WINDOW) {
						outstandingRetries++;
						m_scheduler.schedule(RETRY_DELAY, [this, interest, failedFrame] { resendInterest(interest, failedFrame); });
					}
					else {
						std::cout << "WARN: Too many outstanding retries, skipping retry for Frame-" << failedFrame << std::endl;
					}

				}
				else {
					std::cout << "WARN: Failure for non-pending or already handled interest: " << interest.getName() << std::endl;
				}
			}

			// Function to resend a specific interest.
			void resendInterest(Interest interest, int frameToResend)
			{
				outstandingRetries--;

				// Only resend if it's still pending and is the current blocking frame.
				if (pendingInterests.count(frameToResend) && frameToResend == lowestFailedFrame.load()) {
					// Update timestamp for the resent interest.
					pendingInterests[frameToResend] = std::chrono::steady_clock::now();

					// Reset lifetime and refresh nonce for the retry.
					interest.setInterestLifetime(INTEREST_LIFETIME);
					interest.refreshNonce();

					std::cout << "Resending Interest " << interest << " (Frame-" << frameToResend << ")" << std::endl;
					m_face.expressInterest(interest,
						std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
						std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
						std::bind(&Consumer::onTimeout, this, std::placeholders::_1));
				}
				else {
					std::cout << "INFO: Skipping resend for Frame-" << frameToResend << ". Reason: ";
					if (!pendingInterests.count(frameToResend)) std::cout << "No longer pending." << std::endl;
					else if (frameToResend != lowestFailedFrame.load()) std::cout << "Not the current blocking frame (" << lowestFailedFrame.load() << ")." << std::endl;
					else std::cout << "Unknown." << std::endl;
				}
			}

			// Helper to parse frame number from name.
			int parseFrameNumber(const Name& name) const {
				if (name.empty()) return -1;
				if (name.size() < 2) {
					std::cerr << "ERROR: Name too short to parse frame number: " << name << std::endl;
					return -1;
				}
				try {
					// Assumes name format /prefix/<frame-number>.
					return std::stoi(name[-1].toUri());
				}
				catch (const std::exception& e) {
					std::cerr << "ERROR: Cannot parse frame number from name: " << name << ", Error: " << e.what() << std::endl;
					return -1;
				}
			}

		private:
			Face m_face;
			ValidatorConfig m_validator{ m_face };
			Scheduler m_scheduler;

			// State for VOD simulation.
			std::atomic<int> nextFrameToRequest;
			std::atomic<int> lowestFailedFrame;
			std::atomic<int> outstandingRetries;
			std::map<int, std::chrono::steady_clock::time_point> pendingInterests;
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
