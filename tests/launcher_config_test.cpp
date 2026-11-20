#include "launcher_config.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>

namespace {

void Require(bool condition, std::string_view message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

std::filesystem::path TemporaryDirectory() {
  auto path = std::filesystem::temp_directory_path() /
              ("n3-launcher-config-" + std::to_string(std::rand()));
  std::filesystem::remove_all(path);
  std::filesystem::create_directories(path);
  return path;
}

void TestDefaults() {
  const auto directory = TemporaryDirectory();
  auto config =
      n3::launcher::LauncherConfig::Load(directory / "missing.toml");
  Require(config.values.window_mode == n3::launcher::WindowMode::kWindowed &&
              config.values.window_width == 1280 &&
              config.values.present_effect == "fsr1" &&
              config.values.controller_buttons[0] == "a" &&
              config.values.keybindings[0] == "Semicolon,Space",
          "Launcher defaults changed");
  std::filesystem::remove_all(directory);
}

void TestLoadSaveAndPreservation() {
  const auto directory = TemporaryDirectory();
  const auto path = directory / "n3.toml";
  {
    std::ofstream out(path);
    out << "[ui]\nfullscreen = true\nfullscreen_exclusive = false\n"
           "window_width = 1920\nwindow_height = 1080\n"
           "[gpu]\ndriver = \"vulkan\"\nresolution_scale_x = 2\n"
           "resolution_scale_y = 2\n"
           "[n3]\nframe_rate = 40\ndeveloper_probe = \"keep me\"\n"
           "[n3.controller]\nbutton_a = \"b\"\n"
           "[hid]\nmnk_mode = true\nkeybind_a = \"Return\"\n";
  }
  auto config = n3::launcher::LauncherConfig::Load(path);
  Require(config.values.window_mode ==
                  n3::launcher::WindowMode::kBorderless &&
              config.values.window_width == 1920 &&
              config.values.renderer == "vulkan" &&
              config.values.render_scale == 2 &&
              config.values.frame_rate == 40 &&
              config.values.controller_buttons[0] == "b" &&
              config.values.keyboard_mouse_mode &&
              config.values.keybindings[0] == "Return",
          "Launcher did not load known settings");
  config.values.audio_gain = 0.75;
  config.values.left_trigger = "right_trigger";
  config.Save(path);
  std::ifstream saved_file(path);
  const std::string saved((std::istreambuf_iterator<char>(saved_file)),
                          std::istreambuf_iterator<char>{});
  saved_file.close();
  Require(saved.find("developer_probe") != std::string::npos &&
              saved.find("keep me") != std::string::npos &&
              saved.find("gain = 0.75") != std::string::npos &&
              saved.find("left_trigger") != std::string::npos &&
              saved.find("right_trigger") != std::string::npos,
          "Launcher did not preserve unknown settings or save changed settings");
  auto reloaded = n3::launcher::LauncherConfig::Load(path);
  Require(reloaded.values.audio_gain == 0.75 &&
              reloaded.values.left_trigger == "right_trigger",
          "Launcher did not reload its saved settings");
  std::filesystem::remove_all(directory);
}

void TestInvalidKnownSetting() {
  const auto directory = TemporaryDirectory();
  const auto path = directory / "n3.toml";
  {
    std::ofstream out(path);
    out << "[n3]\nframe_rate = 55\n";
  }
  bool rejected = false;
  try {
    (void)n3::launcher::LauncherConfig::Load(path);
  } catch (const std::exception& error) {
    rejected = std::string_view(error.what()).find("n3.frame_rate") !=
               std::string_view::npos;
  }
  Require(rejected, "Launcher accepted an unsupported known setting");
  std::filesystem::remove_all(directory);
}

void TestInvalidSave() {
  const auto directory = TemporaryDirectory();
  auto config =
      n3::launcher::LauncherConfig::Load(directory / "missing.toml");
  config.values.render_scale = 9;
  bool rejected = false;
  try {
    config.Save(directory / "n3.toml");
  } catch (const std::exception& error) {
    rejected = std::string_view(error.what()).find("gpu") !=
               std::string_view::npos;
  }
  Require(rejected, "Launcher saved an invalid curated setting");
  config.values.render_scale = 1;
  config.values.keybindings[0] = "DefinitelyNotAKey";
  rejected = false;
  try {
    config.Save(directory / "n3.toml");
  } catch (const std::exception& error) {
    rejected = std::string_view(error.what()).find("hid.keybind_a") !=
               std::string_view::npos;
  }
  Require(rejected, "Launcher saved an invalid keyboard binding");
  std::filesystem::remove_all(directory);
}

}  // namespace

int main() {
  TestDefaults();
  TestLoadSaveAndPreservation();
  TestInvalidKnownSetting();
  TestInvalidSave();
  return 0;
}
