#include <Windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>

#include "launcher_config.h"
#include "launcher_options.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <format>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

namespace fs = std::filesystem;
using n3::launcher::DefaultLauncherValues;
using n3::launcher::LauncherConfig;
using n3::launcher::LauncherOptions;
using n3::launcher::LauncherValues;
using n3::launcher::WindowMode;

constexpr wchar_t kWindowClass[] = L"N3RecompiledLauncher";
constexpr int kWindowWidth = 930;
constexpr int kWindowHeight = 720;

enum ControlId {
  kIdTab = 100,
  kIdResetPage,
  kIdSave,
  kIdPlay,
  kIdClose,
  kIdChangeGameData,
  kIdOpenInstallFolder,
  kIdBrowseVoice,
  kIdClearVoice,
};

std::wstring Wide(std::string_view text) {
  if (text.empty()) return {};
  const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                                         text.data(),
                                         static_cast<int>(text.size()), nullptr, 0);
  if (length <= 0) throw std::runtime_error("Invalid UTF-8 text");
  std::wstring result(static_cast<size_t>(length), L'\0');
  if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                          static_cast<int>(text.size()), result.data(), length) !=
      length) {
    throw std::runtime_error("Cannot convert UTF-8 text");
  }
  return result;
}

std::string Utf8(std::wstring_view text) {
  if (text.empty()) return {};
  const int length =
      WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(),
                          static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
  if (length <= 0) throw std::runtime_error("Invalid Unicode text");
  std::string result(static_cast<size_t>(length), '\0');
  if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(),
                          static_cast<int>(text.size()), result.data(), length,
                          nullptr, nullptr) != length) {
    throw std::runtime_error("Cannot convert Unicode text");
  }
  return result;
}

std::string PathText(const fs::path& path) {
  const auto text = path.generic_u8string();
  return std::string(reinterpret_cast<const char*>(text.data()), text.size());
}

fs::path PathFromUtf8(std::string_view text) {
  const auto* begin = reinterpret_cast<const char8_t*>(text.data());
  return fs::path(std::u8string(begin, begin + text.size()));
}

std::wstring ErrorText(const std::exception& error) {
  try {
    return Wide(error.what());
  } catch (...) {
    return L"An error occurred while processing launcher settings.";
  }
}

fs::path ExecutablePath() {
  std::wstring buffer(32768, L'\0');
  const DWORD length =
      GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
  if (length == 0 || length == buffer.size()) {
    throw std::runtime_error("Cannot locate the launcher executable");
  }
  buffer.resize(length);
  return fs::path(buffer);
}

fs::path UserRoot() {
  PWSTR local = nullptr;
  if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_CREATE, nullptr,
                                  &local))) {
    throw std::runtime_error("Cannot locate the local application data folder");
  }
  fs::path result = fs::path(local) / L"N3Recompiled";
  CoTaskMemFree(local);
  return result;
}

std::optional<fs::path> ReadRememberedGamePath(const fs::path& link) {
  if (!fs::exists(link)) return std::nullopt;
  std::ifstream in(link, std::ios::binary);
  std::string text((std::istreambuf_iterator<char>(in)),
                   std::istreambuf_iterator<char>{});
  if (!in.eof() && in.fail()) {
    throw std::runtime_error("Cannot read the selected game data location");
  }
  while (!text.empty() &&
         (text.back() == '\r' || text.back() == '\n' || text.back() == ' ' ||
          text.back() == '\t')) {
    text.pop_back();
  }
  if (text.empty()) return std::nullopt;
  return PathFromUtf8(text);
}

std::wstring GetWindowString(HWND control) {
  const int length = GetWindowTextLengthW(control);
  std::wstring text(static_cast<size_t>(length) + 1, L'\0');
  const int copied =
      GetWindowTextW(control, text.data(), static_cast<int>(text.size()));
  text.resize(static_cast<size_t>(std::max(copied, 0)));
  return text;
}

std::string Trim(std::string text) {
  const auto whitespace = [](unsigned char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
  };
  while (!text.empty() && whitespace(text.front())) text.erase(text.begin());
  while (!text.empty() && whitespace(text.back())) text.pop_back();
  return text;
}

int ParseInt(HWND edit, std::string_view label, int minimum, int maximum) {
  const std::string text = Trim(Utf8(GetWindowString(edit)));
  int value = 0;
  const auto [end, error] =
      std::from_chars(text.data(), text.data() + text.size(), value);
  if (error != std::errc{} || end != text.data() + text.size() ||
      value < minimum || value > maximum) {
    throw std::runtime_error(std::format(
        "{} must be a whole number between {} and {}", label, minimum, maximum));
  }
  return value;
}

double ParseDouble(HWND edit, std::string_view label, double minimum,
                   double maximum) {
  const std::string text = Trim(Utf8(GetWindowString(edit)));
  size_t used = 0;
  double value = 0.0;
  try {
    value = std::stod(text, &used);
  } catch (const std::exception&) {
    throw std::runtime_error(std::format("{} must be a number", label));
  }
  if (used != text.size() || !std::isfinite(value) || value < minimum ||
      value > maximum) {
    throw std::runtime_error(std::format(
        "{} must be between {} and {}", label, minimum, maximum));
  }
  return value;
}

bool IsChecked(HWND control) {
  return SendMessageW(control, BM_GETCHECK, 0, 0) == BST_CHECKED;
}

void SetChecked(HWND control, bool checked) {
  SendMessageW(control, BM_SETCHECK, checked ? BST_CHECKED : BST_UNCHECKED, 0);
}

using ComboOptions = std::vector<std::pair<std::wstring, std::string>>;

