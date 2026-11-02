#include "voice_override.h"

#include "voice_pack.h"

#include <rex/cvar.h>
#include <rex/filesystem/devices/host_path_device.h>
#include <rex/logging.h>
#include <rex/runtime.h>

#include <stdexcept>
#include <string_view>

REXCVAR_DEFINE_STRING(
    n3_voice_directory, "", "N3/Audio",
    "Alternate SoundRes directory from a user-owned compatible edition (restart required)")
    .lifecycle(rex::cvar::Lifecycle::kRequiresRestart);

namespace {

constexpr std::string_view kMount = "\\Device\\N3VoiceOverride";
rex::filesystem::VirtualFileSystem* mounted_vfs = nullptr;
std::string mounted_link;

std::filesystem::path PathFromUtf8(std::string_view value) {
  std::u8string utf8;
  utf8.reserve(value.size());
  for (const auto c : value) utf8.push_back(static_cast<char8_t>(c));
  return std::filesystem::path(utf8);
}

}  // namespace

void ShutdownVoiceOverride() {
  if (!mounted_vfs) return;
  if (!mounted_link.empty()) mounted_vfs->UnregisterSymbolicLink(mounted_link);
  mounted_vfs->UnregisterDevice(kMount);
  mounted_vfs = nullptr;
  mounted_link.clear();
}

bool InstallVoiceOverride(rex::Runtime& runtime,
                          const std::filesystem::path& game_data_root) {
  ShutdownVoiceOverride();
  const auto configured = REXCVAR_GET(n3_voice_directory);
  if (configured.empty()) return false;

  const auto alternate = std::filesystem::absolute(PathFromUtf8(configured));
  const auto base = game_data_root / "data" / "Sound" / "ENG" / "SoundRes";
  const auto validation = n3::voice::ValidateVoicePack(base, alternate);
  auto* vfs = runtime.file_system();
  if (!vfs) throw std::runtime_error("Runtime file system is unavailable for the voice override");

  std::string game_mount;
  if (!vfs->FindSymbolicLink("game:", game_mount))
    throw std::runtime_error("Game mount is unavailable for the voice override");
  const auto link = game_mount + "\\data\\Sound\\ENG\\SoundRes";
  std::string existing;
  if (vfs->FindSymbolicLink(link, existing))
    throw std::runtime_error("Game voice path is already overridden");

  bool device_registered = false;
  try {
    auto device = std::make_unique<rex::filesystem::HostPathDevice>(
        std::string(kMount), alternate, true);
    if (!device->Initialize() || !vfs->RegisterDevice(std::move(device)))
      throw std::runtime_error("Alternate voice directory could not be mounted");
    device_registered = true;
    if (!vfs->RegisterSymbolicLink(link, std::string(kMount)))
      throw std::runtime_error("Alternate voice path could not be linked");
  } catch (...) {
    if (device_registered) vfs->UnregisterDevice(kMount);
    throw;
  }

  mounted_vfs = vfs;
  mounted_link = link;
  REXLOG_INFO("Alternate voice banks mounted read-only: {} files ({} XWB, {} XSB)",
              validation.files, validation.wave_banks, validation.sound_banks);
  for (const auto& warning : validation.warnings)
    REXLOG_WARN("Alternate voice compatibility warning: {}", warning);
  return true;
}
