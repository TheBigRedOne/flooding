/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2013-2024 Regents of the University of California.
 *
 * This file is part of ndn-cxx library (NDN C++ library with eXperimental eXtensions).
 *
 * ndn-cxx library is free software: you can redistribute it and/or modify it under the
 * terms of the GNU Lesser General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * ndn-cxx library is distributed in the hope that it will be useful, but WITHOUT ANY
 * WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
 * PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.
 *
 * You should have received copies of the GNU General Public License and GNU Lesser
 * General Public License along with ndn-cxx, e.g., in COPYING.md file.  If not, see
 * <http://www.gnu.org/licenses/>.
 *
 * See AUTHORS.md for complete list of ndn-cxx authors and contributors.
 */

#ifndef NDN_CXX_TRANSPORT_DETAIL_STREAM_TRANSPORT_IMPL_HPP
#define NDN_CXX_TRANSPORT_DETAIL_STREAM_TRANSPORT_IMPL_HPP

#include "ndn-cxx/transport/transport.hpp"

#include <boost/asio/steady_timer.hpp>
#include <boost/asio/write.hpp>
#include <boost/lexical_cast.hpp>

#include <array>
#include <list>
#include <queue>

namespace ndn::detail {

/**
 * \brief Implementation detail of a Boost.Asio-based stream-oriented transport.
 * \tparam BaseTransport a subclass of Transport
 * \tparam Protocol a Boost.Asio stream-oriented protocol, e.g., `boost::asio::ip::tcp`
 *                  or `boost::asio::local::stream_protocol`
 */
template<typename BaseTransport, typename Protocol>
class StreamTransportImpl : public std::enable_shared_from_this<StreamTransportImpl<BaseTransport, Protocol>>
{
protected:
  using TransmissionQueue = std::queue<Block, std::list<Block>>;

public:
  StreamTransportImpl(BaseTransport& transport, boost::asio::io_context& ioCtx)
    : m_transport(transport)
    , m_socket(ioCtx)
    , m_connectTimer(ioCtx)
  {
  }

  void
  connect(const typename Protocol::endpoint& endpoint)
  {
    if (m_transport.getState() == Transport::State::CONNECTING) {
      return;
    }

    m_endpoint = endpoint;
    m_transport.setState(Transport::State::CONNECTING);

    // Wait at most 4 seconds to connect
    /// @todo Decide whether this number should be configurable
    m_connectTimer.expires_after(std::chrono::seconds(4));
    m_connectTimer.async_wait([self = this->shared_from_this()] (const auto& ec) {
      if (ec) // e.g., cancelled timer
        return;

      self->m_transport.close();
      NDN_THROW(Transport::Error(boost::system::errc::make_error_code(boost::system::errc::timed_out),
                                 "could not connect to NDN forwarder at " +
                                 boost::lexical_cast<std::string>(self->m_endpoint)));
    });

    m_socket.async_connect(m_endpoint, [self = this->shared_from_this()] (const auto& ec) {
      self->connectHandler(ec);
    });
  }

  void
  close()
  {
    m_transport.setState(Transport::State::CLOSED);

    m_connectTimer.cancel();
    boost::system::error_code error; // to silently ignore all errors
    m_socket.cancel(error);
    m_socket.close(error);

    TransmissionQueue{}.swap(m_transmissionQueue); // clear the queue
  }

  void
  pause()
  {
    if (m_transport.getState() == Transport::State::RUNNING) {
      m_socket.cancel();
      m_transport.setState(Transport::State::PAUSED);
    }
  }

  void
  resume()
  {
    if (m_transport.getState() == Transport::State::PAUSED) {
      m_transport.setState(Transport::State::RUNNING);
      m_rxBufferSize = 0;
      asyncReceive();
    }
  }