ComboOptions DigitalOptions() {
  return {
      {L"Disabled", "none"},
      {L"A", "a"},
      {L"B", "b"},
      {L"X", "x"},
      {L"Y", "y"},
      {L"Left shoulder", "left_shoulder"},
      {L"Right shoulder", "right_shoulder"},
      {L"Left stick press", "left_thumb"},
      {L"Right stick press", "right_thumb"},
      {L"D-pad up", "dpad_up"},
      {L"D-pad down", "dpad_down"},
      {L"D-pad left", "dpad_left"},
      {L"D-pad right", "dpad_right"},
      {L"Back", "back"},
      {L"Start", "start"},
      {L"Guide", "guide"},
  };
}

class LauncherWindow {
 public:
  LauncherWindow(HINSTANCE instance, fs::path executable, LauncherOptions options,
                 LauncherConfig config)
      : instance_(instance),
        executable_(std::move(executable)),
        install_directory_(executable_.parent_path()),
        options_(std::move(options)),
        config_path_(*options_.config_file),
        game_path_link_(*options_.user_root / L"game-path.txt"),
        config_(std::move(config)) {
    remembered_game_path_ = n3::launcher::SelectGameRoot(
        options_.game_root, ReadRememberedGamePath(game_path_link_));
    options_.game_root = remembered_game_path_;
  }

  HWND Create() {
    WNDCLASSEXW window_class{sizeof(window_class)};
    window_class.lpfnWndProc = &LauncherWindow::WindowProcedure;
    window_class.hInstance = instance_;
    window_class.hIcon =
        LoadIconW(instance_, MAKEINTRESOURCEW(101));
    window_class.hIconSm = window_class.hIcon;
    window_class.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    window_class.hbrBackground =
        reinterpret_cast<HBRUSH>(COLOR_BTNFACE + 1);
    window_class.lpszClassName = kWindowClass;
    if (!RegisterClassExW(&window_class) &&
        GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
      throw std::runtime_error("Cannot register the launcher window");
    }

    RECT bounds{0, 0, kWindowWidth, kWindowHeight};
    const DWORD style =
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    AdjustWindowRectEx(&bounds, style, FALSE, 0);
    hwnd_ = CreateWindowExW(
        0, kWindowClass, L"N3 Recompiled Launcher", style, CW_USEDEFAULT,
        CW_USEDEFAULT, bounds.right - bounds.left, bounds.bottom - bounds.top,
        nullptr, nullptr, instance_, this);
    if (!hwnd_) throw std::runtime_error("Cannot create the launcher window");
    return hwnd_;
  }

 private:
  static LRESULT CALLBACK WindowProcedure(HWND hwnd, UINT message, WPARAM wparam,
                                          LPARAM lparam) {
    LauncherWindow* self = reinterpret_cast<LauncherWindow*>(
        GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
      auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
      self = static_cast<LauncherWindow*>(create->lpCreateParams);
      self->hwnd_ = hwnd;
      SetWindowLongPtrW(hwnd, GWLP_USERDATA,
                        reinterpret_cast<LONG_PTR>(self));
    }
    if (!self) return DefWindowProcW(hwnd, message, wparam, lparam);
    try {
      return self->HandleMessage(message, wparam, lparam);
    } catch (const std::exception& error) {
      MessageBoxW(hwnd, ErrorText(error).c_str(), L"N3 Recompiled Launcher",
                  MB_OK | MB_ICONERROR);
      return message == WM_CREATE ? -1 : 0;
    } catch (...) {
      MessageBoxW(hwnd, L"An unexpected launcher error occurred.",
                  L"N3 Recompiled Launcher", MB_OK | MB_ICONERROR);
      return message == WM_CREATE ? -1 : 0;
    }
  }

