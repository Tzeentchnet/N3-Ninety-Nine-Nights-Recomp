#pragma once

#include <cstdint>

namespace n3::test {
inline constexpr bool kPhysicalOffsetInCode =
#if defined(REX_PHYSICAL_OFFSET_IN_CODE) && REX_PHYSICAL_OFFSET_IN_CODE
    true;
#else
    false;
#endif

inline constexpr uint64_t TestGuestHostOffset(uint32_t address) {
  return uint64_t(address) +
      (kPhysicalOffsetInCode && address >= 0xe0000000u ? 0x1000u : 0u);
}
}  // namespace n3::test