  void
  send(const Block& block)
  {
    m_transmissionQueue.push(block);

    if (m_transport.getState() != Transport::State::CLOSED &&
        m_transport.getState() != Transport::State::CONNECTING &&
        m_transmissionQueue.size() == 1) {
      asyncWrite();
    }
    // if not connected or there's another transmission in progress (m_transmissionQueue.size() > 1),
    // the next write will be scheduled either in connectHandler or in asyncWriteHandler
  }

protected:
  void
  connectHandler(const boost::system::error_code& error)
  {
    m_connectTimer.cancel();

    if (error) {
      if (error == boost::asio::error::operation_aborted) {
        // async_connect was explicitly cancelled (e.g., socket close)
        return;
      }
      m_transport.close();
      NDN_THROW(Transport::Error(error, "could not connect to NDN forwarder at " +
                                 boost::lexical_cast<std::string>(m_endpoint)));
    }

    m_transport.setState(Transport::State::PAUSED);

    if (!m_transmissionQueue.empty()) {
      resume();
      asyncWrite();
    }
  }

  void
  asyncWrite()
  {
    BOOST_ASSERT(!m_transmissionQueue.empty());
    boost::asio::async_write(m_socket, boost::asio::buffer(m_transmissionQueue.front()),
      // capture a copy of the shared_ptr to "this" to prevent deallocation
      [this, self = this->shared_from_this()] (const auto& error, size_t) {
        if (error) {
          if (error == boost::asio::error::operation_aborted) {
            // async_write was explicitly cancelled (e.g., socket close)
            return;
          }
          m_transport.close();
          NDN_THROW(Transport::Error(error, "socket write error"));
        }

        if (m_transport.getState() == Transport::State::CLOSED) {
          return; // queue has already been cleared
        }

        BOOST_ASSERT(!m_transmissionQueue.empty());
        m_transmissionQueue.pop();

        if (!m_transmissionQueue.empty()) {
          asyncWrite();
        }
      });
  }

  void
  asyncReceive()
  {
    m_socket.async_receive(boost::asio::buffer(m_rxBuffer.data() + m_rxBufferSize,
                                               m_rxBuffer.size() - m_rxBufferSize),
      // capture a copy of the shared_ptr to "this" to prevent deallocation
      [this, self = this->shared_from_this()] (const auto& error, size_t nBytesRecvd) {
        if (error) {
          if (error == boost::asio::error::operation_aborted) {
            // async_receive was explicitly cancelled (e.g., socket close)
            return;
          }
          m_transport.close();
          NDN_THROW(Transport::Error(error, "socket read error"));
        }

        m_rxBufferSize += nBytesRecvd;
        auto unparsedBytes = make_span(m_rxBuffer).first(m_rxBufferSize);
        while (!unparsedBytes.empty()) {
          auto [isOk, element] = Block::fromBuffer(unparsedBytes);
          if (!isOk) {
            break;
          }
          unparsedBytes = unparsedBytes.subspan(element.size());
          m_transport.m_receiveCallback(element);
        }

        if (unparsedBytes.empty()) {
          // nothing left in the receive buffer
          m_rxBufferSize = 0;
        }
        else if (unparsedBytes.data() != m_rxBuffer.data()) {
          // move remaining unparsed bytes to the beginning of the receive buffer
          std::copy(unparsedBytes.begin(), unparsedBytes.end(), m_rxBuffer.begin());
          m_rxBufferSize = unparsedBytes.size();
        }
        else if (unparsedBytes.size() == m_rxBuffer.size()) {
          m_transport.close();
          NDN_THROW(Transport::Error("receive buffer full, but a valid TLV cannot be decoded"));
        }

        asyncReceive();
      });
  }

protected:
  BaseTransport& m_transport;
  typename Protocol::endpoint m_endpoint;
  typename Protocol::socket m_socket;
  boost::asio::steady_timer m_connectTimer;
  TransmissionQueue m_transmissionQueue;
  size_t m_rxBufferSize = 0;
  std::array<uint8_t, MAX_NDN_PACKET_SIZE> m_rxBuffer;
};

} // namespace ndn::detail

#endif // NDN_CXX_TRANSPORT_DETAIL_STREAM_TRANSPORT_IMPL_HPP
