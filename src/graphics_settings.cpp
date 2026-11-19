#include "graphics_settings.h"
#include "frame_rate.h"
#include "display_settings.h"
#include "graphics_filtering.h"
#include "n3_settings.h"
#include <rex/gpu/graphics_system.h>
#include <rex/logging.h>
#include <array>
#include <algorithm>
#include <optional>
#include <string>

namespace {
rex::gpu::GraphicsSettings* graphics_settings = nullptr;
std::optional<rex::ScopeGuard> frame_rate_watch;

void ApplyPresentationRate(rex::gpu::GraphicsSettings& settings, uint32_t fps,
                           rex::SettingLayer source) {
  const auto target_layer =
      source == rex::SettingLayer::kDefault ? rex::SettingLayer::kTitle : source;
  const auto result =
      settings.frame_limit.SetText(target_layer, std::to_string(fps));
  if (!result) {
    REXLOG_WARN("Could not apply N3 display presentation target: {}",
                result.error().GetDescription());
    return;
  }
  if (fps) {
    REXLOG_INFO("Display presentation limited to {} FPS; game timing remains at 30 FPS", fps);
  } else {
    REXLOG_INFO("Display presentation limit disabled; game timing remains at 30 FPS");
  }
}
}

void InstallGraphicsSettings(rex::gpu::GraphicsSettings& settings) {
  graphics_settings = &settings;
  frame_rate_watch.emplace(N3_SETTINGS().frame_rate.OnChange(
      [&settings](const rex::u32& fps) {
        ApplyPresentationRate(settings, fps, N3_SETTINGS().frame_rate.GetLayer());
      }));
  if (N3_SETTINGS().frame_rate.GetLayer() >= settings.frame_limit.GetLayer()) {
    ApplyPresentationRate(settings, ConfiguredFrameRate(),
                          N3_SETTINGS().frame_rate.GetLayer());
  }
}

void ShutdownGraphicsSettings() {
  frame_rate_watch.reset();
  graphics_settings = nullptr;
}

bool ApplyGraphicsChoice(uint32_t row, uint32_t index) {
  if (!graphics_settings) return false;
  constexpr std::array<uint32_t, 3> rates{30, 40, 60};
  constexpr std::array<uint32_t, 4> heights{720, 1080, 1440, 2160};
  if (row == 1 && index < rates.size()) return SetFrameRate(rates[index]);
  if (row == 2 && index < n3::graphics::kAnisotropicOverrides.size())
    return graphics_settings->anisotropic_override
        .Set(n3::graphics::kAnisotropicOverrides[index]).has_value();
  if (row == 3 && index < heights.size()) return SetDisplayHeight(heights[index]);
  if (row == 4 && index < 3) {
    const auto scale = static_cast<rex::i32>(index + 1);
    return graphics_settings->resolution_scale_x.Set(scale).has_value() &&
           graphics_settings->resolution_scale_y.Set(scale).has_value();
  }
  return row == 5 && index < 2 &&
         graphics_settings->vsync.Set(index != 0).has_value();
}

uint32_t ConfiguredAnisotropicChoice() {
  if (!graphics_settings) return 0;
  const auto current = graphics_settings->anisotropic_override.Get();
  const auto index = n3::graphics::AnisotropicChoiceIndex(current);
  const auto actual = n3::graphics::kAnisotropicOverrides[index];
  if (current != actual) (void)graphics_settings->anisotropic_override.Set(actual);
  return index;
}

uint32_t ConfiguredRenderScaleChoice() {
  if (!graphics_settings) return 0;
  const auto scale = std::max(graphics_settings->resolution_scale_x.Get(),
                              graphics_settings->resolution_scale_y.Get());
  return static_cast<uint32_t>(std::clamp(scale, 1, 3) - 1);
}

bool ConfiguredVSync() {
  return graphics_settings && graphics_settings->vsync.Get();
}
