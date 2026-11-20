#include "game_setup.h"
#include "game_data.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <commdlg.h>
#include <shlobj.h>
#include <rex/path_settings.h>

#include <atomic>
#include <exception>
#include <fstream>
#include <thread>

namespace fs = std::filesystem;
namespace {
bool Matches(const fs::path& folder) {
  try { n3::data::VerifyGameFolder(folder); return true; } catch (const std::exception&) { return false; }
}
fs::path ReadLink(const fs::path& filename) {
  std::ifstream in(filename, std::ios::binary);
  std::string line;
  std::getline(in, line);
  if (line.size() > 32768 || line.empty()) return {};
  return fs::path(std::u8string(reinterpret_cast<const char8_t*>(line.data()), line.size()));
}
void SaveLink(const fs::path& filename, const fs::path& folder) {
  fs::create_directories(filename.parent_path());
  const auto temp = fs::path(filename.wstring() + L".tmp");
  const auto utf8 = fs::absolute(folder).generic_u8string();
  {
    std::ofstream out(temp, std::ios::binary | std::ios::trunc);
    if (!out.write(reinterpret_cast<const char*>(utf8.data()), utf8.size())) throw std::runtime_error("Cannot remember the game folder");
    out.close();
    if (!out) throw std::runtime_error("Cannot finish saving the game folder link");
  }
  if (!MoveFileExW(temp.c_str(), filename.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
    throw std::runtime_error("Cannot save the game folder link");
  }
}
fs::path PickSource(HWND owner) {
  wchar_t filename[32768]{};
  OPENFILENAMEW picker{};
  picker.lStructSize = sizeof(picker);
  picker.hwndOwner = owner;
  picker.lpstrTitle = L"N3 Recompiled - Select your own disc image or extracted default.xex";
  picker.lpstrFilter = L"Xbox 360 disc image or executable\0*.iso;*.xex\0Disc image (*.iso)\0*.iso\0Executable (default.xex)\0*.xex\0\0";
  picker.lpstrFile = filename;
  picker.nMaxFile = static_cast<DWORD>(std::size(filename));
  picker.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
  if (GetOpenFileNameW(&picker)) return fs::path(filename);
  if (CommDlgExtendedError()) throw std::runtime_error("Cannot open the game selection dialog");
  return {};
}
class ImportProgress {
 public:
  explicit ImportProgress(HWND owner) {
    const auto initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (SUCCEEDED(initialized)) {
      initialized_ = true;
    } else if (initialized != RPC_E_CHANGED_MODE) {
      throw std::runtime_error("Cannot initialize the disc import progress window");
    }
    if (FAILED(CoCreateInstance(CLSID_ProgressDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&dialog_)))) {
      if (initialized_) {
        CoUninitialize();
        initialized_ = false;
      }
      throw std::runtime_error("Cannot create the disc import progress window");
    }
    dialog_->SetTitle(L"N3 Recompiled - Importing disc");
    dialog_->SetLine(1, L"Validating the disc and preparing the import...", FALSE, nullptr);
    dialog_->SetLine(2, L"Your original image will remain unchanged.", FALSE, nullptr);
    dialog_->SetCancelMsg(L"Cancelling import and removing partial files...", nullptr);
    dialog_->SetProgress64(0, 1);
    dialog_->StartProgressDialog(owner, nullptr,
                                 PROGDLG_MODAL | PROGDLG_AUTOTIME | PROGDLG_NOMINIMIZE, nullptr);
  }
  ~ImportProgress() {
    if (dialog_) { dialog_->StopProgressDialog(); dialog_->Release(); }
    if (initialized_) CoUninitialize();
  }
  void Import(const fs::path& source, const fs::path& folder) {
    std::atomic<uint64_t> done{0};
    std::atomic<uint64_t> total{0};
    std::atomic<bool> cancelled{false};
    std::atomic<bool> finished{false};
    std::exception_ptr failure;
    std::thread worker([&] {
      try {
        n3::data::ImportDisc(source, folder, [&](uint64_t next_done, uint64_t next_total) {
          total.store(next_total, std::memory_order_release);
          done.store(next_done, std::memory_order_release);
          return !cancelled.load(std::memory_order_acquire);
        });
      } catch (...) {
        failure = std::current_exception();
      }
      finished.store(true, std::memory_order_release);
    });

    bool copying = false;
    bool cancelling = false;
    while (!finished.load(std::memory_order_acquire)) {
      PumpMessages(cancelled);
      if (dialog_->HasUserCancelled()) cancelled.store(true, std::memory_order_release);
      const auto next_total = total.load(std::memory_order_acquire);
      if (next_total) {
        if (!copying) {
          dialog_->SetLine(1, L"Copying game data from your disc image...", FALSE, nullptr);
          copying = true;
        }
        dialog_->SetProgress64(done.load(std::memory_order_acquire), next_total);
      }
      if (cancelled.load(std::memory_order_acquire) && !cancelling) {
        dialog_->SetLine(1, L"Cancelling import and removing partial files...", FALSE, nullptr);
        cancelling = true;
      }
      if (!finished.load(std::memory_order_acquire)) {
        MsgWaitForMultipleObjectsEx(0, nullptr, 50, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
      }
    }
    worker.join();
    PumpMessages(cancelled);
    if (quit_requested_) PostQuitMessage(quit_code_);
    if (failure) std::rethrow_exception(failure);
  }
 private:
  void PumpMessages(std::atomic<bool>& cancelled) {
    MSG message{};
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
      if (message.message == WM_QUIT) {
        quit_requested_ = true;
        quit_code_ = static_cast<int>(message.wParam);
        cancelled.store(true, std::memory_order_release);
        continue;
      }
      TranslateMessage(&message);
      DispatchMessageW(&message);
    }
  }
  bool initialized_ = false;
  bool quit_requested_ = false;
  int quit_code_ = 0;
  IProgressDialog* dialog_ = nullptr;
};
fs::path NewImportFolder(const fs::path& root) {
  GUID guid{};
  if (FAILED(CoCreateGuid(&guid))) throw std::runtime_error("Cannot create an import identifier");
  wchar_t name[64]{};
  StringFromGUID2(guid, name, static_cast<int>(std::size(name)));
  return root / (std::wstring(L"game-data-") + name);
}
}  // namespace

