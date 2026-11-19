#pragma once

#include <filesystem>

#include <rex/setting.h>
#include <rex/settings_registry.h>

class N3Settings final : public rex::SettingOwner {
 public:
  N3Settings() : SettingOwner("n3") {}

  REX_SETTING(rex::u32, frame_rate, 60,
              "Display presentation rate; game timing remains at 30 FPS",
              rex::Allowed("0", "30", "40", "60"));
  REX_SETTING(bool, legacy_60fps, false,
              "Compatibility alias for the previous 60 FPS setting",
              rex::kDebugOnly);
  REX_SETTING(bool, frame_pacing_trace, false,
              "Log guest presentation counts and intervals for development",
              rex::kDebugOnly);
  REX_SETTING(rex::u32, display_resolution, 720,
              "Window/output resolution height",
              rex::Allowed("720", "1080", "1440", "2160"));
  REX_SETTING(bool, graphics_trace, false,
              "Trace actual graphics output and sampler state", rex::kDebugOnly);
  REX_SETTING(bool, graphics_audit, false,
              "Developer probe: cycle graphics controls without saving",
              rex::kDebugOnly);
  REX_SETTING(std::string, text_language, "english", "Text language",
              rex::Allowed("english", "french", "german", "italian", "spanish"),
              rex::kRestart);
  REX_SETTING(std::filesystem::path, voice_directory, "",
              "Alternate SoundRes directory from a user-owned compatible edition",
              rex::kRestart);
};

inline N3Settings& GetN3Settings() {
  static N3Settings settings;
  return settings;
}

#define N3_SETTINGS() ::GetN3Settings()
