// optoflood-daemon.cpp
//
// Standalone OptoFlood mobility control daemon. It relocates the mobility
// control-plane logic (guard keep-alive, host mobility detection, guard-Data
// signing) out of the business producer/consumer applications so those apps
// remain plain baseline NDN apps. The daemon runs as a separate process
// alongside NFD on each participating node, analogous to NLSR: it drives the
// local NFD's OptoFlood forwarding module via ordinary NDN packets.
//
// Roles (selected via argv[1] or env OPTOFLOOD_ROLE):
//   consumer : periodically re-express a constant guard Interest
//              <advertisedPrefix>/_guard so that one aggregated guard Interest
//              is always pending at the producer (PIT aggregation collapses all
//              consumers of a prefix into a single guard).
//   producer : register <advertisedPrefix>/_guard, hold the single aggregated
//              guard Interest without replying, detect host mobility via
//              Netlink, and on mobility flood that one guard Data (carrying the
//              OptoFlood mobility markers) so the modified NFD installs TFIB and
//              repairs the path.
//
// Configuration (environment variables):
//   OPTOFLOOD_ROLE          "consumer" | "producer" (overridden by argv[1])
//   GUARD_PREFIX            producer advertised/movable prefix (default /LiveStream)
//   EXP_GUARD_INTERVAL_MS   consumer re-express period P in ms (default 1000)

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/data.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/meta-info.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <ndn-cxx/optoflood.hpp>

#include <boost/asio/io_context.hpp>
#include <boost/asio/posix/stream_descriptor.hpp>

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <cerrno>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <thread>

// Linux Netlink headers for host interface-state (mobility) detection.
#include <asm/types.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <unistd.h>

namespace ndn {
namespace optoflood_daemon {

// Guard control sub-namespace marker. The guard name is the constant
// <advertisedPrefix>/_guard; a leading underscore marks it as a reserved
// control component (consistent with the discovery "_meta" marker).
constexpr char GUARD_MARKER[] = "_guard";

static uint64_t
nowNs()
{
  return std::chrono::system_clock::now().time_since_epoch().count();
}

/**
 * @brief Listens for host network-interface state changes via a Netlink socket
 *        and reports them as mobility events. Relocated unchanged from the
 *        former producer application so mobility detection lives in the daemon.
 */
class NetlinkListener : noncopyable
{
public:
  using MobilityCallback = std::function<void()>;

  NetlinkListener(boost::asio::io_context& io, MobilityCallback callback)
    : m_callback(std::move(callback))
    , m_netlinkSocket(io)
  {
  }

  void
  start()
  {
    int sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (sock < 0) {
      throw std::runtime_error("Failed to create Netlink socket");
    }

    struct sockaddr_nl sa;
    memset(&sa, 0, sizeof(sa));
    sa.nl_family = AF_NETLINK;
    sa.nl_groups = RTMGRP_LINK;

    if (bind(sock, (struct sockaddr*)&sa, sizeof(sa)) < 0) {
      close(sock);
      throw std::runtime_error("Failed to bind Netlink socket");
    }

    m_netlinkSocket.assign(sock);
    waitForEvent();
  }

private:
  void
  waitForEvent()
  {
    m_netlinkSocket.async_wait(boost::asio::posix::stream_descriptor::wait_read,
                               bind(&NetlinkListener::handleEvent, this, _1));
  }

