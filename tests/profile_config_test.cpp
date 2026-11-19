#include "profile_config.h"
#include <rex/settings_registry.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <chrono>

class ProbeSettings final : public rex::SettingOwner {
 public:
  ProbeSettings() : SettingOwner("config_probe") {}

  REX_SETTING(std::string, path, "", "Persistence probe");
  REX_SETTING(rex::u32, fps, 30, "Persistence probe");
  REX_SETTING(bool, enabled, false, "Persistence probe");
};

void Require(bool ok, const char* error) { if (!ok) throw std::runtime_error(error); }
std::string Read(const std::filesystem::path& file) {
  std::ifstream in(file, std::ios::binary);
  return {std::istreambuf_iterator<char>(in), {}};
}
int main() {
  const auto folder = std::filesystem::temp_directory_path() /
      ("n3-config-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  try {
    std::filesystem::create_directory(folder);
    const auto file = folder / "settings.toml";
    const std::string path = "C:\\Games\\N3\\a \"quoted\" folder\\next\nline\tend";
    ProbeSettings settings;
    Require(REX_SETTINGS().Register(settings).has_value(), "Could not register probe settings");
    REX_SETTINGS().AddAlias("config_probe_path", "config_probe.path");
    REX_SETTINGS().AddAlias("config_probe_fps", "config_probe.fps");
    REX_SETTINGS().AddAlias("config_probe_enabled", "config_probe.enabled");
    Require(settings.path.Set(path).has_value(), "Could not set probe path");
    Require(settings.fps.Set(60).has_value(), "Could not set probe frame rate");
    Require(settings.enabled.Set(true).has_value(), "Could not set probe toggle");
    SaveProfileConfig(file);
    Require(settings.path.Reset().has_value() && settings.fps.Reset().has_value() &&
                settings.enabled.Reset().has_value(),
            "Could not reset probe settings");
    Require(REX_SETTINGS().Load(file).has_value(), "Saved settings did not reload");
    Require(settings.path.Get() == path && settings.fps.Get() == 60 &&
                settings.enabled.Get(),
            "Saved settings did not reload");
    Require(!RepairLegacyProfileConfig(file), "Valid configuration was rewritten");
    {
      std::ofstream out(file);
      out << "# Auto-generated cvar configuration\nconfig_probe_path = \"C:\\Games\\N3\\folder\"\nconfig_probe_fps = 40\n";
    }
    Require(RepairLegacyProfileConfig(file), "Legacy Windows-path configuration was not repaired");
    Require(settings.path.Reset().has_value() && settings.fps.Reset().has_value(),
            "Could not reset repaired settings");
    Require(REX_SETTINGS().Load(file).has_value(),
            "Repaired legacy settings did not load");
    Require(settings.path.Get() == "C:\\Games\\N3\\folder" &&
                settings.fps.Get() == 40,
            "Legacy settings changed during repair");
    const std::string malformed = "# Auto-generated cvar configuration\ninvalid = [\n";
    { std::ofstream out(file, std::ios::binary); out << malformed; }
    Require(!RepairLegacyProfileConfig(file) && Read(file) == malformed, "Unknown malformed config was altered");
    // Replacing a nonempty config with defaults must remove the old settings.
    Require(settings.path.Reset().has_value() && settings.fps.Reset().has_value() &&
                settings.enabled.Reset().has_value(),
            "Could not reset probe settings");
    SaveProfileConfig(file);
    Require(Read(file).find("[config_probe]") == std::string::npos,
            "Reset-to-default left an old value on disk");
    std::filesystem::remove_all(folder);
    std::cout << "Configuration escaping, reload, legacy repair and default reset passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    std::filesystem::remove_all(folder);
    return 1;
  }
}
