#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace n3::frames {

struct PacingSummary {
  std::size_t samples = 0;
  double frames_per_second = 0;
  double mean_ms = 0;
  double p95_ms = 0;
  double p99_ms = 0;
  double maximum_ms = 0;
  std::size_t long_intervals = 0;
};

class PacingWindow {
 public:
  void Add(int64_t microseconds) {
    if (microseconds > 0) intervals_.push_back(microseconds);
  }

  void Clear() { intervals_.clear(); }

  PacingSummary Summarize() const {
    PacingSummary summary;
    summary.samples = intervals_.size();
    if (intervals_.empty()) return summary;

    auto sorted = intervals_;
    std::sort(sorted.begin(), sorted.end());
    long double total = 0;
    for (const auto interval : sorted) total += interval;
    const double mean_us = static_cast<double>(total / sorted.size());
    summary.frames_per_second = 1'000'000.0 / mean_us;
    summary.mean_ms = mean_us / 1000.0;
    summary.p95_ms = Percentile(sorted, 95) / 1000.0;
    summary.p99_ms = Percentile(sorted, 99) / 1000.0;
    summary.maximum_ms = sorted.back() / 1000.0;
    for (const auto interval : sorted)
      if (interval > mean_us * 2) ++summary.long_intervals;
    return summary;
  }

 private:
  static double Percentile(const std::vector<int64_t>& sorted, std::size_t percentile) {
    const auto rank = std::max<std::size_t>(
        1, (sorted.size() * percentile + 99) / 100);
    return static_cast<double>(sorted[rank - 1]);
  }

  std::vector<int64_t> intervals_;
};

}  // namespace n3::frames
