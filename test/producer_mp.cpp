#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/security/signing-helpers.hpp>
#include <iostream>
#include <thread>
#include <atomic>
#include <queue>
#include <map>
#include <mutex>
#include <condition_variable>
#include <chrono>

namespace ndn {
    namespace examples {

        class Producer
        {
        public:
            Producer()
                : keepRunning(true), isMobile(false) {
            }

            void run()
            {
                std::system("nlsrc advertise /example/liveStream");
                m_face.registerPrefix("/example/liveStream",
                    std::bind(&Producer::onRegisterSuccess, this, std::placeholders::_1),
                    std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));
                m_face.setInterestFilter("/example/liveStream",
                    std::bind(&Producer::onInterestReceived, this, std::placeholders::_2),
                    nullptr,
                    std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

                std::cout << "Producer running, waiting for Interests...\n";

                // Start interest processing and face monitoring threads.
                interestProcessingThread = std::thread(&Producer::processInterestQueue, this);
                faceMonitorThread = std::thread(&Producer::monitorFaceStatus, this);

                m_face.processEvents();

                keepRunning.store(false);
                // Notify condition variable to wake up processing thread for clean exit.
                interestQueueCondition.notify_all();
                if (interestProcessingThread.joinable()) {
                    interestProcessingThread.join();
                }
                if (faceMonitorThread.joinable()) {
                    faceMonitorThread.join();
                }
            }

        private:
            // Called on successful prefix registration - keep track of face
            void onRegisterSuccess(const Name& prefix)
            {
                std::cout << "Successfully registered prefix: " << prefix << std::endl;
                {
                    std::lock_guard<std::mutex> lock(faceStatusMutex);
                    lastRegisteredPrefix = prefix;
                    isConnected = true;
                }
                faceStatusCV.notify_all();
            }

            // Monitor face status to detect mobility
            void monitorFaceStatus()
            {
                while (keepRunning.load()) {
                    // Check face status every 500ms
                    std::this_thread::sleep_for(std::chrono::milliseconds(500));

                    try {
                        // Attempt to send a dummy interest to check connectivity
                        Interest probeInterest("/local/nfd/rib/list");
                        probeInterest.setInterestLifetime(100_ms);

                        bool prevConnected;
                        {
                            std::lock_guard<std::mutex> lock(faceStatusMutex);
                            prevConnected = isConnected;
                        }

                        try {
                            m_face.expressInterest(probeInterest,
                                nullptr, // onData
                                nullptr, // onNack
                                nullptr); // onTimeout

                            // If we reach here, the face is able to express interests
                            {
                                std::lock_guard<std::mutex> lock(faceStatusMutex);
                                if (!isConnected && prevConnected) {
                                    // We've reconnected after being disconnected - mobility event
                                    std::cout << "MOBILITY EVENT: Producer has reconnected to the network" << std::endl;

                                    // Set mobile flag to generate mobility data packets for pending interests
                                    isMobile.store(true);

                                    // Notify the interest processing thread to generate data for pending interests
                                    interestQueueCondition.notify_all();
                                }
                                isConnected = true;
                            }
                        }
                        catch (const std::exception& e) {
                            // Connection failed
                            std::lock_guard<std::mutex> lock(faceStatusMutex);
                            if (isConnected) {
                                std::cout << "MOBILITY EVENT: Producer has disconnected from the network" << std::endl;
                                isConnected = false;

                                // Save pending interests to be processed when reconnected
                                std::cout << "Saving pending interests to be processed after reconnection" << std::endl;
                            }
                        }
                    }
                    catch (const std::exception& e) {
                        std::cerr << "Error in face status monitoring: " << e.what() << std::endl;
                    }
                }
            }

            // Add Interest to processing queue
            void onInterestReceived(const Interest& interest)
            {
                int requestedFrame = parseRequestedFrame(interest.getName());
                std::cout << ">> Received Interest for Frame-" << requestedFrame << std::endl;

                {
                    std::lock_guard<std::mutex> lock(interestQueueMutex);
                    // Store interest in the queue for the requested frame.
                    if (interestQueue.find(requestedFrame) == interestQueue.end()) {
                        interestQueue[requestedFrame] = std::queue<Interest>();
                    }
                    interestQueue[requestedFrame].push(interest);
                }

                interestQueueCondition.notify_one();
            }

