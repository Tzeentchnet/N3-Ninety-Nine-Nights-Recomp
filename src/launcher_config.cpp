#include "launcher_config.h"

#include "controller_remap.h"

#include <rex/input_keys.h>
#include <toml++/toml.hpp>

#include <cmath>
#include <fstream>
#include <format>
#include <optional>
#include <stdexcept>
#include <system_error>
#include <utility>

#ifdef _WIN32
#include <Windows.h>
#endif

namespace n3::launcher {
namespace {

std::runtime_error Invalid(std::string_view name, std::string_view reason) {
  return std::runtime_error(std::format("Invalid setting '{}': {}", name, reason));
}

template <typename T>
std::optional<T> ReadOptional(const toml::table& document,
                              std::string_view name) {
  const auto node = document.at_path(name);
  if (!node) return std::nullopt;
  auto value = node.value<T>();
  if (!value) throw Invalid(name, "unexpected value type");
  return value;
}

bool ReadBool(const toml::table& document, std::string_view name,
              bool default_value) {
  return ReadOptional<bool>(document, name).value_or(default_value);
}

std::string ReadString(const toml::table& document, std::string_view name,
                       std::string default_value) {
  return ReadOptional<std::string>(document, name).value_or(
      std::move(default_value));
}

int ReadInt(const toml::table& document, std::string_view name,
            int default_value, int minimum, int maximum) {
  const int64_t value =
      ReadOptional<int64_t>(document, name).value_or(default_value);
  if (value < minimum || value > maximum) {
    throw Invalid(name, std::format("must be between {} and {}", minimum, maximum));
  }
  return static_cast<int>(value);
}

double ReadDouble(const toml::table& document, std::string_view name,
                  double default_value, double minimum, double maximum) {
  const double value =
      ReadOptional<double>(document, name).value_or(default_value);
  if (!std::isfinite(value) || value < minimum || value > maximum) {
    throw Invalid(name, std::format("must be between {} and {}", minimum, maximum));
  }
  return value;
}

template <typename... Values>
std::string ReadAllowed(const toml::table& document, std::string_view name,
                        std::string default_value, Values... allowed) {
  const std::string value =
      ReadString(document, name, std::move(default_value));
  if (((value == allowed) || ...)) return value;
  throw Invalid(name, "unsupported value");
}

void RequireAllowedInt(std::string_view name, int value,
                       std::initializer_list<int> allowed) {
  for (const int candidate : allowed) {
    if (value == candidate) return;
  }
  throw Invalid(name, "unsupported value");
}

std::filesystem::path Utf8Path(std::string_view value) {
  const auto* begin = reinterpret_cast<const char8_t*>(value.data());
  return std::filesystem::path(std::u8string(begin, begin + value.size()));
}

std::string Utf8Text(const std::filesystem::path& value) {
  const auto text = value.generic_u8string();
  return std::string(reinterpret_cast<const char*>(text.data()), text.size());
}

toml::table& EnsureTable(toml::table& root, std::string_view dotted_scope) {
  toml::table* table = &root;
  size_t start = 0;
  while (start < dotted_scope.size()) {
    const size_t dot = dotted_scope.find('.', start);
    const std::string part(
        dotted_scope.substr(start, dot == std::string_view::npos
                                       ? dotted_scope.size() - start
                                       : dot - start));
    auto* child = table->get_as<toml::table>(part);
    if (!child) {
      if (table->contains(part)) {
        throw Invalid(dotted_scope, "a parent key is not a table");
      }
      table->insert(part, toml::table{});
      child = table->get_as<toml::table>(part);
    }
    table = child;
    if (dot == std::string_view::npos) break;
    start = dot + 1;
  }
  return *table;
}

template <typename T>
void Set(toml::table& root, std::string_view name, T&& value) {
  const size_t dot = name.rfind('.');
  if (dot == std::string_view::npos) {
    root.insert_or_assign(name, std::forward<T>(value));
    return;
  }
  auto& table = EnsureTable(root, name.substr(0, dot));
  table.insert_or_assign(name.substr(dot + 1), std::forward<T>(value));
}

void ReplaceFile(const std::filesystem::path& temporary,
                 const std::filesystem::path& destination) {
#ifdef _WIN32
  if (!MoveFileExW(temporary.c_str(), destination.c_str(),
                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
    throw std::filesystem::filesystem_error(
        "Cannot replace launcher configuration", temporary, destination,
        std::error_code(GetLastError(), std::system_category()));
  }
#else
  std::filesystem::rename(temporary, destination);
#endif
}

void ValidateValues(const LauncherValues& values) {
  if (values.window_width < 0 || values.window_width > 16384 ||
      values.window_height < 0 || values.window_height > 16384 ||
      values.monitor < 0 || values.monitor > 16) {
    throw Invalid("ui", "display dimensions or monitor are out of range");
  }
  RequireAllowedInt("n3.frame_rate", values.frame_rate, {0, 30, 40, 60});
  RequireAllowedInt("n3.display_resolution", values.display_resolution,
                    {720, 1080, 1440, 2160});
  if (values.renderer != "d3d12" && values.renderer != "vulkan") {
    throw Invalid("gpu.driver", "unsupported value");
  }
  if (values.render_scale < 1 || values.render_scale > 8 ||
      values.anisotropic < -1 || values.anisotropic > 5) {
    throw Invalid("gpu", "render scale or anisotropic filtering is out of range");
  }
  if (values.present_effect != "bilinear" &&
      values.present_effect != "fsr1") {
    throw Invalid("gpu.xenos.present_effect", "unsupported value");
  }
  if (values.text_language != "english" &&
      values.text_language != "french" &&
      values.text_language != "german" &&
      values.text_language != "italian" &&
      values.text_language != "spanish") {
    throw Invalid("n3.text_language", "unsupported value");
  }
  if (!std::isfinite(values.audio_gain) || values.audio_gain < 0.0 ||
      values.audio_gain > 4.0) {
    throw Invalid("apu.gain", "must be between 0 and 4");
  }
  if (values.input_drivers != "sdl3" && values.input_drivers != "xinput" &&
      values.input_drivers != "sdl3,xinput" &&
      values.input_drivers != "xinput,sdl3") {
    throw Invalid("hid.drivers", "unsupported value");
  }
  if (!std::isfinite(values.left_deadzone) || values.left_deadzone < 0.0 ||
      values.left_deadzone > 1.0 || !std::isfinite(values.right_deadzone) ||
      values.right_deadzone < 0.0 || values.right_deadzone > 1.0 ||
      !std::isfinite(values.mouse_sensitivity) ||
      values.mouse_sensitivity < 0.01 || values.mouse_sensitivity > 100.0) {
    throw Invalid("hid", "deadzone or mouse sensitivity is out of range");
  }
  for (size_t index = 0; index < values.controller_buttons.size(); ++index) {
    if (!n3::input::ParseDigitalSource(values.controller_buttons[index])) {
      throw Invalid(
          "n3.controller." +
              std::string(kControllerButtonDefinitions[index].key),
          "unsupported button source");
    }
  }
  if (!n3::input::ParseTriggerSource(values.left_trigger) ||
      !n3::input::ParseTriggerSource(values.right_trigger) ||
      !n3::input::ParseStickSource(values.left_stick) ||
      !n3::input::ParseStickSource(values.right_stick)) {
    throw Invalid("n3.controller", "unsupported analog source");
  }
  for (size_t index = 0; index < values.keybindings.size(); ++index) {
    const auto& binding = values.keybindings[index];
    if (binding.find_first_of("\r\n") != std::string::npos) {
      throw Invalid("hid.keybind", "bindings must stay on one line");
    }
    size_t start = 0;
    while (start <= binding.size()) {
      const size_t comma = binding.find(',', start);
      std::string_view token(binding.data() + start,
                             (comma == std::string::npos ? binding.size()
                                                        : comma) -
                                 start);
      while (!token.empty() && (token.front() == ' ' || token.front() == '\t'))
        token.remove_prefix(1);
      while (!token.empty() && (token.back() == ' ' || token.back() == '\t'))
        token.remove_suffix(1);
      if (!token.empty()) {
        if (auto parsed = rex::ParseInputSource(token); !parsed) {
          throw Invalid(
              "hid." + std::string(kBindingDefinitions[index].key),
              parsed.error().GetDescription());
        }
      }
      if (comma == std::string::npos) break;
      start = comma + 1;
    }
  }
}

}  // namespace

struct LauncherConfig::State {
  toml::table document;
};

LauncherValues DefaultLauncherValues() {
  LauncherValues values;
  for (size_t index = 0; index < kControllerButtonDefinitions.size(); ++index) {
    values.controller_buttons[index] =
        kControllerButtonDefinitions[index].default_value;
  }
  for (size_t index = 0; index < kBindingDefinitions.size(); ++index) {
    values.keybindings[index] = kBindingDefinitions[index].default_value;
  }
  return values;
}

LauncherConfig::LauncherConfig(std::unique_ptr<State> state)
    : values(DefaultLauncherValues()), state_(std::move(state)) {}

LauncherConfig::LauncherConfig(LauncherConfig&&) noexcept = default;
LauncherConfig& LauncherConfig::operator=(LauncherConfig&&) noexcept = default;
LauncherConfig::~LauncherConfig() = default;

LauncherConfig LauncherConfig::Load(const std::filesystem::path& path) {
  auto state = std::make_unique<State>();
  if (std::filesystem::exists(path)) {
    try {
      state->document = toml::parse_file(Utf8Text(path));
    } catch (const toml::parse_error& error) {
      throw std::runtime_error(
          std::format("{}: {}", path.string(), error.description()));
    }
  }

  LauncherConfig config(std::move(state));
  auto& document = config.state_->document;
  auto& values = config.values;

  const bool fullscreen = ReadBool(document, "ui.fullscreen", false);
  const bool exclusive =
      ReadBool(document, "ui.fullscreen_exclusive", false);
  values.window_mode =
      !fullscreen ? WindowMode::kWindowed
                  : exclusive ? WindowMode::kExclusive
                              : WindowMode::kBorderless;
  values.window_width =
      ReadInt(document, "ui.window_width", values.window_width, 0, 16384);
  values.window_height =
      ReadInt(document, "ui.window_height", values.window_height, 0, 16384);
  values.monitor = ReadInt(document, "ui.monitor", values.monitor, 0, 16);
  values.frame_rate =
      ReadInt(document, "n3.frame_rate", values.frame_rate, 0, 60);
  RequireAllowedInt("n3.frame_rate", values.frame_rate, {0, 30, 40, 60});
  values.display_resolution = ReadInt(document, "n3.display_resolution",
                                      values.display_resolution, 720, 2160);
  RequireAllowedInt("n3.display_resolution", values.display_resolution,
                    {720, 1080, 1440, 2160});
  values.renderer = ReadAllowed(document, "gpu.driver", values.renderer, "d3d12",
                                "vulkan");
  values.vsync = ReadBool(document, "gpu.vsync", values.vsync);
  const int scale_x = ReadInt(document, "gpu.resolution_scale_x",
                              values.render_scale, 1, 8);
  const int scale_y = ReadInt(document, "gpu.resolution_scale_y",
                              values.render_scale, 1, 8);
  if (scale_x != scale_y) {
    throw Invalid("gpu.resolution_scale_x",
                  "launcher requires equal X and Y render scales");
  }
  values.render_scale = scale_x;
  values.anisotropic = ReadInt(document, "gpu.anisotropic_override",
                               values.anisotropic, -1, 5);
  values.present_effect =
      ReadAllowed(document, "gpu.xenos.present_effect", values.present_effect,
                  "bilinear", "fsr1");

  values.text_language =
      ReadAllowed(document, "n3.text_language", values.text_language, "english",
                  "french", "german", "italian", "spanish");
  values.voice_directory =
      Utf8Path(ReadString(document, "n3.voice_directory", ""));
  values.audio_mute = ReadBool(document, "apu.mute", values.audio_mute);
  values.audio_mute_unfocused =
      ReadBool(document, "apu.mute_unfocused", values.audio_mute_unfocused);
  values.audio_gain =
      ReadDouble(document, "apu.gain", values.audio_gain, 0.0, 4.0);

  values.input_drivers =
      ReadAllowed(document, "hid.drivers", values.input_drivers, "sdl3",
                  "xinput", "sdl3,xinput", "xinput,sdl3");
  values.vibration =
      ReadBool(document, "hid.vibration", values.vibration);
  values.guide_button =
      ReadBool(document, "hid.guide_button", values.guide_button);
  values.left_deadzone = ReadDouble(document, "hid.left_stick_deadzone",
                                    values.left_deadzone, 0.0, 1.0);
  values.right_deadzone = ReadDouble(document, "hid.right_stick_deadzone",
                                     values.right_deadzone, 0.0, 1.0);
  values.keyboard_mouse_mode =
      ReadBool(document, "hid.mnk_mode", values.keyboard_mouse_mode);
  values.mouse_right_stick =
      ReadBool(document, "hid.mnk_mouse", values.mouse_right_stick);
  values.mouse_sensitivity = ReadDouble(
      document, "hid.mnk_sensitivity", values.mouse_sensitivity, 0.01, 100.0);
  values.keyboard_passthrough =
      ReadBool(document, "hid.mnk_passthrough", values.keyboard_passthrough);

  for (size_t index = 0; index < kControllerButtonDefinitions.size(); ++index) {
    const auto& definition = kControllerButtonDefinitions[index];
    const std::string name = "n3.controller." + std::string(definition.key);
    values.controller_buttons[index] =
        ReadString(document, name, values.controller_buttons[index]);
    if (!n3::input::ParseDigitalSource(values.controller_buttons[index])) {
      throw Invalid(name, "unsupported button source");
    }
  }
  values.left_trigger = ReadString(document, "n3.controller.left_trigger",
                                   values.left_trigger);
  values.right_trigger = ReadString(document, "n3.controller.right_trigger",
                                    values.right_trigger);
  values.left_stick =
      ReadString(document, "n3.controller.left_stick", values.left_stick);
  values.right_stick =
      ReadString(document, "n3.controller.right_stick", values.right_stick);
  if (!n3::input::ParseTriggerSource(values.left_trigger) ||
      !n3::input::ParseTriggerSource(values.right_trigger)) {
    throw Invalid("n3.controller", "unsupported trigger source");
  }
  if (!n3::input::ParseStickSource(values.left_stick) ||
      !n3::input::ParseStickSource(values.right_stick)) {
    throw Invalid("n3.controller", "unsupported stick source");
  }
  values.invert_left_x = ReadBool(document, "n3.controller.invert_left_x",
                                  values.invert_left_x);
  values.invert_left_y = ReadBool(document, "n3.controller.invert_left_y",
                                  values.invert_left_y);
  values.invert_right_x = ReadBool(document, "n3.controller.invert_right_x",
                                   values.invert_right_x);
  values.invert_right_y = ReadBool(document, "n3.controller.invert_right_y",
                                   values.invert_right_y);

  for (size_t index = 0; index < kBindingDefinitions.size(); ++index) {
    const auto& definition = kBindingDefinitions[index];
    const std::string name = "hid." + std::string(definition.key);
    values.keybindings[index] =
        ReadString(document, name, values.keybindings[index]);
  }
  ValidateValues(values);
  return config;
}

void LauncherConfig::Save(const std::filesystem::path& path) const {
  ValidateValues(values);
  toml::table document = state_->document;
  const bool fullscreen = values.window_mode != WindowMode::kWindowed;
  Set(document, "ui.fullscreen", fullscreen);
  Set(document, "ui.fullscreen_exclusive",
      values.window_mode == WindowMode::kExclusive);
  Set(document, "ui.window_width", values.window_width);
  Set(document, "ui.window_height", values.window_height);
  Set(document, "ui.monitor", values.monitor);
  Set(document, "n3.frame_rate", values.frame_rate);
  Set(document, "n3.display_resolution", values.display_resolution);
  Set(document, "gpu.driver", values.renderer);
  Set(document, "gpu.vsync", values.vsync);
  Set(document, "gpu.resolution_scale_x", values.render_scale);
  Set(document, "gpu.resolution_scale_y", values.render_scale);
  Set(document, "gpu.anisotropic_override", values.anisotropic);
  Set(document, "gpu.xenos.present_effect", values.present_effect);
  Set(document, "n3.text_language", values.text_language);
  Set(document, "n3.voice_directory", Utf8Text(values.voice_directory));
  Set(document, "apu.mute", values.audio_mute);
  Set(document, "apu.mute_unfocused", values.audio_mute_unfocused);
  Set(document, "apu.gain", values.audio_gain);
  Set(document, "hid.drivers", values.input_drivers);
  Set(document, "hid.vibration", values.vibration);
  Set(document, "hid.guide_button", values.guide_button);
  Set(document, "hid.left_stick_deadzone", values.left_deadzone);
  Set(document, "hid.right_stick_deadzone", values.right_deadzone);
  Set(document, "hid.mnk_mode", values.keyboard_mouse_mode);
  Set(document, "hid.mnk_mouse", values.mouse_right_stick);
  Set(document, "hid.mnk_sensitivity", values.mouse_sensitivity);
  Set(document, "hid.mnk_passthrough", values.keyboard_passthrough);
  for (size_t index = 0; index < kControllerButtonDefinitions.size(); ++index) {
    Set(document,
        "n3.controller." +
            std::string(kControllerButtonDefinitions[index].key),
        values.controller_buttons[index]);
  }
  Set(document, "n3.controller.left_trigger", values.left_trigger);
  Set(document, "n3.controller.right_trigger", values.right_trigger);
  Set(document, "n3.controller.left_stick", values.left_stick);
  Set(document, "n3.controller.right_stick", values.right_stick);
  Set(document, "n3.controller.invert_left_x", values.invert_left_x);
  Set(document, "n3.controller.invert_left_y", values.invert_left_y);
  Set(document, "n3.controller.invert_right_x", values.invert_right_x);
  Set(document, "n3.controller.invert_right_y", values.invert_right_y);
  for (size_t index = 0; index < kBindingDefinitions.size(); ++index) {
    Set(document, "hid." + std::string(kBindingDefinitions[index].key),
        values.keybindings[index]);
  }

  std::error_code ec;
  if (path.has_parent_path()) {
    std::filesystem::create_directories(path.parent_path(), ec);
    if (ec) {
      throw std::filesystem::filesystem_error(
          "Cannot create launcher configuration directory", path.parent_path(),
          ec);
    }
  }
  auto temporary = path;
  temporary += ".tmp";
  {
    std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
    if (!out) {
      throw std::runtime_error(
          std::format("Cannot write {}", temporary.string()));
    }
    out << document << '\n';
    out.close();
    if (!out) {
      throw std::runtime_error(
          std::format("Cannot write {}", temporary.string()));
    }
  }
  try {
    ReplaceFile(temporary, path);
  } catch (...) {
    std::filesystem::remove(temporary, ec);
    throw;
  }
}

}  // namespace n3::launcher
