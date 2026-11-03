#include "animation_trace.h"
#include "animation_trace_model.h"
#include "game_data.h"
#include "guest_memory_address.h"

#include <Windows.h>
#include <rex/logging.h>
#include <rex/ppc.h>
#include <xmmintrin.h>
#include <array>
#include <atomic>
#include <bit>
#include <cfenv>
#include <cerrno>
#include <cstring>
#include <limits>

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
std::atomic<bool> enabled{false}, trace_open{false};
std::atomic<bool> resource_scope{false};
std::atomic_flag trace_lock = ATOMIC_FLAG_INIT;
std::atomic<uint32_t> selected_actor{0}, selected_manager{0}, selected_handle{0};
std::atomic<uint32_t> selected_instance{0}, selected_ba{0};
std::atomic<uint32_t> inflight{0}, active_controllers{0}, active_ba_evaluations{0};
std::atomic<StopReason> abort_reason{StopReason::none};
std::atomic<uint64_t> setup_calls{0}, controller_calls{0}, queue_calls{0}, evaluation_calls{0};
std::atomic<uint64_t> actor_filtered{0}, unselected{0}, invalid{0}, reentrant{0};
std::atomic<uint64_t> concurrent{0}, after_stop{0}, lock_dropped{0};
std::atomic<uint64_t> pose_outputs{0}, invalid_outputs{0};

struct PoseScope {
  uint32_t instance, bones, outputs = 0, invalid = 0;
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

class Flight {
 public:
  Flight() noexcept {
    if (!enabled.load(std::memory_order_acquire)) return;
    inflight.fetch_add(1, std::memory_order_acq_rel);
    if (!enabled.load(std::memory_order_acquire)) {
      inflight.fetch_sub(1, std::memory_order_release);
      return;
    }
    active_ = true;
  }
  ~Flight() { if (active_) inflight.fetch_sub(1, std::memory_order_release); }
  explicit operator bool() const { return active_; }
 private:
  bool active_ = false;
};

void Abort(StopReason reason) noexcept {
  auto expected = StopReason::none;
  abort_reason.compare_exchange_strong(expected, reason);
}

class TryTrace {
 public:
  TryTrace() noexcept {
    if (trace_lock.test_and_set(std::memory_order_acquire)) {
      lock_dropped.fetch_add(1);
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

Check Instance(uint8_t* base, const Identity& id) noexcept {
  uint32_t manager = 0, count = 0, table = 0, instance = 0, vtable = 0;
  uint32_t handle = 0, ba_handle = 0, ba = 0, ba_vtable = 0, manager_ba = 0;
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
  if (!Field(base, ba, 0, ba_vtable) ||
      !Field(base, manager, 26168 + id.ba_handle * 4, manager_ba))
    return Check::mapping;
  if (ba_vtable != kBaVtable || manager_ba != ba)
    return Check::changed;
  return Check::ok;
}

Check Actor(uint8_t* base, const Identity& id) noexcept {
  uint32_t vtable = 0, handle = 0, signal = 0, info = 0, getter = 0;
  if (!Field(base, id.actor, 0, vtable) || !Field(base, id.actor, 16, handle) ||
      !Field(base, id.actor, 312, signal) || !Field(base, id.actor, 316, info) ||
      !Field(base, vtable, 44, getter)) return Check::mapping;
  if (vtable != id.actor_vtable || handle != id.instance_handle || signal != id.signal ||
      info != id.info || getter != kStepGetter) return Check::changed;
  return Instance(base, id);
}

void Invalid(Check check) noexcept {
  invalid.fetch_add(1);
  Abort(check == Check::mapping ? StopReason::invalid_mapping : StopReason::identity_changed);
}

struct SetupInput {
  uint32_t actor = 0, vtable = 0, ba_handle = 0, signal_index = 0, info_index = 0;
};

bool BeforeSetup(PPCContext& ctx, uint8_t* base, SetupInput& input) noexcept {
  input.actor = ctx.r3.u32;
  if (!MatchesActor(trace.filter, input.actor)) { actor_filtered.fetch_add(1); return false; }
  if (!Field(base, input.actor, 0, input.vtable) ||
      !Field(base, ctx.r4.u32, 48, input.ba_handle) ||
      !Field(base, ctx.r4.u32, 52, input.signal_index) ||
      !Field(base, ctx.r4.u32, 56, input.info_index)) {
    invalid.fetch_add(1); return false;
  }
  if (!ValidActorVtable(input.vtable) || input.ba_handle >= 1000) {
    actor_filtered.fetch_add(1); return false;
  }
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
  return Instance(base, id) == Check::ok;
}

void AfterSetup(uint8_t* base, const SetupInput& input) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || trace.selected) return;
  Identity identity{};
  if (!MakeIdentity(base, input, identity)) { invalid.fetch_add(1); return; }
  trace.identity = identity;
  trace.selected = true;
  ++trace.counters.setup_accepted;
  selected_manager.store(identity.manager);
  selected_handle.store(identity.instance_handle);
  selected_instance.store(identity.instance);
  selected_ba.store(identity.ba);
  selected_actor.store(identity.actor, std::memory_order_release);
}

void BindResource(PPCContext& ctx, uint8_t* base) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || trace.selected) return;
  Identity identity{};
  uint32_t count = 0, table = 0;
  identity.instance_handle = ctx.r4.u32;
  if (!Word(base, kManagerGlobal, identity.manager) || !identity.manager ||
      ctx.r3.u32 != identity.manager ||
      !Field(base, identity.manager, 66268, count) ||
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
      Instance(base, identity) != Check::ok) {
    invalid.fetch_add(1);
    return;
  }
  trace.identity = identity;
  trace.selected = true;
  ++trace.counters.resource_bindings;
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
  if (state.clip == UINT32_MAX) { unselected.fetch_add(1); return false; }
  if (state.clip >= id.clips || state.clip >= id.signal_groups || state.clip >= id.info_rows ||
      !FiniteFloatBits(state.current) || !FiniteFloatBits(state.previous) ||
      !FiniteFloatBits(state.step)) {
    invalid.fetch_add(1); Abort(StopReason::invalid_value); return false;
  }
  return true;
}

