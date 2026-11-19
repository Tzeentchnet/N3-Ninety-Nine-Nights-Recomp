#pragma once

#include "animation_trace.h"
#include "app_icon.h"
#include "crash_diagnostics.h"
#include "display_settings.h"
#include "frame_rate.h"
#include "game_setup.h"
#include "graphics_audit.h"
#include "graphics_menu.h"
#include "graphics_notification.h"
#include "graphics_settings.h"
#include "n3_settings.h"
#include "profile_config.h"
#include "voice_override.h"

#include <rex/app/title_app.h>
#include <rex/gpu/graphics_system.h>
#include <rex/kernel/title_paths.h>
#include <rex/path_settings.h>
#include <rex/ui/ui_system.h>

class N3App final : public rex::app::TitleApp {
 public:
  N3App() : TitleApp("n3", kPPCImageConfig) {}

 protected:
  rex::Result<void> OnConfigure(rex::SettingsRegistry& settings) override {
    REX_TRY_VOID(settings.Register(N3_SETTINGS()));
    settings.AddAlias("n3_frame_rate", "n3.frame_rate");
    settings.AddAlias("n3_60fps", "n3.legacy_60fps");
    settings.AddAlias("frame_pacing_trace", "n3.frame_pacing_trace");
    settings.AddAlias("n3_display_resolution", "n3.display_resolution");
    settings.AddAlias("n3_vsync", "gpu.vsync");
    settings.AddAlias("graphics_trace", "n3.graphics_trace");
    settings.AddAlias("graphics_audit", "n3.graphics_audit");
    settings.AddAlias("n3_text_language", "n3.text_language");
    settings.AddAlias("n3_voice_directory", "n3.voice_directory");
    settings.AddAlias("anisotropic_override", "gpu.anisotropic_override");
    settings.AddAlias("draw_resolution_scale_x", "gpu.resolution_scale_x");
    settings.AddAlias("draw_resolution_scale_y", "gpu.resolution_scale_y");

    try {
      ConfigureGameDataPaths();
      REX_TRY_VOID(REX_PATHS().config_file.Set(
          std::filesystem::path("{app.user_root}/n3.toml")));
      REX_TRY_VOID(log_root.Set(std::filesystem::path("{app.user_root}/logs")));
      RepairLegacyProfileConfig(REX_PATHS().config_file.Get());
    } catch (const std::exception& error) {
      return rex::Err(rex::ErrorCategory::kConfig, error.what());
    }

    auto& ui = GetUI().GetSettings();
    REX_TRY_VOID(ui.fullscreen.Set(false));
    REX_TRY_VOID(ui.window_width.Set(1280));
    REX_TRY_VOID(ui.window_height.Set(720));
    REX_TRY_VOID(GetGraphics().GetSettings().driver.Set("d3d12"));
    return rex::Ok();
  }

  rex::Result<void> OnInit() override {
    game_profile_ = REX_PATHS().user_root.Get();
    try {
      const auto& title_paths = GetTitleRuntime().GetTitlePaths();
      const auto game_root =
          ResolveGameData(title_paths.game_root.Get(), game_profile_,
                          IsHeadlessRequested());
      if (!game_root) {
        RequestShutdown();
        return rex::Ok();
      }
      if (title_paths.game_root.Get().empty()) {
        REX_TRY_VOID(GetTitleRuntime().GetTitlePaths().game_root.Set(*game_root));
      }

      InstallCrashDiagnostics(log_root.Get());
      ApplyAppIcon(GetUI());
      InstallGraphicsSettings(GetGraphics().GetSettings());
      InstallDisplaySettings(GetUI());
      GetUI().AddDialog(CreateGraphicsNotification());
      InstallGraphicsAudit(GetUI());
      return rex::Ok();
    } catch (const std::exception& error) {
      return rex::Err(rex::ErrorCategory::kConfig, error.what());
    }
  }

  rex::Result<void> OnTitleLaunch(rex::kernel::TitleRuntime& title) override {
    try {
      const auto game_root = title.GetTitlePaths().game_root.Get();
      InitializeFrameRate();
      InstallVoiceOverride(title, game_root);
      InstallGraphicsMenu(title, game_root, game_profile_);
      InitializeAnimationTrace(game_root, game_profile_);
      return rex::Ok();
    } catch (const std::exception& error) {
      return rex::Err(rex::ErrorCategory::kRuntime, error.what());
    }
  }

  void OnTitleExit(rex::kernel::TitleExitReason reason) override {
    ShutdownAnimationTrace();
    ShutdownVoiceOverride();
    rex::app::TitleApp::OnTitleExit(reason);
  }

  void OnShutdown() override {
    ShutdownAnimationTrace();
    ShutdownVoiceOverride();
    ShutdownGraphicsAudit();
    ShutdownDisplaySettings();
    ShutdownGraphicsSettings();
  }

 private:
  std::filesystem::path game_profile_;
};
