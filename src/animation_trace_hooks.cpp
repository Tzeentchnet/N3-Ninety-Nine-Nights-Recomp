#include "animation_trace.h"
#include "animation_trace_model.h"
#include "game_data.h"
#include "guest_memory_address.h"

#include <Windows.h>
#include <rex/logging.h>
#include <rex/ppc.h>
#include <xmmintrin.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cfenv>
#include <climits>
#include <cerrno>
#include <cstring>
#include <limits>
#include <memory>

namespace {
using namespace n3::animation_trace;
constexpr uint32_t kManagerGlobal = 0x825e12f0;
constexpr uint32_t kSignalVector = 0x82b4814c;
constexpr uint32_t kInfoVector = 0x82b4815c;
constexpr uint32_t kInstanceVtable = 0x82051f88;
constexpr uint32_t kBaVtable = 0x82051f14;
constexpr uint32_t kStepGetter = 0x82080068;
constexpr uint32_t kPoseReturn = 0x8229ad64;

Trace trace;
std::filesystem::path output_path;
std::filesystem::path attachment_output_path;
std::filesystem::path timeout_output_path;
std::atomic<bool> enabled{false}, trace_open{false};
std::atomic<bool> resource_scope{false};
std::atomic_flag trace_lock = ATOMIC_FLAG_INIT;
std::atomic<uint32_t> selected_actor{0}, selected_manager{0}, selected_handle{0};
std::atomic<uint32_t> selected_instance{0}, selected_ba{0};
constexpr uint32_t kAdmissionClosed = 1u << 31;
constexpr uint32_t kFlightCountMask = kAdmissionClosed - 1;
std::atomic<uint32_t> inflight{0}, active_controllers{0}, active_ba_evaluations{0};
std::atomic<uint32_t> active_associations{0}, active_resolvers{0}, active_archive_changes{0};
std::atomic<StopReason> abort_reason{StopReason::none};
std::atomic<uint64_t> setup_calls{0}, controller_calls{0}, queue_calls{0}, evaluation_calls{0};
std::atomic<uint64_t> actor_filtered{0}, unselected{0}, invalid{0}, reentrant{0};
std::atomic<uint64_t> concurrent{0}, after_stop{0}, lock_dropped{0};
std::atomic<uint64_t> pose_outputs{0}, invalid_outputs{0};
std::atomic<uint64_t> abandoned_unlocked{0};
std::array<std::atomic<uint64_t>, 5> setup_wrapper_calls{};
std::array<std::atomic<uint64_t>, 9> setup_rejections{};
struct AtomicVtableCount { std::atomic<uint64_t> key{0}, calls{0}; };
std::array<AtomicVtableCount, kUnsupportedVtableCapacity> unsupported_vtables{};
std::atomic<uint64_t> vtable_full{0}, vtable_zero{0}, getter_unreadable{0};
std::atomic<uint64_t> dispatch_calls{0}, dispatch_flag_zero{0}, dispatch_handle_minus_one{0};
std::atomic<uint64_t> dispatch_eligible{0}, dispatch_unreadable{0};
std::atomic<bool> quaternion_enabled{false};
std::atomic<bool> signal_enabled{false};
std::atomic<bool> attachment_enabled{false};
std::atomic<uint64_t> quaternion_seen{0}, quaternion_invalid_context{0};
std::atomic<uint64_t> quaternion_invalid_input{0}, quaternion_invalid_output{0};
std::atomic<uint64_t> quaternion_per_evaluation_full{0}, quaternion_total_full{0};
std::atomic<uint64_t> quaternion_parent_dropped{0};
std::atomic<bool> counter_saturated{false};
std::array<std::atomic<uint64_t>, kSignalKindCount> signal_seen{}, signal_full{};
std::array<std::atomic<uint64_t>, kSignalKindCount> signal_unreadable{}, signal_skipped{};
std::atomic<uint64_t> signal_unresolved_sources{0}, signal_record_map_full{0};
std::atomic<uint64_t> signal_record_map_invalid{0}, signal_actor_registry_full{0};
std::atomic<uint64_t> signal_asset_registry_full{0};
#ifdef N3_ANIMATION_TRACE_TEST
std::atomic<bool> pause_invalid_output_for_test{false}, invalid_output_paused_for_test{false};
#endif
std::array<std::atomic<uint64_t>, kAttachmentKindCount> attachment_seen{};
std::array<std::array<std::atomic<uint64_t>, kAttachmentOutcomeCount>,
           kAttachmentKindCount> attachment_outcomes{};
std::atomic<uint64_t> attachment_sequence{0}, attachment_resolver_calls{0};
std::atomic<uint64_t> attachment_resolver_returns{0}, attachment_resolver_verified{0};
std::atomic<uint64_t> attachment_request_unreadable{0}, attachment_reentrant{0};
std::atomic<uint64_t> attachment_concurrent{0};
std::atomic<uint64_t> attachment_budget_full{0};
std::atomic<uint32_t> active_attachment_reads{0};

struct ArchiveRecord {
  uint32_t address = 0, size = 0;
  uint64_t generation = 0;
};
struct BaRecord {
  uint32_t manager = 0, address = 0;
  uint64_t generation = 0;
  SourceIdentity source;
};
struct InstanceRecord {
  uint32_t address = 0;
  uint64_t generation = 0;
};
std::array<ArchiveRecord, kMaxArchiveSlots> archives{};
std::array<BaRecord, 1000> ba_records{};
std::array<InstanceRecord, 1024> instances{};

struct SignalAssetRecord {
  uint32_t address = 0;
  uint64_t generation = 0;
  SignalKind kind = SignalKind::as_load;
  SourceIdentity source;
};
struct SignalActorRecord {
  SignalSample identity;
};
struct SignalRecordBinding {
  uint32_t signal = 0, address = 0, group = 0, retained = 0;
  uint32_t group_offset = 0, table_offset = 0, record_offset = 0;
  uint32_t kind = 0, words = 0;
  int32_t time = 0, bounded = 0;
  uint64_t generation = 0;
};
std::array<SignalAssetRecord, 256> signal_assets{};
std::array<SignalActorRecord, 1024> signal_actors{};
std::array<SignalRecordBinding, 16384> signal_records{};
size_t signal_record_count = 0;

struct LoadScope {
  SourceIdentity source;
  uint32_t decoded_ba = 0, read_address = 0, read_size = 0;
  bool resolved = false, read = false, decoded = false;
};
thread_local LoadScope* load_scope = nullptr;
struct SignalLoadScope {
  SignalKind kind = SignalKind::as_load;
  uint32_t object = 0, read_address = 0, read_size = 0, group = 0;
  uint64_t generation = 0;
  SourceIdentity source;
  bool resolved = false, read = false;
};
thread_local SignalLoadScope* signal_load_scope = nullptr;
struct AttachmentReadScope {
  AttachmentKind kind = AttachmentKind::other;
  std::array<char, 260> request{};
  uint32_t request_address = 0, address_output = 0, size_output = 0, read_caller = 0;
  uint32_t manager = 0, archive = 0;
  uint64_t sequence = 0;
  SourceIdentity source;
  bool resolver_seen = false, resolved = false, ambiguous = false, budget_exhausted = false;
};
thread_local AttachmentReadScope* attachment_read_scope = nullptr;
thread_local bool in_signal_read = false;
thread_local Event* current_event = nullptr;
thread_local SignalSample* signal_request_scope = nullptr;
thread_local SignalSample* signal_group_scope = nullptr;
thread_local SignalSample* signal_dispatch_scope = nullptr;
thread_local uint32_t flight_depth = 0;
thread_local unsigned association_depth = 0;
thread_local bool in_controller = false, in_queue = false, in_evaluation = false, in_ba_read = false;
thread_local uint32_t lifecycle_bits = 0;
constexpr uint32_t kSetupActive = 1u << 0, kCollectActive = 1u << 1, kCreateActive = 1u << 2;
constexpr uint32_t kSubmitActive = 1u << 3, kRemoveDirectActive = 1u << 4;
constexpr uint32_t kResetActive = 1u << 5, kManagerDestroyActive = 1u << 6;

struct PoseScope {
  uint32_t instance, ba, bones, outputs = 0, invalid = 0;
  size_t quaternion_count = 0;
  std::array<QuaternionSample, kQuaternionPerEvaluationCapacity> quaternion{};
};
thread_local PoseScope* pose_scope = nullptr;

// Probe helpers must not leak CRT/Win32 or host FP status into translated code.
class HostState {
 public:
  HostState() noexcept : csr_(_mm_getcsr()), error_(GetLastError()), errno_(errno) {
    have_env_ = std::fegetenv(&environment_) == 0;
  }
  ~HostState() {
    if (have_env_) std::fesetenv(&environment_);
    _mm_setcsr(csr_);
    errno = errno_;
    SetLastError(error_);
  }
 private:
  uint32_t csr_;
  DWORD error_;
  int errno_;
  std::fenv_t environment_{};
  bool have_env_ = false;
};

void Abort(StopReason reason) noexcept;

bool IncrementActive(std::atomic<uint32_t>& counter, uint32_t& previous) noexcept {
  previous = counter.load(std::memory_order_relaxed);
  while (previous != UINT32_MAX) {
    if (counter.compare_exchange_weak(previous, previous + 1, std::memory_order_acq_rel))
      return true;
  }
  counter_saturated.store(true, std::memory_order_relaxed);
  Abort(StopReason::counter_overflow);
  return false;
}

class Flight {
 public:
  Flight() noexcept {
    if (!flight_depth && !enabled.load(std::memory_order_acquire)) return;
    auto state = inflight.load(std::memory_order_acquire);
    while (true) {
      if (!flight_depth && (state & kAdmissionClosed)) return;
      if ((state & kFlightCountMask) == kFlightCountMask || flight_depth == UINT32_MAX) {
        counter_saturated.store(true, std::memory_order_relaxed);
        Abort(StopReason::counter_overflow);
        return;
      }
      if (inflight.compare_exchange_weak(state, state + 1, std::memory_order_acq_rel,
                                         std::memory_order_acquire)) break;
    }
    ++flight_depth;
    active_ = true;
  }
  ~Flight() {
    if (active_) {
      --flight_depth;
      inflight.fetch_sub(1, std::memory_order_release);
    }
  }
  explicit operator bool() const { return active_; }
 private:
  bool active_ = false;
};

bool CanObserve() noexcept {
  return flight_depth || enabled.load(std::memory_order_acquire);
}

uint32_t FlightsInProgress() noexcept {
  return inflight.load(std::memory_order_acquire) & kFlightCountMask;
}

bool SelectedSignalActor(uint32_t actor) noexcept {
  const auto selected = selected_actor.load(std::memory_order_acquire);
  return selected && actor == selected;
}

void Abort(StopReason reason) noexcept {
  auto expected = StopReason::none;
  abort_reason.compare_exchange_strong(expected, reason);
}

void Count(std::atomic<uint64_t>& counter) noexcept {
  auto value = counter.load(std::memory_order_relaxed);
  while (value != UINT64_MAX) {
    if (counter.compare_exchange_weak(value, value + 1, std::memory_order_acq_rel,
                                      std::memory_order_relaxed)) return;
  }
  counter_saturated.store(true, std::memory_order_relaxed);
  Abort(StopReason::counter_overflow);
}

bool Next(std::atomic<uint64_t>& counter, uint64_t& result) noexcept {
  auto value = counter.load(std::memory_order_relaxed);
  while (value != UINT64_MAX) {
    if (counter.compare_exchange_weak(value, value + 1, std::memory_order_relaxed)) {
      result = value + 1;
      return true;
    }
  }
  counter_saturated.store(true, std::memory_order_relaxed);
  Abort(StopReason::counter_overflow);
  return false;
}

void AttachmentResult(AttachmentKind kind, AttachmentOutcome result) noexcept {
  Count(attachment_outcomes[size_t(kind)][size_t(result)]);
}

class LifecycleScope {
 public:
  explicit LifecycleScope(uint32_t bit) noexcept : bit_(bit) {
    if (lifecycle_bits & bit) {
      Count(reentrant);
      Abort(StopReason::reentrant);
    } else {
      lifecycle_bits |= bit;
      entered_ = true;
    }
  }
  ~LifecycleScope() { if (entered_) lifecycle_bits &= ~bit_; }
  explicit operator bool() const { return entered_; }
 private:
  uint32_t bit_;
  bool entered_ = false;
};

class Association {
 public:
  Association() noexcept {
    if (association_depth == UINT_MAX) {
      counter_saturated = true;
      Abort(StopReason::counter_overflow);
      return;
    }
    if (!association_depth) {
      uint32_t previous = 0;
      if (!IncrementActive(active_associations, previous)) return;
      if (previous) { Count(concurrent); Abort(StopReason::concurrent_actor); }
    }
    ++association_depth;
    entered_ = true;
  }
  ~Association() {
    if (entered_ && !--association_depth) active_associations.fetch_sub(1);
  }
 private:
  bool entered_ = false;
};

class Activity {
 public:
  explicit Activity(std::atomic<uint32_t>& counter) noexcept : counter_(counter) {
    entered_ = IncrementActive(counter_, previous_);
  }
  ~Activity() { if (entered_) counter_.fetch_sub(1); }
  explicit operator bool() const { return entered_; }
  uint32_t previous() const { return previous_; }
 private:
  std::atomic<uint32_t>& counter_;
  uint32_t previous_ = 0;
  bool entered_ = false;
};

class EventScope {
 public:
  explicit EventScope(Event& event) noexcept : previous_(current_event) { current_event = &event; }
  ~EventScope() { current_event = previous_; }
 private:
  Event* previous_;
};

template <typename T>
class PointerScope {
 public:
  PointerScope(T*& slot, T* value) noexcept : slot_(slot), previous_(slot) { slot_ = value; }
  ~PointerScope() { slot_ = previous_; }
 private:
  T*& slot_;
  T* previous_;
};

class SuspendSignalActorContext {
 public:
  SuspendSignalActorContext()
      : request_(signal_request_scope, nullptr), group_(signal_group_scope, nullptr),
        dispatch_(signal_dispatch_scope, nullptr), event_(current_event, nullptr) {}
 private:
  PointerScope<SignalSample> request_, group_, dispatch_;
  PointerScope<Event> event_;
};

class TryTrace {
 public:
  TryTrace() noexcept {
    if (trace_lock.test_and_set(std::memory_order_acquire)) {
      Count(lock_dropped);
      Count(concurrent);
      Abort(StopReason::concurrent_probe);
      return;
    }
    if (!trace_open.load(std::memory_order_acquire)) {
      trace_lock.clear(std::memory_order_release);
      return;
    }
    held_ = true;
    const auto reason = abort_reason.load();
    if (reason != StopReason::none) trace.Stop(reason);
  }
  ~TryTrace() { if (held_) trace_lock.clear(std::memory_order_release); }
  explicit operator bool() const { return held_; }
 private:
  bool held_ = false;
};

bool Address(uint8_t* base, uint32_t guest, uint32_t size, uintptr_t& host) noexcept {
  if (!base || !guest || !size || !n3::guest::FitsLinearGuestRange(guest, size)) return false;
  const auto base_address = reinterpret_cast<uintptr_t>(base);
  const auto offset = n3::guest::GuestHostOffset(guest);
  if (offset > std::numeric_limits<uintptr_t>::max() - base_address) return false;
  host = base_address + static_cast<uintptr_t>(offset);
  return size <= std::numeric_limits<uintptr_t>::max() - host;
}

bool Mapped(uint8_t* base, uint32_t guest, uint32_t size) noexcept {
  uintptr_t host = 0;
  if (!Address(base, guest, size, host)) return false;
  const auto end = host + size;
  auto cursor = host;
  while (cursor < end) {
    MEMORY_BASIC_INFORMATION info{};
    if (!VirtualQuery(reinterpret_cast<const void*>(cursor), &info, sizeof(info)) ||
        info.State != MEM_COMMIT || (info.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
    const auto protection = info.Protect & 0xff;
    if (protection != PAGE_READONLY && protection != PAGE_READWRITE &&
        protection != PAGE_WRITECOPY && protection != PAGE_EXECUTE_READ &&
        protection != PAGE_EXECUTE_READWRITE && protection != PAGE_EXECUTE_WRITECOPY)
      return false;
    const auto start = reinterpret_cast<uintptr_t>(info.BaseAddress);
    if (info.RegionSize > std::numeric_limits<uintptr_t>::max() - start) return false;
    const auto next = start + info.RegionSize;
    if (next <= cursor) return false;
    cursor = next < end ? next : end;
  }
  return true;
}

bool Read(uint8_t* base, uint32_t guest, void* result, uint32_t size) noexcept {
  uintptr_t host = 0;
  if (!Mapped(base, guest, size) || !Address(base, guest, size, host)) return false;
  SIZE_T copied = 0;
  return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(host),
      result, size, &copied) && copied == size;
}

bool Word(uint8_t* base, uint32_t address, uint32_t& result) noexcept {
  uint32_t value = 0;
  if (!Read(base, address, &value, sizeof(value))) return false;
  result = std::byteswap(value);
  return true;
}
bool Field(uint8_t* base, uint32_t object, uint32_t offset, uint32_t& result) noexcept {
  const auto address = uint64_t(object) + offset;
  return address <= UINT32_MAX && Word(base, uint32_t(address), result);
}

bool Tick(uint64_t& tick) noexcept {
  LARGE_INTEGER value{};
  if (!QueryPerformanceCounter(&value) || value.QuadPart < 0) {
    Count(invalid);
    Abort(StopReason::clock_failure);
    return false;
  }
  tick = uint64_t(value.QuadPart);
  return true;
}

bool StartEvent(Event& event) noexcept {
  uint64_t tick = 0;
  return Tick(tick) && trace.BeginEvent(event, current_event ? current_event->id : 0, tick);
}

bool FinishEvent(Event& event) noexcept {
  uint64_t tick = 0;
  if (!Tick(tick) || tick < event.begin) {
    Abort(StopReason::clock_failure);
    return false;
  }
  event.end = tick;
  return true;
}

bool BeginSignal(SignalSample& sample) noexcept {
  const auto kind = size_t(sample.kind);
  if (kind >= kSignalKindCount) return false;
  Count(signal_seen[kind]);
  if (abort_reason.load() != StopReason::none) {
    Count(signal_skipped[kind]);
    return false;
  }
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) {
    Count(signal_skipped[kind]);
    return false;
  }
  if (trace.signal_recorded[kind] + trace.signal_inflight[kind] >= kSignalCapacities[kind]) {
    Count(signal_full[kind]);
    return false;
  }
  if (!StartEvent(sample.event)) {
    Count(signal_unreadable[kind]);
    return false;
  }
  ++trace.signal_inflight[kind];
  return true;
}

void SkipSignal(SignalKind kind) noexcept {
  Count(signal_seen[size_t(kind)]);
  Count(signal_skipped[size_t(kind)]);
}

void UnreadableSignal(SignalKind kind) noexcept {
  Count(signal_seen[size_t(kind)]);
  Count(signal_unreadable[size_t(kind)]);
}

void FinishSignal(SignalSample& sample) noexcept {
  const auto kind = size_t(sample.kind);
  const auto finished = FinishEvent(sample.event);
  TryTrace lock;
  if (!lock) {
    Count(abandoned_unlocked);
    return;
  }
  if (trace.signal_inflight[kind]) --trace.signal_inflight[kind];
  if (!finished || trace.signal_count == trace.signal_samples.size()) {
    Count(signal_unreadable[kind]);
    trace.AbandonEvent();
    return;
  }
  trace.signal_samples[trace.signal_count++] = sample;
  ++trace.signal_recorded[kind];
}

void AbandonSignal(SignalSample& sample) noexcept {
  const auto kind = size_t(sample.kind);
  Count(signal_unreadable[kind]);
  TryTrace lock;
  if (!lock) { Count(abandoned_unlocked); return; }
  if (trace.signal_inflight[kind]) --trace.signal_inflight[kind];
  trace.AbandonEvent();
}

bool ReadString(uint8_t* base, uint32_t address, char* text, size_t capacity) noexcept {
  for (size_t i = 0; i < capacity; ++i) {
    const auto at = uint64_t(address) + i;
    if (at > UINT32_MAX || !Read(base, uint32_t(at), &text[i], 1)) return false;
    const auto c = static_cast<unsigned char>(text[i]);
    if (!c) return i != 0;
    if (c < 32 || c > 126) return false;
  }
  return false;
}

bool SameAsciiName(const char* left, const char* right) noexcept {
  for (;;) {
    auto a = static_cast<unsigned char>(*left++);
    auto b = static_cast<unsigned char>(*right++);
    if (a >= 'A' && a <= 'Z') a += 'a' - 'A';
    if (b >= 'A' && b <= 'Z') b += 'a' - 'A';
    if (a != b) return false;
    if (!a) return true;
  }
}

bool HashGuest(uint8_t* base, uint32_t address, uint32_t size,
               std::array<uint8_t, 32>& digest) noexcept {
  if (!size || !n3::guest::FitsLinearGuestRange(address, size)) return false;
  Sha256 hash;
  std::array<uint8_t, 16384> buffer{};
  uint32_t offset = 0;
  while (offset < size) {
    const auto count = (std::min)(uint32_t(buffer.size()), size - offset);
    const auto at = uint64_t(address) + offset;
    if (at > UINT32_MAX || !Read(base, uint32_t(at), buffer.data(), count)) return false;
    hash.Update(buffer.data(), count);
    offset += count;
  }
  digest = hash.Finish();
  return true;
}

ArchiveRecord* FindArchive(uint32_t address) noexcept {
  if (!address) return nullptr;
  for (auto& entry : archives) if (entry.address == address) return &entry;
  return nullptr;
}

InstanceRecord* FindInstance(uint32_t address) noexcept {
  if (!address) return nullptr;
  for (auto& entry : instances) if (entry.address == address) return &entry;
  return nullptr;
}

SignalAssetRecord* FindSignalAsset(SignalKind kind, uint32_t address) noexcept {
  if (!address) return nullptr;
  for (auto& entry : signal_assets)
    if (entry.address == address && entry.kind == kind) return &entry;
  return nullptr;
}

SignalActorRecord* FindSignalActor(uint32_t address) noexcept {
  if (!address) return nullptr;
  for (auto& entry : signal_actors) if (entry.identity.actor == address) return &entry;
  return nullptr;
}

void InvalidateSignalAsset(SignalKind kind, uint32_t address) noexcept {
  if (auto* entry = FindSignalAsset(kind, address)) *entry = {};
}

bool RegisterSignalAsset(const SignalLoadScope& load) noexcept {
  InvalidateSignalAsset(load.kind, load.object);
  for (auto& entry : signal_assets) {
    if (entry.address) continue;
    entry = {load.object, load.generation, load.kind, load.source};
    return true;
  }
  Count(signal_asset_registry_full);
  return false;
}

void RegistryFull() noexcept {
  trace.Count(trace.counters.registry_full);
  trace.Stop(StopReason::registry_full);
  Abort(StopReason::registry_full);
}

void RegisterArchive(uint8_t* base, uint32_t address, uint32_t size) noexcept {
  if (!address || !size || !n3::guest::FitsLinearGuestRange(address, size) ||
      !Mapped(base, address, (std::min)(size, uint32_t(4)))) {
    Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
    return;
  }
  if (FindArchive(address)) {
    Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
    return;
  }
  for (auto& entry : archives) {
    if (entry.address) continue;
    const auto generation = trace.NextGeneration();
    if (!generation) { Abort(trace.stop); return; }
    entry = {address, size, generation};
    return;
  }
  RegistryFull();
}

bool CaptureSource(uint8_t* base, uint32_t manager, uint32_t handle,
                   const char* request, SourceIdentity& result) noexcept {
  const auto object = handle & ~1u;
  uint32_t slot = 0, start = 0, end = 0, archive = 0, count = 0;
  if (!(handle & 1u) || !object || !Field(base, object, 20, slot) || slot >= archives.size() ||
      !Field(base, object, 8, start) || !Field(base, object, 16, end) || end < start ||
      !Field(base, manager, 8 + slot * 16, archive)) return false;
  const char* basename = request;
  for (const char* c = request; *c; ++c)
    if (*c == '\\' || *c == '/') basename = c + 1;
  if (!*basename) return false;
  for (uint32_t candidate_slot = 0; candidate_slot <= slot; ++candidate_slot) {
    uint32_t candidate = 0;
    if (!Field(base, manager, 8 + candidate_slot * 16, candidate)) return false;
    if (!candidate) continue;
    const auto* record = FindArchive(candidate);
    if (!record || !record->generation || !record->size || record->size > kMaxArchiveBytes ||
        !Word(base, candidate, count) || count > kMaxArchiveMembers ||
        uint64_t(4) + uint64_t(count) * 268 > record->size) return false;
    for (uint32_t index = 0; index < count; ++index) {
      const auto at = uint64_t(candidate) + 4 + uint64_t(index) * 268;
      std::array<char, 256> name{};
      if (at > UINT32_MAX || !ReadString(base, uint32_t(at), name.data(), name.size()))
        return false;
      if (!SameAsciiName(name.data(), basename)) continue;
      uint32_t offset = 0, size = 0;
      if (candidate_slot != slot || candidate != archive || start < archive ||
          uint64_t(end) > uint64_t(archive) + record->size || end == start ||
          end - start > kMaxMemberBytes || !Field(base, uint32_t(at), 260, offset) ||
          !Field(base, uint32_t(at), 264, size) ||
          uint64_t(offset) + size > record->size || uint64_t(archive) + offset != start ||
          size != end - start) return false;
      result.resolved = true;
      result.archive_slot = slot;
      result.member_index = index;
      result.archive_size = record->size;
      result.member_size = end - start;
      result.archive_generation = record->generation;
      return HashGuest(base, archive, record->size, result.archive_digest) &&
             HashGuest(base, start, result.member_size, result.member_digest);
    }
  }
  return false;
}

bool ReserveAttachmentHash(uint8_t* base, uint32_t manager, uint32_t handle) noexcept {
  const auto object = handle & ~1u;
  uint32_t slot = 0, start = 0, end = 0, archive = 0;
  if (!(handle & 1u) || !object || !Field(base, object, 20, slot) || slot >= archives.size() ||
      !Field(base, object, 8, start) || !Field(base, object, 16, end) || end < start ||
      !Field(base, manager, 8 + slot * 16, archive))
    return true;
  const auto* record = FindArchive(archive);
  if (!record || start < archive || uint64_t(end) > uint64_t(archive) + record->size)
    return true;
  const auto bytes = uint64_t(record->size) + 2ull * (end - start);
  if (bytes > kAttachmentHashBudgetBytes - trace.attachment.hash_bytes) return false;
  trace.attachment.hash_bytes += bytes;
  return true;
}

bool ValidActorVtable(uint32_t vtable) noexcept {
  return vtable == 0x82040170 || vtable == 0x82041570;
}

bool VectorEntry(uint8_t* base, uint32_t vector, uint32_t index, uint32_t expected) noexcept {
  uint32_t first = 0, last = 0, entry = 0, value = 0;
  if (!Field(base, vector, 4, first) || !Field(base, vector, 8, last) ||
      !first || last < first || (last - first) % 4 || (last - first) / 4 > 65536 ||
      index >= (last - first) / 4 || !Field(base, first, index * 4, entry) ||
      !Field(base, entry, 4, value)) return false;
  return value == expected;
}

bool ReadName(uint8_t* base, uint32_t ba, uint32_t& length, uint64_t& fingerprint) noexcept {
  const auto at = uint64_t(ba) + 28;
  std::array<char, 260> name{};
  if (at > UINT32_MAX || !Read(base, uint32_t(at), name.data(), uint32_t(name.size()))) return false;
  size_t end = 0, start = 0;
  while (end < name.size() && name[end]) {
    const auto c = static_cast<unsigned char>(name[end]);
    if (c < 32 || c > 126) return false;
    if (c == '\\' || c == '/') start = end + 1;
    ++end;
  }
  if (!end || end == name.size() || start == end) return false;
  length = static_cast<uint32_t>(end - start);
  fingerprint = BasenameFingerprint(name.data(), end);
  return true;
}

enum class Check { ok, mapping, changed };

bool Associate(Identity& id) noexcept {
  const auto& ba_record = ba_records[id.ba_handle];
  const auto* instance_record = FindInstance(id.instance);
  if (ba_record.manager != id.manager || ba_record.address != id.ba ||
      !ba_record.generation || !instance_record || !instance_record->generation) {
    trace.Count(trace.counters.cache_untracked);
    trace.Stop(StopReason::untracked_lifetime);
    Abort(StopReason::untracked_lifetime);
    return false;
  }
  id.ba_generation = ba_record.generation;
  id.instance_generation = instance_record->generation;
  id.source = ba_record.source;
  if (id.actor) id.actor_generation = trace.NextGeneration();
  return !id.actor || id.actor_generation != 0;
}

Check Instance(uint8_t* base, const Identity& id) noexcept {
  uint32_t manager = 0, count = 0, table = 0, instance = 0, vtable = 0;
  uint32_t handle = 0, ba_handle = 0, ba = 0, ba_vtable = 0, manager_ba = 0;
  uint32_t clips = 0, bones = 0, name_length = 0;
  uint64_t name_fingerprint = 0;
  if (id.ba_handle >= ba_records.size()) return Check::changed;
  const auto& ba_record = ba_records[id.ba_handle];
  const auto* instance_record = FindInstance(id.instance);
  if (ba_record.manager != id.manager || ba_record.address != id.ba ||
      ba_record.generation != id.ba_generation || !instance_record ||
      instance_record->generation != id.instance_generation) return Check::changed;
  if (!Word(base, kManagerGlobal, manager) || !manager ||
      !Field(base, manager, 66268, count) || !Field(base, manager, 66272, table))
    return Check::mapping;
  if (manager != id.manager || count > 65536 || id.instance_handle >= count || !table)
    return Check::changed;
  if (!Field(base, table, id.instance_handle * 4, instance)) return Check::mapping;
  if (instance != id.instance) return Check::changed;
  if (!Field(base, instance, 0, vtable) || !Field(base, instance, 8, handle) ||
      !Field(base, instance, 216, ba_handle) || !Field(base, instance, 220, ba))
    return Check::mapping;
  if (vtable != kInstanceVtable || handle != id.instance_handle ||
      ba_handle != id.ba_handle || ba != id.ba) return Check::changed;
  if (!Field(base, ba, 0, ba_vtable) || !Field(base, ba, 8, clips) ||
      !Field(base, ba, 12, bones) || !ReadName(base, ba, name_length, name_fingerprint) ||
      !Field(base, manager, 26168 + id.ba_handle * 4, manager_ba))
    return Check::mapping;
  if (ba_vtable != kBaVtable || manager_ba != ba || clips != id.clips ||
      bones != id.bones || name_length != id.name_length || name_fingerprint != id.name_fingerprint)
    return Check::changed;
  return Check::ok;
}

Check Actor(uint8_t* base, const Identity& id) noexcept {
  uint32_t vtable = 0, handle = 0, signal = 0, info = 0, getter = 0;
  uint32_t signal_groups = 0, info_rows = 0;
  if (!Field(base, id.actor, 0, vtable) || !Field(base, id.actor, 16, handle) ||
      !Field(base, id.actor, 312, signal) || !Field(base, id.actor, 316, info) ||
      !Field(base, vtable, 44, getter) || !Field(base, signal, 4, signal_groups) ||
      !Field(base, info, 440, info_rows)) return Check::mapping;
  if (vtable != id.actor_vtable || handle != id.instance_handle || signal != id.signal ||
      info != id.info || getter != kStepGetter || signal_groups != id.signal_groups ||
      info_rows != id.info_rows ||
      !VectorEntry(base, kSignalVector, id.setup_signal_index, id.signal) ||
      !VectorEntry(base, kInfoVector, id.setup_info_index, id.info)) return Check::changed;
  return Instance(base, id);
}

void Invalid(Check check) noexcept {
  Count(invalid);
  Abort(check == Check::mapping ? StopReason::invalid_mapping : StopReason::identity_changed);
}

struct SetupInput {
  uint32_t actor = 0, vtable = 0, ba_handle = 0, signal_index = 0, info_index = 0;
};
enum SetupCounter : size_t {
  kScopeSkipped, kFilterMismatch, kVtableUnreadable, kVtableUnsupported,
  kInputInvalid, kCandidate, kPostIdentityFailed, kOtherAfterSelection, kRepeatSelected,
};
void CountUnsupportedVtable(uint8_t* base, uint32_t vtable) noexcept {
  uint32_t getter = 0;
  if (!Field(base, vtable, 44, getter)) Count(getter_unreadable);
  const auto key = (uint64_t(vtable) << 32) | getter;
  if (!key) { Count(vtable_zero); return; }
  for (auto& entry : unsupported_vtables) {
    auto existing = entry.key.load(std::memory_order_relaxed);
    if (!existing) entry.key.compare_exchange_strong(existing, key, std::memory_order_relaxed);
    if (!existing || existing == key) { Count(entry.calls); return; }
  }
  Count(vtable_full);
}

bool BeforeSetup(PPCContext& ctx, uint8_t* base, SetupInput& input) noexcept {
  input.actor = ctx.r3.u32;
  if (!MatchesActor(trace.filter, input.actor)) {
    Count(setup_rejections[kFilterMismatch]); Count(actor_filtered); return false;
  }
  if (!Field(base, input.actor, 0, input.vtable)) {
    Count(setup_rejections[kVtableUnreadable]); Invalid(Check::mapping); return false;
  }
  if (!ValidActorVtable(input.vtable)) {
    Count(setup_rejections[kVtableUnsupported]);
    CountUnsupportedVtable(base, input.vtable);
    if (trace.filter.actor) Invalid(Check::changed);
    else Count(actor_filtered);
    return false;
  }
  if (!Field(base, ctx.r4.u32, 48, input.ba_handle) ||
      !Field(base, ctx.r4.u32, 52, input.signal_index) ||
      !Field(base, ctx.r4.u32, 56, input.info_index) || input.ba_handle >= 1000) {
    Count(setup_rejections[kInputInvalid]); Invalid(Check::mapping); return false;
  }
  Count(setup_rejections[kCandidate]);
  return true;
}

bool MakeIdentity(uint8_t* base, const SetupInput& in, Identity& id) noexcept {
  id.actor = in.actor; id.actor_vtable = in.vtable; id.ba_handle = in.ba_handle;
  id.setup_signal_index = in.signal_index; id.setup_info_index = in.info_index;
  uint32_t vtable = 0, getter = 0, count = 0, table = 0;
  if (!Field(base, id.actor, 0, vtable) || !Field(base, vtable, 44, getter) ||
      !Field(base, id.actor, 16, id.instance_handle) ||
      !Field(base, id.actor, 312, id.signal) || !Field(base, id.actor, 316, id.info) ||
      !Word(base, kManagerGlobal, id.manager) ||
      !Field(base, id.manager, 66268, count) || !Field(base, id.manager, 66272, table) ||
      count > 65536 || id.instance_handle >= count || !table ||
      !Field(base, table, id.instance_handle * 4, id.instance) ||
      !Field(base, id.instance, 220, id.ba) ||
      !Field(base, id.ba, 8, id.clips) || !Field(base, id.ba, 12, id.bones) ||
      !Field(base, id.signal, 4, id.signal_groups) || !Field(base, id.info, 440, id.info_rows))
    return false;
  if (vtable != in.vtable || getter != kStepGetter || !id.clips || id.clips > kMaxClips ||
      !id.bones || id.bones > kMaxBones || !id.signal_groups ||
      id.signal_groups > kMaxClips || !id.info_rows || id.info_rows > kMaxClips ||
      !VectorEntry(base, kSignalVector, in.signal_index, id.signal) ||
      !VectorEntry(base, kInfoVector, in.info_index, id.info) ||
      !ReadName(base, id.ba, id.name_length, id.name_fingerprint)) return false;
  return Associate(id) && Instance(base, id) == Check::ok;
}

void AfterSetup(uint8_t* base, const SetupInput& input) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || trace.selected) return;
  Identity identity{};
  if (!MakeIdentity(base, input, identity)) {
    Count(setup_rejections[kPostIdentityFailed]); Invalid(Check::mapping); return;
  }
  trace.identity = identity;
  trace.selected = true;
  trace.Count(trace.counters.setup_accepted);
  selected_manager.store(identity.manager);
  selected_handle.store(identity.instance_handle);
  selected_instance.store(identity.instance);
  selected_ba.store(identity.ba);
  selected_actor.store(identity.actor, std::memory_order_release);
}

