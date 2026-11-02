#include "text_language.h"

#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {

void Require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

}  // namespace

int main() {
  try {
    using n3::text::LanguageCode;
    Require(LanguageCode("english") == 1 && LanguageCode("german") == 3 &&
                LanguageCode("french") == 4 && LanguageCode("spanish") == 5 &&
                LanguageCode("italian") == 6,
            "PAL language codes do not match XLanguage");
    for (const auto invalid : {"", "japanese", "Spanish", "spa", "spanish "})
      Require(LanguageCode(invalid) == 1, "Unknown language did not retain English");

    std::set<std::string_view> names;
    std::set<uint32_t> codes;
    for (const auto& language : n3::text::kLanguages) {
      Require(names.insert(language.name).second, "Duplicate text-language name");
      Require(codes.insert(language.xbox_code).second, "Duplicate text-language code");
      Require(language.xbox_code != 2, "Japanese text is not present on the supported disc");
    }

    std::ifstream file(N3_MANIFEST_PATH);
    Require(file.good(), "Cannot open n3_manifest.toml");
    std::stringstream contents;
    contents << file.rdbuf();
    const auto manifest = contents.str();
    auto require_hook = [&](std::string_view address, std::string_view jump) {
      const auto start = manifest.find("address = " + std::string(address));
      Require(start != std::string::npos, "Missing language hook at " + std::string(address));
      const auto next = manifest.find("[[", start);
      const auto block = manifest.substr(start, next - start);
      Require(block.contains("name = \"N3GetTextLanguage\"") &&
                  block.contains("registers = [\"r3\"]") &&
                  block.contains("jump_address = " + std::string(jump)),
              "Language hook has the wrong target or register contract");
    };
    require_hook("0x8211019C", "0x821101A0");
    require_hook("0x8252FBDC", "0x8252FBE0");
    std::cout << "Text-language policy and manifest hooks passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
