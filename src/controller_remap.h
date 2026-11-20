#pragma once

#include <cstdint>
#include <optional>
#include <string_view>

namespace n3::input {

enum class DigitalSource : uint16_t {
  kNone = 0,
  kDPadUp = 0x0001,
  kDPadDown = 0x0002,
  kDPadLeft = 0x0004,
  kDPadRight = 0x0008,
  kStart = 0x0010,
  kBack = 0x0020,
  kLeftThumb = 0x0040,
  kRightThumb = 0x0080,
  kLeftShoulder = 0x0100,
  kRightShoulder = 0x0200,
  kGuide = 0x0400,
  kA = 0x1000,
  kB = 0x2000,
  kX = 0x4000,
  kY = 0x8000,
};

enum class TriggerSource {
  kNone,
  kLeft,
  kRight,
};

enum class StickSource {
  kNone,
  kLeft,
  kRight,
};

struct ControllerState {
  uint16_t buttons = 0;
  uint8_t left_trigger = 0;
  uint8_t right_trigger = 0;
  int16_t left_x = 0;
  int16_t left_y = 0;
  int16_t right_x = 0;
  int16_t right_y = 0;

  constexpr bool operator==(const ControllerState&) const = default;
};

struct ControllerRemap {
  DigitalSource dpad_up = DigitalSource::kDPadUp;
  DigitalSource dpad_down = DigitalSource::kDPadDown;
  DigitalSource dpad_left = DigitalSource::kDPadLeft;
  DigitalSource dpad_right = DigitalSource::kDPadRight;
  DigitalSource start = DigitalSource::kStart;
  DigitalSource back = DigitalSource::kBack;
  DigitalSource left_thumb = DigitalSource::kLeftThumb;
  DigitalSource right_thumb = DigitalSource::kRightThumb;
  DigitalSource left_shoulder = DigitalSource::kLeftShoulder;
  DigitalSource right_shoulder = DigitalSource::kRightShoulder;
  DigitalSource guide = DigitalSource::kGuide;
  DigitalSource a = DigitalSource::kA;
  DigitalSource b = DigitalSource::kB;
  DigitalSource x = DigitalSource::kX;
  DigitalSource y = DigitalSource::kY;
  TriggerSource left_trigger = TriggerSource::kLeft;
  TriggerSource right_trigger = TriggerSource::kRight;
  StickSource left_stick = StickSource::kLeft;
  StickSource right_stick = StickSource::kRight;
  bool invert_left_x = false;
  bool invert_left_y = false;
  bool invert_right_x = false;
  bool invert_right_y = false;
};

ControllerState ApplyControllerRemap(const ControllerState& input,
                                     const ControllerRemap& remap);
std::optional<DigitalSource> ParseDigitalSource(std::string_view text);
std::optional<TriggerSource> ParseTriggerSource(std::string_view text);
std::optional<StickSource> ParseStickSource(std::string_view text);

}  // namespace n3::input