  void
  handleEvent(const boost::system::error_code& error)
  {
    if (error) {
      std::cerr << "[" << nowNs() << "] ERROR: Netlink socket error: " << error.message()
                << " (code: " << error.value() << ")" << std::endl;
      if (error == boost::asio::error::operation_aborted) {
        return;
      }
      std::this_thread::sleep_for(std::chrono::seconds(1));
      waitForEvent();
      return;
    }

    char buf[8192];
    struct iovec iov = { buf, sizeof(buf) };
    struct sockaddr_nl sa;
    struct msghdr msg = { &sa, sizeof(sa), &iov, 1, nullptr, 0, 0 };

    ssize_t len = recvmsg(m_netlinkSocket.native_handle(), &msg, 0);
    if (len < 0) {
      int err = errno;
      std::cerr << "[" << nowNs() << "] ERROR: Netlink recvmsg failed: " << strerror(err)
                << " (errno: " << err << ")" << std::endl;
      if (err == EAGAIN || err == EWOULDBLOCK || err == ENOBUFS) {
        waitForEvent();
      }
      return;
    }

    for (struct nlmsghdr* nlh = (struct nlmsghdr*)buf; NLMSG_OK(nlh, len); nlh = NLMSG_NEXT(nlh, len)) {
      if (nlh->nlmsg_type == RTM_NEWLINK) {
        struct ifinfomsg* ifi = (struct ifinfomsg*)NLMSG_DATA(nlh);
        if ((ifi->ifi_flags & IFF_UP) && (ifi->ifi_flags & IFF_RUNNING)) {
          struct rtattr* rta = IFLA_RTA(ifi);
          int rta_len = nlh->nlmsg_len - NLMSG_LENGTH(sizeof(*ifi));
          for (; RTA_OK(rta, rta_len); rta = RTA_NEXT(rta, rta_len)) {
            if (rta->rta_type == IFLA_IFNAME) {
              std::string ifname(static_cast<char*>(RTA_DATA(rta)));
              std::cout << "[" << nowNs() << "] MOBILITY: interface '" << ifname
                        << "' UP (flags 0x" << std::hex << ifi->ifi_flags << std::dec
                        << "); triggering mobility handler" << std::endl;
              m_callback();
              break;
            }
          }
        }
      }
    }
    waitForEvent();
  }

private:
  MobilityCallback m_callback;
  boost::asio::posix::stream_descriptor m_netlinkSocket;
};

/**
 * @brief Consumer-side role: keep one guard Interest continuously pending at
 *        the producer by re-expressing the constant name <advertisedPrefix>/_guard
 *        every P. Each expression carries a fresh nonce and MustBeFresh so it is
 *        never answered from a Content Store. Guard replies (on hand-off) are a
 *        pure flood trigger and carry no payload, so nothing is consumed here.
 */
class GuardConsumer : noncopyable
{
public:
  GuardConsumer(const Name& advertisedPrefix, time::milliseconds interval)
    : m_face(m_io)
    , m_scheduler(m_io)
    , m_guardName(Name(advertisedPrefix).append(GUARD_MARKER))
    , m_interval(interval)
  {
  }

  void
  run()
  {
    std::cout << "[" << nowNs() << "] GUARD-CONSUMER: name=" << m_guardName
              << " interval_ms=" << m_interval.count() << std::endl;
    sendGuard();
    m_io.run();
  }

private:
  void
  sendGuard()
  {
    // A fresh Interest object each period yields a fresh nonce; the name is the
    // constant guard name so all consumers of the prefix aggregate in the PIT.
    Interest interest(m_guardName);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    // InterestLifetime left at the ndn-cxx default; the guard is a keep-alive,
    // re-expressed every P well within its lifetime.

    m_face.expressInterest(interest,
                           [] (const Interest&, const Data&) {},
                           [] (const Interest&, const lp::Nack&) {},
                           [] (const Interest&) {});

    m_timer = m_scheduler.schedule(m_interval, [this] { this->sendGuard(); });
  }

  boost::asio::io_context m_io;
  Face m_face;
  Scheduler m_scheduler;
  Name m_guardName;
  time::milliseconds m_interval;
  scheduler::ScopedEventId m_timer;
};

/**
 * @brief Producer-side role: register the single guard sub-namespace
 *        <advertisedPrefix>/_guard, hold the (aggregated) guard Interest without
 *        replying in steady state, and on host mobility flood one guard Data
 *        carrying the OptoFlood mobility markers. One guard Data repairs all
 *        consumers of the prefix via network-wide TFIB installation.
 */
class GuardProducer : noncopyable
{
public:
  explicit
  GuardProducer(const Name& advertisedPrefix)
    : m_face(m_io)
    , m_scheduler(m_io)
    , m_advertisedPrefix(advertisedPrefix)
    , m_guardName(Name(advertisedPrefix).append(GUARD_MARKER))
  {
  }

