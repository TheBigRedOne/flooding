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

#include "tfib.hpp"
#include "common/logger.hpp"

namespace nfd {
namespace tfib {

NFD_LOG_INIT(Tfib);

Entry::Entry(const Name& prefix, Face& face, uint32_t newFaceSeq, uint64_t floodId)
  : m_prefix(prefix)
  , m_face(face)
  , m_newFaceSeq(newFaceSeq)
  , m_floodId(floodId)
  , m_expiry(time::steady_clock::now() + DEFAULT_LIFETIME)
{
}

Tfib::Tfib(Scheduler& scheduler)
  : m_scheduler(scheduler)
{
  scheduleCleanup();
}

Entry*
Tfib::findLongestPrefixMatch(const Name& name)
{
  // First, try to find an exact match
  auto exact = findExactMatch(name);
  if (exact != nullptr) {
    return exact;
  }

  // Then, search for the longest prefix match
  // Start from the full name and remove components one by one
  Name prefix = name;
  while (prefix.size() > 0) {
    prefix = prefix.getPrefix(-1);  // Remove last component
    auto it = m_entries.find(prefix);
    if (it != m_entries.end() && !it->second->isExpired()) {
      return it->second.get();
    }
  }

  return nullptr;
}

Entry*
Tfib::findExactMatch(const Name& prefix)
{
  auto it = m_entries.find(prefix);
  if (it != m_entries.end() && !it->second->isExpired()) {
    return it->second.get();
  }
  return nullptr;
}

void
Tfib::insert(const Name& prefix, Face& face, uint32_t newFaceSeq, uint64_t floodId)
{
  NFD_LOG_DEBUG("Insert " << prefix << " face=" << face.getId() 
                << " seq=" << newFaceSeq << " floodId=" << floodId);

  auto it = m_entries.find(prefix);
  
  if (it != m_entries.end()) {
    // Entry exists, check if we should update it
    auto& entry = it->second;
    
    // Update only if the new sequence number is higher or flood ID is different
    if (newFaceSeq > entry->getNewFaceSeq() || floodId != entry->getFloodId()) {
      NFD_LOG_DEBUG("Updating existing entry for " << prefix);
      m_entries[prefix] = std::make_unique<Entry>(prefix, face, newFaceSeq, floodId);
      afterInsert(prefix, face, newFaceSeq);
    }
    else {
      // Just refresh the expiry time
      entry->refresh();
      NFD_LOG_DEBUG("Refreshed entry for " << prefix);
    }
  }
  else {
    // Create new entry
    NFD_LOG_DEBUG("Creating new entry for " << prefix);
    m_entries[prefix] = std::make_unique<Entry>(prefix, face, newFaceSeq, floodId);
    afterInsert(prefix, face, newFaceSeq);
  }
}

void
Tfib::erase(const Name& prefix)
{
  auto it = m_entries.find(prefix);
  if (it != m_entries.end()) {
    NFD_LOG_DEBUG("Erase " << prefix);
    beforeRemove(prefix);
    m_entries.erase(it);
  }
}

void
Tfib::scheduleCleanup()
{
  m_cleanupEvent = m_scheduler.schedule(CLEANUP_INTERVAL, [this] {
    cleanup();
    scheduleCleanup();  // Reschedule
  });
}

void
Tfib::cleanup()
{
  NFD_LOG_TRACE("Starting TFIB cleanup");
  
  // Collect expired entries
  std::vector<Name> toRemove;
  for (const auto& [prefix, entry] : m_entries) {
    if (entry->isExpired()) {
      toRemove.push_back(prefix);
    }
  }
  
  // Remove expired entries
  for (const auto& prefix : toRemove) {
    NFD_LOG_DEBUG("Removing expired entry: " << prefix);
    erase(prefix);
  }
  
  if (!toRemove.empty()) {
    NFD_LOG_DEBUG("Cleaned up " << toRemove.size() << " expired entries");
  }
}

} // namespace tfib
} // namespace nfd
