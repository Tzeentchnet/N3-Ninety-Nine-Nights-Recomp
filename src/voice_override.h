#pragma once

#include <filesystem>

namespace rex {
class Runtime;
}

bool InstallVoiceOverride(rex::Runtime& runtime,
                          const std::filesystem::path& game_data_root);
void ShutdownVoiceOverride();
