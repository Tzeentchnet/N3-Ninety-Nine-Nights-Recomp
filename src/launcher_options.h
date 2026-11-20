#pragma once

#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace n3::launcher {

struct LauncherOptions {
  std::optional<std::filesystem::path> config_file;
  std::optional<std::filesystem::path> user_root;
  std::optional<std::filesystem::path> game_root;
  std::optional<std::filesystem::path> cache_root;
  std::optional<std::filesystem::path> log_root;
};

LauncherOptions ParseLauncherOptions(
    std::span<const std::wstring> arguments);
std::optional<std::filesystem::path> SelectGameRoot(
    const std::optional<std::filesystem::path>& fallback,
    const std::optional<std::filesystem::path>& remembered);
std::vector<std::wstring> RuntimeArguments(const LauncherOptions& options,
                                           bool reset_game_data);
std::wstring QuoteWindowsArgument(std::wstring_view argument);
std::wstring BuildWindowsCommandLine(
    const std::filesystem::path& executable,
    std::span<const std::wstring> arguments);

}  // namespace n3::launcher
