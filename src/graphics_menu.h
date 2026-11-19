#pragma once
#include <filesystem>
namespace rex::kernel { class TitleRuntime; }
bool InstallGraphicsMenu(rex::kernel::TitleRuntime& runtime,
                         const std::filesystem::path& game_root,
                         const std::filesystem::path& profile);
