#include "graphics_settings.h"
#include "frame_rate.h"
#include "display_settings.h"
#include "graphics_filtering.h"
#include <rex/gpu/graphics_system.h>
#include <array>
#include <algorithm>

namespace {
rex::gpu::GraphicsSettings* graphics_settings = nullptr;
}

void InstallGraphicsSettings(rex::gpu::GraphicsSettings& settings) {
  graphics_settings = &settings;
}

void ShutdownGraphicsSettings() {
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
