#pragma once
#include <memory>
#include <rex/ui/ui_system.h>

std::unique_ptr<rex::ui::IDialog> CreateGraphicsNotification();
void NotifyGraphicsSaved(bool success);
