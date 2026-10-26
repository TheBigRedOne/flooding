#include "guard_flood_id.hpp"

#include <iostream>
#include <optional>

namespace {

int
fail(const std::string& message)
{
  std::cerr << message << std::endl;
  return 1;
}

} // namespace

int
main()
{
  uint64_t floodId = 0;
  std::string error;
  if (!guardFloodId(std::nullopt, 1, floodId, error) || floodId != 1) {
    return fail("legacy first FloodId");
  }
  if (!guardFloodId(std::nullopt, 2, floodId, error) || floodId != 2) {
    return fail("legacy sequence");
  }
  if (guardFloodId(std::nullopt, 0, floodId, error)) {
    return fail("legacy sequence 0 must fail");
  }
  if (!guardFloodId(1, 1, floodId, error) || floodId != 4294967297ULL) {
    return fail("producer 1 sequence 1");
  }
  if (!guardFloodId(1, 2, floodId, error) || floodId != 4294967298ULL) {
    return fail("producer 1 sequence 2");
  }
  if (!guardFloodId(2, 1, floodId, error) || floodId != 8589934593ULL) {
    return fail("producer 2 sequence 1");
  }
  const uint64_t repeated = floodId;
  if (!guardFloodId(2, 1, floodId, error) || floodId != repeated) {
    return fail("repeated forwarding identity");
  }
  if (guardFloodId(0, 1, floodId, error) || guardFloodId(5, 1, floodId, error)) {
    return fail("index range");
  }
  if (guardFloodId(1, (uint64_t(UINT32_MAX) + 1), floodId, error)) {
    return fail("sequence must not use the index bits");
  }
  return 0;
}
