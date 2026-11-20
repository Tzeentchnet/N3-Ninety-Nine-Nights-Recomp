#pragma once

#include <array>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>

namespace n3::launcher {

enum class WindowMode {
  kWindowed,
  kBorderless,
  kExclusive,
};

struct BindingDefinition {
  std::string_view key;
  std::string_view label;
  std::string_view default_value;
};

inline constexpr std::array<BindingDefinition, 25> kBindingDefinitions = {{
    {"keybind_a", "A button", "Semicolon,Space"},
    {"keybind_b", "B button", "Quote,Backspace"},
    {"keybind_x", "X button", "L"},
    {"keybind_y", "Y button", "P"},
    {"keybind_left_shoulder", "Left shoulder", "1"},
    {"keybind_right_shoulder", "Right shoulder", "3"},
    {"keybind_left_trigger", "Left trigger", "Q,I"},
    {"keybind_right_trigger", "Right trigger", "E,O"},
    {"keybind_lstick_press", "Left stick press", "F"},
    {"keybind_rstick_press", "Right stick press", "K"},
    {"keybind_back", "Back", "Z,Tab"},
    {"keybind_start", "Start", "X,Return"},
    {"keybind_dpad_up", "D-pad up", "Shift+Up"},
    {"keybind_dpad_down", "D-pad down", "Shift+Down"},
    {"keybind_dpad_left", "D-pad left", "Shift+Left"},
    {"keybind_dpad_right", "D-pad right", "Shift+Right"},
    {"keybind_lstick_up", "Left stick up", "W"},
    {"keybind_lstick_down", "Left stick down", "S"},
    {"keybind_lstick_left", "Left stick left", "A"},
    {"keybind_lstick_right", "Left stick right", "D"},
    {"keybind_rstick_up", "Right stick up", "Up"},
    {"keybind_rstick_down", "Right stick down", "Down"},
    {"keybind_rstick_left", "Right stick left", "Left"},
    {"keybind_rstick_right", "Right stick right", "Right"},
    {"keybind_guide", "Guide", ""},
}};

struct ControllerButtonDefinition {
  std::string_view key;
  std::string_view label;
  std::string_view default_value;
};

inline constexpr std::array<ControllerButtonDefinition, 15>
    kControllerButtonDefinitions = {{
        {"button_a", "A", "a"},
        {"button_b", "B", "b"},
        {"button_x", "X", "x"},
        {"button_y", "Y", "y"},
        {"left_shoulder", "Left shoulder", "left_shoulder"},
        {"right_shoulder", "Right shoulder", "right_shoulder"},
        {"left_thumb", "Left stick press", "left_thumb"},
        {"right_thumb", "Right stick press", "right_thumb"},
        {"dpad_up", "D-pad up", "dpad_up"},
        {"dpad_down", "D-pad down", "dpad_down"},
        {"dpad_left", "D-pad left", "dpad_left"},
        {"dpad_right", "D-pad right", "dpad_right"},
        {"back", "Back", "back"},
        {"start", "Start", "start"},
        {"guide", "Guide", "guide"},
    }};

struct LauncherValues {
  WindowMode window_mode = WindowMode::kWindowed;
  int window_width = 1280;
  int window_height = 720;
  int monitor = 0;
  int frame_rate = 60;
  int display_resolution = 720;
  std::string renderer = "d3d12";
  bool vsync = true;
  int render_scale = 1;
  int anisotropic = 3;
  std::string present_effect = "fsr1";

  std::string text_language = "english";
  std::filesystem::path voice_directory;
  bool audio_mute = false;
  bool audio_mute_unfocused = false;
  double audio_gain = 1.0;

  std::string input_drivers = "sdl3";
  bool vibration = true;
  bool guide_button = false;
  double left_deadzone = 0.0;
  double right_deadzone = 0.0;
  bool keyboard_mouse_mode = false;
  bool mouse_right_stick = false;
  double mouse_sensitivity = 1.0;
  bool keyboard_passthrough = false;

  std::array<std::string, kControllerButtonDefinitions.size()>
      controller_buttons;
  std::string left_trigger = "left_trigger";
  std::string right_trigger = "right_trigger";
  std::string left_stick = "left_stick";
  std::string right_stick = "right_stick";
  bool invert_left_x = false;
  bool invert_left_y = false;
  bool invert_right_x = false;
  bool invert_right_y = false;

  std::array<std::string, kBindingDefinitions.size()> keybindings;
};

LauncherValues DefaultLauncherValues();

class LauncherConfig {
 public:
  static LauncherConfig Load(const std::filesystem::path& path);

  LauncherConfig(LauncherConfig&&) noexcept;
  LauncherConfig& operator=(LauncherConfig&&) noexcept;
  ~LauncherConfig();

  LauncherConfig(const LauncherConfig&) = delete;
  LauncherConfig& operator=(const LauncherConfig&) = delete;

  void Save(const std::filesystem::path& path) const;

  LauncherValues values;

 private:
  struct State;
  explicit LauncherConfig(std::unique_ptr<State> state);
  std::unique_ptr<State> state_;
};

}  // namespace n3::launcher