  void
  run()
  {
    m_face.setInterestFilter(m_guardName,
                             std::bind(&GuardProducer::onGuardInterest, this, _2),
                             std::bind(&GuardProducer::onRegisterSuccess, this, _1),
                             std::bind(&GuardProducer::onRegisterFailed, this, _1, _2));
    try {
      m_netlink = std::make_unique<NetlinkListener>(m_io, [this] { this->onMobilityEvent(); });
      m_netlink->start();
      std::cout << "[" << nowNs() << "] GUARD-PRODUCER: Netlink mobility detection started"
                << std::endl;
    }
    catch (const std::exception& e) {
      std::cerr << "[" << nowNs() << "] ERROR: Netlink listener failed: " << e.what() << std::endl;
    }
    m_io.run();
  }

private:
  void
  onRegisterSuccess(const Name& prefix)
  {
    std::cout << "[" << nowNs() << "] GUARD-PRODUCER: registered guard prefix " << prefix
              << std::endl;
  }

  void
  onRegisterFailed(const Name& prefix, const std::string& reason)
  {
    std::cerr << "[" << nowNs() << "] ERROR: failed to register guard prefix " << prefix
              << ": " << reason << std::endl;
    m_face.shutdown();
  }

  // Hold the aggregated guard: record the pending Interest and the instant its
  // lifetime lapses; do NOT reply in steady state. The expiry mirrors what the local
  // NFD recorded for the corresponding PIT in-record, and follows the same rule the
  // baseline producer applies to parked business Interests: once the lifetime has
  // elapsed the PIT entry is gone, so a Data produced then would be unsolicited.
  void
  onGuardInterest(const Interest& interest)
  {
    m_heldGuard = HeldGuard{interest.getName(),
                            time::steady_clock::now() + interest.getInterestLifetime()};
    std::cout << "[" << nowNs() << "] GUARD-PRODUCER: holding guard " << interest.getName()
              << " lifetime_ms=" << interest.getInterestLifetime().count() << std::endl;
  }

  // Host mobility: advance the epoch, arm the local NFD for the stranded business
  // Data, and reply to the held guard if it is still pending.
  void
  onMobilityEvent()
  {
    m_epoch++;
    const bool guardLive = m_heldGuard && time::steady_clock::now() <= m_heldGuard->expiry;
    std::cout << "[" << nowNs() << "] MOBILITY: epoch=" << m_epoch
              << " guardLive=" << (guardLive ? 1 : 0) << std::endl;
    // Arm the local NFD so the producer's pending business Data (the stranded set
    // at this instant) is LP-marked and flooded too (rescue in-flight interests).
    armNfd();
    // Reply to the held guard so a floodable trigger exists even when there is no
    // pending business traffic. A lapsed guard is dropped without replying.
    if (guardLive) {
      floodGuard();
    }
    m_heldGuard.reset(); // consumed or lapsed; consumer re-expression re-arms it
  }

  // Arm the local NFD's OptoFlood business-marking for this producer's advertised
  // prefix via the local command Interest /localhost/nfd/optoflood/arm/<prefix>.
  // Fire-and-forget: NFD consumes it; no reply is expected.
  void
  armNfd()
  {
    Name armName("/localhost/nfd/optoflood/arm");
    armName.append(m_advertisedPrefix);
    Interest interest(armName);
    interest.setCanBePrefix(false);
    interest.setMustBeFresh(true);
    interest.setInterestLifetime(1_s);
    m_face.expressInterest(interest,
                           [] (const Interest&, const Data&) {},
                           [] (const Interest&, const lp::Nack&) {},
                           [] (const Interest&) {});
    std::cout << "[" << nowNs() << "] MOBILITY: armed NFD " << armName << std::endl;
  }