bool BeforeController(uint8_t* base, ActorState& state) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none || !trace.selected) return false;
  return ReadActorState(base, trace.identity, state);
}

void AfterController(uint8_t* base, uint32_t caller, const ActorState& before) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  ActorState after{};
  if (!ReadActorState(base, trace.identity, after)) return;
  trace.AddController({caller, before.clip, after.clip, before.current, after.current, before.step});
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

void BeforeQueue(PPCContext& ctx, uint8_t* base) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  const auto status = Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); return; }
  const auto clip = ctx.r5.u32;
  if (trace.filter.scope == Scope::actor &&
      (clip >= trace.identity.signal_groups || clip >= trace.identity.info_rows)) {
    invalid.fetch_add(1); Abort(StopReason::invalid_value); return;
  }
  trace.AddQueue({uint32_t(ctx.lr), clip, ctx.f1.u64});
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

bool BeforeEvaluation(PPCContext& ctx, uint8_t* base, EvaluationSample& sample) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return false;
  const auto status = Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); return false; }
  sample.caller = uint32_t(ctx.lr);
  if (!Field(base, trace.identity.instance, 228, sample.queue_count) ||
      !Field(base, trace.identity.instance, 232, sample.clip) ||
      !Field(base, trace.identity.instance, 252, sample.time)) {
    Invalid(Check::mapping); return false;
  }
  if (!sample.queue_count) { unselected.fetch_add(1); return false; }
  if (sample.queue_count > 5 || sample.clip >= trace.identity.clips ||
      (trace.filter.scope == Scope::actor &&
       (sample.clip >= trace.identity.signal_groups || sample.clip >= trace.identity.info_rows)) ||
      !FiniteFloatBits(sample.time)) {
    invalid.fetch_add(1); Abort(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(trace.filter, sample.clip)) { ++trace.counters.clip_filtered; return false; }
  return true;
}

