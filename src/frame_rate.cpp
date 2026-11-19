#include "frame_rate.h"
#include "frame_rate_policy.h"
#include "frame_pacing_stats.h"
#include "guest_frame_clock.h"
#include "n3_settings.h"
#include <rex/ppc.h>
#include <rex/logging.h>
#include <rex/memory/utils.h>
#include <chrono>
#include <atomic>
#include <thread>
#include <rex/chrono/clock.h>

#ifdef N3_FRAME_RATE_TEST
extern thread_local bool n3_frame_rate_native_used;
#endif

namespace {
std::atomic<uint32_t> simulation_fps{n3::frames::kGameFramesPerSecond};
uint32_t Read32(uint8_t* base, uint32_t address) {
  return rex::memory::load_and_swap<uint32_t>(n3::guest::GuestHostAddress(base, address));
}
void Write32(uint8_t* base, uint32_t address, uint32_t value) {
  rex::memory::store_and_swap<uint32_t>(n3::guest::GuestHostAddress(base, address), value);
}
void TracePresent() {
  thread_local bool tracing = false;
  if (!N3_SETTINGS().frame_pacing_trace.Get()) {
    tracing = false;
    return;
  }
  thread_local n3::frames::PacingWindow intervals;
  thread_local auto start = std::chrono::steady_clock::now();
  thread_local std::chrono::steady_clock::time_point previous{};
  const auto now = std::chrono::steady_clock::now();
  if (!tracing) {
    intervals.Clear();
    start = now;
    previous = now;
    tracing = true;
    return;
  }
  intervals.Add(std::chrono::duration_cast<std::chrono::microseconds>(now - previous).count());
  previous = now;
  const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(now - start).count();
  if (elapsed >= 2000000) {
    const auto summary = intervals.Summarize();
    REXLOG_INFO(
        "N3 title frame pacing: native target {}, display target {} | {} intervals, "
        "{:.1f} fps | mean {:.2f} ms, p95 {:.2f} ms, p99 {:.2f} ms, max {:.2f} ms | "
        ">2x mean {}",
        simulation_fps.load(), ConfiguredFrameRate(), summary.samples,
        summary.frames_per_second, summary.mean_ms, summary.p95_ms,
        summary.p99_ms, summary.maximum_ms, summary.long_intervals);
    intervals.Clear();
    start = now;
  }
}
void PacePresent() {
  using Clock = std::chrono::steady_clock;
  thread_local uint32_t previous_target = 0;
  thread_local Clock::time_point deadline{};
  const auto target = simulation_fps.load();
  if (!target) { previous_target = 0; return; }
  const auto period = std::chrono::nanoseconds(1000000000 / target);
  auto now = Clock::now();
  if (previous_target != target) {
    previous_target = target;
    deadline = now + period;
    return;
  }
  if (now < deadline) std::this_thread::sleep_until(deadline);
  now = Clock::now();
  deadline += period;
  // Movies, loading and slow frames may present less often; never catch up in a burst.
  if (now > deadline) deadline = now + period;
}
}

