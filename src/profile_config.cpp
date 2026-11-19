#include "profile_config.h"

#include <rex/settings_registry.h>

#include <cctype>
#include <fstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#ifdef _WIN32
#include <Windows.h>
#endif

namespace {
constexpr auto kLegacyHeader = "# Auto-generated cvar configuration";
constexpr auto kRepairedHeader = "# Repaired legacy cvar configuration";

struct LegacyValue {
  std::string name;
  std::string value;
  bool string = false;
};

bool IsSettingName(std::string_view name) {
  if (name.empty()) return false;
  for (const unsigned char c : name) {
    if (!std::isalnum(c) && c != '_') return false;
  }
  return true;
}

bool IsScalar(std::string_view value) {
  if (value == "true" || value == "false") return true;
  if (value.empty()) return false;
  size_t index = value.front() == '-' || value.front() == '+' ? 1 : 0;
  bool digit = false;
  bool dot = false;
  for (; index < value.size(); ++index) {
    const char c = value[index];
    if (c >= '0' && c <= '9') {
      digit = true;
    } else if (c == '.' && !dot) {
      dot = true;
    } else {
      return false;
    }
  }
  return digit;
}

std::string Quote(std::string_view value) {
  std::string result = "\"";
  for (const unsigned char c : value) {
    switch (c) {
      case '\\': result += "\\\\"; break;
      case '"': result += "\\\""; break;
      case '\b': result += "\\b"; break;
      case '\t': result += "\\t"; break;
      case '\n': result += "\\n"; break;
      case '\f': result += "\\f"; break;
      case '\r': result += "\\r"; break;
      default:
        if (c < 0x20 || c == 0x7F) return {};
        result.push_back(static_cast<char>(c));
        break;
    }
  }
  result.push_back('"');
  return result;
}

void Write(const std::filesystem::path& path,
           const std::vector<LegacyValue>& values) {
  auto temporary = path;
  temporary += ".tmp";
  {
    std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
    out << kRepairedHeader << '\n';
    for (const auto& value : values) {
      out << value.name << " = "
          << (value.string ? Quote(value.value) : value.value) << '\n';
    }
    out.close();
    if (!out) throw std::runtime_error("Cannot save profile configuration");
  }
#ifdef _WIN32
  if (!MoveFileExW(temporary.c_str(), path.c_str(),
                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
    throw std::filesystem::filesystem_error(
        "Cannot replace profile configuration", temporary, path,
        std::error_code(GetLastError(), std::system_category()));
  }
#else
  std::filesystem::rename(temporary, path);
#endif
}
}  // namespace

void SaveProfileConfig(const std::filesystem::path& path) {
  if (auto saved = REX_SETTINGS().Save(path); !saved)
    throw std::runtime_error(saved.error().GetDescription());
}

bool RepairLegacyProfileConfig(const std::filesystem::path& path) {
  if (!std::filesystem::exists(path)) return false;
  std::ifstream in(path, std::ios::binary);
  std::string line;
  if (!std::getline(in, line)) return false;
  if (!line.empty() && line.back() == '\r') line.pop_back();
  if (line != kLegacyHeader) return false;

  std::vector<LegacyValue> values;
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) continue;
    const auto equal = line.find(" = ");
    if (equal == std::string::npos) return false;
    LegacyValue parsed{line.substr(0, equal), line.substr(equal + 3)};
    if (!IsSettingName(parsed.name)) return false;
    for (const auto& value : values)
      if (value.name == parsed.name) return false;
    if (parsed.value.size() >= 2 && parsed.value.front() == '"' &&
        parsed.value.back() == '"') {
      parsed.string = true;
      parsed.value = parsed.value.substr(1, parsed.value.size() - 2);
      if (Quote(parsed.value).empty()) return false;
    } else if (!IsScalar(parsed.value)) {
      return false;
    }
    values.push_back(std::move(parsed));
  }
  in.close();
  Write(path, values);
  return true;
}
