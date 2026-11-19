#include "app_icon.h"

#include <rex/platform/native_window.h>
#include <rex/ui/ui_system.h>

#ifdef _WIN32
#include <Windows.h>
#endif

void ApplyAppIcon(rex::ui::IUISystem& ui) {
#ifdef _WIN32
  const auto native = ui.GetNativeWindow();
  if (!native || native->type != rex::NativeWindow::Type::kWin32) return;
  const auto hwnd = static_cast<HWND>(native->window);
  const auto module = GetModuleHandleW(nullptr);
  // Resource-loaded shared icons remain valid for the lifetime of the module.
  const auto small_icon = LoadImageW(module, MAKEINTRESOURCEW(101), IMAGE_ICON,
                               GetSystemMetrics(SM_CXSMICON),
                               GetSystemMetrics(SM_CYSMICON), LR_SHARED);
  const auto large_icon = LoadImageW(module, MAKEINTRESOURCEW(101), IMAGE_ICON,
                               GetSystemMetrics(SM_CXICON),
                               GetSystemMetrics(SM_CYICON), LR_SHARED);
  if (hwnd && small_icon)
    SendMessageW(hwnd, WM_SETICON, ICON_SMALL, reinterpret_cast<LPARAM>(small_icon));
  if (hwnd && large_icon)
    SendMessageW(hwnd, WM_SETICON, ICON_BIG, reinterpret_cast<LPARAM>(large_icon));
#endif
}
