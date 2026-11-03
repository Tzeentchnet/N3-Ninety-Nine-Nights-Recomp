#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace n3::animation_trace {
inline constexpr size_t kControllerCapacity = 256;
inline constexpr size_t kQueueCapacity = 64;
inline constexpr size_t kEvaluationCapacity = 64;
inline constexpr size_t kSerializedCapacity = 96 * 1024;
inline constexpr uint32_t kMaxClips = 4096;
inline constexpr uint32_t kMaxBones = 2048;

enum class Scope : uint8_t { actor, resource };

struct Filter {
  // Zero selects the first valid actor; -1 selects all clips.
  uint32_t actor = 0;
  int32_t clip = -1;
  Scope scope = Scope::actor;
};

bool ParseActor(std::string_view text, uint32_t& actor);
bool ParseClip(std::string_view text, int32_t& clip);
bool ParseScope(std::string_view text, Scope& scope);
bool MatchesActor(Filter filter, uint32_t actor);
bool MatchesClip(Filter filter, uint32_t clip);
bool FiniteFloatBits(uint32_t bits);
bool FiniteDoubleBits(uint64_t bits);
uint64_t BasenameFingerprint(const char* name, size_t length);

enum class StopReason : uint8_t {
  none,
  invalid_mapping,
  identity_changed,
  invalid_value,
  concurrent_actor,
  concurrent_shared_ba,
  reentrant,
  two_transitions,
  shutdown,
};

struct Identity {
  uint32_t actor = 0, actor_vtable = 0;
  uint32_t manager = 0, instance_handle = 0, instance = 0;
  uint32_t ba = 0, ba_handle = 0;
  uint32_t signal = 0, info = 0;
  uint32_t setup_signal_index = 0, setup_info_index = 0;
  uint32_t clips = 0, bones = 0, signal_groups = 0, info_rows = 0;
  uint32_t name_length = 0;
  uint64_t name_fingerprint = 0;
};

struct ControllerSample {
  uint32_t caller = 0, before_clip = 0, after_clip = 0;
  uint32_t before_time = 0, after_time = 0, step = 0;
};

struct QueueSample {
  uint32_t caller = 0, clip = 0;
  uint64_t frame = 0;
};

struct EvaluationSample {
  uint32_t caller = 0, clip = 0, time = 0, queue_count = 0;
  uint32_t pose_outputs = 0, invalid_outputs = 0;
};

struct Counters {
  uint64_t setup_calls = 0, setup_accepted = 0, resource_bindings = 0;
  uint64_t controller_calls = 0, queue_calls = 0, evaluation_calls = 0;
  uint64_t actor_filtered = 0, clip_filtered = 0, unselected = 0;
  uint64_t invalid = 0, reentrant = 0, concurrent = 0, after_stop = 0;
  uint64_t lock_dropped = 0, inflight_at_flush = 0;
  uint64_t controller_full = 0, queue_full = 0, evaluation_full = 0;
  uint64_t pose_outputs = 0, invalid_outputs = 0, transitions = 0;
};

struct Trace {
  Filter filter;
  Identity identity;
  Counters counters;
  StopReason stop = StopReason::none;
  bool selected = false, have_last_clip = false;
  uint32_t last_clip = 0;
  size_t controller_count = 0, queue_count = 0, evaluation_count = 0;
  std::array<ControllerSample, kControllerCapacity> controller{};
  std::array<QueueSample, kQueueCapacity> queue{};
  std::array<EvaluationSample, kEvaluationCapacity> evaluation{};

  bool AddController(const ControllerSample& sample);
  bool AddQueue(const QueueSample& sample);
  bool AddEvaluation(const EvaluationSample& sample);
  void Stop(StopReason reason);
};

// The output is all structural metadata; it never includes paths, names,
// matrices, signal payloads, or raw resource bytes. Failure leaves size zero.
bool Serialize(const Trace& trace, char* output, size_t capacity, size_t& size);
}  // namespace n3::animation_trace
