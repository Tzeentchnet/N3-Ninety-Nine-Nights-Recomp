#pragma once

#include <array>
#include <cstdint>
#include <string_view>

namespace n3::text {

struct Language {
  std::string_view name;
  uint32_t xbox_code;
};

inline constexpr std::array<Language, 5> kLanguages{{
    {"english", 1},
    {"german", 3},
    {"french", 4},
    {"spanish", 5},
    {"italian", 6},
}};

constexpr uint32_t LanguageCode(std::string_view name) {
  for (const auto& language : kLanguages)
    if (language.name == name) return language.xbox_code;
  return kLanguages.front().xbox_code;
}

}  // namespace n3::text
