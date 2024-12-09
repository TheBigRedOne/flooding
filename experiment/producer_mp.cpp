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

    // Register Interest filter
    m_face.setInterestFilter("/example/liveStream",
                             std::bind(&Producer::onInterestReceived, this, std::placeholders::_2),
                             nullptr,
                             std::bind(&Producer::onRegisterFailed, this, std::placeholders::_1, std::placeholders::_2));

    std::cout << "Producer running, generating video data...\n";

    // Start threads for data generation and processing
    dataGenerationThread = std::thread(&Producer::generateData, this);
    interestProcessingThread = std::thread(&Producer::processInterestQueue, this);

    m_face.processEvents();

    // Shutdown threads
    keepRunning.store(false);
    if (dataGenerationThread.joinable()) {
      dataGenerationThread.join();
    }
    if (interestProcessingThread.joinable()) {
      interestProcessingThread.join();
    }
  }

private:
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

      {
        std::unique_lock<std::mutex> lock(interestQueueMutex);
        interestQueueCondition.wait(lock, [this] {
          return !interestQueue.empty() || !keepRunning.load();
        });

        if (!keepRunning.load() && interestQueue.empty()) {
          return;
        }

        // Get the next Interest to process
        auto it = interestQueue.begin();
        requestedFrame = it->first;
        interest = it->second.front();
        it->second.pop();

        if (it->second.empty()) {
          interestQueue.erase(it);
        }
      }

      // Wait until the requested frame is available
      std::string frameContent;
      {
        std::unique_lock<std::mutex> lock(dataBufferMutex);
        interestQueueCondition.wait(lock, [this, requestedFrame] {
          return dataBuffer.find(requestedFrame) != dataBuffer.end() || !keepRunning.load();
        });

        if (!keepRunning.load()) {
          return;
        }

        frameContent = dataBuffer[requestedFrame];
      }

      // Create and send data packet
      auto data = std::make_shared<Data>();
      data->setName(interest.getName());
      data->setFreshnessPeriod(1_s);
      data->setContent(makeStringBlock(tlv::Content, frameContent));

      // If the producer is mobile, set mobility flag
      if (isMobile.load()) {
        auto& metaInfo = const_cast<MetaInfo&>(data->getMetaInfo());
        metaInfo.setMobilityFlag(true);
        metaInfo.setHopLimit(5);
      }

      m_keyChain.sign(*data);

      std::cout << "<< Responding with Data for Frame-" << requestedFrame << std::endl;
      m_face.put(*data);
    }
  }

  // Parse the requested frame number from the Interest name
  int parseRequestedFrame(const Name& name)
  {
    // Assume name format: /example/liveStream/<frame-number>
    if (name.size() < 2) {
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

  std::thread dataGenerationThread;
  std::thread interestProcessingThread;
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
