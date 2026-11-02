#include "voice_pack.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string_view>

namespace n3::voice {
namespace {

using FileMap = std::map<std::string, std::filesystem::path>;

std::string LowerAscii(std::string value) {
  for (auto& c : value)
    if (c >= 'A' && c <= 'Z') c = char(c + ('a' - 'A'));
  return value;
}

FileMap CollectFiles(const std::filesystem::path& directory) {
  if (!std::filesystem::is_directory(directory))
    throw std::runtime_error("Voice-bank directory does not exist: " + directory.string());
  FileMap files;
  for (const auto& entry : std::filesystem::directory_iterator(directory)) {
    if (!entry.is_regular_file())
      throw std::runtime_error("Voice-bank directory contains a non-file entry: " +
                               entry.path().filename().string());
    const auto name = LowerAscii(entry.path().filename().string());
    if (!files.emplace(name, entry.path()).second)
      throw std::runtime_error("Voice-bank directory contains duplicate names: " + name);
  }
  return files;
}

uint32_t ReadBigEndian32(std::ifstream& input, uint64_t offset,
                         const std::filesystem::path& path) {
  if (offset > static_cast<uint64_t>(std::numeric_limits<std::streamoff>::max()))
    throw std::runtime_error("Invalid offset in " + path.filename().string());
  std::array<uint8_t, 4> bytes{};
  input.seekg(static_cast<std::streamoff>(offset));
  input.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
  if (!input)
    throw std::runtime_error("Truncated voice-bank file: " + path.filename().string());
  return (uint32_t(bytes[0]) << 24) | (uint32_t(bytes[1]) << 16) |
         (uint32_t(bytes[2]) << 8) | uint32_t(bytes[3]);
}

std::string ReadFixedString(std::ifstream& input, uint64_t offset, std::size_t length,
                            const std::filesystem::path& path) {
  std::string value(length, '\0');
  input.seekg(static_cast<std::streamoff>(offset));
  input.read(value.data(), static_cast<std::streamsize>(length));
  if (!input)
    throw std::runtime_error("Truncated voice-bank file: " + path.filename().string());
  const auto terminator = value.find('\0');
  if (terminator != std::string::npos) value.resize(terminator);
  return value;
}

struct WaveBank {
  uint32_t version = 0;
  uint32_t flags = 0;
  uint32_t entries = 0;
  uint32_t metadata_size = 0;
  std::string name;
  std::set<uint32_t> formats;
};

WaveBank ReadWaveBank(const std::filesystem::path& path) {
  const auto file_size = std::filesystem::file_size(path);
  std::ifstream input(path, std::ios::binary);
  std::array<char, 4> signature{};
  input.read(signature.data(), signature.size());
  if (!input || std::string_view(signature.data(), signature.size()) != "DNBW")
    throw std::runtime_error("Not an Xbox 360 XWB file: " + path.filename().string());

  const auto bank_offset = ReadBigEndian32(input, 8, path);
  const auto bank_length = ReadBigEndian32(input, 12, path);
  const auto metadata_offset = ReadBigEndian32(input, 16, path);
  const auto metadata_length = ReadBigEndian32(input, 20, path);
  if (bank_length < 76 || uint64_t(bank_offset) + 76 > file_size)
    throw std::runtime_error("Invalid XWB bank-data segment: " + path.filename().string());

  WaveBank bank;
  bank.version = ReadBigEndian32(input, 4, path);
  bank.flags = ReadBigEndian32(input, bank_offset, path);
  bank.entries = ReadBigEndian32(input, uint64_t(bank_offset) + 4, path);
  bank.name = ReadFixedString(input, uint64_t(bank_offset) + 8, 64, path);
  bank.metadata_size = ReadBigEndian32(input, uint64_t(bank_offset) + 72, path);
  if (bank.entries && bank.metadata_size < 8)
    throw std::runtime_error("Invalid XWB metadata size: " + path.filename().string());
  const uint64_t metadata_bytes = uint64_t(bank.entries) * bank.metadata_size;
  if (metadata_bytes > metadata_length ||
      uint64_t(metadata_offset) + metadata_bytes > file_size)
    throw std::runtime_error("Invalid XWB metadata table: " + path.filename().string());
  for (uint32_t i = 0; i < bank.entries; ++i)
    bank.formats.insert(ReadBigEndian32(
        input, uint64_t(metadata_offset) + uint64_t(i) * bank.metadata_size + 4, path));
  return bank;
}

std::vector<std::string> ReadPreloadNames(const std::filesystem::path& path) {
  const auto file_size = std::filesystem::file_size(path);
  std::ifstream input(path, std::ios::binary);
  const auto count = ReadBigEndian32(input, 0, path);
  constexpr uint64_t entry_size = 268;
  if (count > 1000 || 4 + uint64_t(count) * entry_size > file_size)
    throw std::runtime_error("Invalid xwbpreload.pak table");
  std::vector<std::string> names;
  names.reserve(count);
  for (uint32_t i = 0; i < count; ++i)
    names.push_back(ReadFixedString(input, 4 + uint64_t(i) * entry_size, 256, path));
  return names;
}

bool FilesMatchFrom(const std::filesystem::path& first,
                    const std::filesystem::path& second, uint64_t offset) {
  const auto first_size = std::filesystem::file_size(first);
  if (first_size != std::filesystem::file_size(second) || offset > first_size) return false;
  std::ifstream left(first, std::ios::binary), right(second, std::ios::binary);
  left.seekg(static_cast<std::streamoff>(offset));
  right.seekg(static_cast<std::streamoff>(offset));
  std::array<char, 4096> left_bytes{}, right_bytes{};
  while (left || right) {
    left.read(left_bytes.data(), left_bytes.size());
    right.read(right_bytes.data(), right_bytes.size());
    if (left.gcount() != right.gcount() ||
        !std::equal(left_bytes.begin(), left_bytes.begin() + left.gcount(),
                    right_bytes.begin()))
      return false;
  }
  return true;
}

void RequireSameFileSet(const FileMap& base, const FileMap& alternate) {
  for (const auto& [name, path] : base)
    if (!alternate.contains(name))
      throw std::runtime_error("Alternate voices are missing " + path.filename().string());
  for (const auto& [name, path] : alternate)
    if (!base.contains(name))
      throw std::runtime_error("Alternate voices contain unexpected file " +
                               path.filename().string());
}

}  // namespace

ValidationSummary ValidateVoicePack(const std::filesystem::path& base_directory,
                                    const std::filesystem::path& alternate_directory) {
  const auto base = CollectFiles(base_directory);
  const auto alternate = CollectFiles(alternate_directory);
  RequireSameFileSet(base, alternate);

  ValidationSummary summary;
  summary.files = alternate.size();
  for (const auto& [name, base_path] : base) {
    const auto& alternate_path = alternate.at(name);
    if (name.ends_with(".xwb")) {
      const auto expected = ReadWaveBank(base_path);
      const auto candidate = ReadWaveBank(alternate_path);
      if (candidate.version != expected.version || candidate.flags != expected.flags ||
          candidate.name != expected.name ||
          candidate.metadata_size != expected.metadata_size ||
          candidate.formats != expected.formats)
        throw std::runtime_error("Incompatible alternate wave bank: " +
                                 alternate_path.filename().string());
      if (candidate.entries != expected.entries)
        summary.warnings.push_back(alternate_path.filename().string() +
                                   " has a different entry count");
      ++summary.wave_banks;
    } else if (name.ends_with(".xsb")) {
      if (!FilesMatchFrom(base_path, alternate_path, 0x99))
        throw std::runtime_error("Incompatible alternate sound bank: " +
                                 alternate_path.filename().string());
      ++summary.sound_banks;
    } else if (name == "xwbpreload.pak") {
      if (ReadPreloadNames(base_path) != ReadPreloadNames(alternate_path))
        throw std::runtime_error("Alternate xwbpreload.pak lists different banks");
    }
  }
  return summary;
}

}  // namespace n3::voice
