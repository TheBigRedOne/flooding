/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2024 University of Glasgow
 *
 * This file is part of ndn-cxx library (NDN C++ library with eXperimental eXtensions).
 *
 * ndn-cxx library is free software: you can redistribute it and/or modify it under the
 * terms of the GNU Lesser General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later version.
 */

#ifndef NDN_CXX_OPTOFLOOD_HPP
#define NDN_CXX_OPTOFLOOD_HPP

#include "ndn-cxx/encoding/block.hpp"
#include "ndn-cxx/encoding/tlv.hpp"
#include "ndn-cxx/meta-info.hpp"

#include <optional>
#include <vector>

namespace ndn {
namespace optoflood {

/**
 * @brief OptoFlood TLV-TYPE numbers
 * 
 * These values are in the application-specific range [128, 252]
 */
namespace tlv {
  enum : uint32_t {
    MobilityFlag = 201,    ///< Indicates mobility-related flooding
    FloodId = 202,         ///< Unique identifier for deduplication
    NewFaceSeq = 203,      ///< Sequence number for consistency
    TraceHint = 204        ///< Lightweight breadcrumb of recent PoAs
  };
} // namespace tlv

/**
 * @brief Create a MobilityFlag block
 */
inline Block
makeMobilityFlagBlock()
{
  return Block(tlv::MobilityFlag);
}

/**
 * @brief Create a FloodId block
 * @param floodId Unique identifier for this flooding event
 */
inline Block
makeFloodIdBlock(uint64_t floodId)
{
  return makeNonNegativeIntegerBlock(tlv::FloodId, floodId);
}

/**
 * @brief Create a NewFaceSeq block
 * @param seq Sequence number for the new face
 */
inline Block
makeNewFaceSeqBlock(uint32_t seq)
{
  return makeNonNegativeIntegerBlock(tlv::NewFaceSeq, seq);
}

/**
 * @brief Create a TraceHint block
 * @param hint Binary data representing the trace hint
 */
inline Block
makeTraceHintBlock(const std::vector<uint8_t>& hint)
{
  return makeBinaryBlock(tlv::TraceHint, hint.data(), hint.size());
}

/**
 * @brief Check if MetaInfo contains MobilityFlag
 */
inline bool
hasMobilityFlag(const MetaInfo& metaInfo)
{
  return metaInfo.findAppMetaInfo(tlv::MobilityFlag) != nullptr;
}

/**
 * @brief Extract FloodId from MetaInfo
 * @return FloodId value if present, nullopt otherwise
 */
inline std::optional<uint64_t>
getFloodId(const MetaInfo& metaInfo)
{
  auto block = metaInfo.findAppMetaInfo(tlv::FloodId);
  if (block) {
    try {
      return readNonNegativeInteger(*block);
    }
    catch (const tlv::Error&) {
      // Invalid encoding
    }
  }
  return std::nullopt;
}

/**
 * @brief Extract NewFaceSeq from MetaInfo
 * @return NewFaceSeq value if present, nullopt otherwise
 */
inline std::optional<uint32_t>
getNewFaceSeq(const MetaInfo& metaInfo)
{
  auto block = metaInfo.findAppMetaInfo(tlv::NewFaceSeq);
  if (block) {
    try {
      return static_cast<uint32_t>(readNonNegativeInteger(*block));
    }
    catch (const tlv::Error&) {
      // Invalid encoding
    }
  }
  return std::nullopt;
}

/**
 * @brief Extract TraceHint from MetaInfo
 * @return TraceHint data if present, nullopt otherwise
 */
inline std::optional<std::vector<uint8_t>>
getTraceHint(const MetaInfo& metaInfo)
{
  auto block = metaInfo.findAppMetaInfo(tlv::TraceHint);
  if (block && block->value_size() > 0) {
    return std::vector<uint8_t>(block->value(), block->value() + block->value_size());
  }
  return std::nullopt;
}

/**
 * @brief Create Interest flooding parameters
 * @param traceHint Optional trace hint for guided flooding
 * @param hopLimit Maximum hops for flooding propagation
 */
inline Block
makeInterestFloodingParameters(std::optional<std::vector<uint8_t>> traceHint, uint8_t hopLimit)
{
  EncodingBuffer encoder;
  
  // Encode hop limit
  encoder.prependByte(hopLimit);
  encoder.prependVarNumber(1);  // Length
  encoder.prependVarNumber(205); // TLV type for HopLimit in parameters
  
  // Encode trace hint if present
  if (traceHint) {
    encoder.prependByteArray(traceHint->data(), traceHint->size());
    encoder.prependVarNumber(traceHint->size());
    encoder.prependVarNumber(tlv::TraceHint);
  }
  
  // Wrap in ApplicationParameters
  encoder.prependVarNumber(encoder.size());
  encoder.prependVarNumber(tlv::ApplicationParameters);
  
  return encoder.block();
}

} // namespace optoflood
} // namespace ndn

#endif // NDN_CXX_OPTOFLOOD_HPP
