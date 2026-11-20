#include "launcher_options.h"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

void TestParsing() {
  const std::vector<std::wstring> arguments{
      L"--config-file", L"C:\\N3 User\\n3.toml",
      L"--user-root",   L"C:\\N3 User",
      L"--game-root",   L"D:\\Games\\N3",
      L"--cache-root",  L"C:\\N3 Cache",
      L"--log-root",    L"C:\\N3 Logs",
  };
  const auto options = n3::launcher::ParseLauncherOptions(arguments);
  Require(options.config_file == L"C:\\N3 User\\n3.toml",
          "Config path was not parsed");
  Require(options.user_root == L"C:\\N3 User", "User path was not parsed");
  Require(options.game_root == L"D:\\Games\\N3", "Game path was not parsed");
  Require(options.cache_root == L"C:\\N3 Cache", "Cache path was not parsed");
  Require(options.log_root == L"C:\\N3 Logs", "Log path was not parsed");
}

void TestInvalidOptions() {
  for (const std::vector<std::wstring> arguments : {
           std::vector<std::wstring>{L"--unknown", L"value"},
           std::vector<std::wstring>{L"--user-root"},
           std::vector<std::wstring>{L"--user-root", L""},
           std::vector<std::wstring>{L"--user-root", L"a", L"--user-root",
                                     L"b"},
       }) {
    bool rejected = false;
    try {
      (void)n3::launcher::ParseLauncherOptions(arguments);
    } catch (const std::exception&) {
      rejected = true;
    }
    Require(rejected, "Invalid launcher options were accepted");
  }
}

void TestRuntimeArguments() {
  n3::launcher::LauncherOptions options;
  options.config_file = L"C:\\User\\n3.toml";
  options.user_root = L"C:\\User";
  options.game_root = L"D:\\N3";
  const auto normal = n3::launcher::RuntimeArguments(options, false);
  Require(normal.size() == 6, "Normal runtime arguments are incomplete");
  Require(normal[0] == L"--title.game_root" && normal[1] == L"D:\\N3",
          "Game root was not forwarded");
  const auto reset = n3::launcher::RuntimeArguments(options, true);
  Require(reset.size() == 4, "Reset runtime arguments have the wrong size");
  Require(reset[0] == L"--app.user_root",
          "Reset retained the explicit game root");
}

void TestRememberedGameSelection() {
  const std::optional<std::filesystem::path> fallback = L"D:\\N3 Default";
  const std::optional<std::filesystem::path> remembered = L"E:\\N3 Alternate";
  Require(n3::launcher::SelectGameRoot(fallback, remembered) == remembered,
          "Remembered game data did not override the fallback");
  Require(n3::launcher::SelectGameRoot(fallback, std::nullopt) == fallback,
          "Fallback game data was not selected");
  Require(!n3::launcher::SelectGameRoot(std::nullopt, std::nullopt),
          "Empty game selection did not stay empty");
}

void TestQuoting() {
  Require(n3::launcher::QuoteWindowsArgument(L"plain") == L"plain",
          "Plain argument was changed");
  Require(n3::launcher::QuoteWindowsArgument(L"") == L"\"\"",
          "Empty argument was not quoted");
  Require(n3::launcher::QuoteWindowsArgument(L"C:\\N3 User\\") ==
              L"\"C:\\N3 User\\\\\"",
          "Trailing slash was not escaped");
  const std::vector<std::wstring> arguments{L"--user-root", L"C:\\N3 User"};
  Require(n3::launcher::BuildWindowsCommandLine(
              L"C:\\Program Files\\N3\\n3.exe", arguments) ==
              L"\"C:\\Program Files\\N3\\n3.exe\" --user-root "
              L"\"C:\\N3 User\"",
          "Windows command line was not assembled correctly");
}

}  // namespace

int main() {
  try {
    TestParsing();
    TestInvalidOptions();
    TestRuntimeArguments();
    TestRememberedGameSelection();
    TestQuoting();
    std::cout << "Launcher option tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
