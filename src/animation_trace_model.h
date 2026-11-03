#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace n3::animation_trace {
inline constexpr size_t kControllerCapacity = 256;
inline constexpr size_t kQueueCapacity = 64;
inline constexpr size_t kEvaluationCapacity = 64;
inline constexpr size_t kQuaternionCapacity = 128;
inline constexpr size_t kQuaternionPerEvaluationCapacity = 8;
inline constexpr size_t kUnsupportedVtableCapacity = 16;
inline constexpr size_t kSignalKindCount = 10;
inline constexpr size_t kSignalEventCapacity = 544;
inline constexpr size_t kSerializedCapacity = 512 * 1024;
inline constexpr size_t kAttachmentKindCount = 6;
inline constexpr size_t kAttachmentPerKindCapacity = 128;
inline constexpr size_t kAttachmentObservationCapacity =
    kAttachmentKindCount * kAttachmentPerKindCapacity;
inline constexpr uint64_t kAttachmentHashBudgetBytes = 1024ull * 1024 * 1024;
inline constexpr uint32_t kMaxClips = 4096;
inline constexpr uint32_t kMaxBones = 2048;
inline constexpr uint32_t kMaxArchiveSlots = 64;
inline constexpr uint32_t kMaxArchiveMembers = 4096;
inline constexpr uint32_t kMaxArchiveBytes = 128 * 1024 * 1024;
inline constexpr uint32_t kMaxMemberBytes = 32 * 1024 * 1024;

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

class Sha256 {
 public:
  void Update(const uint8_t* data, size_t size);
  std::array<uint8_t, 32> Finish();

 private:
  void Transform(const uint8_t* block);
  std::array<uint32_t, 8> state_{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  std::array<uint8_t, 64> buffer_{};
  uint64_t bytes_ = 0;
  size_t used_ = 0;
};

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
  untracked_lifetime,
  registry_full,
  counter_overflow,
  clock_failure,
  concurrent_probe,
};

struct SourceIdentity {
  bool resolved = false;
  uint32_t archive_slot = 0, member_index = 0, archive_size = 0, member_size = 0;
  uint64_t archive_generation = 0;
  std::array<uint8_t, 32> archive_digest{}, member_digest{};
  bool operator==(const SourceIdentity&) const = default;
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
  uint64_t actor_generation = 0, instance_generation = 0, ba_generation = 0;
  SourceIdentity source;
  bool operator==(const Identity&) const = default;
};

struct Event {
  uint64_t id = 0, parent = 0, begin = 0, end = 0;
};

struct ControllerSample {
  uint32_t caller = 0, before_clip = 0, after_clip = 0;
  uint32_t before_time = 0, after_time = 0, step = 0;
  Event event;
};

struct QueueSample {
  uint32_t caller = 0, clip = 0;
  uint64_t frame = 0;
  Event event;
};

struct EvaluationSample {
  uint32_t caller = 0, clip = 0, time = 0, queue_count = 0;
  uint32_t pose_outputs = 0, invalid_outputs = 0;
  Event event;
};

struct QuaternionSample {
  uint32_t caller = 0, bone = 0, factor = 0;
  std::array<uint32_t, 4> left{}, right{}, result{};
  Event event;
};

struct QuaternionCounts {
  uint64_t seen = 0, invalid_context = 0, invalid_input = 0, invalid_output = 0;
  uint64_t per_evaluation_full = 0, total_full = 0, parent_dropped = 0;
};

struct Counters {
  uint64_t setup_calls = 0, setup_accepted = 0, resource_bindings = 0;
  uint64_t controller_calls = 0, queue_calls = 0, evaluation_calls = 0;
  uint64_t actor_filtered = 0, clip_filtered = 0, unselected = 0;
  uint64_t invalid = 0, reentrant = 0, concurrent = 0, after_stop = 0;
  uint64_t lock_dropped = 0, inflight_at_flush = 0;
  uint64_t controller_full = 0, queue_full = 0, evaluation_full = 0;
  uint64_t pose_outputs = 0, invalid_outputs = 0, transitions = 0;
  uint64_t events_started = 0, events_abandoned = 0, events_inflight_at_flush = 0;
  uint64_t cache_hits = 0, cache_untracked = 0, registry_full = 0;
  uint64_t counter_saturated = 0;
};

struct DispatchCounts {
  struct VtableCount { uint32_t vtable = 0, getter = 0; uint64_t calls = 0; };
  std::array<uint64_t, 5> setup_wrapper_calls{};
  std::array<uint64_t, 9> setup_rejections{};
  std::array<VtableCount, kUnsupportedVtableCapacity> unsupported_vtables{};
  uint64_t vtable_full = 0, vtable_zero = 0, getter_unreadable = 0;
  uint64_t resource_calls = 0, flag_zero = 0, handle_minus_one = 0;
  uint64_t eligible = 0, unreadable = 0;
};

enum class SignalKind : uint8_t {
  ba_load, as_load, info_load, setup, request, selection, install, group, dispatch, effect
};

inline constexpr std::array<size_t, kSignalKindCount> kSignalCapacities{
    32, 64, 64, 64, 32, 64, 64, 32, 96, 32};

