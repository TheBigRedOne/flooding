#include <ndn-cxx/face.hpp>
#include <ndn-cxx/security/validator-config.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <iostream>
#include <atomic>
#include <deque>
#include <mutex>

namespace ndn {
namespace examples {

class Consumer
{
public:
  Consumer()
    : m_scheduler(m_face.getIoContext()), frameNumber(0)
  {
    m_validator.load("/home/vagrant/mini-ndn/flooding/experiment/trust-schema.conf");
  }

  void run()
  {
    // 启动重传定时器
    m_scheduler.schedule(ndn::time::seconds(1), [this] { retransmitPendingInterests(); });

    // 发送初始兴趣包
    sendInterest();
    m_face.processEvents();
  }

private:
  void sendInterest()
  {
    // 发送新兴趣包
    Name interestName("/example/liveStream");
    interestName.append(std::to_string(frameNumber)); // 请求 Frame-<frameNumber>
    Interest interest(interestName);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(6_s);

    std::cout << "Sending Interest " << interest << std::endl;

    {
      std::lock_guard<std::mutex> lock(pendingMutex);

      // 如果队列满了，丢弃最早的兴趣包
      if (pendingInterests.size() >= maxPendingSize) {
        std::cout << "Pending queue full, dropping oldest Interest: " 
                  << pendingInterests.front().getName() << std::endl;
        pendingInterests.pop_front();
      }

      // 将兴趣包加入未完成队列
      pendingInterests.push_back(interest);
    }

    m_face.expressInterest(interest,
                           std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
                           std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
                           std::bind(&Consumer::onTimeout, this, std::placeholders::_1));

    // 增加帧号
    frameNumber++;

    // 定时发送下一个兴趣包
    m_scheduler.schedule(ndn::time::milliseconds(33), [this] { sendInterest(); });
  }

  void retransmitPendingInterests()
  {
    std::lock_guard<std::mutex> lock(pendingMutex);

    // 遍历未完成兴趣队列并重传
    for (const auto& interest : pendingInterests) {
      std::cout << "Retransmitting Interest " << interest << std::endl;
      m_face.expressInterest(interest,
                             std::bind(&Consumer::onData, this, std::placeholders::_1, std::placeholders::_2),
                             std::bind(&Consumer::onNack, this, std::placeholders::_1, std::placeholders::_2),
                             std::bind(&Consumer::onTimeout, this, std::placeholders::_1));
    }

    // 重新设置重传定时器
    m_scheduler.schedule(ndn::time::seconds(1), [this] { retransmitPendingInterests(); });
  }

  void onData(const Interest& interest, const Data& data)
  {
    std::cout << "Received Data " << data << std::endl;

    {
      std::lock_guard<std::mutex> lock(pendingMutex);
      // 从未完成队列中移除已完成的兴趣包
      pendingInterests.erase(
        std::remove_if(pendingInterests.begin(), pendingInterests.end(),
                       [&interest](const Interest& pending) {
                         return pending.getName() == interest.getName();
                       }),
        pendingInterests.end());
    }

    // 提取数据内容
    std::string content(reinterpret_cast<const char*>(data.getContent().value()),
                        data.getContent().value_size());
    std::cout << "Frame Content: " << content << std::endl;

    // 验证数据
    m_validator.validate(data,
                         [] (const Data&) {
                           std::cout << "Data conforms to trust schema" << std::endl;
                         },
                         [] (const Data&, const security::ValidationError& error) {
                           std::cout << "Error authenticating data: " << error << std::endl;
                         });
  }

  void onNack(const Interest& interest, const lp::Nack& nack)
  {
    std::cout << "Received Nack for Interest " << interest << " with reason " << nack.getReason() << std::endl;
  }

  void onTimeout(const Interest& interest)
  {
    std::cout << "Timeout for Interest " << interest << std::endl;

    // 超时兴趣包无需特别处理，保持在队列中，等待下一次重传
  }

private:
  Face m_face;
  ValidatorConfig m_validator{m_face};
  Scheduler m_scheduler;
  std::atomic<int> frameNumber; // 当前帧号

  std::deque<Interest> pendingInterests; // 未完成兴趣队列
  std::mutex pendingMutex; // 保护未完成队列的互斥锁
  const size_t maxPendingSize = 100; // 未完成兴趣队列最大容量
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
