#pragma once

#include <cstdint>
#include <optional>
#include <string>

// Guard FloodId allocation.
//
// Unset producer index keeps the historical per-process counter: the first
// guard flood is 1, then 2, and so on.
//
// A configured index in 1..4 builds (index << 32) | sequence. sequence is the
// 1-based count for this process. The low 32 bits hold that count, so two
// configured producers cannot emit the same id during one uninterrupted run.
// The same signed Data still carries one id, and NFD deduplicates that id.
inline bool
guardFloodId(std::optional<uint32_t> producerIndex, uint64_t sequence,
             uint64_t& floodId, std::string& error)
{
  if (!producerIndex) {
    if (sequence == 0) {
      error = "legacy Guard FloodId sequence is exhausted";
      return false;
    }
    floodId = sequence;
    return true;
  }
  const uint32_t index = *producerIndex;
  if (index < 1 || index > 4) {
    error = "OPTOFLOOD_PRODUCER_INDEX must be an integer from 1 to 4";
    return false;
  }
  if (sequence < 1 || sequence > UINT32_MAX) {
    error = "Guard FloodId sequence must fit in 32 bits";
    return false;
  }
  floodId = (static_cast<uint64_t>(index) << 32) | sequence;
  return true;
}
