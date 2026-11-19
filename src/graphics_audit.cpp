#include "graphics_audit.h"
#include "graphics_settings.h"
#include "n3_settings.h"
#include <rex/logging.h>
#include <rex/ui/ui_system.h>
#include <thread>
#include <atomic>
#include <memory>
#include <array>

namespace {
std::jthread worker;
std::shared_ptr<std::atomic<bool>> alive;
}
void InstallGraphicsAudit(rex::ui::IUISystem& ui) {
  if (!N3_SETTINGS().graphics_audit.Get()) return;
  alive = std::make_shared<std::atomic<bool>>(true);
  worker = std::jthread([&ui, running = alive](std::stop_token stop) {
    // Let the initial movies finish before exercising the same setters as the
    // native menu. Probe profiles are isolated by the invoking test harness.
    constexpr std::array<std::array<uint32_t, 5>, 6> cases{{
      {0,0,0,0,1}, {1,1,1,1,0}, {2,2,2,2,1},
      {0,3,3,1,0}, {1,4,0,0,1}, {2,0,1,2,0}}};
    auto wait = [&stop](int ticks) {
      for (int tick = 0; tick < ticks && !stop.stop_requested(); ++tick)
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      return !stop.stop_requested();
    };
    if (!wait(180)) return;
    for (uint32_t step = 0; step < cases.size(); ++step) {
      const auto choices = cases[step];
      ui.PostTask([running, choices, step] {
        if (!running->load()) return;
        bool ok = true;
        for (uint32_t row = 1; row <= choices.size(); ++row)
          ok = ApplyGraphicsChoice(row, choices[row - 1]) && ok;
        REXLOG_INFO("Graphics audit step {} accepted {}", step, ok);
      });
      if (!wait(50)) return;
    }
    ui.PostTask([running] {
      if (running->load()) REXLOG_INFO("Graphics audit requests complete");
    });
  });
}
void ShutdownGraphicsAudit() {
  if (alive) alive->store(false);
  if (worker.joinable()) { worker.request_stop(); worker.join(); }
}