struct SignalSetupInput {
  uint32_t actor = 0, caller = 0, ba_handle = 0, signal_index = 0, info_index = 0;
  uint32_t key4 = 0, key88 = 0;
  bool readable = false;
};

SignalSetupInput BeforeSignalSetup(PPCContext& ctx, uint8_t* base) noexcept {
  SignalSetupInput input;
  input.actor = ctx.r3.u32;
  input.caller = uint32_t(ctx.lr);
  input.readable = input.actor && Field(base, ctx.r4.u32, 48, input.ba_handle) &&
      Field(base, ctx.r4.u32, 52, input.signal_index) &&
      Field(base, ctx.r4.u32, 56, input.info_index) &&
      Field(base, ctx.r4.u32, 4, input.key4) && Field(base, ctx.r4.u32, 88, input.key88) &&
      input.ba_handle < ba_records.size() && input.signal_index <= 65535 &&
      input.info_index <= 65535;
  return input;
}

void AfterSignalSetup(uint8_t* base, const SignalSetupInput& input) noexcept {
  const auto kind = size_t(SignalKind::setup);
  if (!input.readable) {
    Count(signal_seen[kind]); Count(signal_unreadable[kind]); return;
  }
  SignalSample sample;
  sample.kind = SignalKind::setup;
  sample.actor = input.actor;
  sample.caller = input.caller;
  sample.ba_handle = input.ba_handle;
  sample.signal_index = input.signal_index;
  sample.info_index = input.info_index;
  sample.setup_key4 = input.key4;
  sample.setup_key88 = input.key88;
  {
    TryTrace lock;
    if (!lock || trace.stop != StopReason::none) {
      Count(signal_seen[kind]); Count(signal_skipped[kind]); return;
    }
    if (!trace.selected || trace.identity.actor != input.actor) {
      Count(signal_seen[kind]); Count(signal_skipped[kind]); return;
    }
    sample.actor_generation = trace.identity.actor_generation;
    uint32_t manager = 0, count = 0, table = 0, instance_handle = 0, instance = 0;
    uint32_t ba_handle = 0, ba = 0;
    const bool fields = Field(base, input.actor, 0, sample.actor_vtable) &&
        Field(base, input.actor, 16, instance_handle) &&
        Field(base, input.actor, 312, sample.signal) &&
        Field(base, input.actor, 316, sample.info) &&
        Word(base, kManagerGlobal, manager) && manager &&
        Field(base, manager, 66268, count) && Field(base, manager, 66272, table) &&
        count <= 65536 && instance_handle < count && table &&
        Field(base, table, instance_handle * 4, instance) && instance &&
        Field(base, instance, 216, ba_handle) && Field(base, instance, 220, ba) &&
        ba_handle == input.ba_handle && ba;
    sample.instance_handle = instance_handle;
    sample.instance = instance;
    sample.ba = ba;
    const auto* instance_record = FindInstance(instance);
    const auto& ba_record = ba_records[input.ba_handle];
    if (instance_record) sample.instance_generation = instance_record->generation;
    if (ba_record.address == ba && ba_record.manager == manager)
      sample.ba_generation = ba_record.generation;
    if (const auto* asset = FindSignalAsset(SignalKind::as_load, sample.signal))
      sample.signal_generation = asset->generation;
    if (const auto* asset = FindSignalAsset(SignalKind::info_load, sample.info))
      sample.info_generation = asset->generation;
    sample.identity_bound = fields && sample.actor_vtable == trace.identity.actor_vtable &&
        sample.instance_handle == trace.identity.instance_handle &&
        sample.instance == trace.identity.instance &&
        sample.instance_generation == trace.identity.instance_generation &&
        ba_handle == trace.identity.ba_handle && sample.ba == trace.identity.ba &&
        sample.ba_generation == trace.identity.ba_generation &&
        sample.signal == trace.identity.signal && sample.info == trace.identity.info &&
        sample.actor_generation &&
        sample.instance_generation && sample.ba_generation && sample.signal_generation &&
        sample.info_generation &&
        VectorEntry(base, kSignalVector, input.signal_index, sample.signal) &&
        VectorEntry(base, kInfoVector, input.info_index, sample.info);
    auto* entry = FindSignalActor(input.actor);
    if (!entry) {
      for (auto& candidate : signal_actors) {
        if (!candidate.identity.actor) { entry = &candidate; break; }
      }
    }
    if (entry) entry->identity = sample;
    else Count(signal_actor_registry_full);
  }
  if (BeginSignal(sample)) FinishSignal(sample);
}

