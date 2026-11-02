#include "frame_pacing_stats.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

bool Near(double first, double second) {
  return std::abs(first - second) < 0.000001;
}

}  // namespace

int main() {
  try {
    n3::frames::PacingWindow empty;
    Require(empty.Summarize().samples == 0, "Empty window produced samples");

    n3::frames::PacingWindow steady;
    for (int i = 0; i < 120; ++i) steady.Add(16667);
    const auto steady_summary = steady.Summarize();
    Require(steady_summary.samples == 120 &&
                std::abs(steady_summary.frames_per_second - 60.0) < 0.01 &&
                Near(steady_summary.p95_ms, 16.667) &&
                Near(steady_summary.maximum_ms, 16.667) &&
                steady_summary.long_intervals == 0,
            "Steady 60 FPS statistics are incorrect");

    n3::frames::PacingWindow hitch;
    for (int i = 0; i < 98; ++i) hitch.Add(16667);
    hitch.Add(100000);
    hitch.Add(100000);
    const auto hitch_summary = hitch.Summarize();
    Require(hitch_summary.long_intervals == 2 &&
                Near(hitch_summary.p95_ms, 16.667) &&
                Near(hitch_summary.p99_ms, 100.0) &&
                Near(hitch_summary.maximum_ms, 100.0),
            "Hitch percentiles are incorrect");

    n3::frames::PacingWindow unordered;
    for (const auto value : {30000, 10000, 20000, 0, -1}) unordered.Add(value);
    const auto unordered_summary = unordered.Summarize();
    Require(unordered_summary.samples == 3 &&
                Near(unordered_summary.mean_ms, 20.0) &&
                Near(unordered_summary.p95_ms, 30.0),
            "Window did not sort intervals or reject invalid samples");
    unordered.Clear();
    Require(unordered.Summarize().samples == 0, "Clear retained pacing samples");
    std::cout << "Frame-pacing statistics passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
