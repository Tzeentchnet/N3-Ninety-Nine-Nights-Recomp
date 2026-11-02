#pragma once

#include <cstddef>
#include <filesystem>
#include <string>
#include <vector>

namespace n3::voice {

struct ValidationSummary {
  std::size_t files = 0;
  std::size_t wave_banks = 0;
  std::size_t sound_banks = 0;
  std::vector<std::string> warnings;
};

ValidationSummary ValidateVoicePack(const std::filesystem::path& base_directory,
                                    const std::filesystem::path& alternate_directory);

}  // namespace n3::voice