  // Produce and put one guard Data named <advertisedPrefix>/_guard with the
  // OptoFlood mobility markers (FloodId + NewFaceSeq epoch) in the signed
  // MetaInfo and an empty payload. The local NFD OptoFlood module detects the
  // FloodId and floods it, installing TFIB toward this producer.
  void
  floodGuard()
  {
    auto data = make_shared<Data>(m_guardName);
    data->setFreshnessPeriod(0_ms); // ephemeral: never satisfies MustBeFresh from CS

    MetaInfo metaInfo = data->getMetaInfo();
    uint64_t floodId = ++m_floodIdSeq;
    metaInfo.addAppMetaInfo(optoflood::makeFloodIdBlock(floodId));
    metaInfo.addAppMetaInfo(optoflood::makeNewFaceSeqBlock(m_epoch));
    data->setMetaInfo(metaInfo);

    m_keyChain.sign(*data);
    m_face.put(*data);

    std::cout << "[" << nowNs() << "] GUARD-PRODUCER: flooded guard"
              << " NewFaceSeq=" << m_epoch << " FloodId=" << floodId
              << " size=" << data->wireEncode().size() << " bytes" << std::endl;
  }

  boost::asio::io_context m_io;
  Face m_face;
  Scheduler m_scheduler;
  KeyChain m_keyChain;
  Name m_advertisedPrefix;
  Name m_guardName;
  // The single aggregated guard Interest currently pending at this producer, with
  // the instant its lifetime lapses. Same lifecycle model as the baseline producer's
  // parked business Interests.
  struct HeldGuard
  {
    Name name;
    time::steady_clock::time_point expiry;
  };

  std::unique_ptr<NetlinkListener> m_netlink;
  std::optional<HeldGuard> m_heldGuard;
  uint32_t m_epoch = 0;
  uint64_t m_floodIdSeq = 0;
};

} // namespace optoflood_daemon
} // namespace ndn

namespace {

std::string
resolveRole(int argc, char** argv)
{
  if (argc > 1) {
    return argv[1];
  }
  const char* env = std::getenv("OPTOFLOOD_ROLE");
  return env ? std::string(env) : std::string();
}

} // anonymous namespace

int
main(int argc, char** argv)
{
  using namespace ndn;

  const std::string role = resolveRole(argc, argv);

  const char* rawPrefix = std::getenv("GUARD_PREFIX");
  Name advertisedPrefix(rawPrefix && rawPrefix[0] != '\0' ? rawPrefix : "/LiveStream");

  const char* rawInterval = std::getenv("EXP_GUARD_INTERVAL_MS");
  int intervalMs = rawInterval ? std::atoi(rawInterval) : 1000;
  if (intervalMs <= 0) {
    intervalMs = 1000;
  }

  std::cout << "[" << optoflood_daemon::nowNs() << "] STARTUP: OptoFlood daemon role='" << role
            << "' prefix=" << advertisedPrefix << " pid=" << getpid() << std::endl;

  try {
    if (role == "consumer") {
      optoflood_daemon::GuardConsumer consumer(advertisedPrefix, time::milliseconds(intervalMs));
      consumer.run();
    }
    else if (role == "producer") {
      optoflood_daemon::GuardProducer producer(advertisedPrefix);
      producer.run();
    }
    else {
      std::cerr << "Usage: optoflood-daemon <consumer|producer>  (or set OPTOFLOOD_ROLE)"
                << std::endl;
      return 2;
    }
  }
  catch (const std::exception& e) {
    std::cerr << "[" << optoflood_daemon::nowNs() << "] FATAL: " << e.what() << std::endl;
    return 1;
  }

  return 0;
}
