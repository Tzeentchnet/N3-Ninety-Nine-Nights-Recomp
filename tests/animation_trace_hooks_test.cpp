#include "animation_trace.h"
#include "sparse_game_fixture.h"

#include <Windows.h>
#include <rex/memory/utils.h>
#include <xmmintrin.h>
#include <bit>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <stdexcept>

extern "C" void sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void sub_82080158(PPCContext&, uint8_t*);
extern "C" void sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void sub_82249628(PPCContext&, uint8_t*);

namespace {
using namespace n3::animation_trace;
constexpr uint32_t actor = 0x4000, setup = 0x5000, instance = 0x6000, ba = 0x7000;
constexpr uint32_t signal = 0x8000, info = 0x9000, table = 0xa000, matrix = 0xd000;
constexpr uint32_t manager = 0x10000, handle = 10, ba_handle = 5;
uint32_t setup_calls = 0, controller_calls = 0, queue_calls = 0, eval_calls = 0, pose_calls = 0;
bool recursive = false, bad_pose_return = false;

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void Alter(PPCContext& ctx) {
  ctx.r3.u64 ^= 0x123456789abcdef0ull;
  ctx.r17.u64 ^= 0x13579;
  ctx.f1.u64 = 0x3ff8000000000000ull;
  ctx.v0.u64[0] ^= 0xabcddcba12344321ull;
  ctx.cr0.set_raw(5);
  ctx.xer.ca = 1;
  ctx.ctr.u64 = 0x987654321ull;
  ctx.lr ^= 0x204;
  ctx.fpscr.csr ^= 0x2000;
  _mm_setcsr(_mm_getcsr() ^ 0x2000);
  SetLastError(0x5678);
  errno = EDOM;
}
void Compare(const PPCContext& expected, const PPCContext& actual, uint32_t expected_csr,
             DWORD expected_error, int expected_errno) {
  Require(std::memcmp(&expected, &actual, sizeof(PPCContext)) == 0, "guest context changed");
  Require(_mm_getcsr() == expected_csr && GetLastError() == expected_error &&
      errno == expected_errno, "host FP or thread state changed");
}
struct Fixture : n3::test::SparseGameFixture {
  Fixture() {
    for (auto address : {0x20000u, 0x82040000u, 0x825e0000u, 0x82b40000u}) {
      Require(VirtualAlloc(base + address, 0x10000, MEM_COMMIT, PAGE_READWRITE) != nullptr,
              "cannot commit synthetic region");
    }
    Store<uint32_t>(0x825e12f0, manager);
    Store<uint32_t>(manager + 66268, 100);
    Store<uint32_t>(manager + 66272, table);
    Store<uint32_t>(manager + 26168 + ba_handle * 4, ba);
    Store<uint32_t>(table + handle * 4, instance);
    Store<uint32_t>(actor, 0x82040170);
    Store<uint32_t>(0x82040170 + 44, 0x82080068);
    Store<uint32_t>(actor + 16, handle);
    Store<uint32_t>(actor + 192, 2);
    Store<uint32_t>(actor + 196, std::bit_cast<uint32_t>(3.0f));
    Store<uint32_t>(actor + 200, std::bit_cast<uint32_t>(2.0f));
    Store<uint32_t>(actor + 204, std::bit_cast<uint32_t>(1.0f));
    Store<uint32_t>(actor + 312, signal);
    Store<uint32_t>(actor + 316, info);
    Store<uint32_t>(setup + 48, ba_handle);
    Store<uint32_t>(setup + 52, 0);
    Store<uint32_t>(setup + 56, 0);
    Store<uint32_t>(instance, 0x82051f88);
    Store<uint32_t>(instance + 8, handle);
    Store<uint32_t>(instance + 216, ba_handle);
    Store<uint32_t>(instance + 220, ba);
    Store<uint32_t>(instance + 228, 1);
    Store<uint32_t>(instance + 232, 2);
    Store<uint32_t>(instance + 252, std::bit_cast<uint32_t>(3.0f));
    Store<uint32_t>(ba, 0x82051f14);
    Store<uint32_t>(ba + 8, 4);
    Store<uint32_t>(ba + 12, 3);
    std::memcpy(base + ba + 28, "SYNTHETIC.BA", sizeof("SYNTHETIC.BA"));
    Store<uint32_t>(signal + 4, 4);
    Store<uint32_t>(info + 440, 4);
    Store<uint32_t>(0x82b4814c + 4, 0xb000);
    Store<uint32_t>(0x82b4814c + 8, 0xb004);
    Store<uint32_t>(0xb000, 0xc000);
    Store<uint32_t>(0xc004, signal);
    Store<uint32_t>(0x82b4815c + 4, 0xb100);
    Store<uint32_t>(0x82b4815c + 8, 0xb104);
    Store<uint32_t>(0xb100, 0xc100);
    Store<uint32_t>(0xc104, info);
  }
};

PPCContext Context(uint32_t r3, uint32_t r4 = 0) {
  PPCContext ctx{};
  ctx.r3.u64 = r3; ctx.r4.u64 = r4;
  ctx.r17.u64 = 0x12345;
  ctx.f1.u64 = std::bit_cast<uint64_t>(2.0);
  ctx.lr = 0x82094b60;
  ctx.fpscr.InitHost();
  return ctx;
}

template<typename F>
void CompareCall(F original, F hook, PPCContext seed, uint8_t* base) {
  auto expected = seed, actual = seed;
  const auto initial_csr = _mm_getcsr();
  SetLastError(7); errno = ERANGE;
  original(expected, base);
  const auto expected_csr = _mm_getcsr();
  const auto expected_error = GetLastError();
  const auto expected_errno = errno;
  _mm_setcsr(initial_csr); SetLastError(7); errno = ERANGE;
  hook(actual, base);
  Compare(expected, actual, expected_csr, expected_error, expected_errno);
  _mm_setcsr(initial_csr);
}
}

