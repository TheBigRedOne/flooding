/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2024 University of Glasgow
 *
 * This file is part of NFD (Named Data Networking Forwarding Daemon).
 * 
 * This file demonstrates how to integrate OptoFlood flooding logic into
 * the NFD forwarder. This code should be integrated into forwarder.cpp
 */

#include "forwarder.hpp"
#include <ndn-cxx/optoflood.hpp>
#include "table/tfib.hpp"
#include "common/logger.hpp"

namespace nfd {

// Add these constants to Forwarder class
static constexpr uint8_t OPTOFLOOD_DEFAULT_HOP_LIMIT = 3;
static constexpr size_t OPTOFLOOD_RATE_LIMIT_PER_SECOND = 100;
static constexpr time::milliseconds OPTOFLOOD_RATE_WINDOW = 1000_ms;

// Add these member variables to Forwarder class
// Tfib m_tfib{m_scheduler};
// std::map<uint64_t, time::steady_clock::TimePoint> m_floodIdCache;  // For deduplication
// size_t m_floodPacketCount = 0;
// time::steady_clock::TimePoint m_floodRateWindowStart;

void
Forwarder::handleOptoFloodData(const Data& data, const FaceEndpoint& ingress)
{
  NFD_LOG_DEBUG("handleOptoFloodData in=" << ingress << " data=" << data.getName());
  
  // Extract OptoFlood fields from MetaInfo
  auto floodId = ndn::optoflood::getFloodId(data.getMetaInfo());
  auto newFaceSeq = ndn::optoflood::getNewFaceSeq(data.getMetaInfo());
  auto traceHint = ndn::optoflood::getTraceHint(data.getMetaInfo());
  
  if (!floodId || !newFaceSeq) {
    NFD_LOG_WARN("OptoFlood Data missing required fields");
    return;
  }
  
  // Check for duplicate flood ID
  auto now = time::steady_clock::now();
  auto floodIt = m_floodIdCache.find(*floodId);
  if (floodIt != m_floodIdCache.end()) {
    // Already processed this flood ID recently
    NFD_LOG_DEBUG("Duplicate flood ID " << *floodId << ", dropping");
    return;
  }
  
  // Add to flood ID cache with expiry
  m_floodIdCache[*floodId] = now;
  
  // Clean old flood IDs (older than 5 seconds)
  for (auto it = m_floodIdCache.begin(); it != m_floodIdCache.end(); ) {
    if (now - it->second > 5_s) {
      it = m_floodIdCache.erase(it);
    } else {
      ++it;
    }
  }
  
  // Update TFIB with the new path
  m_tfib.insert(data.getName().getPrefix(-1), const_cast<Face&>(ingress.face), 
                *newFaceSeq, *floodId);
  
  NFD_LOG_INFO("TFIB updated: " << data.getName().getPrefix(-1) 
               << " -> face " << ingress.face.getId()
               << " seq=" << *newFaceSeq);
  
  // Check rate limit
  if (now - m_floodRateWindowStart > OPTOFLOOD_RATE_WINDOW) {
    m_floodPacketCount = 0;
    m_floodRateWindowStart = now;
  }
  
  if (m_floodPacketCount >= OPTOFLOOD_RATE_LIMIT_PER_SECOND) {
    NFD_LOG_WARN("OptoFlood rate limit exceeded, dropping");
    return;
  }
  m_floodPacketCount++;
  
  // Prepare for controlled flooding
  uint8_t hopLimit = OPTOFLOOD_DEFAULT_HOP_LIMIT;
  
  // Check if Data has HopLimit tag from link layer
  auto hopLimitTag = data.getTag<lp::HopLimitTag>();
  if (hopLimitTag) {
    hopLimit = *hopLimitTag;
    if (hopLimit == 0) {
      NFD_LOG_DEBUG("OptoFlood Data reached hop limit, not flooding");
      return;
    }
    hopLimit--;  // Decrement for next hop
  }
  
  // Flood to all faces except ingress
  size_t floodedCount = 0;
  for (const Face& face : m_faceTable) {
    if (face.getId() == ingress.face.getId()) {
      continue;  // Don't send back to ingress
    }
    
    // Skip faces that are down
    if (face.getState() != face::FaceState::UP) {
      continue;
    }
    
    // For guided flooding with trace hint
    if (traceHint && shouldUseGuidedFlooding(face, *traceHint)) {
      // Prioritize faces matching trace hint
      NFD_LOG_DEBUG("Guided flooding to face " << face.getId());
    }
    
    // Create a copy of the Data packet for flooding
    Data floodData(data);
    
    // Set new hop limit
    floodData.setTag(make_shared<lp::HopLimitTag>(hopLimit));
    
    // Send the flooded Data
    if (this->onOutgoingData(floodData, const_cast<Face&>(face))) {
      floodedCount++;
    }
  }
  
  NFD_LOG_INFO("OptoFlood Data flooded to " << floodedCount << " faces"
               << " with hop limit " << static_cast<int>(hopLimit));
}

bool
Forwarder::shouldFloodInterest(const Interest& interest) const
{
  // Check if Interest has OptoFlood parameters
  auto params = interest.getApplicationParameters();
  if (params.hasWire()) {
    // Simple check: if it has application parameters, it might be OptoFlood
    // In real implementation, parse the parameters properly
    return true;
  }
  
  // Or check based on consecutive failures (would need to track this)
  // This is a simplified version
  return false;
}

void
Forwarder::handleInterestFlooding(const Interest& interest,
                                 const FaceEndpoint& ingress,
                                 const shared_ptr<pit::Entry>& pitEntry)
{
  NFD_LOG_DEBUG("handleInterestFlooding interest=" << interest.getName()
                << " in=" << ingress);
  
  // Parse OptoFlood parameters if present
  uint8_t hopLimit = OPTOFLOOD_DEFAULT_HOP_LIMIT;
  std::optional<std::vector<uint8_t>> traceHint;
  
  auto params = interest.getApplicationParameters();
  if (params.hasWire()) {
    // Parse parameters (simplified - real implementation would properly decode)
    // For now, just use defaults
    NFD_LOG_DEBUG("Interest has OptoFlood parameters");
  }
  
  // Check current hop limit
  auto currentHopLimit = interest.getHopLimit();
  if (currentHopLimit && *currentHopLimit == 0) {
    NFD_LOG_DEBUG("Interest reached hop limit, not flooding");
    return;
  }
  
  // Create flooding Interest
  size_t floodedCount = 0;
  for (const Face& face : m_faceTable) {
    if (face.getId() == ingress.face.getId()) {
      continue;  // Don't flood back to ingress
    }
    
    if (face.getState() != face::FaceState::UP) {
      continue;
    }
    
    // Check if we should flood to this face
    if (traceHint && !shouldUseGuidedFlooding(face, *traceHint)) {
      continue;  // Skip faces not matching trace hint
    }
    
    // Clone the Interest for flooding
    Interest floodInterest(interest);
    
    // Set hop limit
    if (currentHopLimit) {
      floodInterest.setHopLimit(*currentHopLimit - 1);
    } else {
      floodInterest.setHopLimit(hopLimit);
    }
    
    // Forward the Interest
    this->onOutgoingInterest(floodInterest, const_cast<Face&>(face), pitEntry);
    floodedCount++;
  }
  
  NFD_LOG_INFO("OptoFlood Interest flooded to " << floodedCount << " faces");
}

bool
Forwarder::shouldUseGuidedFlooding(const Face& face, 
                                  const std::vector<uint8_t>& traceHint) const
{
  // Simplified implementation
  // Real implementation would check if face matches trace hint
  // For example, check if face ID or network prefix matches hint
  
  // For now, just return true to flood to all faces
  return true;
}

// Integration with onContentStoreMiss
void
Forwarder::onContentStoreMissWithOptoFlood(const Interest& interest,
                                          const FaceEndpoint& ingress,
                                          const shared_ptr<pit::Entry>& pitEntry)
{
  NFD_LOG_DEBUG("onContentStoreMiss interest=" << interest.getName()
                << " in=" << ingress);

  // First check TFIB for temporary paths
  auto tfibEntry = m_tfib.findLongestPrefixMatch(interest.getName());
  if (tfibEntry && !tfibEntry->isExpired()) {
    NFD_LOG_INFO("Using TFIB entry for " << interest.getName()
                 << " -> face " << tfibEntry->getFace().getId());
    
    // Record in PIT and forward
    pitEntry->insertOrUpdateInRecord(ingress.face, interest);
    this->onOutgoingInterest(interest, tfibEntry->getFace(), pitEntry);
    return;
  }
  
  // Regular FIB lookup
  const fib::Entry& fibEntry = m_fib.findLongestPrefixMatch(*pitEntry);
  
  // Check if we should trigger flooding
  if (!fibEntry.hasNextHops() && shouldFloodInterest(interest)) {
    NFD_LOG_INFO("No FIB/TFIB entry found, triggering OptoFlood");
    handleInterestFlooding(interest, ingress, pitEntry);
    return;
  }
  
  // Continue with normal forwarding strategy
  NFD_LOG_DEBUG("onContentStoreMiss interest=" << interest.getName());
  ++m_counters.nCsMisses;

  // attach HopLimit tag if not present, decrement otherwise
  interest.setTag(make_shared<lp::HopLimitTag>(
    interest.getHopLimit() ? *interest.getHopLimit() - 1 : m_defaultHopLimit));

  // insert in-record
  pitEntry->insertOrUpdateInRecord(ingress.face, interest);

  // set PIT expiry timer to the time that the last PIT in-record expires
  auto lastExpiring = std::max_element(pitEntry->in_begin(), pitEntry->in_end(),
                                       [] (const auto& a, const auto& b) {
                                         return a.getExpiry() < b.getExpiry();
                                       });
  auto lastExpiryFromNow = lastExpiring->getExpiry() - time::steady_clock::now();
  this->setExpiryTimer(pitEntry, time::duration_cast<time::milliseconds>(lastExpiryFromNow));

  // forward Interest
  pitEntry->isSatisfied = false;
  m_strategyChoice.findEffectiveStrategy(*pitEntry).afterReceiveInterest(interest, ingress, pitEntry);
}

} // namespace nfd
