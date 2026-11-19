#pragma once

#include <filesystem>

namespace rex {
namespace kernel {
class TitleRuntime;
}
}

bool InstallVoiceOverride(rex::kernel::TitleRuntime& runtime,
                          const std::filesystem::path& game_data_root);
void ShutdownVoiceOverride();
