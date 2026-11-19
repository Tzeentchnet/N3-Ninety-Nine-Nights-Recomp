#include "display_settings.h"
#include "n3_settings.h"
#include <rex/ui/ui_system.h>
#include <rex/logging.h>
#include <optional>

namespace {
std::optional<rex::ScopeGuard> display_height_watch;

void ApplyDisplayHeight(rex::ui::IUISystem& ui, uint32_t height, bool selected) {
  const uint32_t width = height * 16 / 9;
  auto& settings = ui.GetSettings();
  if (selected && settings.fullscreen.Get()) {
    (void)settings.fullscreen.Set(false);
  }
  (void)settings.window_width.Set(static_cast<rex::i32>(width));
  (void)settings.window_height.Set(static_cast<rex::i32>(height));
  REXLOG_INFO("Display size requested: {}x{} pixels", width, height);
}
}  // namespace

uint32_t ConfiguredDisplayHeight() { return N3_SETTINGS().display_resolution.Get(); }
bool SetDisplayHeight(uint32_t height) {
  if (height != 720 && height != 1080 && height != 1440 && height != 2160) return false;
  return N3_SETTINGS().display_resolution.Set(height).has_value();
}

void InstallDisplaySettings(rex::ui::IUISystem& ui) {
  display_height_watch.emplace(N3_SETTINGS().display_resolution.OnChange(
      [&ui](const rex::u32& height) {
        ui.PostTask([&ui, height] { ApplyDisplayHeight(ui, height, true); });
      }));
  auto& settings = ui.GetSettings();
  const auto source = N3_SETTINGS().display_resolution.GetLayer();
  if (source >= settings.window_width.GetLayer() &&
      source >= settings.window_height.GetLayer() &&
      source >= settings.resolution.GetLayer()) {
    ApplyDisplayHeight(ui, ConfiguredDisplayHeight(), false);
  }
}

void ShutdownDisplaySettings() { display_height_watch.reset(); }

void RecordDisplayOutputSize(uint32_t width, uint32_t height) {
  if (width && height) REXLOG_INFO("Display output size: {}x{} pixels", width, height);
}