bool SignalActorIdentity(uint8_t* base, uint32_t actor, SignalSample& sample) noexcept {
  const auto* entry = FindSignalActor(actor);
  if (!entry) return false;
  const auto& id = entry->identity;
  sample.actor = actor;
  sample.actor_generation = id.actor_generation;
  sample.instance = id.instance;
  sample.instance_generation = id.instance_generation;
  sample.ba = id.ba;
  sample.ba_generation = id.ba_generation;
  sample.signal = id.signal;
  sample.signal_generation = id.signal_generation;
  sample.info = id.info;
  sample.info_generation = id.info_generation;
  if (!id.identity_bound) return false;
  uint32_t vtable = 0, handle = 0, signal = 0, info = 0, ba = 0, ba_handle = 0;
  const auto* instance = FindInstance(id.instance);
  const auto& ba_entry = ba_records[id.ba_handle];
  if (!Field(base, actor, 0, vtable) || !Field(base, actor, 16, handle) ||
      !Field(base, actor, 312, signal) || !Field(base, actor, 316, info) ||
      !Field(base, id.instance, 216, ba_handle) || !Field(base, id.instance, 220, ba))
    return false;
  if (!instance || instance->generation != id.instance_generation ||
      ba_entry.address != id.ba || ba_entry.generation != id.ba_generation ||
      vtable != id.actor_vtable || handle != id.instance_handle ||
      signal != id.signal || info != id.info || ba != id.ba || ba_handle != id.ba_handle ||
      !VectorEntry(base, kSignalVector, id.signal_index, signal) ||
      !VectorEntry(base, kInfoVector, id.info_index, info)) return false;
  const auto* as_asset = FindSignalAsset(SignalKind::as_load, signal);
  const auto* info_asset = FindSignalAsset(SignalKind::info_load, info);
  if ((id.signal_generation && (!as_asset || as_asset->generation != id.signal_generation)) ||
      (id.info_generation && (!info_asset || info_asset->generation != id.info_generation)))
    return false;
  return true;
}

void BindResource(PPCContext& ctx, uint8_t* base) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || trace.selected) return;
  Identity identity{};
  uint32_t count = 0, table = 0;
  identity.instance_handle = ctx.r4.u32;
  if (!Word(base, kManagerGlobal, identity.manager) || !identity.manager) {
    Invalid(Check::mapping); return;
  }
  if (ctx.r3.u32 != identity.manager) { Count(actor_filtered); return; }
  if (!Field(base, identity.manager, 66268, count) ||
      !Field(base, identity.manager, 66272, table) ||
      count > 65536 || identity.instance_handle >= count || !table ||
      !Field(base, table, identity.instance_handle * 4, identity.instance) ||
      !Field(base, identity.instance, 216, identity.ba_handle) ||
      identity.ba_handle >= 1000 ||
      !Field(base, identity.instance, 220, identity.ba) ||
      !Field(base, identity.ba, 8, identity.clips) ||
      !Field(base, identity.ba, 12, identity.bones) ||
      !identity.clips || identity.clips > kMaxClips ||
      !identity.bones || identity.bones > kMaxBones ||
      ctx.r5.u32 >= identity.clips || !FiniteDoubleBits(ctx.f1.u64) ||
      !ReadName(base, identity.ba, identity.name_length, identity.name_fingerprint) ||
      !Associate(identity) || Instance(base, identity) != Check::ok) {
    Invalid(Check::mapping);
    return;
  }
  trace.identity = identity;
  trace.selected = true;
  trace.Count(trace.counters.resource_bindings);
  selected_manager.store(identity.manager);
  selected_handle.store(identity.instance_handle);
  selected_ba.store(identity.ba);
  selected_instance.store(identity.instance, std::memory_order_release);
}

bool IdentitySelected() noexcept {
  return resource_scope.load(std::memory_order_relaxed) ?
      selected_instance.load(std::memory_order_acquire) != 0 :
      selected_actor.load(std::memory_order_acquire) != 0;
}

struct ActorState { uint32_t clip = 0, current = 0, previous = 0, step = 0; };
bool ReadActorState(uint8_t* base, const Identity& id, ActorState& state) noexcept {
  const auto status = Actor(base, id);
  if (status != Check::ok) { Invalid(status); return false; }
  if (!Field(base, id.actor, 192, state.clip) || !Field(base, id.actor, 196, state.current) ||
      !Field(base, id.actor, 200, state.previous) || !Field(base, id.actor, 204, state.step)) {
    Invalid(Check::mapping); return false;
  }
  if (state.clip == UINT32_MAX) { Count(unselected); return false; }
  if (state.clip >= id.clips || state.clip >= id.signal_groups || state.clip >= id.info_rows ||
      !FiniteFloatBits(state.current) || !FiniteFloatBits(state.previous) ||
      !FiniteFloatBits(state.step)) {
    Count(invalid); Abort(StopReason::invalid_value); return false;
  }
  return true;
}

bool BeforeController(uint8_t* base, uint32_t caller, ControllerSample& sample) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || !trace.selected) return false;
  ActorState state{};
  if (!ReadActorState(base, trace.identity, state)) return false;
  if (!MatchesClip(trace.filter, state.clip)) {
    trace.Count(trace.counters.clip_filtered);
    return false;
  }
  sample = {caller, state.clip, state.clip, state.current, state.current, state.step};
  return StartEvent(sample.event);
}

void AfterController(uint8_t* base, ControllerSample sample) noexcept {
  TryTrace lock;
  if (!lock) { Count(abandoned_unlocked); return; }
  if (trace.stop != StopReason::none) { trace.AbandonEvent(); return; }
  ActorState after{};
  if (!ReadActorState(base, trace.identity, after) || !FinishEvent(sample.event)) {
    trace.AbandonEvent();
    return;
  }
  sample.after_clip = after.clip;
  sample.after_time = after.current;
  if (!trace.AddController(sample)) trace.AbandonEvent();
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

bool BeforeQueue(PPCContext& ctx, uint8_t* base, QueueSample& sample) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return false;
  const auto status = trace.identity.actor ? Actor(base, trace.identity) : Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); return false; }
  const auto clip = ctx.r5.u32;
  if (clip >= trace.identity.clips || !FiniteDoubleBits(ctx.f1.u64) ||
      (trace.filter.scope == Scope::actor &&
       (clip >= trace.identity.signal_groups || clip >= trace.identity.info_rows))) {
    Count(invalid); Abort(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(trace.filter, clip)) {
    trace.Count(trace.counters.clip_filtered);
    return false;
  }
  sample = {uint32_t(ctx.lr), clip, ctx.f1.u64};
  return StartEvent(sample.event);
}

