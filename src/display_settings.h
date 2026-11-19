#pragma once
#include <cstdint>
namespace rex::ui { class IUISystem; }
void InstallDisplaySettings(rex::ui::IUISystem& ui);
void ShutdownDisplaySettings();
uint32_t ConfiguredDisplayHeight();
bool SetDisplayHeight(uint32_t height);
void RecordDisplayOutputSize(uint32_t width, uint32_t height);
