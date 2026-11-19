#pragma once
#include <filesystem>
#include <optional>

std::optional<std::filesystem::path> ResolveGameData(
    const std::filesystem::path& game_root,
    const std::filesystem::path& user_root,
    bool headless);
void ConfigureGameDataPaths();