void AfterQueue(uint8_t* base, QueueSample sample) noexcept {
  TryTrace lock;
  if (!lock) { Count(abandoned_unlocked); return; }
  if (trace.stop != StopReason::none) { trace.AbandonEvent(); return; }
  const auto status = trace.identity.actor ? Actor(base, trace.identity) : Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); trace.AbandonEvent(); return; }
  if (!FinishEvent(sample.event)) { trace.AbandonEvent(); return; }
  if (!trace.AddQueue(sample)) trace.AbandonEvent();
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

bool BeforeEvaluation(PPCContext& ctx, uint8_t* base, EvaluationSample& sample) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return false;
  const auto status = trace.identity.actor ? Actor(base, trace.identity) : Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); return false; }
  sample.caller = uint32_t(ctx.lr);
  if (!Field(base, trace.identity.instance, 228, sample.queue_count) ||
      !Field(base, trace.identity.instance, 232, sample.clip) ||
      !Field(base, trace.identity.instance, 252, sample.time)) {
    Invalid(Check::mapping); return false;
  }
  if (!sample.queue_count) { Count(unselected); return false; }
  if (sample.queue_count > 5 || sample.clip >= trace.identity.clips ||
      (trace.filter.scope == Scope::actor &&
       (sample.clip >= trace.identity.signal_groups || sample.clip >= trace.identity.info_rows)) ||
      !FiniteFloatBits(sample.time)) {
    Count(invalid); Abort(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(trace.filter, sample.clip)) { trace.Count(trace.counters.clip_filtered); return false; }
  return StartEvent(sample.event);
}

void AfterEvaluation(uint8_t* base, EvaluationSample sample, const PoseScope& scope) noexcept {
  const auto drop_pending = [&] {
    for (size_t i = 0; i < scope.quaternion_count; ++i) Count(quaternion_parent_dropped);
  };
  TryTrace lock;
  if (!lock) { Count(abandoned_unlocked); drop_pending(); return; }
  if (trace.stop != StopReason::none) { trace.AbandonEvent(); drop_pending(); return; }
  const auto status = trace.identity.actor ? Actor(base, trace.identity) : Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); trace.AbandonEvent(); drop_pending(); return; }
  if (!FinishEvent(sample.event)) { trace.AbandonEvent(); drop_pending(); return; }
  sample.pose_outputs = scope.outputs;
  sample.invalid_outputs = scope.invalid;
  if (!trace.AddEvaluation(sample)) { trace.AbandonEvent(); drop_pending(); }
  else {
    for (size_t i = 0; i < scope.quaternion_count; ++i) {
      if (trace.quaternion_count == kQuaternionCapacity) { Count(quaternion_total_full); continue; }
      auto child = scope.quaternion[i];
      const auto begin = child.event.begin, end = child.event.end;
      if (!trace.BeginEvent(child.event, sample.event.id, begin)) {
        Count(quaternion_parent_dropped);
        continue;
      }
      child.event.end = end;
      trace.quaternion[trace.quaternion_count++] = child;
    }
  }
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

void Reset(Filter filter, bool quaternion = false, bool signal = false, bool attachment = false) {
  trace = Trace{};
  trace.filter = filter;
  trace.quaternion_enabled = quaternion;
  trace.signal_enabled = signal;
  trace.attachment.enabled = attachment;
  LARGE_INTEGER frequency{};
  if (QueryPerformanceFrequency(&frequency) && frequency.QuadPart > 0)
    trace.clock_frequency = uint64_t(frequency.QuadPart);
  else trace.Stop(StopReason::clock_failure);
  archives.fill({});
  ba_records.fill({});
  instances.fill({});
  signal_assets.fill({});
  signal_actors.fill({});
  signal_record_count = 0;
  resource_scope.store(filter.scope == Scope::resource, std::memory_order_relaxed);
  selected_actor = selected_manager = selected_handle = selected_instance = selected_ba = 0;
  inflight = active_controllers = active_ba_evaluations = 0;
  active_associations = active_resolvers = active_archive_changes = 0;
  active_attachment_reads = 0;
  abort_reason = StopReason::none;
  setup_calls = controller_calls = queue_calls = evaluation_calls = 0;
  actor_filtered = unselected = invalid = reentrant = concurrent = after_stop = lock_dropped = 0;
  pose_outputs = invalid_outputs = 0;
  abandoned_unlocked = 0;
  for (auto& count : setup_wrapper_calls) count = 0;
  for (auto& count : setup_rejections) count = 0;
  for (auto& entry : unsupported_vtables) { entry.key = 0; entry.calls = 0; }
  vtable_full = vtable_zero = getter_unreadable = 0;
  dispatch_calls = dispatch_flag_zero = dispatch_handle_minus_one = 0;
  dispatch_eligible = dispatch_unreadable = 0;
  quaternion_enabled.store(quaternion, std::memory_order_relaxed);
  signal_enabled.store(signal, std::memory_order_relaxed);
  attachment_enabled.store(attachment, std::memory_order_relaxed);
  quaternion_seen = quaternion_invalid_context = quaternion_invalid_input = 0;
  quaternion_invalid_output = quaternion_per_evaluation_full = quaternion_total_full = 0;
  quaternion_parent_dropped = 0;
  for (size_t i = 0; i < kSignalKindCount; ++i) {
    signal_seen[i] = signal_full[i] = signal_unreadable[i] = signal_skipped[i] = 0;
  }
  signal_unresolved_sources = signal_record_map_full = signal_record_map_invalid = 0;
  signal_actor_registry_full = signal_asset_registry_full = 0;
#ifdef N3_ANIMATION_TRACE_TEST
  pause_invalid_output_for_test = false;
  invalid_output_paused_for_test = false;
#endif
  for (size_t kind = 0; kind < kAttachmentKindCount; ++kind) {
    attachment_seen[kind] = 0;
    for (auto& outcome : attachment_outcomes[kind]) outcome = 0;
  }
  attachment_sequence = attachment_resolver_calls = attachment_resolver_returns = 0;
  attachment_resolver_verified = attachment_request_unreadable = 0;
  attachment_reentrant = attachment_concurrent = 0;
  attachment_budget_full = 0;
  counter_saturated = false;
  trace_lock.clear();
  trace_open.store(true, std::memory_order_release);
  enabled.store(true, std::memory_order_release);
}

void CopyCounters(Trace& target) {
  target.counters.setup_calls = setup_calls.load();
  target.counters.controller_calls = controller_calls.load();
  target.counters.queue_calls = queue_calls.load();
  target.counters.evaluation_calls = evaluation_calls.load();
  target.counters.actor_filtered = actor_filtered.load();
  target.counters.unselected = unselected.load();
  target.Count(target.counters.invalid, invalid.load());
  target.counters.reentrant = reentrant.load();
  target.counters.concurrent = concurrent.load();
  target.Count(target.counters.after_stop, after_stop.load());
  target.counters.lock_dropped = lock_dropped.load();
  target.counters.pose_outputs = pose_outputs.load();
  target.counters.invalid_outputs = invalid_outputs.load();
  target.counters.inflight_at_flush = FlightsInProgress();
  for (size_t i = 0; i < setup_wrapper_calls.size(); ++i)
    target.dispatch.setup_wrapper_calls[i] = setup_wrapper_calls[i].load();
  for (size_t i = 0; i < setup_rejections.size(); ++i)
    target.dispatch.setup_rejections[i] = setup_rejections[i].load();
  for (size_t i = 0; i < unsupported_vtables.size(); ++i) {
    const auto key = unsupported_vtables[i].key.load();
    target.dispatch.unsupported_vtables[i] = {
        uint32_t(key >> 32), uint32_t(key), unsupported_vtables[i].calls.load()};
  }
  target.dispatch.vtable_full = vtable_full.load();
  target.dispatch.vtable_zero = vtable_zero.load();
  target.dispatch.getter_unreadable = getter_unreadable.load();
  target.dispatch.resource_calls = dispatch_calls.load();
  target.dispatch.flag_zero = dispatch_flag_zero.load();
  target.dispatch.handle_minus_one = dispatch_handle_minus_one.load();
  target.dispatch.eligible = dispatch_eligible.load();
  target.dispatch.unreadable = dispatch_unreadable.load();
  target.quaternion_counts = {
      0, quaternion_invalid_context.load(), quaternion_invalid_input.load(),
      quaternion_invalid_output.load(), quaternion_per_evaluation_full.load(),
      quaternion_total_full.load(), quaternion_parent_dropped.load()};
  target.quaternion_counts.seen = quaternion_seen.load(std::memory_order_acquire);
  for (size_t i = 0; i < kSignalKindCount; ++i) {
    target.signal_counts.full[i] = signal_full[i].load(std::memory_order_acquire);
    target.signal_counts.unreadable[i] = signal_unreadable[i].load(std::memory_order_acquire);
    target.signal_counts.skipped[i] = signal_skipped[i].load(std::memory_order_acquire);
    target.signal_counts.seen[i] = signal_seen[i].load(std::memory_order_acquire);
  }
  target.signal_counts.unresolved_sources = signal_unresolved_sources.load();
  target.signal_counts.record_map_full = signal_record_map_full.load();
  target.signal_counts.record_map_invalid = signal_record_map_invalid.load();
  target.signal_counts.actor_registry_full = signal_actor_registry_full.load();
  target.signal_counts.asset_registry_full = signal_asset_registry_full.load();
  for (size_t kind = 0; kind < kAttachmentKindCount; ++kind) {
    for (size_t outcome = 0; outcome < kAttachmentOutcomeCount; ++outcome)
      target.attachment.outcomes[kind][outcome] =
          attachment_outcomes[kind][outcome].load(std::memory_order_acquire);
    target.attachment.seen[kind] = attachment_seen[kind].load(std::memory_order_acquire);
  }
  target.attachment.sequence_count = attachment_sequence.load();
  target.attachment.resolver_verified = attachment_resolver_verified.load(std::memory_order_acquire);
  target.attachment.resolver_returns = attachment_resolver_returns.load(std::memory_order_acquire);
  target.attachment.resolver_calls = attachment_resolver_calls.load(std::memory_order_acquire);
  target.attachment.request_unreadable = attachment_request_unreadable.load();
  target.attachment.reentrant = attachment_reentrant.load();
  target.attachment.concurrent = attachment_concurrent.load();
  target.attachment.hash_budget_full = attachment_budget_full.load();
  target.attachment.read_inflight_at_flush = active_attachment_reads.load();
  target.Count(target.counters.events_abandoned, abandoned_unlocked.load());
  const auto recorded = target.controller_count + target.queue_count + target.evaluation_count +
                        target.quaternion_count + target.signal_count;
  if (recorded <= target.counters.events_started &&
      target.counters.events_abandoned <= target.counters.events_started - recorded) {
    target.counters.events_inflight_at_flush =
        target.counters.events_started - recorded - target.counters.events_abandoned;
  } else {
    target.Stop(StopReason::invalid_value);
  }
  if (counter_saturated.load()) {
    target.counters.counter_saturated = 1;
    target.Stop(StopReason::counter_overflow);
  }
  const auto reason = abort_reason.load();
  if (reason != StopReason::none) target.Stop(reason);
}
}  // namespace