void AfterEvaluation(uint8_t* base, EvaluationSample sample, const PoseScope& scope) noexcept {
  TryTrace lock;
  if (!lock || trace.stop != StopReason::none) return;
  const auto status = Instance(base, trace.identity);
  if (status != Check::ok) { Invalid(status); return; }
  sample.pose_outputs = scope.outputs;
  sample.invalid_outputs = scope.invalid;
  trace.AddEvaluation(sample);
  if (trace.stop != StopReason::none) Abort(trace.stop);
}

void Reset(Filter filter) {
  trace = Trace{};
  trace.filter = filter;
  resource_scope.store(filter.scope == Scope::resource, std::memory_order_relaxed);
  selected_actor = selected_manager = selected_handle = selected_instance = selected_ba = 0;
  inflight = active_controllers = active_ba_evaluations = 0;
  abort_reason = StopReason::none;
  setup_calls = controller_calls = queue_calls = evaluation_calls = 0;
  actor_filtered = unselected = invalid = reentrant = concurrent = after_stop = lock_dropped = 0;
  pose_outputs = invalid_outputs = 0;
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
  target.counters.invalid += invalid.load();
  target.counters.reentrant = reentrant.load();
  target.counters.concurrent = concurrent.load();
  target.counters.after_stop += after_stop.load();
  target.counters.lock_dropped = lock_dropped.load();
  target.counters.pose_outputs = pose_outputs.load();
  target.counters.invalid_outputs = invalid_outputs.load();
  target.counters.inflight_at_flush = inflight.load();
  const auto reason = abort_reason.load();
  if (reason != StopReason::none) target.Stop(reason);
}
}  // namespace