            // Process Interests from the queue
            void processInterestQueue()
            {
                while (keepRunning.load()) {
                    Interest interest;
                    int requestedFrame = -1;
                    bool interestFound = false;

                    {
                        std::unique_lock<std::mutex> lock(interestQueueMutex);

                        // Wait until the queue is not empty, a mobility event occurs, or the producer is stopping.
                        interestQueueCondition.wait(lock, [this] {
                            return !interestQueue.empty() || isMobile.load() || !keepRunning.load();
                            });

                        if (!keepRunning.load()) {
                            if (interestQueue.empty()) return;
                        }

                        // Get an interest if the queue is not empty.
                        if (!interestQueue.empty()) {
                            auto it = interestQueue.begin();
                            requestedFrame = it->first;
                            interest = it->second.front();
                            it->second.pop();
                            interestFound = true;

                            if (it->second.empty()) {
                                interestQueue.erase(it);
                            }
                        }
                    }

                    if (interestFound) {
                        // Simulate processing delay.
                        std::this_thread::sleep_for(std::chrono::milliseconds(10));

                        // Check if still running after delay.
                        if (!keepRunning.load()) break;

                        // Generate content on-the-fly for VOD scenario.
                        std::string frameContent = "Chunk-" + std::to_string(requestedFrame);

                        // Create Data packet.
                        auto data = std::make_shared<Data>();
                        data->setName(interest.getName());
                        // Set Data FreshnessPeriod.
                        data->setFreshnessPeriod(1_s);
                        data->setContent(makeStringBlock(tlv::Content, frameContent));

                        bool currentlyMobile = isMobile.load();
                        if (currentlyMobile) {
                            auto& metaInfo = const_cast<MetaInfo&>(data->getMetaInfo());
                            metaInfo.setMobilityFlag(true);
                            metaInfo.setFloodingHopLimit(5);

                            auto now = time::system_clock::now().time_since_epoch();
                            auto msTimestamp = time::duration_cast<time::milliseconds>(now);
                            metaInfo.setFloodingTimestamp(msTimestamp);

                            std::cout << "<< Responding with Mobility Data for Chunk-" << requestedFrame << std::endl;
                        }
                        else {
                            std::cout << "<< Responding with Data for Chunk-" << requestedFrame << std::endl;
                        }

                        m_keyChain.sign(*data);
                        m_face.put(*data);

                    }

                    // Reset the mobility flag after processing interests potentially affected by mobility.
                    bool wasMobile = isMobile.load();
                    if (wasMobile) {
                        isMobile.store(false);
                        std::cout << "Mobility response processing cycle complete, reset mobility flag" << std::endl;
                    }
                }
            }

            // Parse the requested frame number from the Interest name
            int parseRequestedFrame(const Name& name)
            {
                // Assume name format: /example/liveStream/<frame-number>
                if (name.size() < 3) {
                    throw std::runtime_error("Invalid Interest name");
                }

                return std::stoi(name[-1].toUri());
            }

            // Handle registration failure
            void onRegisterFailed(const Name& prefix, const std::string& reason)
            {
                std::cerr << "ERROR: Failed to register prefix '" << prefix << "' with the local forwarder (" << reason << ")\n";
                m_face.shutdown();
            }

        private:
            Face m_face;
            KeyChain m_keyChain;

            std::atomic<bool> keepRunning;
            std::atomic<bool> isMobile;

            std::map<int, std::queue<Interest>> interestQueue;
            std::mutex interestQueueMutex;
            std::condition_variable interestQueueCondition;

            // Face status monitoring members.
            std::mutex faceStatusMutex;
            std::condition_variable faceStatusCV;
            bool isConnected = false;
            Name lastRegisteredPrefix;

            std::thread interestProcessingThread;
            std::thread faceMonitorThread;
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