// Strong definitions replace the generated weak entries for both direct and
// indirect calls; __imp__ always retains the original translated implementation.
extern "C" void __imp__sub_82248D38(PPCContext& ctx, uint8_t* base);
extern "C" void sub_82248D38(PPCContext& ctx, uint8_t* base) {
  const auto clock = ctx.r3.u32;
  // The initializer reserves 112 bytes and its frequency helper another 96.
  // Preserve all prologue aliases before reading a clock snapshot.
  const auto stack = ctx.r1.u32;
  if (!n3::guest::FitsLinearGuestRange(clock, 48) || stack < 208 ||
      !n3::guest::FitsLinearGuestRange(stack - 208, 208) ||
      !n3::guest::DisjointGuestHostRanges(clock, 48, stack - 208, 208))
    return __imp__sub_82248D38(ctx, base);
  const n3::guest::FrameClockView view(base, clock);
  auto state = view.Read();
  const auto original = state.frames_per_second;
  if (n3::frames::SupportsClock(original)) {
    state.frames_per_second = n3::frames::kGameFramesPerSecond;
    state.step_seconds_bits =
        n3::frames::StepSecondsBits(n3::frames::kGameFramesPerSecond);
    simulation_fps.store(n3::frames::kGameFramesPerSecond);
    // The pinned Xbox import returns a 32-bit frequency. Keep that behavior,
    // and keep audio/movie/global clock scaling untouched.
    const auto frequency = static_cast<uint32_t>(rex::Clock::GetGuestTickFrequency());
    if (n3::native::InitializeFrameClock(state, frequency,
                                         rex::Clock::QueryGuestTickCount())) {
      view.Write(state);
      view.Enable();
      REXLOG_DEBUG("Native frame clock initialized: {} FPS, {} ticks/second, {} ticks/frame",
                   state.frames_per_second, state.ticks_per_second, state.ticks_per_frame);
      // The original's final timebase helper returns success in r3. Other
      // caller-saved registers are unspecified; nonvolatile state is untouched.
      ctx.r3.u64 = 1;
      ctx.lr = uint32_t(ctx.lr);
#ifdef N3_FRAME_RATE_TEST
      n3_frame_rate_native_used = true;
#endif
      return;
    }
  }
  // Keep unrecognized clock modes on the original implementation.
  __imp__sub_82248D38(ctx, base);
}

extern "C" void __imp__sub_823AA3B0(PPCContext& ctx, uint8_t* base);
extern "C" void sub_823AA3B0(PPCContext& ctx, uint8_t* base) {
  const auto address = ctx.r3.u32 + n3::frames::kPresentIntervalOffset;
  if (!n3::guest::FitsLinearGuestRange(address, 4))
    return __imp__sub_823AA3B0(ctx, base);
  const auto original = Read32(base, address);
  const auto interval = n3::frames::PresentInterval(original, ConfiguredFrameRate());
  if (interval != original) Write32(base, address, interval);
  __imp__sub_823AA3B0(ctx, base);
  if (interval != original) Write32(base, address, original);
}

extern "C" void __imp__sub_823AA520(PPCContext& ctx, uint8_t* base);
extern "C" void sub_823AA520(PPCContext& ctx, uint8_t* base) {
  PacePresent();
  TracePresent();
  __imp__sub_823AA520(ctx, base);
}

void InitializeFrameRate() {
  auto target = N3_SETTINGS().frame_rate.Get();
  if (N3_SETTINGS().legacy_60fps.Get() &&
      N3_SETTINGS().frame_rate.GetLayer() == rex::SettingLayer::kDefault) {
    target = 60;
    (void)N3_SETTINGS().frame_rate.Set(60);
  }
  simulation_fps.store(n3::frames::kGameFramesPerSecond);
  REXLOG_INFO(
      "N3 display presentation target: {} FPS; game timing remains at 30 FPS",
      target);
}

uint32_t ConfiguredFrameRate() {
  const auto configured = N3_SETTINGS().frame_rate.Get();
  return n3::frames::SupportsPresentationRate(configured) ? configured : 60;
}

bool SetFrameRate(uint32_t fps) {
  if (!n3::frames::SupportsPresentationRate(fps)) return false;
  if (!N3_SETTINGS().frame_rate.Set(fps)) return false;
  (void)N3_SETTINGS().legacy_60fps.Set(false);
  return true;
}

void ApplyFrameRateAtBoundary(uint8_t* base) {
  (void)base;
}

extern "C" void __imp__sub_8223FE70(PPCContext& ctx, uint8_t* base);
extern "C" void sub_8223FE70(PPCContext& ctx, uint8_t* base) {
  ApplyFrameRateAtBoundary(base);
  __imp__sub_8223FE70(ctx, base);
}
