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
                : keepRunning(true), frameRate(30), isMobile(false) {}

            void run()
            {
                // Automatically advertise prefix using system call
                std::system("nlsrc advertise /example/liveStream");
                // Register for connection status notifications
                m_face.registerPrefix("/example/liveStream",
                    std::bind(&Producer::onRegisterSuccess, this, std::placeholders::_1),
                    std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

                // Register Interest filter
                m_face.setInterestFilter("/example/liveStream",
                    std::bind(&Producer::onInterestReceived, this, std::placeholders::_2),
                    nullptr,
                    std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

                std::cout << "Producer running, generating video data...\n";

                // Start threads for data generation and processing
                dataGenerationThread = std::thread(&Producer::generateData, this);
                interestProcessingThread = std::thread(&Producer::processInterestQueue, this);
                faceMonitorThread = std::thread(&Producer::monitorFaceStatus, this);

                m_face.processEvents();

                // Shutdown threads
                keepRunning.store(false);
                if (dataGenerationThread.joinable()) {
                    dataGenerationThread.join();
                }
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

            // Data generation thread: simulate video frame generation
            void generateData()
            {
                int frameNumber = 0;
                while (keepRunning.load()) {
                    // Simulate frame generation at a fixed frame rate
                    std::this_thread::sleep_for(std::chrono::milliseconds(1000 / frameRate));

                    // Create frame data
                    std::string frameContent = "Frame-" + std::to_string(frameNumber);
                    {
                        std::lock_guard<std::mutex> lock(dataBufferMutex);
                        dataBuffer[frameNumber] = frameContent;
                    }

                    // Notify waiting threads if Interests are waiting for this frame
                    {
                        std::lock_guard<std::mutex> lock(interestQueueMutex);
                        if (interestQueue.find(frameNumber) != interestQueue.end()) {
                            interestQueueCondition.notify_all();
                        }
                    }

                    std::cout << "Generated data for " << frameContent << std::endl;
                    ++frameNumber;
                }
            }

            // Add Interest to processing queue
            void onInterestReceived(const Interest& interest)
            {
                int requestedFrame = parseRequestedFrame(interest.getName());
                std::cout << ">> Received Interest for Frame-" << requestedFrame << std::endl;

                {
                    std::lock_guard<std::mutex> lock(interestQueueMutex);
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

                        interestQueueCondition.wait(lock, [this] {
                            return !interestQueue.empty() || isMobile.load() || !keepRunning.load();
                            });

                        if (!keepRunning.load()) {
                            if (interestQueue.empty()) return;
                        }

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
                        std::string frameContent;
                        bool frameAvailable = false;

                        {
                            std::unique_lock<std::mutex> lock(dataBufferMutex);
                            interestQueueCondition.wait(lock, [this, requestedFrame] {
                                return !keepRunning.load() || dataBuffer.count(requestedFrame) > 0;
                                });

                            if (keepRunning.load() && dataBuffer.count(requestedFrame) > 0) {
                                frameContent = dataBuffer[requestedFrame];
                                frameAvailable = true;
                                // The frame remains in the dataBuffer after being sent.
                            }
                        }

                        if (frameAvailable) {
                            auto data = std::make_shared<Data>();
                            data->setName(interest.getName());
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

                                std::cout << "<< Responding with Mobility Data for Frame-" << requestedFrame << std::endl;
                            }
                            else {
                                std::cout << "<< Responding with Data for Frame-" << requestedFrame << std::endl;
                            }

                            m_keyChain.sign(*data);
                            m_face.put(*data);
                        }
                        else {
                            std::cout << "WARN: Frame " << requestedFrame << " did not become available for Interest " << interest.getName() << std::endl;
                        }
                    }

                    // Reset the mobility flag after processing interests potentially affected by mobility.
                    // This resets the flag after one processing cycle where mobility was detected.
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
            int frameRate; // Frames per second

            std::map<int, std::string> dataBuffer; // Buffer for generated frames
            std::mutex dataBufferMutex;

            std::map<int, std::queue<Interest>> interestQueue; // Map for received Interests
            std::mutex interestQueueMutex;
            std::condition_variable interestQueueCondition;

            // Face status monitoring
            std::mutex faceStatusMutex;
            std::condition_variable faceStatusCV;
            bool isConnected = false;
            Name lastRegisteredPrefix;

            std::thread dataGenerationThread;
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