extern "C" void __imp__sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82080158(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82249628(PPCContext&, uint8_t*);
extern "C" void __imp__sub_822733B8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82273000(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82272AF0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82272F58(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82272C40(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8224E6F0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82298E78(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8224E9B0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8229CF30(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8224AC98(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82251D38(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8224E0B8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82249FB0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_820A4648(PPCContext&, uint8_t*);
extern "C" void __imp__sub_820AF768(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8208D878(PPCContext&, uint8_t*);
extern "C" void __imp__sub_820AAFB0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_820A2968(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8217AD08(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8229CA98(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210BF78(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210CB78(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210BE98(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210CAB8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210C728(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8210CFE8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82097868(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82097958(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82097D00(PPCContext&, uint8_t*);
extern "C" void __imp__sub_820927C0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8209BE30(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82097D90(PPCContext&, uint8_t*);
extern "C" void __imp__sub_8212ACA8(PPCContext&, uint8_t*);

namespace {
using Original = void (*)(PPCContext&, uint8_t*);

void ObserveArchiveLoad(PPCContext& ctx, uint8_t* base, Original original) {
  Flight flight;
  if (!flight) return original(ctx, base);
  Association association;
  Activity changing(active_archive_changes);
  if (changing.previous() || active_resolvers.load()) {
    Count(concurrent); Abort(StopReason::concurrent_probe);
  }
  const auto address_output = ctx.r4.u32, size_output = ctx.r5.u32;
  bool outputs_valid = false;
  {
    HostState state;
    outputs_valid = Mapped(base, address_output, 4) && Mapped(base, size_output, 4);
    if (!outputs_valid) { Count(invalid); Abort(StopReason::invalid_mapping); }
  }
  original(ctx, base);
  if (!outputs_valid || ctx.r3.s32 < 0 || abort_reason.load() != StopReason::none) return;
  HostState state;
  uint32_t address = 0, size = 0;
  if (!Word(base, address_output, address) || !Word(base, size_output, size)) {
    Count(invalid); Abort(StopReason::invalid_mapping); return;
  }
  TryTrace lock;
  if (lock && trace.stop == StopReason::none) RegisterArchive(base, address, size);
}

void ObserveBaRead(PPCContext& ctx, uint8_t* base) {
  Flight flight;
  if (!flight) return __imp__sub_82273000(ctx, base);
  if (in_ba_read || load_scope->read) {
    Count(reentrant); Abort(StopReason::reentrant);
    return __imp__sub_82273000(ctx, base);
  }
  Association association;
  const auto address_output = ctx.r4.u32, size_output = ctx.r5.u32;
  {
    HostState state;
    if (!Mapped(base, address_output, 4) || !Mapped(base, size_output, 4)) {
      Count(invalid); Abort(StopReason::invalid_mapping);
    }
  }
  in_ba_read = true;
  struct RestoreRead { ~RestoreRead() { in_ba_read = false; } } restore;
  __imp__sub_82273000(ctx, base);
  in_ba_read = false;
  if (ctx.r3.s32 < 0 || abort_reason.load() != StopReason::none) return;
  HostState state;
  uint32_t address = 0, size = 0;
  if (!Word(base, address_output, address) || !Word(base, size_output, size) ||
      !address || !size || size > kMaxMemberBytes ||
      !n3::guest::FitsLinearGuestRange(address, size) || !Mapped(base, address, size)) {
    Count(invalid); Abort(StopReason::invalid_mapping); return;
  }
  if (load_scope->resolved) {
    std::array<uint8_t, 32> digest{};
    if (size != load_scope->source.member_size || !HashGuest(base, address, size, digest) ||
        digest != load_scope->source.member_digest) {
      Count(invalid); Abort(StopReason::identity_changed); return;
    }
  }
  load_scope->read = true;
  load_scope->read_address = address;
  load_scope->read_size = size;
}

void ObserveSignalRead(PPCContext& ctx, uint8_t* base) {
  Flight flight;
  if (!flight) return __imp__sub_82273000(ctx, base);
  if (in_signal_read || signal_load_scope->read) {
    Count(signal_unresolved_sources);
    return __imp__sub_82273000(ctx, base);
  }
  Association association;
  const auto address_output = ctx.r4.u32, size_output = ctx.r5.u32;
  bool outputs_valid = false;
  {
    HostState state;
    outputs_valid = Mapped(base, address_output, 4) && Mapped(base, size_output, 4);
  }
  in_signal_read = true;
  struct RestoreRead { ~RestoreRead() { in_signal_read = false; } } restore;
  __imp__sub_82273000(ctx, base);
  in_signal_read = false;
  if (ctx.r3.s32 < 0 || !outputs_valid || abort_reason.load() != StopReason::none) {
    Count(signal_unresolved_sources); return;
  }
  HostState state;
  uint32_t address = 0, size = 0;
  std::array<uint8_t, 32> digest{};
  if (!Word(base, address_output, address) || !Word(base, size_output, size) ||
      !address || !size || size > kMaxMemberBytes || !signal_load_scope->resolved ||
      size != signal_load_scope->source.member_size || !HashGuest(base, address, size, digest) ||
      digest != signal_load_scope->source.member_digest) {
    Count(signal_unresolved_sources); return;
  }
  signal_load_scope->read = true;
  signal_load_scope->read_address = address;
  signal_load_scope->read_size = size;
}
}

extern "C" void sub_822733B8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || uint32_t(ctx.lr) != 0x82272ef0)
    return __imp__sub_822733B8(ctx, base);
  ObserveArchiveLoad(ctx, base, __imp__sub_822733B8);
}

namespace {
void DispatchRead(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve())
    return __imp__sub_82273000(ctx, base);
  if (uint32_t(ctx.lr) == 0x8223e8f0) ObserveArchiveLoad(ctx, base, __imp__sub_82273000);
  else if (load_scope && uint32_t(ctx.lr) == 0x8224e8a8) ObserveBaRead(ctx, base);
  else if (signal_enabled.load(std::memory_order_relaxed) && signal_load_scope &&
           ((signal_load_scope->kind == SignalKind::as_load && uint32_t(ctx.lr) == 0x8210bf98) ||
            (signal_load_scope->kind == SignalKind::info_load && uint32_t(ctx.lr) == 0x8210cba8)))
    ObserveSignalRead(ctx, base);
  else __imp__sub_82273000(ctx, base);
}

void ObserveAttachmentRead(PPCContext& ctx, uint8_t* base) {
  Flight flight;
  if (!flight) return DispatchRead(ctx, base);
  AttachmentReadScope scope;
  scope.request_address = ctx.r3.u32;
  scope.address_output = ctx.r4.u32;
  scope.size_output = ctx.r5.u32;
  scope.read_caller = uint32_t(ctx.lr);
  bool readable = false;
  {
    HostState state;
    readable = ReadString(base, scope.request_address, scope.request.data(), scope.request.size());
    if (!readable) Count(attachment_request_unreadable);
    else scope.kind = ClassifyAttachmentRequest(scope.request.data());
  }
  if (!readable || scope.kind == AttachmentKind::other) return DispatchRead(ctx, base);
  const auto kind = size_t(scope.kind);
  uint64_t ordinal = 0;
  if (!Next(attachment_seen[kind], ordinal) || !Next(attachment_sequence, scope.sequence))
    return DispatchRead(ctx, base);
  if (ordinal > kAttachmentPerKindCapacity) {
    AttachmentResult(scope.kind, AttachmentOutcome::full);
    return DispatchRead(ctx, base);
  }
  if (attachment_read_scope) {
    Count(attachment_reentrant);
    Abort(StopReason::reentrant);
    AttachmentResult(scope.kind, AttachmentOutcome::skipped);
    return DispatchRead(ctx, base);
  }
  Activity activity(active_attachment_reads);
  if (!activity || activity.previous()) {
    Count(attachment_concurrent);
    Abort(StopReason::concurrent_probe);
    AttachmentResult(scope.kind, AttachmentOutcome::skipped);
    return DispatchRead(ctx, base);
  }
  bool outputs_valid = false;
  {
    HostState state;
    outputs_valid = Mapped(base, scope.address_output, 4) &&
                    Mapped(base, scope.size_output, 4);
  }
  {
    PointerScope pointer(attachment_read_scope, &scope);
    DispatchRead(ctx, base);
  }
  HostState state;
  if (abort_reason.load() != StopReason::none) {
    AttachmentResult(scope.kind, AttachmentOutcome::skipped);
    return;
  }
  if (ctx.r3.s32 < 0) {
    AttachmentResult(scope.kind, AttachmentOutcome::read_failed);
    return;
  }
  std::array<char, 260> after{};
  if (!outputs_valid || !ReadString(base, scope.request_address, after.data(), after.size())) {
    AttachmentResult(scope.kind, AttachmentOutcome::unreadable);
    return;
  }
  if (std::strcmp(scope.request.data(), after.data())) {
    AttachmentResult(scope.kind, AttachmentOutcome::changed);
    return;
  }
  if (scope.budget_exhausted) {
    AttachmentResult(scope.kind, AttachmentOutcome::full);
    return;
  }
  if (!scope.resolver_seen) {
    AttachmentResult(scope.kind, AttachmentOutcome::no_resolver);
    return;
  }
  if (!scope.resolved || scope.ambiguous) {
    AttachmentResult(scope.kind, AttachmentOutcome::unresolved);
    return;
  }
  uint32_t address = 0, size = 0;
  std::array<uint8_t, 32> digest{};
  if (!Word(base, scope.address_output, address) || !Word(base, scope.size_output, size) ||
      !address || !size || size > kMaxMemberBytes || !HashGuest(base, address, size, digest)) {
    AttachmentResult(scope.kind, AttachmentOutcome::unreadable);
    return;
  }
  if (size != scope.source.member_size || digest != scope.source.member_digest) {
    AttachmentResult(scope.kind, AttachmentOutcome::mismatch);
    return;
  }
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || active_archive_changes.load()) {
    AttachmentResult(scope.kind, AttachmentOutcome::skipped);
    return;
  }
  uint32_t archive = 0;
  const auto* record = FindArchive(scope.archive);
  if (!Field(base, scope.manager, 8 + scope.source.archive_slot * 16, archive) ||
      archive != scope.archive || !record || record->generation != scope.source.archive_generation ||
      record->size != scope.source.archive_size) {
    AttachmentResult(scope.kind, AttachmentOutcome::changed);
    return;
  }
  if (!AddAttachmentObservation(trace.attachment, scope.kind, scope.read_caller,
                                scope.sequence, scope.source)) {
    AttachmentResult(scope.kind, AttachmentOutcome::full);
    return;
  }
  AttachmentResult(scope.kind, AttachmentOutcome::verified);
}
}  // namespace

extern "C" void sub_82273000(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() ||
      !attachment_enabled.load(std::memory_order_relaxed))
    return DispatchRead(ctx, base);
  ObserveAttachmentRead(ctx, base);
}

extern "C" void sub_82272AF0(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82272AF0(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82272AF0(ctx, base);
  Association association;
  Activity changing(active_archive_changes);
  if (changing.previous() || active_resolvers.load()) {
    Count(concurrent); Abort(StopReason::concurrent_probe);
  }
  const auto address = ctx.r4.u32;
  __imp__sub_82272AF0(ctx, base);
  if (ctx.r3.u32 || abort_reason.load() != StopReason::none) return;
  HostState state;
  TryTrace lock;
  if (lock) if (auto* record = FindArchive(address)) *record = {};
}

extern "C" void sub_82272F58(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82272F58(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82272F58(ctx, base);
  Association association;
  Activity changing(active_archive_changes);
  if (changing.previous() || active_resolvers.load()) {
    Count(concurrent); Abort(StopReason::concurrent_probe);
  }
  if (abort_reason.load() == StopReason::none) {
    HostState state;
    TryTrace lock;
    if (lock) if (auto* record = FindArchive(ctx.r3.u32)) *record = {};
  }
  __imp__sub_82272F58(ctx, base);
}

extern "C" void sub_82272C40(PPCContext& ctx, uint8_t* base) {
  const bool ba_read = load_scope && in_ba_read;
  const bool signal_read = signal_enabled.load(std::memory_order_relaxed) &&
      signal_load_scope && in_signal_read;
  const bool attachment_read = attachment_enabled.load(std::memory_order_relaxed) &&
      attachment_read_scope;
  if (!CanObserve() || (!ba_read && !signal_read && !attachment_read))
    return __imp__sub_82272C40(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82272C40(ctx, base);
  Association association;
  Activity resolving(active_resolvers);
  if (resolving.previous() || active_archive_changes.load()) {
    Count(concurrent); Abort(StopReason::concurrent_probe);
    if (attachment_read) Count(attachment_concurrent);
  }
  const auto manager = ctx.r3.u32;
  std::array<char, 260> request{};
  bool valid = false;
  bool same_request = false;
  {
    HostState state;
    valid = ReadString(base, ctx.r4.u32, request.data(), request.size());
    if (!valid && ba_read) { Count(invalid); Abort(StopReason::invalid_mapping); }
    if (attachment_read) {
      Count(attachment_resolver_calls);
      attachment_read_scope->resolver_seen = true;
      const auto basename = [](const char* text) {
        const char* result = text;
        for (const char* c = text; *c; ++c)
          if (*c == '\\' || *c == '/') result = c + 1;
        return result;
      };
      same_request = valid && SameAsciiName(basename(request.data()),
                                            basename(attachment_read_scope->request.data()));
      if (!same_request) attachment_read_scope->ambiguous = true;
    }
  }
  __imp__sub_82272C40(ctx, base);
  if (attachment_read && ctx.r3.u32) Count(attachment_resolver_returns);
  if (!valid || !ctx.r3.u32 || abort_reason.load() != StopReason::none) return;
  HostState state;
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  SourceIdentity source{};
  const bool attachment_allowed = attachment_read && same_request &&
      ReserveAttachmentHash(base, manager, ctx.r3.u32);
  if (attachment_read && same_request && !attachment_allowed) {
    attachment_read_scope->budget_exhausted = true;
    Count(attachment_budget_full);
  }
  const bool captured = (ba_read || signal_read || attachment_allowed) &&
      CaptureSource(base, manager, ctx.r3.u32, request.data(), source);
  if (ba_read) {
    if (!captured || (load_scope->resolved && !(load_scope->source == source))) {
      Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
      return;
    }
    load_scope->source = source;
    load_scope->resolved = true;
  } else if (signal_read && captured &&
             (!signal_load_scope->resolved || signal_load_scope->source == source)) {
    signal_load_scope->source = source;
    signal_load_scope->resolved = true;
  } else if (signal_read) {
    signal_load_scope->resolved = false;
  }
  if (attachment_allowed) {
    uint32_t archive = 0;
    if (!captured || !Field(base, manager, 8 + source.archive_slot * 16, archive) || !archive) {
      attachment_read_scope->ambiguous = true;
    } else {
      Count(attachment_resolver_verified);
      if (attachment_read_scope->resolved &&
          (!(attachment_read_scope->source == source) ||
           attachment_read_scope->manager != manager || attachment_read_scope->archive != archive))
        attachment_read_scope->ambiguous = true;
      else {
        attachment_read_scope->source = source;
        attachment_read_scope->manager = manager;
        attachment_read_scope->archive = archive;
        attachment_read_scope->resolved = true;
      }
    }
  }
}

namespace {
bool SignalSourceWord(uint8_t* base, const SignalLoadScope& load,
                      uint64_t offset, uint32_t& value) noexcept {
  const auto address = uint64_t(load.read_address) + offset;
  return load.read && offset + 4 <= load.read_size && address <= UINT32_MAX &&
      Word(base, uint32_t(address), value);
}

void MapSignalGroup(uint8_t* base, const SignalLoadScope& load, uint32_t group,
                    uint32_t group_object, uint32_t stream, uint32_t group_offset) noexcept {
  uint32_t version = 0, groups = 0, declared = 0, runtime_groups = 0;
  uint32_t runtime_group_table = 0, runtime_count = 0, runtime_records = 0, cursor = 0;
  if (!load.read || !load.generation ||
      !SignalSourceWord(base, load, 0, version) || version != 101 ||
      !SignalSourceWord(base, load, 4, groups) || groups > 2048 || group >= groups ||
      group_offset < 520 || !SignalSourceWord(base, load, group_offset, declared) ||
      !Field(base, load.object, 4, runtime_groups) || runtime_groups != groups ||
      !Field(base, load.object, 8, runtime_group_table) ||
      uint64_t(runtime_group_table) + uint64_t(group) * 12 != group_object ||
      !Field(base, group_object, 4, runtime_count) ||
      !Field(base, group_object, 8, runtime_records) || !Field(base, stream, 4, cursor)) {
    Count(signal_record_map_invalid); return;
  }
  if (declared == 0 || declared == 65536) return;
  if (declared > signal_records.size() ||
      declared > signal_records.size() - signal_record_count) {
    Count(signal_record_map_full); return;
  }
  const uint64_t table_start = uint64_t(group_offset) + 4;
  const uint64_t table_end = table_start + uint64_t(declared) * 8;
  if (table_end > load.read_size || runtime_count > declared ||
      (runtime_count && !runtime_records)) {
    Count(signal_record_map_invalid); return;
  }
  const auto start = signal_record_count;
  uint64_t expected = table_end;
  uint32_t retained = 0;
  bool valid = true;
  for (uint32_t ordinal = 0; ordinal < declared; ++ordinal) {
    const uint64_t table = table_start + uint64_t(ordinal) * 8;
    uint32_t kind = 0, offset = 0, time = 0, bounded = 0, words = 0;
    if (!SignalSourceWord(base, load, table, kind) ||
        !SignalSourceWord(base, load, table + 4, offset) || offset != expected ||
        !SignalSourceWord(base, load, offset, time) ||
        !SignalSourceWord(base, load, uint64_t(offset) + 4, bounded) ||
        !SignalSourceWord(base, load, uint64_t(offset) + 8, words)) {
      valid = false; break;
    }
    expected = uint64_t(offset) + 12 + uint64_t(words) * 4 + 16;
    if (expected > load.read_size) { valid = false; break; }
    const auto signed_time = std::bit_cast<int32_t>(time);
    const auto signed_bounded = std::bit_cast<int32_t>(bounded);
    if (signed_time < 0 || signed_bounded < 0 || signed_bounded >= 16) continue;
    if (retained >= runtime_count) { valid = false; break; }
    const auto runtime = uint64_t(runtime_records) + uint64_t(retained) * 20;
    uint32_t rt_time = 0, rt_kind = 0, rt_bounded = 0, rt_words = 0;
    if (runtime > UINT32_MAX || !Word(base, uint32_t(runtime), rt_time) ||
        !Field(base, uint32_t(runtime), 4, rt_kind) ||
        !Field(base, uint32_t(runtime), 8, rt_bounded) ||
        !Field(base, uint32_t(runtime), 12, rt_words) ||
        rt_time != time || rt_kind != kind || rt_bounded != bounded || rt_words != words) {
      valid = false; break;
    }
    signal_records[signal_record_count++] = {
        load.object, uint32_t(runtime), group, retained, group_offset, uint32_t(table), offset,
        kind, words, signed_time, signed_bounded, load.generation};
    ++retained;
  }
  if (!valid || retained != runtime_count || expected != cursor) {
    signal_record_count = start;
    Count(signal_record_map_invalid);
  }
}

void ObserveSignalLoad(PPCContext& ctx, uint8_t* base, Original original, SignalKind kind) {
  Flight flight;
  if (!flight) return original(ctx, base);
  if (signal_load_scope) {
    Count(signal_seen[size_t(kind)]); Count(signal_skipped[size_t(kind)]);
    return original(ctx, base);
  }
  Association association;
  SignalLoadScope load;
  load.kind = kind;
  load.object = ctx.r3.u32;
  SignalSample sample;
  sample.kind = kind;
  sample.caller = uint32_t(ctx.lr);
  if (kind == SignalKind::as_load) sample.signal = load.object;
  else sample.info = load.object;
  {
    HostState state;
    TryTrace lock;
    if (lock && trace.stop == StopReason::none) {
      InvalidateSignalAsset(kind, load.object);
      load.generation = trace.NextGeneration();
    }
  }
  if (kind == SignalKind::as_load) sample.signal_generation = load.generation;
  else sample.info_generation = load.generation;
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
  }
  {
    PointerScope pointer(signal_load_scope, &load);
    if (sampled) {
      EventScope event(sample.event);
      original(ctx, base);
    } else original(ctx, base);
  }
  sample.loaded = ctx.r3.u32 != 0;
  if (load.read) sample.source = load.source;
  if (sample.loaded && load.object && load.generation &&
      abort_reason.load() == StopReason::none) {
    HostState state;
    TryTrace lock;
    if (lock && trace.stop == StopReason::none) {
      if (!load.read) load.source = {};
      RegisterSignalAsset(load);
    }
  }
  if (sampled) {
    HostState state;
    if (sample.loaded && (!load.object || !load.generation)) AbandonSignal(sample);
    else FinishSignal(sample);
  }
}
}

extern "C" void sub_8210BF78(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed))
    return __imp__sub_8210BF78(ctx, base);
  ObserveSignalLoad(ctx, base, __imp__sub_8210BF78, SignalKind::as_load);
}

extern "C" void sub_8210CB78(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed))
    return __imp__sub_8210CB78(ctx, base);
  ObserveSignalLoad(ctx, base, __imp__sub_8210CB78, SignalKind::info_load);
}

namespace {
void ObserveSignalRelease(PPCContext& ctx, uint8_t* base, Original original, SignalKind kind) {
  Flight flight;
  if (!flight) return original(ctx, base);
  Association association;
  {
    HostState state;
    TryTrace lock;
    if (lock) InvalidateSignalAsset(kind, ctx.r3.u32);
  }
  original(ctx, base);
}
}

extern "C" void sub_8210BE98(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed))
    return __imp__sub_8210BE98(ctx, base);
  ObserveSignalRelease(ctx, base, __imp__sub_8210BE98, SignalKind::as_load);
}

extern "C" void sub_8210CAB8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed))
    return __imp__sub_8210CAB8(ctx, base);
  ObserveSignalRelease(ctx, base, __imp__sub_8210CAB8, SignalKind::info_load);
}

extern "C" void sub_8210C728(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed) ||
      !signal_load_scope || signal_load_scope->kind != SignalKind::as_load ||
      uint32_t(ctx.lr) != 0x8210c0d4) return __imp__sub_8210C728(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8210C728(ctx, base);
  const auto group = signal_load_scope->group++;
  const auto group_object = ctx.r3.u32, stream = ctx.r4.u32;
  uint32_t cursor = 0, address = 0, size = 0;
  bool valid = false;
  {
    HostState state;
    valid = Field(base, stream, 4, cursor) && Field(base, stream, 8, address) &&
        Field(base, stream, 12, size) && signal_load_scope->read &&
        address == signal_load_scope->read_address && size == signal_load_scope->read_size;
  }
  __imp__sub_8210C728(ctx, base);
  if (!valid || !ctx.r3.u32 || abort_reason.load() != StopReason::none) {
    if (!valid) Count(signal_record_map_invalid);
    return;
  }
  HostState state;
  TryTrace lock;
  if (lock && trace.stop == StopReason::none)
    MapSignalGroup(base, *signal_load_scope, group, group_object, stream, cursor);
}

extern "C" void sub_82298E78(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !load_scope || uint32_t(ctx.lr) != 0x8224e954)
    return __imp__sub_82298E78(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82298E78(ctx, base);
  Association association;
  if (load_scope->decoded) { Count(reentrant); Abort(StopReason::reentrant); }
  if (selected_ba.load() && selected_ba.load() == ctx.r3.u32) {
    Count(invalid); Abort(StopReason::identity_changed);
  }
  {
    HostState state;
    uint32_t address = 0, size = 0;
    if (!load_scope->read || !Field(base, ctx.r4.u32, 8, address) ||
        !Field(base, ctx.r4.u32, 12, size) || address != load_scope->read_address ||
        size != load_scope->read_size) {
      Count(invalid); Abort(StopReason::untracked_lifetime);
    }
  }
  load_scope->decoded = true;
  load_scope->decoded_ba = ctx.r3.u32;
  __imp__sub_82298E78(ctx, base);
}

extern "C" void sub_8224E6F0(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8224E6F0(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8224E6F0(ctx, base);
  struct BaSignalAttempt {
    bool pending;
    ~BaSignalAttempt() {
      if (!pending) return;
      HostState state;
      Count(signal_seen[size_t(SignalKind::ba_load)]);
      Count(signal_unreadable[size_t(SignalKind::ba_load)]);
    }
  } signal_attempt{signal_enabled.load(std::memory_order_relaxed)};
  const auto caller = uint32_t(ctx.lr);
  if (load_scope || (lifecycle_bits & kCollectActive)) {
    Count(reentrant); Abort(StopReason::reentrant);
    return __imp__sub_8224E6F0(ctx, base);
  }
  Association association;
  const auto manager = ctx.r3.u32;
  LoadScope local{};
  load_scope = &local;
  struct RestoreLoad { ~RestoreLoad() { load_scope = nullptr; } } restore;
  __imp__sub_8224E6F0(ctx, base);
  load_scope = nullptr;
  if (ctx.r3.u32 == UINT32_MAX || abort_reason.load() != StopReason::none) return;
  HostState state;
  SignalSample sample;
  sample.kind = SignalKind::ba_load;
  sample.caller = caller;
  {
    TryTrace lock;
    if (!lock || trace.stop != StopReason::none) return;
    const auto handle = ctx.r3.u32;
    uint32_t address = 0;
    if (handle >= ba_records.size() || !Field(base, manager, 26168 + handle * 4, address) || !address) {
      Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
      return;
    }
    auto& record = ba_records[handle];
    if (!local.decoded) {
      if (record.manager != manager || record.address != address || !record.generation) {
        trace.Count(trace.counters.cache_untracked);
        trace.Stop(StopReason::untracked_lifetime); Abort(StopReason::untracked_lifetime);
        return;
      }
      trace.Count(trace.counters.cache_hits);
    } else {
      if (local.decoded_ba != address || record.generation) {
        Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
        return;
      }
      for (const auto& other : ba_records) if (other.generation && other.address == address) {
        Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
        return;
      }
      const auto generation = trace.NextGeneration();
      if (!generation) { Abort(trace.stop); return; }
      record = {manager, address, generation, local.source};
    }
    sample.ba = address;
    sample.ba_handle = handle;
    sample.ba_generation = record.generation;
    sample.source = record.source;
    sample.loaded = true;
  }
  if (signal_attempt.pending) {
    signal_attempt.pending = false;
    if (BeginSignal(sample)) FinishSignal(sample);
  }
}

extern "C" void sub_8224E9B0(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8224E9B0(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8224E9B0(ctx, base);
  LifecycleScope lifecycle(kCollectActive);
  if (!lifecycle) return __imp__sub_8224E9B0(ctx, base);
  if (load_scope) { Count(reentrant); Abort(StopReason::reentrant); }
  Association association;
  if (abort_reason.load() == StopReason::none) {
    HostState state;
    TryTrace lock;
    if (lock && trace.stop == StopReason::none) {
      for (auto& record : ba_records) {
        if (!record.generation || record.manager != ctx.r3.u32) continue;
        uint32_t references = 0;
        if (!Field(base, record.address, 4, references)) {
          Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
          break;
        }
        if (std::bit_cast<int32_t>(references) > 0) continue;
        if (selected_ba.load() == record.address) {
          Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
        }
        record = {};
      }
    }
  }
  __imp__sub_8224E9B0(ctx, base);
}

extern "C" void sub_8229CF30(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8229CF30(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8229CF30(ctx, base);
  LifecycleScope lifecycle(kCreateActive);
  if (!lifecycle) return __imp__sub_8229CF30(ctx, base);
  if (lifecycle_bits & kCollectActive) { Count(reentrant); Abort(StopReason::reentrant); }
  Association association;
  const auto address = ctx.r3.u32;
  if (selected_instance.load() && selected_instance.load() == address) {
    Count(invalid); Abort(StopReason::identity_changed);
  }
  __imp__sub_8229CF30(ctx, base);
  if (abort_reason.load() != StopReason::none) return;
  HostState state;
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  uint32_t vtable = 0;
  if (!Field(base, address, 0, vtable) || vtable != kInstanceVtable) {
    Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
    return;
  }
  if (FindInstance(address)) {
    Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
    return;
  }
  InstanceRecord* record = nullptr;
  for (auto& candidate : instances) if (!candidate.address) { record = &candidate; break; }
  if (!record) { RegistryFull(); return; }
  const auto generation = trace.NextGeneration();
  if (!generation) { Abort(trace.stop); return; }
  *record = {address, generation};
}

namespace {
void BeforeInstanceRemoval(PPCContext& ctx, uint8_t* base) noexcept {
  const auto manager = ctx.r3.u32, handle = ctx.r4.u32;
  if (selected_manager.load() == manager && selected_instance.load() &&
      selected_handle.load() == handle) {
    Count(invalid); Abort(StopReason::identity_changed);
    return;
  }
  HostState state;
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  uint32_t count = 0, table = 0, address = 0;
  if (!Field(base, manager, 66268, count) || !Field(base, manager, 66272, table) ||
      count > 65536 || (count && !table)) {
    Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
    return;
  }
  if (handle >= count) return;
  if (!Field(base, table, handle * 4, address)) {
    Count(invalid); trace.Stop(StopReason::invalid_mapping); Abort(StopReason::invalid_mapping);
    return;
  }
  if (address && address == selected_instance.load()) {
    Count(invalid); trace.Stop(StopReason::identity_changed); Abort(StopReason::identity_changed);
    return;
  }
  if (auto* record = FindInstance(address)) *record = {};
}

void ObserveInstanceRemoval(PPCContext& ctx, uint8_t* base, Original original, uint32_t bit) {
  Flight flight;
  if (!flight) return original(ctx, base);
  LifecycleScope lifecycle(bit);
  if (!lifecycle) return original(ctx, base);
  Association association;
  if (abort_reason.load() == StopReason::none) BeforeInstanceRemoval(ctx, base);
  original(ctx, base);
}

void ObserveInstanceSubmission(PPCContext& ctx, uint8_t* base) {
  Flight flight;
  if (!flight) return __imp__sub_8224AC98(ctx, base);
  LifecycleScope lifecycle(kSubmitActive);
  if (!lifecycle) return __imp__sub_8224AC98(ctx, base);
  Association association;
  const bool selected = selected_instance.load(std::memory_order_acquire) &&
      selected_manager.load() == ctx.r3.u32 && selected_handle.load() == ctx.r4.u32;
  const auto check_identity = [&] {
    HostState state;
    TryTrace lock;
    if (!lock || trace.stop != StopReason::none) return;
    const auto status = trace.identity.actor ? Actor(base, trace.identity) :
                                             Instance(base, trace.identity);
    if (status != Check::ok) Invalid(status);
  };
  if (selected && abort_reason.load() == StopReason::none) check_identity();
  __imp__sub_8224AC98(ctx, base);
  if (selected && abort_reason.load() == StopReason::none) check_identity();
}
}

extern "C" void sub_8224AC98(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8224AC98(ctx, base);
  ObserveInstanceSubmission(ctx, base);
}

extern "C" void sub_82251D38(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82251D38(ctx, base);
  ObserveInstanceRemoval(ctx, base, __imp__sub_82251D38, kRemoveDirectActive);
}

extern "C" void sub_8224E0B8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8224E0B8(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8224E0B8(ctx, base);
  LifecycleScope lifecycle(kResetActive);
  if (!lifecycle) return __imp__sub_8224E0B8(ctx, base);
  Association association;
  if (selected_manager.load() == ctx.r3.u32 && selected_instance.load()) {
    Count(invalid); Abort(StopReason::identity_changed);
  } else if (abort_reason.load() == StopReason::none) {
    HostState state;
    TryTrace lock;
    if (lock && trace.stop == StopReason::none) {
      uint32_t count = 0, table = 0;
      if (!Field(base, ctx.r3.u32, 66268, count) ||
          !Field(base, ctx.r3.u32, 66272, table) ||
          count > 65536 || (count && !table)) {
        Invalid(Check::mapping);
      } else {
        for (uint32_t index = 0; index < count; ++index) {
          uint32_t address = 0;
          if (!Field(base, table, index * 4, address)) {
            Invalid(Check::mapping);
            break;
          }
          if (address && address == selected_instance.load()) {
            Invalid(Check::changed);
            break;
          }
          if (auto* record = FindInstance(address)) *record = {};
        }
      }
    }
  }
  __imp__sub_8224E0B8(ctx, base);
}

extern "C" void sub_82249FB0(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82249FB0(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82249FB0(ctx, base);
  LifecycleScope lifecycle(kManagerDestroyActive);
  if (!lifecycle) return __imp__sub_82249FB0(ctx, base);
  Association association;
  if (selected_manager.load() && selected_manager.load() == ctx.r3.u32) {
    Count(invalid); Abort(StopReason::identity_changed);
  }
  if (abort_reason.load() == StopReason::none) {
    HostState state;
    TryTrace lock;
    if (lock) {
      for (auto& record : ba_records) if (record.manager == ctx.r3.u32) record = {};
    }
  }
  __imp__sub_82249FB0(ctx, base);
}

extern "C" void sub_82093BE8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82093BE8(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82093BE8(ctx, base);
  Count(setup_calls);
  if (resource_scope.load(std::memory_order_relaxed)) {
    Count(setup_rejections[kScopeSkipped]);
    return __imp__sub_82093BE8(ctx, base);
  }
  LifecycleScope lifecycle(kSetupActive);
  if (!lifecycle) return __imp__sub_82093BE8(ctx, base);
  if (lifecycle_bits & kCollectActive) { Count(reentrant); Abort(StopReason::reentrant); }
  Association association;
  SetupInput input{};
  SignalSetupInput signal_input{};
  bool candidate = false;
  if (flight && abort_reason.load() == StopReason::none) {
    const auto chosen = selected_actor.load(std::memory_order_acquire);
    if (chosen && chosen == ctx.r3.u32) {
      Count(setup_rejections[kRepeatSelected]);
      Count(invalid);
      Abort(StopReason::identity_changed);
    } else if (!chosen) {
      HostState state;
      candidate = BeforeSetup(ctx, base, input);
    } else { Count(setup_rejections[kOtherAfterSelection]); Count(actor_filtered); }
  } else Count(after_stop);
  const bool observe_signal = candidate && signal_enabled.load(std::memory_order_relaxed);
  if (observe_signal) {
    HostState state;
    signal_input = BeforeSignalSetup(ctx, base);
  }
  __imp__sub_82093BE8(ctx, base);
  if (candidate) { HostState state; AfterSetup(base, input); }
  // Before selection only asset loads are retained; actor observations begin with
  // the setup that successfully selected the primary actor.
  if (observe_signal && SelectedSignalActor(input.actor)) {
    HostState state;
    AfterSignalSetup(base, signal_input);
  }
}

namespace {
void PopulateSignalActor(uint8_t* base, uint32_t actor, SignalSample& sample) noexcept {
  sample.actor = actor;
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  sample.identity_bound = SignalActorIdentity(base, actor, sample);
  if (!sample.signal) Field(base, actor, 312, sample.signal);
  if (!sample.info) Field(base, actor, 316, sample.info);
  if (!sample.signal_generation) {
    if (const auto* asset = FindSignalAsset(SignalKind::as_load, sample.signal))
      sample.signal_generation = asset->generation;
  }
  if (!sample.info_generation) {
    if (const auto* asset = FindSignalAsset(SignalKind::info_load, sample.info))
      sample.info_generation = asset->generation;
  }
}

void PopulateInfoGeneration(SignalSample& sample) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  if (const auto* asset = FindSignalAsset(SignalKind::info_load, sample.info))
    sample.info_generation = asset->generation;
}

bool ReadInfoRow(uint8_t* base, uint32_t info, int32_t row, SignalSample& sample) noexcept {
  uint32_t count = 0, table = 0, type = 0, index = 0, attribute = 0;
  if (row < 0 || !Field(base, info, 440, count) || count > 2048 ||
      uint32_t(row) >= count || !Field(base, info, 444, table) || !table ||
      uint64_t(table) + uint64_t(uint32_t(row)) * 32 > UINT32_MAX) return false;
  const auto address = table + uint32_t(row) * 32;
  if (!Field(base, address, 4, attribute) || !Field(base, address, 8, type) ||
      !Field(base, address, 12, index)) return false;
  sample.row_type = std::bit_cast<int32_t>(type);
  sample.row_index = std::bit_cast<int32_t>(index);
  sample.row_attribute = std::bit_cast<int32_t>(attribute);
  return true;
}

bool ReadSignalRecord(uint8_t* base, const SignalSample& group, uint32_t record,
                      SignalSample& sample) noexcept {
  uint32_t count = 0, groups = 0, group_count = 0, records = 0;
  if (!group.group_read || group.group_index == UINT32_MAX ||
      !Field(base, group.signal, 4, group_count) || group_count > 2048 ||
      group.group_index >= group_count || !Field(base, group.signal, 8, groups) || !groups ||
      uint64_t(groups) + uint64_t(group.group_index) * 12 > UINT32_MAX) return false;
  const auto group_address = groups + group.group_index * 12;
  if (!Field(base, group_address, 4, count) || count > 1000000 ||
      !Field(base, group_address, 8, records) || !records || record < records ||
      (record - records) % 20 || (record - records) / 20 >= count) return false;
  uint32_t time = 0, kind = 0, bounded = 0, words = 0;
  if (!Word(base, record, time) || !Field(base, record, 4, kind) ||
      !Field(base, record, 8, bounded) || !Field(base, record, 12, words)) return false;
  sample.retained_index = (record - records) / 20;
  sample.record_time = std::bit_cast<int32_t>(time);
  sample.record_kind = kind;
  sample.record_bounded = std::bit_cast<int32_t>(bounded);
  sample.record_words = words;
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return true;
  for (size_t i = 0; i < signal_record_count; ++i) {
    const auto& binding = signal_records[i];
    if (binding.address != record || binding.signal != group.signal ||
        binding.generation != group.signal_generation || binding.group != group.group_index ||
        binding.retained != sample.retained_index) continue;
    if (binding.kind == kind && binding.words == words && binding.time == sample.record_time &&
        binding.bounded == sample.record_bounded) {
      sample.source_offset = true;
      sample.group_offset = binding.group_offset;
      sample.table_offset = binding.table_offset;
      sample.record_offset = binding.record_offset;
    }
    break;
  }
  return true;
}

bool ReadActorByte(uint8_t* base, uint32_t actor, uint8_t& value) noexcept {
  const auto address = uint64_t(actor) + 1056;
  return address <= UINT32_MAX && Read(base, uint32_t(address), &value, 1);
}

bool ReadOccupancy(uint8_t* base, uint32_t manager, std::array<bool, 180>& result) noexcept {
  for (size_t i = 0; i < result.size(); ++i) {
    const auto address = uint64_t(manager) + 740 + uint64_t(i) * 96;
    uint8_t value = 0;
    if (address > UINT32_MAX || !Read(base, uint32_t(address), &value, 1)) return false;
    result[i] = value != 0;
  }
  return true;
}

void ObserveSignalDispatch(PPCContext& ctx, uint8_t* base, Original original, uint32_t path) {
  Flight flight;
  if (!flight || !signal_group_scope || !SelectedSignalActor(ctx.r3.u32) ||
      ctx.r3.u32 != signal_group_scope->actor) return original(ctx, base);
  if (signal_dispatch_scope) {
    SignalSample dropped;
    dropped.actor = ctx.r3.u32;
    bool inline_effect = false;
    {
      HostState state;
      SkipSignal(SignalKind::dispatch);
      inline_effect = path == 2 &&
          ReadSignalRecord(base, *signal_group_scope, ctx.r4.u32, dropped) &&
          dropped.record_kind == 24;
    }
    {
      PointerScope pointer(signal_dispatch_scope, &dropped);
      original(ctx, base);
    }
    if (inline_effect) { HostState state; SkipSignal(SignalKind::effect); }
    return;
  }
  Association association;
  auto* group = signal_group_scope;
  SignalSample sample;
  sample.kind = SignalKind::dispatch;
  sample.caller = uint32_t(ctx.lr);
  sample.actor = ctx.r3.u32;
  sample.actor_generation = group->actor_generation;
  sample.signal_generation = group->signal_generation;
  sample.group_read = group->group_read;
  sample.group_index = group->group_index;
  sample.dispatch_path = path;
  const auto record = ctx.r4.u32;
  bool sampled = false;
  uint8_t before = 0;
  bool effect_candidate = false, effect_read = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    sample.record_read = ReadSignalRecord(base, *group, record, sample);
    effect_candidate = sample.record_read && path == 2 && sample.record_kind == 24;
    effect_read = sampled && effect_candidate && ReadActorByte(base, sample.actor, before);
  }
  {
    PointerScope pointer(signal_dispatch_scope, &sample);
    if (sampled) {
      EventScope event(sample.event);
      original(ctx, base);
      if (effect_candidate) {
        HostState state;
        uint8_t after = 0;
        if (effect_read && ReadActorByte(base, sample.actor, after)) {
          SignalSample effect;
          effect.kind = SignalKind::effect;
          effect.caller = sample.caller;
          effect.actor = sample.actor;
          effect.actor_generation = sample.actor_generation;
          effect.effect_kind = 1;
          effect.changed_slots = before == after ? 0 : 1;
          if (BeginSignal(effect)) FinishSignal(effect);
        } else UnreadableSignal(SignalKind::effect);
      }
    } else {
      original(ctx, base);
      if (effect_candidate) {
        HostState state;
        SkipSignal(SignalKind::effect);
      }
    }
  }
  if (sampled) { HostState state; FinishSignal(sample); }
}
}

extern "C" void sub_82097868(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed))
    return __imp__sub_82097868(ctx, base);
  if (!SelectedSignalActor(ctx.r3.u32)) {
    SuspendSignalActorContext suspended;
    return __imp__sub_82097868(ctx, base);
  }
  Flight flight;
  if (!flight) return __imp__sub_82097868(ctx, base);
  Association association;
  SignalSample sample;
  sample.kind = SignalKind::request;
  sample.caller = uint32_t(ctx.lr);
  sample.actor = ctx.r3.u32;
  sample.requested_type = ctx.r4.s32;
  sample.requested_index = ctx.r5.s32;
  sample.requested_attribute = ctx.r6.s32;
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    if (sampled) PopulateSignalActor(base, sample.actor, sample);
  }
  {
    PointerScope pointer(signal_request_scope, &sample);
    if (sampled) {
      EventScope event(sample.event);
      __imp__sub_82097868(ctx, base);
    } else __imp__sub_82097868(ctx, base);
  }
  if (sampled) { HostState state; FinishSignal(sample); }
}

extern "C" void sub_8210CFE8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed) ||
      !signal_request_scope || !SelectedSignalActor(signal_request_scope->actor))
    return __imp__sub_8210CFE8(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8210CFE8(ctx, base);
  Association association;
  SignalSample sample;
  sample.kind = SignalKind::selection;
  sample.caller = uint32_t(ctx.lr);
  sample.info = ctx.r3.u32;
  sample.requested_type = ctx.r4.s32;
  sample.requested_index = ctx.r5.s32;
  sample.requested_attribute = ctx.r6.s32;
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    if (sampled) PopulateInfoGeneration(sample);
  }
  if (sampled) { EventScope event(sample.event); __imp__sub_8210CFE8(ctx, base); }
  else __imp__sub_8210CFE8(ctx, base);
  if (sampled) {
    HostState state;
    sample.selected_row = ctx.r3.s32;
    sample.row_read = ReadInfoRow(base, sample.info, sample.selected_row, sample);
    FinishSignal(sample);
  }
}

extern "C" void sub_82097958(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed) ||
      !SelectedSignalActor(ctx.r3.u32))
    return __imp__sub_82097958(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82097958(ctx, base);
  Association association;
  SignalSample sample;
  sample.kind = SignalKind::install;
  sample.caller = uint32_t(ctx.lr);
  sample.actor = ctx.r3.u32;
  sample.selected_row = ctx.r4.s32;
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    if (sampled) {
      PopulateSignalActor(base, sample.actor, sample);
      sample.row_read = ReadInfoRow(base, sample.info, sample.selected_row, sample);
    }
  }
  if (sampled) { EventScope event(sample.event); __imp__sub_82097958(ctx, base); }
  else __imp__sub_82097958(ctx, base);
  if (sampled) {
    HostState state;
    uint32_t installed = UINT32_MAX, info = 0;
    if (Field(base, sample.actor, 192, installed)) sample.installed_row = std::bit_cast<int32_t>(installed);
    if (!Field(base, sample.actor, 316, info) || info != sample.info) sample.row_read = false;
    FinishSignal(sample);
  }
}