extern "C" void __imp__sub_82093BE8(PPCContext& ctx, uint8_t*) {
  ++setup_calls; Alter(ctx);
}
extern "C" void __imp__sub_82080158(PPCContext& ctx, uint8_t* base) {
  ++controller_calls;
  rex::memory::store_and_swap<uint32_t>(base + ctx.r3.u32 + 196,
                                      std::bit_cast<uint32_t>(4.0f));
  Alter(ctx);
}
extern "C" void __imp__sub_82252BD8(PPCContext& ctx, uint8_t*) {
  ++queue_calls; Alter(ctx);
}
extern "C" void __imp__sub_82249628(PPCContext& ctx, uint8_t*) {
  ++pose_calls; Alter(ctx);
}
extern "C" void __imp__sub_82298FF0(PPCContext& ctx, uint8_t* base) {
  ++eval_calls;
  if (recursive) {
    recursive = false;
    auto nested = Context(ba, instance);
    sub_82298FF0(nested, base);
  }
  for (uint32_t node = 0; node < 2; ++node) {
    auto output = Context(instance, matrix);
    output.r5.u32 = node;
    output.lr = bad_pose_return ? 0x8229ad60 : 0x8229ad64;
    sub_82249628(output, base);
  }
  Alter(ctx);
}

int main() {
  const auto saved_csr = _mm_getcsr();
  try {
    Fixture fixture;
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, Context(actor, setup), fixture.base);
    Require(setup_calls == 2, "disabled hook did not retain exactly one call");

    ConfigureAnimationTraceForTest({0, -1});
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, Context(actor, setup), fixture.base);
    auto snapshot = AnimationTraceSnapshotForTest();
    Require(setup_calls == 4 && snapshot.selected && snapshot.identity.actor == actor &&
        snapshot.identity.instance == instance && snapshot.identity.ba == ba &&
        snapshot.counters.setup_accepted == 1, "synthetic actor binding");

    fixture.Store<uint32_t>(actor + 196, std::bit_cast<uint32_t>(3.0f));
    CompareCall(__imp__sub_82080158, sub_82080158, Context(actor), fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(controller_calls == 2 && snapshot.controller_count == 1 &&
        snapshot.controller[0].before_clip == 2, "controller call or sample");

    auto queued = Context(manager, handle);
    queued.r5.u32 = 2;
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(queue_calls == 2 && snapshot.queue_count == 1 && snapshot.queue[0].clip == 2,
            "queue call or sample");

    auto evaluation = Context(ba, instance);
    evaluation.lr = 0x8229ea94;
    CompareCall(__imp__sub_82298FF0, sub_82298FF0, evaluation, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(eval_calls == 2 && pose_calls == 4 && snapshot.evaluation_count == 1 &&
        snapshot.evaluation[0].pose_outputs == 2 && snapshot.counters.pose_outputs == 2,
        "evaluation or pose call count");

    uint32_t value = 0;
    Require(AnimationTraceReadForTest(fixture.base, actor, &value, 4), "mapped read rejected");
    Require(!AnimationTraceReadForTest(fixture.base, 0xdffffffc, &value, 8),
            "physical shadow boundary accepted");
    DWORD old = 0;
    Require(VirtualProtect(fixture.base + 0x18000, 4096, PAGE_NOACCESS, &old) != 0,
            "cannot protect fixture page");
    const bool inaccessible = AnimationTraceReadForTest(fixture.base, 0x18000, &value, 4);
    DWORD ignored = 0;
    VirtualProtect(fixture.base + 0x18000, 4096, old, &ignored);
    Require(!inaccessible, "unmapped read accepted");

    recursive = true;
    auto nested = Context(ba, instance);
    sub_82298FF0(nested, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::reentrant && snapshot.counters.reentrant == 1 &&
        eval_calls == 4, "reentrant original or stop");

    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    auto invalid_queue = Context(manager + 4, handle);
    invalid_queue.r5.u32 = 2;
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, invalid_queue, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.counters.invalid == 1, "invalid resource accepted");
    fixture.Store<uint32_t>(table + handle * 4, 0);
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    fixture.Store<uint32_t>(ba, 0);
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    fixture.Store<uint32_t>(ba, 0x82051f14);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.counters.invalid == 3,
        "invalid resource mapping or vtable accepted");
    const auto queue_before = queue_calls;
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(queue_calls == queue_before + 2 && snapshot.selected &&
        snapshot.filter.scope == Scope::resource && snapshot.identity.actor == 0 &&
        snapshot.identity.instance == instance && snapshot.identity.ba == ba &&
        snapshot.counters.resource_bindings == 1 && snapshot.queue_count == 1,
        "resource binding or queue sample");
    auto other_clip = queued;
    other_clip.r5.u32 = 1;
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, other_clip, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.queue_count == 1 && snapshot.counters.clip_filtered == 1,
        "resource clip filter");
    const auto eval_before = eval_calls;
    CompareCall(__imp__sub_82298FF0, sub_82298FF0, evaluation, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(eval_calls == eval_before + 2 && snapshot.evaluation_count == 1 &&
        snapshot.evaluation[0].pose_outputs == 2, "resource evaluation or pose sample");
    fixture.Store<uint32_t>(table + handle * 4, instance + 0x100);
    sub_82252BD8(queued, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    if (snapshot.stop != StopReason::identity_changed || snapshot.counters.invalid != 4)
      std::cerr << "resource changed stop=" << unsigned(snapshot.stop)
                << " invalid=" << snapshot.counters.invalid << '\n';
    Require(snapshot.stop == StopReason::identity_changed && snapshot.counters.invalid == 4,
        "changed resource identity did not stop capture");
    fixture.Store<uint32_t>(table + handle * 4, instance);
    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    auto rebound = Context(manager, handle);
    rebound.r5.u32 = 2;
    sub_82252BD8(rebound, fixture.base);
    bad_pose_return = true;
    CompareCall(__imp__sub_82298FF0, sub_82298FF0, evaluation, fixture.base);
    bad_pose_return = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::invalid_mapping &&
        snapshot.counters.invalid_outputs == 2 && snapshot.counters.pose_outputs == 0,
        "invalid pose return accepted");
    _mm_setcsr(saved_csr);
    std::cout << "animation trace hooks: retained calls, host state and guarded mappings passed\n";
    return 0;
  } catch (const std::exception& error) {
    _mm_setcsr(saved_csr);
    std::cerr << error.what() << '\n';
    return 1;
  }
}
