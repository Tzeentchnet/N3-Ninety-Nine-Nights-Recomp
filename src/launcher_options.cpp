#include "launcher_options.h"

#include <array>
#include <stdexcept>
#include <unordered_set>

namespace n3::launcher {
namespace {

struct OptionDefinition {
  std::wstring_view name;
  std::optional<std::filesystem::path> LauncherOptions::*member;
};

constexpr std::array<OptionDefinition, 5> kOptions{{
    {L"--config-file", &LauncherOptions::config_file},
    {L"--user-root", &LauncherOptions::user_root},
    {L"--game-root", &LauncherOptions::game_root},
    {L"--cache-root", &LauncherOptions::cache_root},
    {L"--log-root", &LauncherOptions::log_root},
}};

const OptionDefinition* FindOption(std::wstring_view name) {
  for (const auto& option : kOptions) {
    if (option.name == name) return &option;
  }
  return nullptr;
}

void AddPathArgument(std::vector<std::wstring>& arguments,
                     std::wstring_view name,
                     const std::optional<std::filesystem::path>& value) {
  if (!value) return;
  arguments.emplace_back(name);
  arguments.push_back(value->wstring());
}

}  // namespace

LauncherOptions ParseLauncherOptions(
    std::span<const std::wstring> arguments) {
  LauncherOptions result;
  std::unordered_set<std::wstring> seen;
  for (size_t index = 0; index < arguments.size(); ++index) {
    const auto* option = FindOption(arguments[index]);
    if (!option) {
      throw std::runtime_error("Unknown launcher option");
    }
    if (!seen.emplace(option->name).second) {
      throw std::runtime_error("Duplicate launcher option");
    }
    if (++index == arguments.size() || arguments[index].empty()) {
      throw std::runtime_error("Launcher option requires a path");
    }
    result.*(option->member) = std::filesystem::path(arguments[index]);
  }
  return result;
}

std::optional<std::filesystem::path> SelectGameRoot(
    const std::optional<std::filesystem::path>& fallback,
    const std::optional<std::filesystem::path>& remembered) {
  return remembered ? remembered : fallback;
}

std::vector<std::wstring> RuntimeArguments(const LauncherOptions& options,
                                           bool reset_game_data) {
  std::vector<std::wstring> arguments;
  if (!reset_game_data) {
    AddPathArgument(arguments, L"--title.game_root", options.game_root);
  }
  AddPathArgument(arguments, L"--app.user_root", options.user_root);
  AddPathArgument(arguments, L"--app.config_file", options.config_file);
  AddPathArgument(arguments, L"--app.cache_root", options.cache_root);
  AddPathArgument(arguments, L"--app.log_root", options.log_root);
  return arguments;
}

std::wstring QuoteWindowsArgument(std::wstring_view argument) {
  if (!argument.empty() &&
      argument.find_first_of(L" \t\n\v\"") == std::wstring_view::npos) {
    return std::wstring(argument);
  }
  std::wstring result(1, L'"');
  size_t backslashes = 0;
  for (const wchar_t character : argument) {
    if (character == L'\\') {
      ++backslashes;
      continue;
    }
    if (character == L'"') {
      result.append(backslashes * 2 + 1, L'\\');
      result.push_back(character);
      backslashes = 0;
      continue;
    }
    result.append(backslashes, L'\\');
    backslashes = 0;
    result.push_back(character);
  }
  result.append(backslashes * 2, L'\\');
  result.push_back(L'"');
  return result;
}

std::wstring BuildWindowsCommandLine(
    const std::filesystem::path& executable,
    std::span<const std::wstring> arguments) {
  std::wstring result = QuoteWindowsArgument(executable.wstring());
  for (const auto& argument : arguments) {
    result.push_back(L' ');
    result += QuoteWindowsArgument(argument);
  }
  return result;
}

}  // namespace n3::launcher