extern "C" void sub_82097D00(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed) ||
      !SelectedSignalActor(ctx.r3.u32))
    return __imp__sub_82097D00(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82097D00(ctx, base);
  Association association;
  SignalSample sample;
  sample.kind = SignalKind::group;
  sample.caller = uint32_t(ctx.lr);
  sample.actor = ctx.r3.u32;
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    PopulateSignalActor(base, sample.actor, sample);
    sample.group_read = Field(base, sample.actor, 192, sample.group_index);
    sample.time_read = Field(base, sample.actor, 196, sample.actor_time) &&
        Field(base, sample.actor, 204, sample.actor_step_field) &&
        FiniteFloatBits(sample.actor_time) && FiniteFloatBits(sample.actor_step_field);
  }
  {
    PointerScope pointer(signal_group_scope, &sample);
    if (sampled) {
      EventScope event(sample.event);
      __imp__sub_82097D00(ctx, base);
    } else __imp__sub_82097D00(ctx, base);
  }
  if (sampled) { HostState state; FinishSignal(sample); }
}

#define SIGNAL_DISPATCH(address, path) \
  extern "C" void sub_##address(PPCContext& ctx, uint8_t* base) { \
    if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed)) \
      return __imp__sub_##address(ctx, base); \
    ObserveSignalDispatch(ctx, base, __imp__sub_##address, path); \
  }
