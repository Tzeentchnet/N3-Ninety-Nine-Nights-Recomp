#include "voice_pack.h"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

void WriteBigEndian32(std::vector<uint8_t>& bytes, std::size_t offset, uint32_t value) {
  bytes.at(offset) = uint8_t(value >> 24);
  bytes.at(offset + 1) = uint8_t(value >> 16);
  bytes.at(offset + 2) = uint8_t(value >> 8);
  bytes.at(offset + 3) = uint8_t(value);
}

void WriteFile(const std::filesystem::path& path, const std::vector<uint8_t>& bytes) {
  std::ofstream output(path, std::ios::binary);
  output.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
  if (!output) throw std::runtime_error("Could not create voice-pack fixture");
}

void WriteWaveBank(const std::filesystem::path& path, uint32_t entries, uint32_t format) {
  std::vector<uint8_t> bytes(256, 0);
  bytes[0] = 'D';
  bytes[1] = 'N';
  bytes[2] = 'B';
  bytes[3] = 'W';
  WriteBigEndian32(bytes, 4, 46);
  WriteBigEndian32(bytes, 8, 64);
  WriteBigEndian32(bytes, 12, 80);
  WriteBigEndian32(bytes, 16, 144);
  WriteBigEndian32(bytes, 20, entries * 8);
  WriteBigEndian32(bytes, 64, 3);
  WriteBigEndian32(bytes, 68, entries);
  constexpr std::string_view name = "mission_voice";
  std::copy(name.begin(), name.end(), bytes.begin() + 72);
  WriteBigEndian32(bytes, 136, 8);
  for (uint32_t i = 0; i < entries; ++i)
    WriteBigEndian32(bytes, 144 + i * 8 + 4, format);
  WriteFile(path, bytes);
}

void WriteSoundBank(const std::filesystem::path& path, uint8_t header_byte,
                    uint8_t payload_byte) {
  std::vector<uint8_t> bytes(192, 0);
  bytes[0] = header_byte;
  bytes[0x99] = payload_byte;
  WriteFile(path, bytes);
}

void WritePreload(const std::filesystem::path& path, std::string_view bank_name) {
  std::vector<uint8_t> bytes(4 + 268, 0);
  WriteBigEndian32(bytes, 0, 1);
  std::copy(bank_name.begin(), bank_name.end(), bytes.begin() + 4);
  WriteFile(path, bytes);
}

template <typename Callback>
void RequireRejected(Callback&& callback, const char* message) {
  try {
    callback();
  } catch (const std::runtime_error&) {
    return;
  }
  throw std::runtime_error(message);
}

}  // namespace

int main() {
  const auto root = std::filesystem::temp_directory_path() /
      ("n3-voice-pack-" + std::to_string(
          std::chrono::steady_clock::now().time_since_epoch().count()));
  const auto base = root / "base";
  const auto alternate = root / "alternate";
  try {
    std::filesystem::create_directories(base);
    std::filesystem::create_directories(alternate);
    WriteWaveBank(base / "mission.xwb", 2, 0x12345678);
    WriteWaveBank(alternate / "mission.xwb", 1, 0x12345678);
    WriteSoundBank(base / "mission.xsb", 1, 7);
    WriteSoundBank(alternate / "mission.xsb", 2, 7);
    WritePreload(base / "xwbpreload.pak", "mission");
    WritePreload(alternate / "xwbpreload.pak", "mission");

    const auto summary = n3::voice::ValidateVoicePack(base, alternate);
    Require(summary.files == 3 && summary.wave_banks == 1 &&
                summary.sound_banks == 1 && summary.warnings.size() == 1,
            "Compatible voice pack summary is incorrect");

    std::filesystem::remove(alternate / "mission.xsb");
    RequireRejected([&] { n3::voice::ValidateVoicePack(base, alternate); },
                    "Missing alternate bank was accepted");
    WriteSoundBank(alternate / "mission.xsb", 2, 7);

    WriteWaveBank(alternate / "mission.xwb", 1, 0x87654321);
    RequireRejected([&] { n3::voice::ValidateVoicePack(base, alternate); },
                    "Incompatible wave format was accepted");
    WriteWaveBank(alternate / "mission.xwb", 1, 0x12345678);

    WriteSoundBank(alternate / "mission.xsb", 2, 8);
    RequireRejected([&] { n3::voice::ValidateVoicePack(base, alternate); },
                    "Incompatible sound-bank payload was accepted");
    WriteSoundBank(alternate / "mission.xsb", 2, 7);

    WritePreload(alternate / "xwbpreload.pak", "other");
    RequireRejected([&] { n3::voice::ValidateVoicePack(base, alternate); },
                    "Incompatible preload bank list was accepted");
    WritePreload(alternate / "xwbpreload.pak", "mission");

    WriteFile(alternate / "unexpected.bin", {1});
    RequireRejected([&] { n3::voice::ValidateVoicePack(base, alternate); },
                    "Unexpected alternate file was accepted");
    std::filesystem::remove_all(root);
    std::cout << "Voice-pack compatibility validation passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    std::filesystem::remove_all(root);
    return 1;
  }
}