extern "C" void __imp__sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82080158(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void __imp__sub_82249628(PPCContext&, uint8_t*);

extern "C" void sub_82093BE8(PPCContext& ctx, uint8_t* base) {
  if (!enabled.load(std::memory_order_acquire)) return __imp__sub_82093BE8(ctx, base);
  setup_calls.fetch_add(1);
  if (resource_scope.load(std::memory_order_relaxed)) return __imp__sub_82093BE8(ctx, base);
  Flight flight;
  SetupInput input{};
  bool candidate = false;
  if (flight && abort_reason.load() == StopReason::none) {
    const auto chosen = selected_actor.load(std::memory_order_acquire);
    if (!chosen || chosen == ctx.r3.u32) {
      HostState state;
      candidate = BeforeSetup(ctx, base, input);
    } else actor_filtered.fetch_add(1);
  } else after_stop.fetch_add(1);
  __imp__sub_82093BE8(ctx, base);
  if (candidate) { HostState state; AfterSetup(base, input); }
}

extern "C" void sub_82080158(PPCContext& ctx, uint8_t* base) {
  if (!enabled.load(std::memory_order_acquire)) return __imp__sub_82080158(ctx, base);
  controller_calls.fetch_add(1);
  const auto chosen = selected_actor.load(std::memory_order_acquire);
  if (!chosen) { unselected.fetch_add(1); return __imp__sub_82080158(ctx, base); }
  if (ctx.r3.u32 != chosen) { actor_filtered.fetch_add(1); return __imp__sub_82080158(ctx, base); }
  Flight flight;
  if (!flight) return __imp__sub_82080158(ctx, base);
  const auto active = active_controllers.fetch_add(1);
  struct ActiveController { ~ActiveController() { active_controllers.fetch_sub(1); } } active_controller;
  if (active) { concurrent.fetch_add(1); Abort(StopReason::concurrent_actor); }
  ActorState before{};
  const auto caller = uint32_t(ctx.lr);
  bool sampled = false;
  if (abort_reason.load() == StopReason::none) { HostState state; sampled = BeforeController(base, before); }
  else after_stop.fetch_add(1);
  __imp__sub_82080158(ctx, base);
  if (sampled) { HostState state; AfterController(base, caller, before); }
}

extern "C" void sub_82252BD8(PPCContext& ctx, uint8_t* base) {
  if (!enabled.load(std::memory_order_acquire)) return __imp__sub_82252BD8(ctx, base);
  queue_calls.fetch_add(1);
  if (resource_scope.load(std::memory_order_relaxed) && !IdentitySelected()) {
    Flight flight;
    if (flight && abort_reason.load() == StopReason::none) { HostState state; BindResource(ctx, base); }
  }
  if (!IdentitySelected()) {
    unselected.fetch_add(1); return __imp__sub_82252BD8(ctx, base);
  }
  if (ctx.r3.u32 != selected_manager.load() || ctx.r4.u32 != selected_handle.load()) {
    actor_filtered.fetch_add(1); return __imp__sub_82252BD8(ctx, base);
  }
  Flight flight;
  if (flight && abort_reason.load() == StopReason::none) { HostState state; BeforeQueue(ctx, base); }
  else after_stop.fetch_add(1);
  __imp__sub_82252BD8(ctx, base);
}

extern "C" void sub_82249628(PPCContext& ctx, uint8_t* base) {
  if (pose_scope) {
    HostState state;
    if (ctx.r3.u32 != pose_scope->instance || uint32_t(ctx.lr) != kPoseReturn ||
        ctx.r5.u32 >= pose_scope->bones || !Mapped(base, ctx.r4.u32, 64)) {
      ++pose_scope->invalid;
      invalid_outputs.fetch_add(1);
      invalid.fetch_add(1);
      Abort(StopReason::invalid_mapping);
    } else {
      ++pose_scope->outputs;
      pose_outputs.fetch_add(1);
    }
  }
  __imp__sub_82249628(ctx, base);
}

extern "C" void sub_82298FF0(PPCContext& ctx, uint8_t* base) {
  if (!enabled.load(std::memory_order_acquire)) {
    if (!pose_scope) return __imp__sub_82298FF0(ctx, base);
    auto* saved = pose_scope;
    struct RestorePose { PoseScope* saved; ~RestorePose() { pose_scope = saved; } } restore{saved};
    pose_scope = nullptr;
    reentrant.fetch_add(1);
    Abort(StopReason::reentrant);
    return __imp__sub_82298FF0(ctx, base);
  }
  evaluation_calls.fetch_add(1);
  auto* previous = pose_scope;
  if (previous) { reentrant.fetch_add(1); Abort(StopReason::reentrant); }
  if (!IdentitySelected() || ctx.r3.u32 != selected_ba.load()) {
    if (!IdentitySelected()) unselected.fetch_add(1); else actor_filtered.fetch_add(1);
    struct RestorePose { PoseScope* saved; ~RestorePose() { pose_scope = saved; } } restore{previous};
    pose_scope = nullptr;
    __imp__sub_82298FF0(ctx, base);
    return;
  }
  Flight flight;
  if (!flight) return __imp__sub_82298FF0(ctx, base);
  const auto active = active_ba_evaluations.fetch_add(1);
  struct ActiveScope {
    PoseScope* previous;
    ~ActiveScope() { pose_scope = previous; active_ba_evaluations.fetch_sub(1); }
  } active_scope{previous};
  pose_scope = nullptr;
  if (active) { concurrent.fetch_add(1); Abort(StopReason::concurrent_shared_ba); }
  EvaluationSample sample{};
  bool sampled = false;
  if (ctx.r4.u32 != selected_instance.load()) actor_filtered.fetch_add(1);
  else if (abort_reason.load() == StopReason::none) { HostState state; sampled = BeforeEvaluation(ctx, base, sample); }
  else after_stop.fetch_add(1);
  PoseScope scope{ctx.r4.u32, 0};
  if (sampled) {
    scope.bones = trace.identity.bones;
    pose_scope = &scope;
  }
  __imp__sub_82298FF0(ctx, base);
  pose_scope = nullptr;
  if (sampled) { HostState state; AfterEvaluation(base, sample, scope); }
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
  std::array<char, 16> on{}, actor{}, clip{}, scope{};
  if (Environment("N3_ANIM_TRACE", on.data(), DWORD(on.size())) != EnvironmentResult::valid ||
      std::strcmp(on.data(), "1")) return;
  Filter filter;
  const auto actor_result = Environment("N3_ANIM_TRACE_ACTOR", actor.data(), DWORD(actor.size()));
  const auto clip_result = Environment("N3_ANIM_TRACE_CLIP", clip.data(), DWORD(clip.size()));
  const auto scope_result = Environment("N3_ANIM_TRACE_SCOPE", scope.data(), DWORD(scope.size()));
  if (actor_result == EnvironmentResult::invalid || clip_result == EnvironmentResult::invalid ||
      scope_result == EnvironmentResult::invalid ||
      !ParseActor(actor_result == EnvironmentResult::missing ? "first" : actor.data(), filter.actor) ||
      !ParseClip(clip_result == EnvironmentResult::missing ? "all" : clip.data(), filter.clip) ||
      !ParseScope(scope_result == EnvironmentResult::missing ? "actor" : scope.data(), filter.scope) ||
      (filter.scope == Scope::resource && filter.actor)) {
    REXLOG_WARN("Animation trace disabled: invalid scope, actor or clip filter");
    return;
  }
  try {
    n3::data::VerifyGameFolder(game_root);
    output_path = user_root / "animation-trace-v2.json";
    if (!std::filesystem::is_directory(user_root) || std::filesystem::exists(output_path)) {
      REXLOG_WARN("Animation trace disabled: output directory missing or capture already exists");
      return;
    }
    Reset(filter);
    REXLOG_INFO("Bounded animation trace enabled for the verified game executable");
  } catch (const std::exception&) {
    REXLOG_WARN("Animation trace disabled: game verification or output setup failed");
  }
}

void ShutdownAnimationTrace() {
  if (!enabled.exchange(false, std::memory_order_acq_rel)) return;
  for (unsigned i = 0; i < 2000 && inflight.load(std::memory_order_acquire); ++i) Sleep(1);
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
  Trace snapshot = trace;
  CopyCounters(snapshot);
  snapshot.Stop(StopReason::shutdown);
  trace_lock.clear(std::memory_order_release);
  std::array<char, kSerializedCapacity> output{};
  size_t size = 0;
  if (!Serialize(snapshot, output.data(), output.size(), size)) {
    REXLOG_WARN("Animation trace serialization exceeded its bounds");
    return;
  }
  const auto file = CreateFileW(output_path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
      FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    REXLOG_WARN("Animation trace output could not be created");
    return;
  }
  DWORD written = 0;
  const bool ok = WriteFile(file, output.data(), static_cast<DWORD>(size), &written, nullptr) &&
      written == size && FlushFileBuffers(file);
  CloseHandle(file);
  if (!ok) {
    DeleteFileW(output_path.c_str());
    REXLOG_WARN("Animation trace output could not be flushed");
  } else REXLOG_INFO("Bounded animation trace flushed");
}

#ifdef N3_ANIMATION_TRACE_TEST
void ConfigureAnimationTraceForTest(Filter filter) { Reset(filter); }
Trace AnimationTraceSnapshotForTest() {
  Trace snapshot = trace;
  CopyCounters(snapshot);
  return snapshot;
}
bool AnimationTraceReadForTest(uint8_t* base, uint32_t address, void* output, uint32_t size) {
  HostState state;
  return Read(base, address, output, size);
}
#endif
