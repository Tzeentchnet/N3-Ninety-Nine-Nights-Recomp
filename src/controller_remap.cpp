#include "controller_remap.h"

#include <limits>

namespace n3::input {
namespace {

constexpr uint16_t kKnownButtons =
    static_cast<uint16_t>(DigitalSource::kDPadUp) |
    static_cast<uint16_t>(DigitalSource::kDPadDown) |
    static_cast<uint16_t>(DigitalSource::kDPadLeft) |
    static_cast<uint16_t>(DigitalSource::kDPadRight) |
    static_cast<uint16_t>(DigitalSource::kStart) |
    static_cast<uint16_t>(DigitalSource::kBack) |
    static_cast<uint16_t>(DigitalSource::kLeftThumb) |
    static_cast<uint16_t>(DigitalSource::kRightThumb) |
    static_cast<uint16_t>(DigitalSource::kLeftShoulder) |
    static_cast<uint16_t>(DigitalSource::kRightShoulder) |
    static_cast<uint16_t>(DigitalSource::kGuide) |
    static_cast<uint16_t>(DigitalSource::kA) |
    static_cast<uint16_t>(DigitalSource::kB) |
    static_cast<uint16_t>(DigitalSource::kX) |
    static_cast<uint16_t>(DigitalSource::kY);

void MapButton(uint16_t input, DigitalSource source, DigitalSource target,
               uint16_t& output) {
  if ((input & static_cast<uint16_t>(source)) != 0) {
    output |= static_cast<uint16_t>(target);
  }
}

uint8_t SelectTrigger(const ControllerState& input, TriggerSource source) {
  switch (source) {
    case TriggerSource::kLeft:
      return input.left_trigger;
    case TriggerSource::kRight:
      return input.right_trigger;
    default:
      return 0;
  }
}

struct Stick {
  int16_t x;
  int16_t y;
};

Stick SelectStick(const ControllerState& input, StickSource source) {
  switch (source) {
    case StickSource::kLeft:
      return {input.left_x, input.left_y};
    case StickSource::kRight:
      return {input.right_x, input.right_y};
    default:
      return {};
  }
}

int16_t InvertAxis(int16_t value) {
  if (value == std::numeric_limits<int16_t>::min()) {
    return std::numeric_limits<int16_t>::max();
  }
  return static_cast<int16_t>(-value);
}

}  // namespace

ControllerState ApplyControllerRemap(const ControllerState& input,
                                     const ControllerRemap& remap) {
  ControllerState output = input;
  output.buttons = input.buttons & ~kKnownButtons;
  MapButton(input.buttons, remap.dpad_up, DigitalSource::kDPadUp, output.buttons);
  MapButton(input.buttons, remap.dpad_down, DigitalSource::kDPadDown,
            output.buttons);
  MapButton(input.buttons, remap.dpad_left, DigitalSource::kDPadLeft,
            output.buttons);
  MapButton(input.buttons, remap.dpad_right, DigitalSource::kDPadRight,
            output.buttons);
  MapButton(input.buttons, remap.start, DigitalSource::kStart, output.buttons);
  MapButton(input.buttons, remap.back, DigitalSource::kBack, output.buttons);
  MapButton(input.buttons, remap.left_thumb, DigitalSource::kLeftThumb,
            output.buttons);
  MapButton(input.buttons, remap.right_thumb, DigitalSource::kRightThumb,
            output.buttons);
  MapButton(input.buttons, remap.left_shoulder, DigitalSource::kLeftShoulder,
            output.buttons);
  MapButton(input.buttons, remap.right_shoulder, DigitalSource::kRightShoulder,
            output.buttons);
  MapButton(input.buttons, remap.guide, DigitalSource::kGuide, output.buttons);
  MapButton(input.buttons, remap.a, DigitalSource::kA, output.buttons);
  MapButton(input.buttons, remap.b, DigitalSource::kB, output.buttons);
  MapButton(input.buttons, remap.x, DigitalSource::kX, output.buttons);
  MapButton(input.buttons, remap.y, DigitalSource::kY, output.buttons);

  output.left_trigger = SelectTrigger(input, remap.left_trigger);
  output.right_trigger = SelectTrigger(input, remap.right_trigger);

  Stick left = SelectStick(input, remap.left_stick);
  Stick right = SelectStick(input, remap.right_stick);
  output.left_x = remap.invert_left_x ? InvertAxis(left.x) : left.x;
  output.left_y = remap.invert_left_y ? InvertAxis(left.y) : left.y;
  output.right_x = remap.invert_right_x ? InvertAxis(right.x) : right.x;
  output.right_y = remap.invert_right_y ? InvertAxis(right.y) : right.y;
  return output;
}

std::optional<DigitalSource> ParseDigitalSource(std::string_view text) {
  if (text == "none") return DigitalSource::kNone;
  if (text == "dpad_up") return DigitalSource::kDPadUp;
  if (text == "dpad_down") return DigitalSource::kDPadDown;
  if (text == "dpad_left") return DigitalSource::kDPadLeft;
  if (text == "dpad_right") return DigitalSource::kDPadRight;
  if (text == "start") return DigitalSource::kStart;
  if (text == "back") return DigitalSource::kBack;
  if (text == "left_thumb") return DigitalSource::kLeftThumb;
  if (text == "right_thumb") return DigitalSource::kRightThumb;
  if (text == "left_shoulder") return DigitalSource::kLeftShoulder;
  if (text == "right_shoulder") return DigitalSource::kRightShoulder;
  if (text == "guide") return DigitalSource::kGuide;
  if (text == "a") return DigitalSource::kA;
  if (text == "b") return DigitalSource::kB;
  if (text == "x") return DigitalSource::kX;
  if (text == "y") return DigitalSource::kY;
  return std::nullopt;
}

std::optional<TriggerSource> ParseTriggerSource(std::string_view text) {
  if (text == "none") return TriggerSource::kNone;
  if (text == "left_trigger") return TriggerSource::kLeft;
  if (text == "right_trigger") return TriggerSource::kRight;
  return std::nullopt;
}

std::optional<StickSource> ParseStickSource(std::string_view text) {
  if (text == "none") return StickSource::kNone;
  if (text == "left_stick") return StickSource::kLeft;
  if (text == "right_stick") return StickSource::kRight;
  return std::nullopt;
}

}  // namespace n3::input