void ConfigureGameDataPaths() {
  auto& paths = REX_PATHS();
  if (paths.user_root.GetLayer() == rex::SettingLayer::kDefault) {
    PWSTR local = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_CREATE, nullptr, &local)))
      throw std::runtime_error("Cannot locate the local application data folder");
    const auto user_root = fs::path(local) / "N3Recompiled";
    CoTaskMemFree(local);
    if (auto set = paths.user_root.Set(user_root); !set)
      throw std::runtime_error(set.error().GetDescription());
    if (paths.cache_root.GetLayer() == rex::SettingLayer::kDefault) {
      if (auto set = paths.cache_root.Set(user_root / "cache"); !set)
        throw std::runtime_error(set.error().GetDescription());
    }
  }
  fs::create_directories(paths.user_root.Get());
}

std::optional<fs::path> ResolveGameData(const fs::path& game_root,
                                        const fs::path& user_root,
                                        bool headless) {
  const auto link = user_root / "game-path.txt";
  if (!game_root.empty()) {
    n3::data::VerifyGameFolder(game_root);
    return game_root;
  }
  const auto remembered = ReadLink(link);
  if (!remembered.empty() && Matches(remembered)) return remembered;
  if (headless) throw std::runtime_error(
      "Matching game data is required; run once with a UI to choose your disc or extracted default.xex");
  for (;;) {
    try {
      const auto owner = GetActiveWindow();
      const auto source = PickSource(owner);
      if (source.empty()) return std::nullopt;
      fs::path folder;
      if (_wcsicmp(source.extension().c_str(), L".iso") == 0) {
        n3::data::DiscImage(source).VerifyExecutable();
        if (MessageBoxW(owner,
            L"Import game data from this disc image? About 5.8 GB of free space is required.\n\nThe original image will remain unchanged. You only need to import once.",
            L"N3 Recompiled - Import your disc", MB_OKCANCEL | MB_ICONINFORMATION) != IDOK) continue;
        folder = NewImportFolder(user_root);
        ImportProgress progress(owner);
        progress.Import(source, folder);
      } else {
        folder = source.parent_path();
        n3::data::VerifyGameFolder(folder);
      }
      SaveLink(link, folder);
      return folder;
    } catch (const std::exception& error) {
      MessageBoxA(GetActiveWindow(), error.what(), "N3 Recompiled - Game setup", MB_OK | MB_ICONERROR);
    }
  }
}