SIGNAL_DISPATCH(82097D90, 1)
SIGNAL_DISPATCH(820927C0, 2)
SIGNAL_DISPATCH(8209BE30, 3)
#undef SIGNAL_DISPATCH

extern "C" void sub_8212ACA8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve() || !signal_enabled.load(std::memory_order_relaxed) ||
      !signal_dispatch_scope || !SelectedSignalActor(signal_dispatch_scope->actor) ||
      uint32_t(ctx.lr) != 0x8212aca0)
    return __imp__sub_8212ACA8(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_8212ACA8(ctx, base);
  if (!current_event || !signal_dispatch_scope->event.id ||
      current_event->id != signal_dispatch_scope->event.id) {
    { HostState state; SkipSignal(SignalKind::effect); }
    return __imp__sub_8212ACA8(ctx, base);
  }
  Association association;
  SignalSample sample;
  sample.kind = SignalKind::effect;
  sample.caller = uint32_t(ctx.lr);
  sample.actor = signal_dispatch_scope->actor;
  sample.actor_generation = signal_dispatch_scope->actor_generation;
  sample.effect_kind = 2;
  const auto manager = ctx.r3.u32;
  std::array<bool, 180> before{}, after{};
  bool sampled = false;
  {
    HostState state;
    sampled = BeginSignal(sample);
    if (sampled && !ReadOccupancy(base, manager, before)) {
      AbandonSignal(sample);
      sampled = false;
    }
  }
  if (sampled) { EventScope event(sample.event); __imp__sub_8212ACA8(ctx, base); }
  else __imp__sub_8212ACA8(ctx, base);
  if (sampled) {
    HostState state;
    if (!ReadOccupancy(base, manager, after)) AbandonSignal(sample);
    else {
      for (size_t i = 0; i < before.size(); ++i) sample.changed_slots += before[i] != after[i];
      FinishSignal(sample);
    }
  }
}

