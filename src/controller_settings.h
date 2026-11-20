#pragma once

#include <rex/setting.h>
#include <rex/settings_registry.h>

#include <string>

namespace n3::input {

inline rex::Allowed DigitalSources() {
  return rex::Allowed("none", "a", "b", "x", "y", "left_shoulder",
                      "right_shoulder", "left_thumb", "right_thumb", "dpad_up",
                      "dpad_down", "dpad_left", "dpad_right", "back", "start",
                      "guide");
}

inline rex::Allowed TriggerSources() {
  return rex::Allowed("none", "left_trigger", "right_trigger");
}

inline rex::Allowed StickSources() {
  return rex::Allowed("none", "left_stick", "right_stick");
}

class ControllerSettings final : public rex::SettingOwner {
 public:
  ControllerSettings() : SettingOwner("n3.controller") {}

  REX_SETTING(std::string, button_a, "a", "Physical input mapped to A",
              DigitalSources());
  REX_SETTING(std::string, button_b, "b", "Physical input mapped to B",
              DigitalSources());
  REX_SETTING(std::string, button_x, "x", "Physical input mapped to X",
              DigitalSources());
  REX_SETTING(std::string, button_y, "y", "Physical input mapped to Y",
              DigitalSources());
  REX_SETTING(std::string, left_shoulder, "left_shoulder",
              "Physical input mapped to the left shoulder", DigitalSources());
  REX_SETTING(std::string, right_shoulder, "right_shoulder",
              "Physical input mapped to the right shoulder", DigitalSources());
  REX_SETTING(std::string, left_thumb, "left_thumb",
              "Physical input mapped to the left stick press", DigitalSources());
  REX_SETTING(std::string, right_thumb, "right_thumb",
              "Physical input mapped to the right stick press",
              DigitalSources());
  REX_SETTING(std::string, dpad_up, "dpad_up",
              "Physical input mapped to D-pad up", DigitalSources());
  REX_SETTING(std::string, dpad_down, "dpad_down",
              "Physical input mapped to D-pad down", DigitalSources());
  REX_SETTING(std::string, dpad_left, "dpad_left",
              "Physical input mapped to D-pad left", DigitalSources());
  REX_SETTING(std::string, dpad_right, "dpad_right",
              "Physical input mapped to D-pad right", DigitalSources());
  REX_SETTING(std::string, back, "back", "Physical input mapped to Back",
              DigitalSources());
  REX_SETTING(std::string, start, "start", "Physical input mapped to Start",
              DigitalSources());
  REX_SETTING(std::string, guide, "guide", "Physical input mapped to Guide",
              DigitalSources());
  REX_SETTING(std::string, left_trigger, "left_trigger",
              "Physical trigger mapped to the left trigger", TriggerSources());
  REX_SETTING(std::string, right_trigger, "right_trigger",
              "Physical trigger mapped to the right trigger", TriggerSources());
  REX_SETTING(std::string, left_stick, "left_stick",
              "Physical stick mapped to the left stick", StickSources());
  REX_SETTING(std::string, right_stick, "right_stick",
              "Physical stick mapped to the right stick", StickSources());
  REX_SETTING(bool, invert_left_x, false, "Invert the mapped left stick X axis");
  REX_SETTING(bool, invert_left_y, false, "Invert the mapped left stick Y axis");
  REX_SETTING(bool, invert_right_x, false,
              "Invert the mapped right stick X axis");
  REX_SETTING(bool, invert_right_y, false,
              "Invert the mapped right stick Y axis");
};

inline ControllerSettings& GetControllerSettings() {
  static ControllerSettings settings;
  return settings;
}

}  // namespace n3::input

#define N3_CONTROLLER_SETTINGS() ::n3::input::GetControllerSettings()