struct SignalSample {
  SignalKind kind = SignalKind::ba_load;
  Event event;
  SourceIdentity source;
  uint32_t caller = 0, actor = 0, actor_vtable = 0, instance = 0, ba = 0;
  uint32_t signal = 0, info = 0, instance_handle = 0, ba_handle = 0;
  uint32_t signal_index = 0, info_index = 0, setup_key4 = 0, setup_key88 = 0;
  uint64_t actor_generation = 0, instance_generation = 0, ba_generation = 0;
  uint64_t signal_generation = 0, info_generation = 0;
  int32_t requested_type = 0, requested_index = 0, requested_attribute = 0;
  int32_t selected_row = -1, installed_row = -1;
  int32_t row_type = 0, row_index = 0, row_attribute = 0;
  int32_t record_time = 0, record_bounded = 0;
  uint32_t group_index = 0, retained_index = 0, group_offset = 0;
  uint32_t table_offset = 0, record_offset = 0, record_kind = 0, record_words = 0;
  uint32_t actor_time = 0, actor_step_field = 0;
  uint32_t dispatch_path = 0, effect_kind = 0, changed_slots = 0;
  bool identity_bound = false, row_read = false, group_read = false, record_read = false;
  bool source_offset = false, time_read = false;
  bool loaded = false;
};

struct SignalCounts {
  std::array<uint64_t, kSignalKindCount> seen{}, full{}, unreadable{}, skipped{};
  uint64_t unresolved_sources = 0, record_map_full = 0, record_map_invalid = 0;
  uint64_t actor_registry_full = 0, asset_registry_full = 0;
};

enum class AttachmentKind : uint8_t {
  character_table, item_table, hero_table, descriptor, model, animation, other
};
enum class AttachmentOutcome : uint8_t {
  verified, no_resolver, read_failed, unreadable, mismatch, changed, unresolved, skipped, full
};
inline constexpr size_t kAttachmentOutcomeCount = 9;

struct AttachmentObservation {
  AttachmentKind kind = AttachmentKind::other;
  uint32_t read_caller = 0;
  SourceIdentity source;
  uint64_t first_sequence = 0, last_sequence = 0, count = 0;
};

struct AttachmentTrace {
  bool enabled = false;
  std::array<uint64_t, kAttachmentKindCount> seen{};
  std::array<std::array<uint64_t, kAttachmentOutcomeCount>, kAttachmentKindCount> outcomes{};
  uint64_t resolver_calls = 0, resolver_returns = 0, resolver_verified = 0;
  uint64_t hash_bytes = 0, hash_budget_full = 0;
  uint64_t request_unreadable = 0, reentrant = 0, concurrent = 0;
  uint64_t read_inflight_at_flush = 0, sequence_count = 0;
  size_t observation_count = 0;
  std::array<AttachmentObservation, kAttachmentObservationCapacity> observations{};
};

AttachmentKind ClassifyAttachmentRequest(std::string_view request);
bool AddAttachmentObservation(AttachmentTrace& trace, AttachmentKind kind, uint32_t read_caller,
                              uint64_t sequence, const SourceIdentity& source);
bool SerializeAttachment(const AttachmentTrace& trace, StopReason stop, char* output,
                         size_t capacity, size_t& size);

struct Trace {
  Filter filter;
  Identity identity;
  Counters counters;
  DispatchCounts dispatch;
  bool quaternion_enabled = false;
  QuaternionCounts quaternion_counts;
  bool signal_enabled = false;
  SignalCounts signal_counts;
  AttachmentTrace attachment;
  std::array<size_t, kSignalKindCount> signal_recorded{}, signal_inflight{};
  size_t signal_count = 0;
  std::array<SignalSample, kSignalEventCapacity> signal_samples{};
  StopReason stop = StopReason::none;
  bool selected = false, have_last_clip = false;
  uint32_t last_clip = 0;
  uint64_t clock_frequency = 0, last_generation = 0, last_event = 0;
  size_t controller_count = 0, queue_count = 0, evaluation_count = 0;
  size_t quaternion_count = 0;
  std::array<ControllerSample, kControllerCapacity> controller{};
  std::array<QueueSample, kQueueCapacity> queue{};
  std::array<EvaluationSample, kEvaluationCapacity> evaluation{};
  std::array<QuaternionSample, kQuaternionCapacity> quaternion{};

  bool AddController(const ControllerSample& sample);
  bool AddQueue(const QueueSample& sample);
  bool AddEvaluation(const EvaluationSample& sample);
  bool Count(uint64_t& counter, uint64_t amount = 1);
  uint64_t NextGeneration();
  bool BeginEvent(Event& event, uint64_t parent, uint64_t tick);
  void AbandonEvent();
  void Stop(StopReason reason);
};

// The optional quaternion probe includes private decoded runtime values.
// Paths, names, matrices, signal payloads and raw resource bytes are never emitted.
bool Serialize(const Trace& trace, char* output, size_t capacity, size_t& size);
bool SerializeDrainTimeout(uint32_t inflight, char* output, size_t capacity, size_t& size);
}  // namespace n3::animation_trace
