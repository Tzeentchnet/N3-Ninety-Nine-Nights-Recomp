#pragma once
#include <bit>
#include <cstdint>

namespace n3::frames {
inline constexpr uint32_t kPresentIntervalOffset = 13788;
inline constexpr uint32_t kGameFramesPerSecond = 30;

constexpr bool SupportsClock(uint32_t original_fps) {
  return original_fps == 30 || original_fps == 40 || original_fps == 60;
}
constexpr bool SupportsPresentationRate(uint32_t fps) {
  return fps == 0 || SupportsClock(fps);
}
constexpr uint32_t StepSecondsBits(uint32_t fps) {
  return std::bit_cast<uint32_t>(1.0f / fps);
}
constexpr uint32_t PresentInterval(uint32_t original, uint32_t target) {
  (void)target;
  return original;
}
}  // namespace n3::frames