extern "C" void sub_82080158(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82080158(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82080158(ctx, base);
  Count(controller_calls);
  const auto chosen = selected_actor.load(std::memory_order_acquire);
  if (!chosen) { Count(unselected); return __imp__sub_82080158(ctx, base); }
  if (ctx.r3.u32 != chosen) { Count(actor_filtered); return __imp__sub_82080158(ctx, base); }
  if (in_controller) {
    Count(reentrant); Abort(StopReason::reentrant);
    return __imp__sub_82080158(ctx, base);
  }
  in_controller = true;
  struct RestoreController { ~RestoreController() { in_controller = false; } } restore;
  Association association;
  Activity active(active_controllers);
  if (active.previous()) { Count(concurrent); Abort(StopReason::concurrent_actor); }
  ControllerSample sample{};
  bool sampled = false;
  if (abort_reason.load() == StopReason::none) {
    HostState state; sampled = BeforeController(base, uint32_t(ctx.lr), sample);
  } else Count(after_stop);
  if (sampled) { EventScope event(sample.event); __imp__sub_82080158(ctx, base); }
  else __imp__sub_82080158(ctx, base);
  if (sampled) { HostState state; AfterController(base, sample); }
}

extern "C" void sub_82252BD8(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82252BD8(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82252BD8(ctx, base);
  Count(queue_calls);
  if (resource_scope.load(std::memory_order_relaxed) && !IdentitySelected()) {
    if (abort_reason.load() == StopReason::none) {
      Association association;
      HostState state; BindResource(ctx, base);
    }
  }
  if (!IdentitySelected()) {
    Count(unselected); return __imp__sub_82252BD8(ctx, base);
  }
  if (ctx.r3.u32 != selected_manager.load() || ctx.r4.u32 != selected_handle.load()) {
    Count(actor_filtered); return __imp__sub_82252BD8(ctx, base);
  }
  if (in_queue) {
    Count(reentrant); Abort(StopReason::reentrant);
    return __imp__sub_82252BD8(ctx, base);
  }
  in_queue = true;
  struct RestoreQueue { ~RestoreQueue() { in_queue = false; } } restore;
  Association association;
  QueueSample sample{};
  bool sampled = false;
  if (abort_reason.load() == StopReason::none) { HostState state; sampled = BeforeQueue(ctx, base, sample); }
  else Count(after_stop);
  if (sampled) { EventScope event(sample.event); __imp__sub_82252BD8(ctx, base); }
  else __imp__sub_82252BD8(ctx, base);
  if (sampled) { HostState state; AfterQueue(base, sample); }
}

extern "C" void sub_82249628(PPCContext& ctx, uint8_t* base) {
  if (pose_scope) {
    HostState state;
    if (ctx.r3.u32 != pose_scope->instance || uint32_t(ctx.lr) != kPoseReturn ||
        ctx.r5.u32 >= pose_scope->bones || !Mapped(base, ctx.r4.u32, 64)) {
      if (pose_scope->invalid != UINT32_MAX) ++pose_scope->invalid;
      else { counter_saturated = true; Abort(StopReason::counter_overflow); }
      Count(invalid_outputs);
#ifdef N3_ANIMATION_TRACE_TEST
      if (pause_invalid_output_for_test.load(std::memory_order_acquire)) {
        invalid_output_paused_for_test.store(true, std::memory_order_release);
        while (pause_invalid_output_for_test.load(std::memory_order_acquire)) Sleep(1);
      }
#endif
      Count(invalid);
      Abort(StopReason::invalid_mapping);
    } else if (pose_scope->outputs >= pose_scope->bones) {
      Count(pose_outputs);
      Count(invalid);
      Abort(StopReason::invalid_value);
    } else {
      if (pose_scope->outputs != UINT32_MAX) ++pose_scope->outputs;
      else { counter_saturated = true; Abort(StopReason::counter_overflow); }
      Count(pose_outputs);
    }
  }
  __imp__sub_82249628(ctx, base);
}

extern "C" void sub_82298FF0(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_82298FF0(ctx, base);
  Flight flight;
  if (!flight) return __imp__sub_82298FF0(ctx, base);
  Count(evaluation_calls);
  auto* previous = pose_scope;
  if (previous || in_evaluation) { Count(reentrant); Abort(StopReason::reentrant); }
  if (!IdentitySelected() || ctx.r3.u32 != selected_ba.load()) {
    if (!IdentitySelected()) Count(unselected); else Count(actor_filtered);
    struct RestorePose { PoseScope* saved; ~RestorePose() { pose_scope = saved; } } restore{previous};
    pose_scope = nullptr;
    __imp__sub_82298FF0(ctx, base);
    return;
  }
  if (in_evaluation) {
    struct RestorePose { PoseScope* saved; ~RestorePose() { pose_scope = saved; } } restore{pose_scope};
    pose_scope = nullptr;
    return __imp__sub_82298FF0(ctx, base);
  }
  in_evaluation = true;
  struct RestoreEvaluation { ~RestoreEvaluation() { in_evaluation = false; } } restore_evaluation;
  Association association;
  Activity active(active_ba_evaluations);
  struct ActiveScope {
    PoseScope* previous;
    ~ActiveScope() { pose_scope = previous; }
  } active_scope{previous};
  pose_scope = nullptr;
  if (active.previous()) { Count(concurrent); Abort(StopReason::concurrent_shared_ba); }
  EvaluationSample sample{};
  bool sampled = false;
  if (ctx.r4.u32 != selected_instance.load()) Count(actor_filtered);
  else if (abort_reason.load() == StopReason::none) { HostState state; sampled = BeforeEvaluation(ctx, base, sample); }
  else Count(after_stop);
  PoseScope scope{ctx.r4.u32, ctx.r3.u32, 0};
  if (sampled) {
    scope.bones = trace.identity.bones;
    pose_scope = &scope;
  }
  if (sampled) { EventScope event(sample.event); __imp__sub_82298FF0(ctx, base); }
  else __imp__sub_82298FF0(ctx, base);
  pose_scope = nullptr;
  if (sampled) { HostState state; AfterEvaluation(base, sample, scope); }
}

extern "C" void sub_8229CA98(PPCContext& ctx, uint8_t* base) {
  const auto caller = uint32_t(ctx.lr);
  if (!quaternion_enabled.load(std::memory_order_relaxed) || !pose_scope ||
      (caller != 0x8229a214 && caller != 0x8229a5d0 &&
       caller != 0x8229a6a4 && caller != 0x8229a868))
    return __imp__sub_8229CA98(ctx, base);
  auto* scope = pose_scope;
  QuaternionSample sample{};
  bool pending = false;
  {
    HostState state;
    Count(quaternion_seen);
    if (ctx.r25.u32 != scope->ba || ctx.r22.u32 != scope->instance ||
        ctx.r24.u32 >= scope->bones || !current_event) {
      Count(quaternion_invalid_context);
    } else if (scope->quaternion_count == kQuaternionPerEvaluationCapacity) {
      Count(quaternion_per_evaluation_full);
    } else {
      sample.caller = caller;
      sample.bone = ctx.r24.u32;
      sample.factor = ctx.v3.u32[3];
      bool valid = FiniteFloatBits(sample.factor);
      for (size_t i = 0; i < 4; ++i) {
        sample.left[i] = ctx.v1.u32[i ^ 3];
        sample.right[i] = ctx.v2.u32[i ^ 3];
        valid = valid && FiniteFloatBits(sample.left[i]) && FiniteFloatBits(sample.right[i]) &&
                ctx.v3.u32[i] == sample.factor;
      }
      if (!valid || !Tick(sample.event.begin)) Count(quaternion_invalid_input);
      else pending = true;
    }
  }
  __imp__sub_8229CA98(ctx, base);
  if (pending) {
    HostState state;
    bool valid = pose_scope == scope && Tick(sample.event.end);
    for (size_t i = 0; i < 4; ++i) {
      sample.result[i] = ctx.v1.u32[i ^ 3];
      valid = valid && FiniteFloatBits(sample.result[i]);
    }
    if (!valid) Count(quaternion_invalid_output);
    else scope->quaternion[scope->quaternion_count++] = sample;
  }
}

namespace {
void ObserveSetupWrapper(PPCContext& ctx, uint8_t* base, Original original, size_t index) {
  Flight flight;
  if (flight) { HostState state; Count(setup_wrapper_calls[index]); }
  original(ctx, base);
}
}

#define SETUP_WRAPPER(address, index) \
  extern "C" void sub_##address(PPCContext& ctx, uint8_t* base) { \
    if (!CanObserve()) return __imp__sub_##address(ctx, base); \
    ObserveSetupWrapper(ctx, base, __imp__sub_##address, index); \
  }
SETUP_WRAPPER(820A4648, 0)
SETUP_WRAPPER(820AF768, 1)
SETUP_WRAPPER(8208D878, 2)
SETUP_WRAPPER(820AAFB0, 3)
SETUP_WRAPPER(820A2968, 4)
#undef SETUP_WRAPPER

extern "C" void sub_8217AD08(PPCContext& ctx, uint8_t* base) {
  if (!CanObserve()) return __imp__sub_8217AD08(ctx, base);
  Flight flight;
  if (flight) {
    HostState state;
    Count(dispatch_calls);
    uint8_t flag = 0;
    uint32_t handle = 0;
    const auto flag_address = uint64_t(ctx.r3.u32) + 112;
    if (flag_address > UINT32_MAX || !Read(base, uint32_t(flag_address), &flag, 1))
      Count(dispatch_unreadable);
    else if (!flag)
      Count(dispatch_flag_zero);
    else if (!Field(base, ctx.r3.u32, 28, handle))
      Count(dispatch_unreadable);
    else if (handle == UINT32_MAX)
      Count(dispatch_handle_minus_one);
    else
      Count(dispatch_eligible);
  }
  __imp__sub_8217AD08(ctx, base);
}

namespace {
enum class EnvironmentResult { missing, valid, invalid };
EnvironmentResult Environment(const char* name, char* buffer, DWORD capacity) {
  SetLastError(ERROR_SUCCESS);
  const auto length = GetEnvironmentVariableA(name, buffer, capacity);
  if (!length) return GetLastError() == ERROR_ENVVAR_NOT_FOUND ?
      EnvironmentResult::missing : EnvironmentResult::invalid;
  return length < capacity ? EnvironmentResult::valid : EnvironmentResult::invalid;
}
}

void InitializeAnimationTrace(const std::filesystem::path& game_root,
                              const std::filesystem::path& user_root) {
  std::array<char, 16> on{}, actor{}, clip{}, scope{}, quaternion{}, signal{}, attachment{};
  if (Environment("N3_ANIM_TRACE", on.data(), DWORD(on.size())) != EnvironmentResult::valid ||
      std::strcmp(on.data(), "1")) return;
  Filter filter;
  const auto actor_result = Environment("N3_ANIM_TRACE_ACTOR", actor.data(), DWORD(actor.size()));
  const auto clip_result = Environment("N3_ANIM_TRACE_CLIP", clip.data(), DWORD(clip.size()));
  const auto scope_result = Environment("N3_ANIM_TRACE_SCOPE", scope.data(), DWORD(scope.size()));
  const auto quaternion_result =
      Environment("N3_ANIM_TRACE_QUATERNION", quaternion.data(), DWORD(quaternion.size()));
  const auto signal_result =
      Environment("N3_ANIM_TRACE_SIGNAL", signal.data(), DWORD(signal.size()));
  const auto attachment_result =
      Environment("N3_ANIM_TRACE_ATTACHMENT", attachment.data(), DWORD(attachment.size()));
  if (actor_result == EnvironmentResult::invalid || clip_result == EnvironmentResult::invalid ||
      scope_result == EnvironmentResult::invalid || quaternion_result == EnvironmentResult::invalid ||
      signal_result == EnvironmentResult::invalid || attachment_result == EnvironmentResult::invalid ||
      (quaternion_result == EnvironmentResult::valid && std::strcmp(quaternion.data(), "1")) ||
      (signal_result == EnvironmentResult::valid && std::strcmp(signal.data(), "1")) ||
      (attachment_result == EnvironmentResult::valid && std::strcmp(attachment.data(), "1")) ||
      !ParseActor(actor_result == EnvironmentResult::missing ? "first" : actor.data(), filter.actor) ||
      !ParseClip(clip_result == EnvironmentResult::missing ? "all" : clip.data(), filter.clip) ||
      !ParseScope(scope_result == EnvironmentResult::missing ? "actor" : scope.data(), filter.scope) ||
      (filter.scope == Scope::resource && filter.actor)) {
    REXLOG_WARN("Animation trace disabled: invalid scope, actor or clip filter");
    return;
  }
  try {
    n3::data::VerifyGameFolder(game_root);
    output_path = user_root / "animation-trace-v3.json";
    attachment_output_path = user_root / "attachment-probe-v1.json";
    timeout_output_path = user_root / "animation-trace-timeout-v1.json";
    if (!std::filesystem::is_directory(user_root) || std::filesystem::exists(output_path) ||
        std::filesystem::exists(timeout_output_path) ||
        (attachment_result == EnvironmentResult::valid &&
         std::filesystem::exists(attachment_output_path))) {
      REXLOG_WARN("Animation trace disabled: output directory missing or capture already exists");
      return;
    }
    Reset(filter, quaternion_result == EnvironmentResult::valid,
          signal_result == EnvironmentResult::valid,
          attachment_result == EnvironmentResult::valid);
    REXLOG_INFO("Bounded animation trace enabled for the verified game executable");
  } catch (const std::exception&) {
    REXLOG_WARN("Animation trace disabled: game verification or output setup failed");
  }
}

namespace {
bool StopAdmission() noexcept {
  if (!enabled.exchange(false, std::memory_order_acq_rel)) return false;
  inflight.fetch_or(kAdmissionClosed, std::memory_order_acq_rel);
  return true;
}

bool DrainAdmission(uint32_t timeout_ms, uint32_t* inflight_on_timeout = nullptr) noexcept {
  if (inflight_on_timeout) *inflight_on_timeout = 0;
  const auto start = GetTickCount64();
  while (FlightsInProgress()) {
    if (GetTickCount64() - start >= timeout_ms) {
      const auto remaining = FlightsInProgress();
      if (!remaining) return true;
      if (inflight_on_timeout) *inflight_on_timeout = remaining;
      Count(concurrent);
      Abort(StopReason::concurrent_probe);
      return false;
    }
    Sleep(1);
  }
  return true;
}

bool WriteCapture(const std::filesystem::path& path, const char* data, size_t count) {
  const auto file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
      FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) return false;
  DWORD written = 0;
  const bool ok = WriteFile(file, data, static_cast<DWORD>(count), &written, nullptr) &&
      written == count && FlushFileBuffers(file);
  CloseHandle(file);
  if (!ok) DeleteFileW(path.c_str());
  return ok;
}
}

void ShutdownAnimationTrace() {
  if (!StopAdmission()) return;
  uint32_t inflight_on_timeout = 0;
  if (!DrainAdmission(2000, &inflight_on_timeout)) {
    trace_open.store(false, std::memory_order_release);
    std::array<char, 256> diagnostic{};
    size_t size = 0;
    if (!SerializeDrainTimeout(inflight_on_timeout, diagnostic.data(), diagnostic.size(), size) ||
        !WriteCapture(timeout_output_path, diagnostic.data(), size))
      REXLOG_WARN("Animation trace drain-timeout diagnostic could not be flushed");
    else REXLOG_WARN(
        "Animation trace drain timed out; incomplete animation-trace-timeout-v1.json flushed");
    return;
  }
  std::unique_ptr<Trace> snapshot;
  std::unique_ptr<std::array<char, kSerializedCapacity>> output;
  try {
    snapshot = std::make_unique<Trace>();
    output = std::make_unique<std::array<char, kSerializedCapacity>>();
  } catch (const std::bad_alloc&) {
    trace_open.store(false, std::memory_order_release);
    REXLOG_WARN("Animation trace shutdown could not allocate its bounded snapshot");
    return;
  }
  bool locked = false;
  for (unsigned i = 0; i < 2000; ++i) {
    if (!trace_lock.test_and_set(std::memory_order_acquire)) { locked = true; break; }
    Sleep(1);
  }
  if (!locked) {
    trace_open.store(false);
    REXLOG_WARN("Animation trace shutdown could not acquire its bounded snapshot");
    return;
  }
  trace_open.store(false, std::memory_order_release);
  *snapshot = trace;
  CopyCounters(*snapshot);
  snapshot->Stop(StopReason::shutdown);
  trace_lock.clear(std::memory_order_release);
  size_t size = 0;
  if (snapshot->attachment.enabled) {
    if (!SerializeAttachment(snapshot->attachment, snapshot->stop, output->data(),
                             output->size(), size) ||
        !WriteCapture(attachment_output_path, output->data(), size))
      REXLOG_WARN("Attachment resolver aggregate could not be flushed");
    else REXLOG_INFO("Bounded attachment resolver aggregate flushed");
  }
  if (!Serialize(*snapshot, output->data(), output->size(), size)) {
    REXLOG_WARN("Animation trace serialization exceeded its bounds");
    return;
  }
  if (!WriteCapture(output_path, output->data(), size)) {
    REXLOG_WARN("Animation trace output could not be flushed");
  } else REXLOG_INFO("Bounded animation trace flushed");
}

#ifdef N3_ANIMATION_TRACE_TEST
void ConfigureAnimationTraceForTest(Filter filter, bool quaternion, bool signal, bool attachment) {
  Reset(filter, quaternion, signal, attachment);
}
void StopAnimationTraceAdmissionForTest() { StopAdmission(); }
bool DrainAnimationTraceForTest(uint32_t timeout_ms) { return DrainAdmission(timeout_ms); }
void PauseAnimationTraceInvalidOutputForTest(bool pause) {
  pause_invalid_output_for_test.store(pause, std::memory_order_release);
}
bool AnimationTraceInvalidOutputPausedForTest() {
  return invalid_output_paused_for_test.load(std::memory_order_acquire);
}
void SetAnimationTraceOutputsForTest(const std::filesystem::path& prefix) {
  output_path = prefix; output_path += ".trace.json";
  attachment_output_path = prefix; attachment_output_path += ".attachment.json";
  timeout_output_path = prefix; timeout_output_path += ".timeout.json";
}
void SetAttachmentHashBytesForTest(uint64_t bytes) { trace.attachment.hash_bytes = bytes; }
const Trace& AnimationTraceSnapshotForTest() {
  static Trace snapshot;
  snapshot = trace;
  CopyCounters(snapshot);
  return snapshot;
}
bool AnimationTraceReadForTest(uint8_t* base, uint32_t address, void* output, uint32_t size) {
  HostState state;
  return Read(base, address, output, size);
}
#endif
