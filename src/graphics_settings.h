#pragma once
#include <cstdint>

namespace rex::gpu { class GraphicsSettings; }

void InstallGraphicsSettings(rex::gpu::GraphicsSettings& settings);
void ShutdownGraphicsSettings();
bool ApplyGraphicsChoice(uint32_t row, uint32_t index);
uint32_t ConfiguredAnisotropicChoice();
uint32_t ConfiguredRenderScaleChoice();
bool ConfiguredVSync();
