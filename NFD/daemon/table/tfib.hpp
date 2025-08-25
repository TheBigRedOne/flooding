/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2024 University of Glasgow
 *
 * This file is part of NFD (Named Data Networking Forwarding Daemon).
 * See AUTHORS.md for complete list of NFD authors and contributors.
 *
 * NFD is free software: you can redistribute it and/or modify it under the terms
 * of the GNU General Public License as published by the Free Software Foundation,
 * either version 3 of the License, or (at your option) any later version.
 */

#ifndef NFD_DAEMON_TABLE_TFIB_HPP
#define NFD_DAEMON_TABLE_TFIB_HPP

#include "face/face.hpp"
#include "common/global.hpp"

#include <ndn-cxx/name.hpp>
#include <map>
#include <memory>

namespace nfd {
namespace tfib {

/**
 * @brief Represents an entry in the Temporary FIB (TFIB)
 * 
 * TFIB entries are created by OptoFlood to establish temporary forwarding paths
 * during producer mobility events. They have a short lifetime (typically 1 second)
 * and are used while waiting for global routing convergence.
 */
class Entry
{
public:
  Entry(const Name& prefix, Face& face, uint32_t newFaceSeq, uint64_t floodId);

  const Name&
  getPrefix() const
  {
    return m_prefix;
  }

  Face&
  getFace() const
  {
    return m_face;
  }

  uint32_t
  getNewFaceSeq() const
  {
    return m_newFaceSeq;
  }

  uint64_t
  getFloodId() const
  {
    return m_floodId;
  }

  time::steady_clock::TimePoint
  getExpiry() const
  {
    return m_expiry;
  }

  bool
  isExpired() const
  {
    return time::steady_clock::now() >= m_expiry;
  }

  void
  refresh()
  {
    m_expiry = time::steady_clock::now() + DEFAULT_LIFETIME;
  }

private:
  static constexpr time::milliseconds DEFAULT_LIFETIME = 1000_ms;

private:
  Name m_prefix;
  Face& m_face;
  uint32_t m_newFaceSeq;
  uint64_t m_floodId;
  time::steady_clock::TimePoint m_expiry;
};

/**
 * @brief Temporary Forwarding Information Base
 * 
 * The TFIB maintains temporary forwarding entries created by OptoFlood
 * to handle producer mobility. Entries are automatically expired after
 * a short period (default 1 second).
 */
class Tfib : noncopyable
{
public:
  explicit
  Tfib(Scheduler& scheduler);

  /**
   * @brief Find longest prefix match
   * @param name The name to match
   * @return Pointer to the matching entry, or nullptr if not found
   */
  Entry*
  findLongestPrefixMatch(const Name& name);

  /**
   * @brief Find exact match
   * @param prefix The exact prefix to match
   * @return Pointer to the matching entry, or nullptr if not found
   */
  Entry*
  findExactMatch(const Name& prefix);

  /**
   * @brief Insert or update an entry
   * @param prefix The prefix for the entry
   * @param face The outgoing face
   * @param newFaceSeq Sequence number from OptoFlood
   * @param floodId Flood identifier for deduplication
   * 
   * If an entry with the same prefix exists and has a lower sequence number,
   * it will be updated. Otherwise, a new entry is created.
   */
  void
  insert(const Name& prefix, Face& face, uint32_t newFaceSeq, uint64_t floodId);

  /**
   * @brief Remove an entry
   * @param prefix The prefix to remove
   */
  void
  erase(const Name& prefix);

  /**
   * @brief Get number of entries
   */
  size_t
  size() const
  {
    return m_entries.size();
  }

  /**
   * @brief Clear all entries
   */
  void
  clear()
  {
    m_entries.clear();
  }

  /**
   * @brief Signal emitted when a new entry is inserted
   * 
   * This can be used to trigger Fast-LSA generation for NLSR integration
   */
  signal::Signal<Tfib, Name, Face&, uint32_t> afterInsert;

  /**
   * @brief Signal emitted before an entry is removed
   */
  signal::Signal<Tfib, Name> beforeRemove;

private:
  /**
   * @brief Schedule cleanup of expired entries
   */
  void
  scheduleCleanup();

  /**
   * @brief Remove expired entries
   */
  void
  cleanup();

private:
  // Use map for efficient longest prefix match
  std::map<Name, std::unique_ptr<Entry>> m_entries;
  Scheduler& m_scheduler;
  scheduler::ScopedEventId m_cleanupEvent;

  static constexpr time::milliseconds CLEANUP_INTERVAL = 100_ms;
};

} // namespace tfib

using tfib::Tfib;

} // namespace nfd

#endif // NFD_DAEMON_TABLE_TFIB_HPP
