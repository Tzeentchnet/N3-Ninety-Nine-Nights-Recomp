#include "voice_override.h"

#include "n3_settings.h"
#include "voice_pack.h"

#include <rex/filesystem/file_system.h>
#include <rex/logging.h>
#include <rex/kernel/title_runtime.h>

#include <stdexcept>
#include <string_view>

namespace {

constexpr std::string_view kMount = "\\Device\\N3VoiceOverride";

}  // namespace

void ShutdownVoiceOverride() {}

bool InstallVoiceOverride(rex::kernel::TitleRuntime& runtime,
                          const std::filesystem::path& game_data_root) {
  const auto configured = N3_SETTINGS().voice_directory.Get();
  if (configured.empty()) return false;

  const auto alternate = std::filesystem::absolute(configured);
  const auto base = game_data_root / "data" / "Sound" / "ENG" / "SoundRes";
  const auto validation = n3::voice::ValidateVoicePack(base, alternate);
  auto& vfs = runtime.GetFileSystem();

  const auto game_mount = vfs.FindLink("game:");
  if (!game_mount)
    throw std::runtime_error("Game mount is unavailable for the voice override");
  const auto link = *game_mount + "\\data\\Sound\\ENG\\SoundRes";
  if (vfs.FindLink(link))
    throw std::runtime_error("Game voice path is already overridden");

  bool mounted = false;
  try {
    if (auto result = vfs.Mount({std::string(kMount),
                                 rex::filesystem::ProviderType::kHostDirectory,
                                 alternate,
                                 rex::filesystem::MountFlags::kNone,
                                 {}});
        !result) {
      throw std::runtime_error("Alternate voice directory could not be mounted");
    }
    mounted = true;
    if (auto result = vfs.Link(link, kMount); !result)
      throw std::runtime_error("Alternate voice path could not be linked");
  } catch (...) {
    if (mounted) (void)vfs.Unmount(kMount);
    throw;
  }

  REXLOG_INFO("Alternate voice banks mounted read-only: {} files ({} XWB, {} XSB)",
              validation.files, validation.wave_banks, validation.sound_banks);
  for (const auto& warning : validation.warnings)
    REXLOG_WARN("Alternate voice compatibility warning: {}", warning);
  return true;
}
