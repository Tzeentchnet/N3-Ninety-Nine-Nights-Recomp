#include "controller_remap.h"

#include <cstdlib>
#include <iostream>
#include <limits>
#include <string_view>

namespace {

using n3::input::ControllerRemap;
using n3::input::ControllerState;
using n3::input::DigitalSource;
using n3::input::StickSource;
using n3::input::TriggerSource;

void Require(bool condition, std::string_view message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

void TestIdentity() {
  const ControllerState input{
      .buttons = 0xF7FF,
      .left_trigger = 23,
      .right_trigger = 241,
      .left_x = -32768,
      .left_y = 32767,
      .right_x = -1234,
      .right_y = 5678,
  };
  Require(n3::input::ApplyControllerRemap(input, {}) == input,
          "Default controller mapping is not an identity mapping");
}

void TestDigitalMapping() {
  ControllerRemap remap;
  remap.a = DigitalSource::kB;
  remap.b = DigitalSource::kA;
  remap.left_shoulder = DigitalSource::kDPadRight;
  remap.dpad_right = DigitalSource::kNone;
  remap.guide = DigitalSource::kA;
  const ControllerState input{
      .buttons = static_cast<uint16_t>(
          static_cast<uint16_t>(DigitalSource::kA) |
          static_cast<uint16_t>(DigitalSource::kDPadRight) | 0x0800),
  };
  const auto output = n3::input::ApplyControllerRemap(input, remap);
  const uint16_t expected =
      static_cast<uint16_t>(DigitalSource::kB) |
      static_cast<uint16_t>(DigitalSource::kLeftShoulder) |
      static_cast<uint16_t>(DigitalSource::kGuide) | 0x0800;
  Require(output.buttons == expected,
          "Digital button swapping, disabling, or unknown-bit preservation failed");
}

void TestAnalogMapping() {
  ControllerRemap remap;
  remap.left_trigger = TriggerSource::kRight;
  remap.right_trigger = TriggerSource::kNone;
  remap.left_stick = StickSource::kRight;
  remap.right_stick = StickSource::kLeft;
  remap.invert_left_x = true;
  remap.invert_left_y = true;
  remap.invert_right_x = true;
  const ControllerState input{
      .left_trigger = 17,
      .right_trigger = 221,
      .left_x = -32768,
      .left_y = -20,
      .right_x = 300,
      .right_y = 32767,
  };
  const auto output = n3::input::ApplyControllerRemap(input, remap);
  Require(output.left_trigger == 221 && output.right_trigger == 0,
          "Trigger remapping failed");
  Require(output.left_x == -300 &&
              output.left_y == std::numeric_limits<int16_t>::min() + 1 &&
              output.right_x == std::numeric_limits<int16_t>::max() &&
              output.right_y == -20,
          "Stick swapping or saturating inversion failed");
}

void TestNames() {
  Require(n3::input::ParseDigitalSource("right_shoulder") ==
              DigitalSource::kRightShoulder &&
              !n3::input::ParseDigitalSource("Right Shoulder"),
          "Digital source parsing failed");
  Require(n3::input::ParseTriggerSource("left_trigger") ==
              TriggerSource::kLeft &&
              !n3::input::ParseTriggerSource("left"),
          "Trigger source parsing failed");
  Require(n3::input::ParseStickSource("none") == StickSource::kNone &&
              !n3::input::ParseStickSource("center"),
          "Stick source parsing failed");
}

}  // namespace

int main() {
  TestIdentity();
  TestDigitalMapping();
  TestAnalogMapping();
  TestNames();
  return 0;
}