  LRESULT HandleMessage(UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
      case WM_CREATE:
        CreateControls();
        return 0;
      case WM_COMMAND:
        HandleCommand(LOWORD(wparam), HIWORD(wparam));
        return 0;
      case WM_NOTIFY: {
        const auto* header = reinterpret_cast<NMHDR*>(lparam);
        if (header->idFrom == kIdTab && header->code == TCN_SELCHANGE) {
          ShowSelectedPage();
        }
        return 0;
      }
      case WM_CLOSE:
        DestroyWindow(hwnd_);
        return 0;
      case WM_DESTROY:
        if (font_owned_) DeleteObject(font_);
        PostQuitMessage(0);
        return 0;
      default:
        return DefWindowProcW(hwnd_, message, wparam, lparam);
    }
  }

  HWND CreateControl(const wchar_t* class_name, const wchar_t* text, DWORD style,
                     int x, int y, int width, int height, HWND parent,
                     int id = 0, DWORD extended_style = 0) {
    HWND control = CreateWindowExW(
        extended_style, class_name, text, WS_CHILD | WS_VISIBLE | style, x, y,
        width, height, parent, reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
        instance_, nullptr);
    if (!control) throw std::runtime_error("Cannot create a launcher control");
    SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font_), TRUE);
    return control;
  }

  HWND Label(HWND parent, const std::wstring& text, int x, int y, int width,
             int height = 22) {
    return CreateControl(L"STATIC", text.c_str(), SS_LEFT, x, y, width, height,
                         parent);
  }

  HWND Edit(HWND parent, std::wstring text, int x, int y, int width,
            bool read_only = false) {
    DWORD style = WS_TABSTOP | WS_BORDER | ES_AUTOHSCROLL;
    if (read_only) style |= ES_READONLY;
    return CreateControl(L"EDIT", text.c_str(), style, x, y, width, 24, parent,
                         0, WS_EX_CLIENTEDGE);
  }

  HWND CheckBox(HWND parent, const std::wstring& text, int x, int y, int width,
                bool checked) {
    HWND control = CreateControl(L"BUTTON", text.c_str(),
                                 WS_TABSTOP | BS_AUTOCHECKBOX, x, y, width, 24,
                                 parent);
    SetChecked(control, checked);
    return control;
  }

  HWND Button(HWND parent, const std::wstring& text, int x, int y, int width,
              int id, bool default_button = false) {
    return CreateControl(
        L"BUTTON", text.c_str(),
        WS_TABSTOP | (default_button ? BS_DEFPUSHBUTTON : BS_PUSHBUTTON), x, y,
        width, 30, parent, id);
  }

  HWND Combo(HWND parent, const ComboOptions& options, std::string_view selected,
             int x, int y, int width) {
    HWND combo = CreateControl(
        WC_COMBOBOXW, L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, x, y,
        width, 300, parent);
    auto& values = combo_values_[combo];
    for (const auto& [label, value] : options) {
      SendMessageW(combo, CB_ADDSTRING, 0,
                   reinterpret_cast<LPARAM>(label.c_str()));
      values.push_back(value);
    }
    SetComboValue(combo, selected);
    return combo;
  }

  void SetComboValue(HWND combo, std::string_view selected) {
    const auto found = combo_values_.find(combo);
    if (found == combo_values_.end()) {
      throw std::runtime_error("Launcher combo box is not registered");
    }
    const auto& values = found->second;
    const auto match = std::find(values.begin(), values.end(), selected);
    if (match == values.end()) {
      throw std::runtime_error(
          std::format("Configured value '{}' is not available", selected));
    }
    SendMessageW(combo, CB_SETCURSEL,
                 static_cast<WPARAM>(std::distance(values.begin(), match)), 0);
  }

  std::string ComboValue(HWND combo) const {
    const auto found = combo_values_.find(combo);
    const LRESULT selected = SendMessageW(combo, CB_GETCURSEL, 0, 0);
    if (found == combo_values_.end() || selected == CB_ERR ||
        static_cast<size_t>(selected) >= found->second.size()) {
      throw std::runtime_error("Choose a value for every launcher option");
    }
    return found->second[static_cast<size_t>(selected)];
  }

  HWND CreatePage() {
    return CreateControl(L"STATIC", L"", WS_CLIPCHILDREN, 30, 56, 870, 548,
                         hwnd_, 0, WS_EX_CONTROLPARENT);
  }

  void CreateControls() {
    NONCLIENTMETRICSW metrics{sizeof(metrics)};
    if (SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics,
                              0)) {
      font_ = CreateFontIndirectW(&metrics.lfMessageFont);
      font_owned_ = font_ != nullptr;
    }
    if (!font_) font_ = static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));

    tab_ = CreateControl(WC_TABCONTROLW, L"", WS_TABSTOP, 16, 14, 898, 604,
                         hwnd_, kIdTab);
    for (const wchar_t* name :
         {L"Play", L"Graphics", L"Language && Audio", L"Controller",
          L"Keyboard && Mouse"}) {
      TCITEMW item{};
      item.mask = TCIF_TEXT;
      item.pszText = const_cast<wchar_t*>(name);
      TabCtrl_InsertItem(tab_, TabCtrl_GetItemCount(tab_), &item);
    }

    pages_[0] = CreatePage();
    pages_[1] = CreatePage();
    pages_[2] = CreatePage();
    pages_[3] = CreatePage();
    pages_[4] = CreatePage();
    CreatePlayPage();
    CreateGraphicsPage();
    CreateLanguagePage();
    CreateControllerPage();
    CreateKeyboardPage();

    reset_button_ =
        Button(hwnd_, L"Reset page", 16, 632, 112, kIdResetPage);
    status_ = Label(hwnd_, L"", 145, 638, 430, 22);
    Button(hwnd_, L"Save", 585, 630, 95, kIdSave);
    Button(hwnd_, L"Play", 687, 630, 105, kIdPlay, true);
    Button(hwnd_, L"Close", 799, 630, 115, kIdClose);
    ShowSelectedPage();
  }

  void CreatePlayPage() {
    HWND page = pages_[0];
    Label(page, L"N3 Recompiled", 20, 18, 320, 28);
    Label(page,
          L"Configure the installed game here, then choose Play. Directly "
          L"starting n3.exe uses the same saved settings.",
          20, 54, 820, 38);

    Label(page, L"Settings file", 20, 112, 140);
    Edit(page, config_path_.wstring(), 170, 108, 650, true);

    Label(page, L"Selected game data", 20, 164, 140);
    game_data_text_ = Edit(page, CurrentGamePathText(), 170, 160, 650, true);
    Button(page, L"Change on next Play...", 170, 202, 190, kIdChangeGameData);
    Button(page, L"Open install folder", 372, 202, 170, kIdOpenInstallFolder);

    Label(page, L"In-game settings", 20, 278, 140);
    Label(page,
          L"Press F4 while the game is running to open ReXGlue's advanced "
          L"settings overlay. Changes saved there also use n3.toml.",
          170, 274, 650, 44);

    Label(page, L"Game data remains outside the installation folder. The "
                L"supported ISO is imported only when you select it in the "
                L"native game-data prompt.",
          20, 365, 800, 44);
  }

  void CreateGraphicsPage() {
    HWND page = pages_[1];
    int y = 20;
    Label(page, L"Display mode", 24, y + 4, 160);
    window_mode_ =
        Combo(page,
              {{L"Windowed", "windowed"},
               {L"Borderless fullscreen", "borderless"},
               {L"Exclusive fullscreen", "exclusive"}},
              config_.values.window_mode == WindowMode::kWindowed
                  ? "windowed"
                  : config_.values.window_mode == WindowMode::kBorderless
                        ? "borderless"
                        : "exclusive",
              190, y, 250);
    Label(page, L"Monitor", 474, y + 4, 100);
    monitor_ = Edit(page, std::to_wstring(config_.values.monitor), 595, y, 90);

    y += 46;
    Label(page, L"Window width", 24, y + 4, 160);
    window_width_ =
        Edit(page, std::to_wstring(config_.values.window_width), 190, y, 120);
    Label(page, L"Window height", 474, y + 4, 110);
    window_height_ =
        Edit(page, std::to_wstring(config_.values.window_height), 595, y, 120);

    y += 46;
    Label(page, L"Output resolution", 24, y + 4, 160);
    display_resolution_ =
        Combo(page,
              {{L"1280 x 720", "720"},
               {L"1920 x 1080", "1080"},
               {L"2560 x 1440", "1440"},
               {L"3840 x 2160", "2160"}},
              std::to_string(config_.values.display_resolution), 190, y, 250);
    Label(page, L"Presentation rate", 474, y + 4, 120);
    frame_rate_ =
        Combo(page,
              {{L"Original / uncapped", "0"},
               {L"30 FPS", "30"},
               {L"40 FPS", "40"},
               {L"60 FPS", "60"}},
              std::to_string(config_.values.frame_rate), 595, y, 190);

    y += 46;
    Label(page, L"Renderer", 24, y + 4, 160);
    renderer_ =
        Combo(page,
              {{L"Direct3D 12 (recommended)", "d3d12"},
               {L"Vulkan", "vulkan"}},
              config_.values.renderer, 190, y, 250);
    Label(page, L"Upscaling filter", 474, y + 4, 120);
    present_effect_ =
        Combo(page,
              {{L"AMD FSR 1", "fsr1"}, {L"Bilinear", "bilinear"}},
              config_.values.present_effect, 595, y, 190);

    y += 46;
    Label(page, L"Internal render scale", 24, y + 4, 160);
    ComboOptions scales;
    for (int scale = 1; scale <= 8; ++scale) {
      scales.emplace_back(std::to_wstring(scale) + L"x",
                          std::to_string(scale));
    }
    render_scale_ = Combo(page, scales,
                          std::to_string(config_.values.render_scale), 190, y,
                          250);
    Label(page, L"Anisotropic filtering", 474, y + 4, 120);
    anisotropic_ =
        Combo(page,
              {{L"Use game setting", "-1"},
               {L"Off", "0"},
               {L"1x", "1"},
               {L"2x", "2"},
               {L"4x", "3"},
               {L"8x", "4"},
               {L"16x", "5"}},
              std::to_string(config_.values.anisotropic), 595, y, 190);

    y += 52;
    vsync_ =
        CheckBox(page, L"Vertical synchronization", 190, y, 270,
                 config_.values.vsync);
    Label(page,
          L"Output resolution and render scale are separate: higher render "
          L"scales improve image quality but increase GPU load.",
          24, y + 58, 790, 42);
  }

  void CreateLanguagePage() {
    HWND page = pages_[2];
    Label(page, L"Text and subtitles", 24, 24, 180);
    text_language_ =
        Combo(page,
              {{L"English", "english"},
               {L"French", "french"},
               {L"German", "german"},
               {L"Italian", "italian"},
               {L"Spanish", "spanish"}},
              config_.values.text_language, 215, 20, 260);

    Label(page, L"Spoken audio", 24, 82, 180);
    CreateVoiceOptions();
    voice_directory_ =
        Combo(page, voice_options_, PathText(config_.values.voice_directory),
              215, 78, 475);
    Button(page, L"Browse...", 704, 76, 110, kIdBrowseVoice);
    Button(page, L"Disc default", 704, 112, 110, kIdClearVoice);
    Label(page,
          L"The supported USA/Europe disc contains English spoken audio. "
          L"Additional entries appear only when compatible SoundRes folders "
          L"are detected or selected.",
          215, 122, 475, 58);

    Label(page, L"Volume", 24, 224, 180);
    const int volume =
        static_cast<int>(std::lround(config_.values.audio_gain * 100.0));
    audio_gain_ = Edit(page, std::to_wstring(volume), 215, 220, 90);
    Label(page, L"% (0 to 400)", 314, 224, 140);
    audio_mute_ =
        CheckBox(page, L"Mute all audio", 215, 268, 220,
                 config_.values.audio_mute);
    audio_mute_unfocused_ =
        CheckBox(page, L"Mute when the game is not focused", 215, 304, 320,
                 config_.values.audio_mute_unfocused);
  }

  void CreateVoiceOptions() {
    voice_options_.clear();
    voice_options_.emplace_back(
        L"Disc default (English on the supported disc)", "");
    if (remembered_game_path_) {
      const fs::path sound = *remembered_game_path_ / L"data" / L"Sound";
      std::error_code ec;
      if (fs::is_directory(sound, ec)) {
        for (const auto& entry : fs::directory_iterator(sound, ec)) {
          if (ec || !entry.is_directory()) continue;
          const fs::path sound_res = entry.path() / L"SoundRes";
          if (!fs::is_directory(sound_res, ec)) continue;
          const std::wstring code = entry.path().filename().wstring();
          std::wstring language = code;
          if (_wcsicmp(code.c_str(), L"ENG") == 0) language = L"English";
          if (_wcsicmp(code.c_str(), L"FRA") == 0) language = L"French";
          if (_wcsicmp(code.c_str(), L"GER") == 0) language = L"German";
          if (_wcsicmp(code.c_str(), L"ITA") == 0) language = L"Italian";
          if (_wcsicmp(code.c_str(), L"SPA") == 0) language = L"Spanish";
          voice_options_.emplace_back(language + L" (" + code + L")",
                                      PathText(fs::absolute(sound_res)));
        }
      }
    }
    const std::string selected = PathText(config_.values.voice_directory);
    if (!selected.empty() &&
        std::none_of(voice_options_.begin(), voice_options_.end(),
                     [&](const auto& option) {
                       return option.second == selected;
                     })) {
      voice_options_.emplace_back(
          L"Custom: " + config_.values.voice_directory.wstring(), selected);
    }
  }

  void CreateControllerPage() {
    HWND page = pages_[3];
    Label(page, L"Input backend", 20, 20, 120);
    input_drivers_ =
        Combo(page,
              {{L"SDL 3 (recommended)", "sdl3"},
               {L"XInput", "xinput"},
               {L"SDL 3, then XInput", "sdl3,xinput"},
               {L"XInput, then SDL 3", "xinput,sdl3"}},
              config_.values.input_drivers, 145, 16, 230);
    vibration_ = CheckBox(page, L"Vibration", 405, 18, 130,
                          config_.values.vibration);
    guide_button_ = CheckBox(page, L"Pass Guide button to the game", 555, 18,
                             250, config_.values.guide_button);

    Label(page, L"Left deadzone", 20, 60, 120);
    left_deadzone_ =
        Edit(page, std::format(L"{:.2f}", config_.values.left_deadzone), 145,
             56, 90);
    Label(page, L"Right deadzone", 270, 60, 125);
    right_deadzone_ =
        Edit(page, std::format(L"{:.2f}", config_.values.right_deadzone), 405,
             56, 90);
    Label(page, L"Deadzone range: 0.00 to 1.00", 555, 60, 250);

    Label(page, L"Game control", 20, 104, 150);
    Label(page, L"Physical input", 145, 104, 210);
    Label(page, L"Game control", 445, 104, 150);
    Label(page, L"Physical input", 570, 104, 210);

    const ComboOptions digital = DigitalOptions();
    for (size_t index = 0;
         index < n3::launcher::kControllerButtonDefinitions.size(); ++index) {
      const bool second_column = index >= 8;
      const size_t row = second_column ? index - 8 : index;
      const int x = second_column ? 445 : 20;
      const int y = 132 + static_cast<int>(row) * 38;
      Label(page,
            Wide(n3::launcher::kControllerButtonDefinitions[index].label), x,
            y + 4, 120);
      controller_buttons_[index] =
          Combo(page, digital, config_.values.controller_buttons[index],
                x + 125, y, 230);
    }

    int y = 436;
    Label(page, L"Left trigger", 20, y + 4, 120);
    left_trigger_ =
        Combo(page,
              {{L"Disabled", "none"},
               {L"Left trigger", "left_trigger"},
               {L"Right trigger", "right_trigger"}},
              config_.values.left_trigger, 145, y, 230);
    Label(page, L"Right trigger", 445, y + 4, 120);
    right_trigger_ =
        Combo(page,
              {{L"Disabled", "none"},
               {L"Left trigger", "left_trigger"},
               {L"Right trigger", "right_trigger"}},
              config_.values.right_trigger, 570, y, 230);

    y += 40;
    Label(page, L"Left stick", 20, y + 4, 120);
    left_stick_ =
        Combo(page,
              {{L"Disabled", "none"},
               {L"Left stick", "left_stick"},
               {L"Right stick", "right_stick"}},
              config_.values.left_stick, 145, y, 230);
    Label(page, L"Right stick", 445, y + 4, 120);
    right_stick_ =
        Combo(page,
              {{L"Disabled", "none"},
               {L"Left stick", "left_stick"},
               {L"Right stick", "right_stick"}},
              config_.values.right_stick, 570, y, 230);

    invert_left_x_ =
        CheckBox(page, L"Invert left X", 20, 516, 130,
                 config_.values.invert_left_x);
    invert_left_y_ =
        CheckBox(page, L"Invert left Y", 155, 516, 130,
                 config_.values.invert_left_y);
    invert_right_x_ =
        CheckBox(page, L"Invert right X", 445, 516, 135,
                 config_.values.invert_right_x);
    invert_right_y_ =
        CheckBox(page, L"Invert right Y", 585, 516, 135,
                 config_.values.invert_right_y);
  }

  void CreateKeyboardPage() {
    HWND page = pages_[4];
    keyboard_mouse_mode_ =
        CheckBox(page, L"Keyboard and mouse act as a controller", 20, 14, 310,
                 config_.values.keyboard_mouse_mode);
    mouse_right_stick_ =
        CheckBox(page, L"Mouse moves the right stick", 350, 14, 240,
                 config_.values.mouse_right_stick);
    keyboard_passthrough_ =
        CheckBox(page, L"Also pass keys to the game", 610, 14, 220,
                 config_.values.keyboard_passthrough);
    Label(page, L"Mouse sensitivity", 20, 50, 140);
    mouse_sensitivity_ =
        Edit(page, std::format(L"{:.2f}", config_.values.mouse_sensitivity),
             165, 46, 90);
    Label(page,
          L"Enter comma-separated alternatives or modifier chords such as "
          L"Shift+Up. Leave a field empty to unbind it.",
          285, 50, 550, 42);

    for (size_t index = 0; index < n3::launcher::kBindingDefinitions.size();
         ++index) {
      const bool second_column = index >= 13;
      const size_t row = second_column ? index - 13 : index;
      const int x = second_column ? 445 : 20;
      const int y = 94 + static_cast<int>(row) * 34;
      Label(page, Wide(n3::launcher::kBindingDefinitions[index].label), x,
            y + 3, 145);
      keybindings_[index] =
          Edit(page, Wide(config_.values.keybindings[index]), x + 150, y, 245);
    }
  }

  void HandleCommand(int id, int notification) {
    if (notification != BN_CLICKED) return;
    switch (id) {
      case kIdResetPage:
        ResetSelectedPage();
        break;
      case kIdSave:
        SaveSettings();
        SetWindowTextW(status_, L"Settings saved.");
        break;
      case kIdPlay:
        SaveSettings();
        StartGame();
        break;
      case kIdClose:
        DestroyWindow(hwnd_);
        break;
      case kIdChangeGameData:
        reset_game_data_ = true;
        SetWindowTextW(game_data_text_,
                       L"The game will ask for a folder or supported ISO on Play.");
        SetWindowTextW(status_, L"Game-data selection will be reset on Play.");
        break;
      case kIdOpenInstallFolder:
        OpenFolder(install_directory_);
        break;
      case kIdBrowseVoice:
        BrowseForVoiceDirectory();
        break;
      case kIdClearVoice:
        SetComboValue(voice_directory_, "");
        break;
    }
  }

  void ShowSelectedPage() {
    const int selected = TabCtrl_GetCurSel(tab_);
    for (size_t index = 0; index < pages_.size(); ++index) {
      ShowWindow(pages_[index],
                 static_cast<int>(index) == selected ? SW_SHOW : SW_HIDE);
    }
    EnableWindow(reset_button_, selected != 0);
  }

  void ResetSelectedPage() {
    const int selected = TabCtrl_GetCurSel(tab_);
    const LauncherValues defaults = DefaultLauncherValues();
    if (selected == 1) {
      config_.values.window_mode = defaults.window_mode;
      config_.values.window_width = defaults.window_width;
      config_.values.window_height = defaults.window_height;
      config_.values.monitor = defaults.monitor;
      config_.values.frame_rate = defaults.frame_rate;
      config_.values.display_resolution = defaults.display_resolution;
      config_.values.renderer = defaults.renderer;
      config_.values.vsync = defaults.vsync;
      config_.values.render_scale = defaults.render_scale;
      config_.values.anisotropic = defaults.anisotropic;
      config_.values.present_effect = defaults.present_effect;
      PopulateGraphics();
    } else if (selected == 2) {
      config_.values.text_language = defaults.text_language;
      config_.values.voice_directory = defaults.voice_directory;
      config_.values.audio_mute = defaults.audio_mute;
      config_.values.audio_mute_unfocused = defaults.audio_mute_unfocused;
      config_.values.audio_gain = defaults.audio_gain;
      PopulateLanguage();
    } else if (selected == 3) {
      config_.values.input_drivers = defaults.input_drivers;
      config_.values.vibration = defaults.vibration;
      config_.values.guide_button = defaults.guide_button;
      config_.values.left_deadzone = defaults.left_deadzone;
      config_.values.right_deadzone = defaults.right_deadzone;
      config_.values.controller_buttons = defaults.controller_buttons;
      config_.values.left_trigger = defaults.left_trigger;
      config_.values.right_trigger = defaults.right_trigger;
      config_.values.left_stick = defaults.left_stick;
      config_.values.right_stick = defaults.right_stick;
      config_.values.invert_left_x = defaults.invert_left_x;
      config_.values.invert_left_y = defaults.invert_left_y;
      config_.values.invert_right_x = defaults.invert_right_x;
      config_.values.invert_right_y = defaults.invert_right_y;
      PopulateController();
    } else if (selected == 4) {
      config_.values.keyboard_mouse_mode = defaults.keyboard_mouse_mode;
      config_.values.mouse_right_stick = defaults.mouse_right_stick;
      config_.values.mouse_sensitivity = defaults.mouse_sensitivity;
      config_.values.keyboard_passthrough = defaults.keyboard_passthrough;
      config_.values.keybindings = defaults.keybindings;
      PopulateKeyboard();
    }
    SetWindowTextW(status_, L"Page reset. Choose Save or Play to keep it.");
  }

  void PopulateGraphics() {
    SetComboValue(window_mode_,
                  config_.values.window_mode == WindowMode::kWindowed
                      ? "windowed"
                      : config_.values.window_mode == WindowMode::kBorderless
                            ? "borderless"
                            : "exclusive");
    SetWindowTextW(window_width_,
                   std::to_wstring(config_.values.window_width).c_str());
    SetWindowTextW(window_height_,
                   std::to_wstring(config_.values.window_height).c_str());
    SetWindowTextW(monitor_, std::to_wstring(config_.values.monitor).c_str());
    SetComboValue(frame_rate_, std::to_string(config_.values.frame_rate));
    SetComboValue(display_resolution_,
                  std::to_string(config_.values.display_resolution));
    SetComboValue(renderer_, config_.values.renderer);
    SetComboValue(present_effect_, config_.values.present_effect);
    SetComboValue(render_scale_, std::to_string(config_.values.render_scale));
    SetComboValue(anisotropic_, std::to_string(config_.values.anisotropic));
    SetChecked(vsync_, config_.values.vsync);
  }

  void PopulateLanguage() {
    SetComboValue(text_language_, config_.values.text_language);
    SetComboValue(voice_directory_, PathText(config_.values.voice_directory));
    SetWindowTextW(audio_gain_,
                   std::to_wstring(static_cast<int>(
                       std::lround(config_.values.audio_gain * 100.0)))
                       .c_str());
    SetChecked(audio_mute_, config_.values.audio_mute);
    SetChecked(audio_mute_unfocused_, config_.values.audio_mute_unfocused);
  }

  void PopulateController() {
    SetComboValue(input_drivers_, config_.values.input_drivers);
    SetChecked(vibration_, config_.values.vibration);
    SetChecked(guide_button_, config_.values.guide_button);
    SetWindowTextW(left_deadzone_,
                   std::format(L"{:.2f}", config_.values.left_deadzone).c_str());
    SetWindowTextW(right_deadzone_,
                   std::format(L"{:.2f}", config_.values.right_deadzone).c_str());
    for (size_t index = 0; index < controller_buttons_.size(); ++index) {
      SetComboValue(controller_buttons_[index],
                    config_.values.controller_buttons[index]);
    }
    SetComboValue(left_trigger_, config_.values.left_trigger);
    SetComboValue(right_trigger_, config_.values.right_trigger);
    SetComboValue(left_stick_, config_.values.left_stick);
    SetComboValue(right_stick_, config_.values.right_stick);
    SetChecked(invert_left_x_, config_.values.invert_left_x);
    SetChecked(invert_left_y_, config_.values.invert_left_y);
    SetChecked(invert_right_x_, config_.values.invert_right_x);
    SetChecked(invert_right_y_, config_.values.invert_right_y);
  }

  void PopulateKeyboard() {
    SetChecked(keyboard_mouse_mode_, config_.values.keyboard_mouse_mode);
    SetChecked(mouse_right_stick_, config_.values.mouse_right_stick);
    SetChecked(keyboard_passthrough_, config_.values.keyboard_passthrough);
    SetWindowTextW(
        mouse_sensitivity_,
        std::format(L"{:.2f}", config_.values.mouse_sensitivity).c_str());
    for (size_t index = 0; index < keybindings_.size(); ++index) {
      SetWindowTextW(keybindings_[index],
                     Wide(config_.values.keybindings[index]).c_str());
    }
  }

  void GatherSettings() {
    auto& values = config_.values;
    const std::string mode = ComboValue(window_mode_);
    values.window_mode =
        mode == "windowed"   ? WindowMode::kWindowed
        : mode == "borderless" ? WindowMode::kBorderless
                               : WindowMode::kExclusive;
    values.window_width =
        ParseInt(window_width_, "Window width", 0, 16384);
    values.window_height =
        ParseInt(window_height_, "Window height", 0, 16384);
    values.monitor = ParseInt(monitor_, "Monitor", 0, 16);
    values.frame_rate = std::stoi(ComboValue(frame_rate_));
    values.display_resolution = std::stoi(ComboValue(display_resolution_));
    values.renderer = ComboValue(renderer_);
    values.present_effect = ComboValue(present_effect_);
    values.render_scale = std::stoi(ComboValue(render_scale_));
    values.anisotropic = std::stoi(ComboValue(anisotropic_));
    values.vsync = IsChecked(vsync_);

    values.text_language = ComboValue(text_language_);
    values.voice_directory = PathFromUtf8(ComboValue(voice_directory_));
    if (!values.voice_directory.empty() &&
        !fs::is_directory(values.voice_directory)) {
      throw std::runtime_error(
          "The selected spoken-audio SoundRes folder is unavailable");
    }
    values.audio_gain =
        static_cast<double>(ParseInt(audio_gain_, "Volume percent", 0, 400)) /
        100.0;
    values.audio_mute = IsChecked(audio_mute_);
    values.audio_mute_unfocused = IsChecked(audio_mute_unfocused_);

    values.input_drivers = ComboValue(input_drivers_);
    values.vibration = IsChecked(vibration_);
    values.guide_button = IsChecked(guide_button_);
    values.left_deadzone =
        ParseDouble(left_deadzone_, "Left stick deadzone", 0.0, 1.0);
    values.right_deadzone =
        ParseDouble(right_deadzone_, "Right stick deadzone", 0.0, 1.0);
    for (size_t index = 0; index < controller_buttons_.size(); ++index) {
      values.controller_buttons[index] =
          ComboValue(controller_buttons_[index]);
    }
    values.left_trigger = ComboValue(left_trigger_);
    values.right_trigger = ComboValue(right_trigger_);
    values.left_stick = ComboValue(left_stick_);
    values.right_stick = ComboValue(right_stick_);
    values.invert_left_x = IsChecked(invert_left_x_);
    values.invert_left_y = IsChecked(invert_left_y_);
    values.invert_right_x = IsChecked(invert_right_x_);
    values.invert_right_y = IsChecked(invert_right_y_);

    values.keyboard_mouse_mode = IsChecked(keyboard_mouse_mode_);
    values.mouse_right_stick = IsChecked(mouse_right_stick_);
    values.keyboard_passthrough = IsChecked(keyboard_passthrough_);
    values.mouse_sensitivity =
        ParseDouble(mouse_sensitivity_, "Mouse sensitivity", 0.01, 100.0);
    for (size_t index = 0; index < keybindings_.size(); ++index) {
      values.keybindings[index] =
          Trim(Utf8(GetWindowString(keybindings_[index])));
      if (values.keybindings[index].find_first_of("\r\n") != std::string::npos) {
        throw std::runtime_error("Key bindings must stay on one line");
      }
    }
  }

  void SaveSettings() {
    GatherSettings();
    config_.Save(config_path_);
  }

  void StartGame() {
    if (reset_game_data_) {
      std::error_code ec;
      fs::remove(game_path_link_, ec);
      if (ec) {
        throw std::filesystem::filesystem_error(
            "Cannot reset the selected game-data location", game_path_link_, ec);
      }
    }
    const fs::path game = install_directory_ / L"n3.exe";
    if (!fs::is_regular_file(game)) {
      throw std::runtime_error(
          "n3.exe is missing from the launcher installation folder");
    }
    const auto arguments =
        n3::launcher::RuntimeArguments(options_, reset_game_data_);
    std::wstring command_line =
        n3::launcher::BuildWindowsCommandLine(game, arguments);
    STARTUPINFOW startup{sizeof(startup)};
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(game.c_str(), command_line.data(), nullptr, nullptr,
                        FALSE, 0, nullptr, install_directory_.c_str(), &startup,
                        &process)) {
      throw std::filesystem::filesystem_error(
          "Cannot start n3.exe", game,
          std::error_code(GetLastError(), std::system_category()));
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    DestroyWindow(hwnd_);
  }

  void OpenFolder(const fs::path& path) {
    const auto result = reinterpret_cast<INT_PTR>(
        ShellExecuteW(hwnd_, L"open", path.c_str(), nullptr, nullptr, SW_SHOWNORMAL));
    if (result <= 32) {
      throw std::runtime_error("Windows could not open the installation folder");
    }
  }

  void BrowseForVoiceDirectory() {
    IFileDialog* dialog = nullptr;
    HRESULT result = CoCreateInstance(CLSID_FileOpenDialog, nullptr,
                                      CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog));
    if (FAILED(result)) {
      throw std::runtime_error("Cannot open the spoken-audio folder picker");
    }
    DWORD options = 0;
    result = dialog->GetOptions(&options);
    if (SUCCEEDED(result)) {
      result = dialog->SetOptions(options | FOS_PICKFOLDERS |
                                  FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
    }
    if (SUCCEEDED(result)) {
      result = dialog->SetTitle(L"Select a compatible SoundRes folder");
    }
    if (SUCCEEDED(result)) result = dialog->Show(hwnd_);
    if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
      dialog->Release();
      return;
    }
    if (FAILED(result)) {
      dialog->Release();
      throw std::runtime_error("The spoken-audio folder picker failed");
    }
    IShellItem* item = nullptr;
    result = dialog->GetResult(&item);
    dialog->Release();
    if (FAILED(result)) {
      throw std::runtime_error("Cannot read the selected spoken-audio folder");
    }
    PWSTR selected = nullptr;
    result = item->GetDisplayName(SIGDN_FILESYSPATH, &selected);
    item->Release();
    if (FAILED(result) || !selected) {
      throw std::runtime_error("Cannot resolve the selected spoken-audio folder");
    }
    const fs::path path(selected);
    CoTaskMemFree(selected);
    const std::string value = PathText(path);
    auto& values = combo_values_[voice_directory_];
    const auto found = std::find(values.begin(), values.end(), value);
    if (found == values.end()) {
      const std::wstring label = L"Custom: " + path.wstring();
      SendMessageW(voice_directory_, CB_ADDSTRING, 0,
                   reinterpret_cast<LPARAM>(label.c_str()));
      values.push_back(value);
    }
    SetComboValue(voice_directory_, value);
  }

  std::wstring CurrentGamePathText() const {
    if (reset_game_data_) {
      return L"The game will ask for a folder or supported ISO on Play.";
    }
    if (!remembered_game_path_) return L"Not selected yet";
    return remembered_game_path_->wstring();
  }

  HINSTANCE instance_ = nullptr;
  HWND hwnd_ = nullptr;
  HFONT font_ = nullptr;
  bool font_owned_ = false;
  fs::path executable_;
  fs::path install_directory_;
  LauncherOptions options_;
  fs::path config_path_;
  fs::path game_path_link_;
  LauncherConfig config_;
  std::optional<fs::path> remembered_game_path_;
  bool reset_game_data_ = false;

  HWND tab_ = nullptr;
  std::array<HWND, 5> pages_{};
  HWND reset_button_ = nullptr;
  HWND status_ = nullptr;
  HWND game_data_text_ = nullptr;
  std::unordered_map<HWND, std::vector<std::string>> combo_values_;

  HWND window_mode_ = nullptr;
  HWND window_width_ = nullptr;
  HWND window_height_ = nullptr;
  HWND monitor_ = nullptr;
  HWND frame_rate_ = nullptr;
  HWND display_resolution_ = nullptr;
  HWND renderer_ = nullptr;
  HWND vsync_ = nullptr;
  HWND render_scale_ = nullptr;
  HWND anisotropic_ = nullptr;
  HWND present_effect_ = nullptr;

  HWND text_language_ = nullptr;
  HWND voice_directory_ = nullptr;
  ComboOptions voice_options_;
  HWND audio_mute_ = nullptr;
  HWND audio_mute_unfocused_ = nullptr;
  HWND audio_gain_ = nullptr;

  HWND input_drivers_ = nullptr;
  HWND vibration_ = nullptr;
  HWND guide_button_ = nullptr;
  HWND left_deadzone_ = nullptr;
  HWND right_deadzone_ = nullptr;
  std::array<HWND, n3::launcher::kControllerButtonDefinitions.size()>
      controller_buttons_{};
  HWND left_trigger_ = nullptr;
  HWND right_trigger_ = nullptr;
  HWND left_stick_ = nullptr;
  HWND right_stick_ = nullptr;
  HWND invert_left_x_ = nullptr;
  HWND invert_left_y_ = nullptr;
  HWND invert_right_x_ = nullptr;
  HWND invert_right_y_ = nullptr;

  HWND keyboard_mouse_mode_ = nullptr;
  HWND mouse_right_stick_ = nullptr;
  HWND mouse_sensitivity_ = nullptr;
  HWND keyboard_passthrough_ = nullptr;
  std::array<HWND, n3::launcher::kBindingDefinitions.size()> keybindings_{};
};

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show_command) {
  try {
    const HRESULT initialized =
        CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    if (FAILED(initialized)) {
      throw std::runtime_error("Cannot initialize Windows dialogs");
    }
    INITCOMMONCONTROLSEX controls{sizeof(controls), ICC_TAB_CLASSES};
    if (!InitCommonControlsEx(&controls)) {
      CoUninitialize();
      throw std::runtime_error("Cannot initialize Windows controls");
    }
    const fs::path executable = ExecutablePath();
    int argument_count = 0;
    LPWSTR* raw_arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (!raw_arguments) {
      throw std::runtime_error("Cannot read launcher arguments");
    }
    std::vector<std::wstring> arguments;
    for (int index = 1; index < argument_count; ++index) {
      arguments.emplace_back(raw_arguments[index]);
    }
    LocalFree(raw_arguments);
    LauncherOptions options = n3::launcher::ParseLauncherOptions(arguments);
    if (!options.config_file) {
      options.config_file = executable.parent_path() / L"n3.toml";
    }
    if (!options.user_root) options.user_root = UserRoot();
    for (auto* path : {&options.config_file, &options.user_root,
                       &options.game_root, &options.cache_root,
                       &options.log_root}) {
      if (*path) **path = fs::absolute(**path).lexically_normal();
    }
    LauncherConfig config = LauncherConfig::Load(*options.config_file);
    LauncherWindow window(instance, executable, std::move(options),
                          std::move(config));
    HWND hwnd = window.Create();
    ShowWindow(hwnd, show_command);
    UpdateWindow(hwnd);
    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
      if (!IsDialogMessageW(hwnd, &message)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
      }
    }
    CoUninitialize();
    return static_cast<int>(message.wParam);
  } catch (const std::exception& error) {
    MessageBoxW(nullptr, ErrorText(error).c_str(), L"N3 Recompiled Launcher",
                MB_OK | MB_ICONERROR);
    return 1;
  } catch (...) {
    MessageBoxW(nullptr, L"An unexpected launcher error occurred.",
                L"N3 Recompiled Launcher", MB_OK | MB_ICONERROR);
    return 1;
  }
}
