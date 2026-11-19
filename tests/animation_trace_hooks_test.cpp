#include "animation_trace.h"
#include "sparse_game_fixture.h"

#include <Windows.h>
#include <rex/logging/logger.h>
#include <rex/memory/utils.h>
#include <xmmintrin.h>
#include <atomic>
#include <bit>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>
#include <utility>

extern "C" void sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void sub_82080158(PPCContext&, uint8_t*);
extern "C" void sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void sub_82249628(PPCContext&, uint8_t*);
extern "C" void sub_822733B8(PPCContext&, uint8_t*);
extern "C" void sub_82273000(PPCContext&, uint8_t*);
extern "C" void sub_82272AF0(PPCContext&, uint8_t*);
extern "C" void sub_82272F58(PPCContext&, uint8_t*);
extern "C" void sub_82272C40(PPCContext&, uint8_t*);
extern "C" void sub_8224E6F0(PPCContext&, uint8_t*);
extern "C" void sub_82298E78(PPCContext&, uint8_t*);
extern "C" void sub_8224E9B0(PPCContext&, uint8_t*);
extern "C" void sub_8229CF30(PPCContext&, uint8_t*);
extern "C" void sub_8224AC98(PPCContext&, uint8_t*);
extern "C" void sub_82251D38(PPCContext&, uint8_t*);
extern "C" void sub_8224E0B8(PPCContext&, uint8_t*);
extern "C" void sub_82249FB0(PPCContext&, uint8_t*);
extern "C" void sub_820A4648(PPCContext&, uint8_t*);
extern "C" void sub_820AF768(PPCContext&, uint8_t*);
extern "C" void sub_8208D878(PPCContext&, uint8_t*);
extern "C" void sub_820AAFB0(PPCContext&, uint8_t*);
extern "C" void sub_820A2968(PPCContext&, uint8_t*);
extern "C" void sub_8217AD08(PPCContext&, uint8_t*);
extern "C" void sub_8229CA98(PPCContext&, uint8_t*);
extern "C" void sub_8210BF78(PPCContext&, uint8_t*);
extern "C" void sub_8210CB78(PPCContext&, uint8_t*);
extern "C" void sub_8210BE98(PPCContext&, uint8_t*);
extern "C" void sub_8210CAB8(PPCContext&, uint8_t*);
extern "C" void sub_8210C728(PPCContext&, uint8_t*);
extern "C" void sub_8210CFE8(PPCContext&, uint8_t*);
extern "C" void sub_82097868(PPCContext&, uint8_t*);
extern "C" void sub_82097958(PPCContext&, uint8_t*);
extern "C" void sub_82097D00(PPCContext&, uint8_t*);
extern "C" void sub_820927C0(PPCContext&, uint8_t*);
extern "C" void sub_8209BE30(PPCContext&, uint8_t*);
extern "C" void sub_82097D90(PPCContext&, uint8_t*);
extern "C" void sub_8212ACA8(PPCContext&, uint8_t*);

namespace {
using namespace n3::animation_trace;
constexpr uint32_t actor = 0x4000, setup = 0x5000, instance = 0x6000, ba = 0x7000;
constexpr uint32_t signal = 0x8000, info = 0x9000, table = 0xa000, matrix = 0xd000;
constexpr uint32_t manager = 0x10000, handle = 10, ba_handle = 5;
constexpr uint32_t file_manager = 0x20000, archive = 0x21000, result_object = 0x23000;
constexpr uint32_t request = 0x24000, outputs = 0x25000, archive_size = 4096;
constexpr uint32_t loaded_member = 0x26000, stream = 0x27000;
uint32_t setup_calls = 0, controller_calls = 0, queue_calls = 0, eval_calls = 0, pose_calls = 0;
uint32_t archive_calls = 0, resolver_calls = 0, ba_load_calls = 0, decode_calls = 0;
uint32_t collect_calls = 0, reset_calls = 0, submit_calls = 0;
uint32_t upstream_original_calls = 0;
uint32_t quaternion_original_calls = 0;
uint32_t mount_slot = 0;
uint32_t archive_result = archive, archive_result_size = archive_size;
bool recursive = false, bad_pose_return = false, extra_pose = false, cache_load = false, resolve_source = true;
bool nested_controller = false, nested_queue_eval = false, corrupt_loaded = false;
bool recursive_setup = false, recursive_collect = false, load_during_collect = false, recursive_reset = false;
bool destroy_during_submit = false;
bool mutate_attachment_request = false;
bool exercise_quaternion = false, quaternion_nan_output = false;
bool signal_fake = false;
bool signal_skip_dispatch = false;
bool signal_nested_path2 = false;
enum class NestedOtherRequest { none, normal, throwing };
NestedOtherRequest nested_other_request = NestedOtherRequest::none;
NestedOtherRequest active_other_request = NestedOtherRequest::none;
bool nested_other_caught = false;
uint32_t signal_fake_offset = 0, signal_fake_size = 0, signal_original_calls = 0;
constexpr uint32_t signal_groups = 0x28000, signal_records = 0x28100;
constexpr uint32_t signal_rows = 0x28200, effect_manager = 0x29000;
std::atomic<bool> block_evaluation{false}, evaluation_entered{false}, release_evaluation{false};
std::atomic<bool> block_signal_request{false}, signal_entered{false}, release_signal_request{false};
std::atomic<bool> block_attachment_read{false}, attachment_entered{false}, release_attachment_read{false};

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void Alter(PPCContext& ctx) {
  ctx.r3.u64 ^= 0x123456789abcdef0ull;
  ctx.r17.u64 ^= 0x13579;
  ctx.f1.u64 = 0x3ff8000000000000ull;
  ctx.v0.u64[0] ^= 0xabcddcba12344321ull;
  ctx.cr0.SetRaw(5);
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
    Store<uint32_t>(ba + 4, 1);
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
    Store<uint32_t>(archive, 2);
    std::memcpy(base + archive + 4, "OTHER.BA", sizeof("OTHER.BA"));
    std::memcpy(base + archive + 4 + 268, "SYNTHETIC.BA", sizeof("SYNTHETIC.BA"));
    Store<uint32_t>(archive + 4 + 268 + 260, 0x300);
    Store<uint32_t>(archive + 4 + 268 + 264, 4);
    std::memcpy(base + archive + 0x300, "DATA", 4);
    std::memcpy(base + request, "C:\\TEST\\SYNTHETIC.BA", sizeof("C:\\TEST\\SYNTHETIC.BA"));
    Store<uint32_t>(result_object + 8, archive + 0x300);
    Store<uint32_t>(result_object + 16, archive + 0x304);
    Store<uint32_t>(result_object + 20, 0);
    Store<uint32_t>(stream + 8, loaded_member);
    Store<uint32_t>(stream + 12, 4);
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

extern "C" void __imp__sub_82093BE8(PPCContext& ctx, uint8_t* base) {
  ++setup_calls;
  if (recursive_setup) {
    recursive_setup = false;
    auto nested = Context(actor, setup);
    sub_82093BE8(nested, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_82080158(PPCContext& ctx, uint8_t* base) {
  ++controller_calls;
  if (nested_controller) {
    nested_controller = false;
    auto queue = Context(manager, handle);
    queue.r5.u32 = 2;
    sub_82252BD8(queue, base);
  }
  rex::memory::store_and_swap<uint32_t>(base + ctx.r3.u32 + 196,
                                      std::bit_cast<uint32_t>(4.0f));
  Alter(ctx);
}
extern "C" void __imp__sub_82252BD8(PPCContext& ctx, uint8_t* base) {
  ++queue_calls;
  if (nested_queue_eval) {
    nested_queue_eval = false;
    auto evaluation = Context(ba, instance);
    evaluation.lr = 0x8229ea94;
    sub_82298FF0(evaluation, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_82249628(PPCContext& ctx, uint8_t*) {
  ++pose_calls; Alter(ctx);
}
extern "C" void __imp__sub_8229CA98(PPCContext& ctx, uint8_t*) {
  ++quaternion_original_calls;
  for (size_t i = 0; i < 4; ++i) ctx.v1.u32[i] = ctx.v2.u32[i];
  if (quaternion_nan_output) ctx.v1.u32[3] = 0x7fc00000;
  Alter(ctx);
}
extern "C" void __imp__sub_82298FF0(PPCContext& ctx, uint8_t* base) {
  ++eval_calls;
  if (block_evaluation.load()) {
    evaluation_entered = true;
    while (!release_evaluation.load()) std::this_thread::yield();
  }
  if (recursive) {
    recursive = false;
    auto nested = Context(ba, instance);
    sub_82298FF0(nested, base);
  }
  if (exercise_quaternion) {
    for (unsigned i = 0; i < 13; ++i) {
      auto helper = Context(0);
      helper.lr = 0x8229a214;
      helper.r25.u32 = ba;
      helper.r22.u32 = instance;
      helper.r24.u32 = i == 0 ? 99 : 1;
      for (size_t lane = 0; lane < 4; ++lane) {
        helper.v1.u32[lane ^ 3] = std::bit_cast<uint32_t>(-float(lane + 1));
        helper.v2.u32[lane ^ 3] = std::bit_cast<uint32_t>(float(lane + 1) / 4);
        helper.v3.u32[lane] = std::bit_cast<uint32_t>(0.25f);
      }
      if (i == 1) helper.v1.u32[3] = 0x7fc00000;
      quaternion_nan_output = i == 2;
      sub_8229CA98(helper, base);
    }
    quaternion_nan_output = false;
  }
  for (uint32_t node = 0; node < (extra_pose ? 4u : 2u); ++node) {
    auto output = Context(instance, matrix);
    output.r5.u32 = node % 3;
    output.lr = bad_pose_return ? 0x8229ad60 : 0x8229ad64;
    sub_82249628(output, base);
  }
  Alter(ctx);
}

extern "C" void __imp__sub_822733B8(PPCContext& ctx, uint8_t* base) {
  ++archive_calls;
  rex::memory::store_and_swap<uint32_t>(base + ctx.r4.u32, archive_result);
  rex::memory::store_and_swap<uint32_t>(base + ctx.r5.u32, archive_result_size);
  Alter(ctx); ctx.r3.u64 = 0;
}
extern "C" void __imp__sub_82273000(PPCContext& ctx, uint8_t* base) {
  if (signal_fake && (uint32_t(ctx.lr) == 0x8210bf98 || uint32_t(ctx.lr) == 0x8210cba8)) {
    const auto address_output = ctx.r4.u32, size_output = ctx.r5.u32;
    auto resolver = Context(file_manager, ctx.r3.u32);
    sub_82272C40(resolver, base);
    std::memcpy(base + loaded_member, base + archive + signal_fake_offset, signal_fake_size);
    rex::memory::store_and_swap<uint32_t>(base + address_output, loaded_member);
    rex::memory::store_and_swap<uint32_t>(base + size_output, signal_fake_size);
    Alter(ctx); ctx.r3.u64 = 0;
    return;
  }
  if (uint32_t(ctx.lr) != 0x8224e8a8) return __imp__sub_822733B8(ctx, base);
  const auto address_output = ctx.r4.u32, size_output = ctx.r5.u32;
  if (block_attachment_read) {
    attachment_entered = true;
    while (!release_attachment_read) std::this_thread::yield();
  }
  if (resolve_source) {
    auto resolver = Context(file_manager, request);
    sub_82272C40(resolver, base);
  }
  std::memcpy(base + loaded_member, base + archive + 0x300, 4);
  if (corrupt_loaded) base[loaded_member] ^= 1;
  if (mutate_attachment_request) base[request] ^= 1;
  rex::memory::store_and_swap<uint32_t>(base + address_output, loaded_member);
  rex::memory::store_and_swap<uint32_t>(base + size_output, 4);
  Alter(ctx); ctx.r3.u64 = 0;
}
extern "C" void __imp__sub_82272AF0(PPCContext& ctx, uint8_t* base) {
  const auto address = ctx.r4.u32;
  rex::memory::store_and_swap<uint32_t>(base + ctx.r3.u32 + 8 + mount_slot * 16, address);
  Alter(ctx); ctx.r3.u64 = address;
}
extern "C" void __imp__sub_82272F58(PPCContext& ctx, uint8_t* base) {
  rex::memory::store_and_swap<uint32_t>(base + file_manager + 8, 0);
  Alter(ctx);
}
extern "C" void __imp__sub_82272C40(PPCContext& ctx, uint8_t*) {
  ++resolver_calls; Alter(ctx); ctx.r3.u64 = result_object | 1;
}
extern "C" void __imp__sub_82298E78(PPCContext& ctx, uint8_t*) {
  ++decode_calls; Alter(ctx);
}
extern "C" void __imp__sub_8224E6F0(PPCContext& ctx, uint8_t* base) {
  ++ba_load_calls;
  if (!cache_load) {
    auto read = Context(request, outputs + 16);
    read.r5.u32 = outputs + 20; read.lr = 0x8224e8a8;
    sub_82273000(read, base);
    auto decoder = Context(ba, stream);
    decoder.lr = 0x8224e954;
    sub_82298E78(decoder, base);
  }
  Alter(ctx); ctx.r3.u64 = ba_handle;
}
extern "C" void __imp__sub_8224E9B0(PPCContext& ctx, uint8_t* base) {
  ++collect_calls;
  if (recursive_collect) {
    recursive_collect = false;
    auto nested = Context(manager);
    sub_8224E9B0(nested, base);
  }
  if (load_during_collect) {
    load_during_collect = false;
    auto nested = Context(manager);
    sub_8224E6F0(nested, base);
  }
  const auto references = rex::memory::load_and_swap<uint32_t>(base + ba + 4);
  if (std::bit_cast<int32_t>(references) <= 0)
    rex::memory::store_and_swap<uint32_t>(base + manager + 26168 + ba_handle * 4, 0);
  Alter(ctx);
}
extern "C" void __imp__sub_8229CF30(PPCContext& ctx, uint8_t* base) {
  rex::memory::store_and_swap<uint32_t>(base + ctx.r3.u32, 0x82051f88);
  Alter(ctx);
}
extern "C" void __imp__sub_82249FB0(PPCContext& ctx, uint8_t*) { Alter(ctx); }
extern "C" void __imp__sub_8224AC98(PPCContext& ctx, uint8_t* base) {
  ++submit_calls;
  if (destroy_during_submit) {
    destroy_during_submit = false;
    auto remove = Context(manager, handle);
    sub_82251D38(remove, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_820A4648(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_820AF768(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_8208D878(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_820AAFB0(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_820A2968(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_8217AD08(PPCContext& ctx, uint8_t*) { ++upstream_original_calls; Alter(ctx); }
extern "C" void __imp__sub_82251D38(PPCContext& ctx, uint8_t* base) {
  rex::memory::store_and_swap<uint32_t>(base + table + handle * 4, 0);
  Alter(ctx);
}
extern "C" void __imp__sub_8224E0B8(PPCContext& ctx, uint8_t* base) {
  ++reset_calls;
  if (recursive_reset) {
    recursive_reset = false;
    auto nested = Context(manager);
    sub_8224E0B8(nested, base);
  }
  __imp__sub_82251D38(ctx, base);
}

#define SIGNAL_STUB(address) \
  extern "C" void __imp__sub_##address(PPCContext& ctx, uint8_t*) { ++signal_original_calls; Alter(ctx); }
SIGNAL_STUB(8210BE98)
SIGNAL_STUB(8210CAB8)
SIGNAL_STUB(8209BE30)
SIGNAL_STUB(82097D90)
#undef SIGNAL_STUB

extern "C" void __imp__sub_8210C728(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) {
    rex::memory::store_and_swap<uint32_t>(base + signal_groups + 4, 2);
    rex::memory::store_and_swap<uint32_t>(base + signal_groups + 8, signal_records);
    for (uint32_t i = 0; i < 2; ++i) {
      const auto record = signal_records + i * 20;
      rex::memory::store_and_swap<uint32_t>(base + record, i ? 3 : 2);
      rex::memory::store_and_swap<uint32_t>(base + record + 4, i ? 33 : 24);
      rex::memory::store_and_swap<uint32_t>(base + record + 8, i ? 1 : 0);
      rex::memory::store_and_swap<uint32_t>(base + record + 12, 0);
    }
    rex::memory::store_and_swap<uint32_t>(base + stream + 4, 632);
  }
  Alter(ctx); if (signal_fake) ctx.r3.u64 = 1;
}

extern "C" void __imp__sub_8210BF78(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) {
    auto read = Context(ctx.r4.u32, outputs + 16);
    read.r5.u32 = outputs + 20; read.lr = 0x8210bf98;
    sub_82273000(read, base);
    rex::memory::store_and_swap<uint32_t>(base + signal + 4, 1);
    rex::memory::store_and_swap<uint32_t>(base + signal + 8, signal_groups);
    rex::memory::store_and_swap<uint32_t>(base + stream + 4, 520);
    rex::memory::store_and_swap<uint32_t>(base + stream + 8, loaded_member);
    rex::memory::store_and_swap<uint32_t>(base + stream + 12, signal_fake_size);
    auto group = Context(signal_groups, stream); group.lr = 0x8210c0d4;
    sub_8210C728(group, base);
  }
  Alter(ctx); if (signal_fake) ctx.r3.u64 = 1;
}

extern "C" void __imp__sub_8210CB78(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) {
    auto read = Context(ctx.r4.u32, outputs + 16);
    read.r5.u32 = outputs + 20; read.lr = 0x8210cba8;
    sub_82273000(read, base);
    rex::memory::store_and_swap<uint32_t>(base + info + 440, 2);
    rex::memory::store_and_swap<uint32_t>(base + info + 444, signal_rows);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 4, 5);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 8, 7);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 12, 3);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 32 + 4, 9);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 32 + 8, 7);
    rex::memory::store_and_swap<uint32_t>(base + signal_rows + 32 + 12, 0);
  }
  Alter(ctx); if (signal_fake) ctx.r3.u64 = 1;
}

extern "C" void __imp__sub_8210CFE8(PPCContext& ctx, uint8_t*) {
  ++signal_original_calls; Alter(ctx); if (signal_fake) ctx.r3.u64 = 0;
}
extern "C" void __imp__sub_8212ACA8(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) base[effect_manager + 740] = 1;
  Alter(ctx);
}
extern "C" void __imp__sub_820927C0(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) {
    if (ctx.r3.u32 == actor && nested_other_request != NestedOtherRequest::none) {
      active_other_request = nested_other_request;
      nested_other_request = NestedOtherRequest::none;
      auto other = Context(actor + 0x200, 123);
      other.r5.u32 = 456; other.r6.u32 = 789;
      try {
        sub_82097868(other, base);
      } catch (const std::runtime_error&) {
        nested_other_caught = true;
      }
      active_other_request = NestedOtherRequest::none;
      auto restored_selection = Context(info, 7);
      restored_selection.r5.u32 = 3; restored_selection.r6.u32 = 5;
      restored_selection.lr = 0x820978dc;
      sub_8210CFE8(restored_selection, base);
    }
    if (signal_nested_path2) {
      signal_nested_path2 = false;
      auto nested = Context(ctx.r3.u32, signal_records);
      sub_820927C0(nested, base);
    }
    base[ctx.r3.u32 + 1056] ^= 1;
    auto downstream = Context(effect_manager); downstream.lr = 0x8212aca0;
    sub_8212ACA8(downstream, base);
    auto nested = Context(ctx.r3.u32, signal_records);
    sub_82097D90(nested, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_82097D00(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake && !signal_skip_dispatch) {
    auto dispatch = Context(ctx.r3.u32, signal_records); dispatch.lr = 0x82097d68;
    sub_820927C0(dispatch, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_82097958(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (signal_fake) {
    rex::memory::store_and_swap<uint32_t>(base + ctx.r3.u32 + 192, ctx.r4.u32);
    auto group = Context(ctx.r3.u32); group.lr = 0x82097ad8;
    sub_82097D00(group, base);
  }
  Alter(ctx);
}
extern "C" void __imp__sub_82097868(PPCContext& ctx, uint8_t* base) {
  ++signal_original_calls;
  if (block_signal_request.load()) {
    signal_entered = true;
    while (!release_signal_request.load()) std::this_thread::yield();
  }
  if (signal_fake) {
    auto selection = Context(info, ctx.r4.u32);
    selection.r5.u32 = ctx.r5.u32; selection.r6.u32 = ctx.r6.u32;
    selection.lr = 0x820978dc;
    sub_8210CFE8(selection, base);
    if (active_other_request != NestedOtherRequest::none) {
      auto child_controller = Context(actor);
      child_controller.lr = 0x82094b64;
      sub_82080158(child_controller, base);
    }
    auto install = Context(ctx.r3.u32, selection.r3.u32); install.lr = 0x82097944;
    sub_82097958(install, base);
    if (active_other_request == NestedOtherRequest::throwing)
      throw std::runtime_error("synthetic nested request exception");
  }
  Alter(ctx);
}

namespace {
void TrackResources(Fixture& fixture) {
  cache_load = false;
  resolve_source = true;
  fixture.Store<uint32_t>(manager + 26168 + ba_handle * 4, ba);
  fixture.Store<uint32_t>(ba + 4, 1);
  fixture.Store<uint32_t>(file_manager + 8, 0);
  auto load = Context(0, outputs);
  load.r5.u32 = outputs + 4; load.lr = 0x82272ef0;
  sub_822733B8(load, fixture.base);
  auto mount = Context(file_manager, archive);
  sub_82272AF0(mount, fixture.base);
  auto resource = Context(manager);
  sub_8224E6F0(resource, fixture.base);
  auto create = Context(instance);
  sub_8229CF30(create, fixture.base);
}

void TrackSignalAssets(Fixture& fixture) {
  auto release = Context(archive);
  sub_82272F58(release, fixture.base);
  std::memset(fixture.base + archive, 0, archive_size);
  fixture.Store<uint32_t>(archive, 2);
  std::memcpy(fixture.base + archive + 4, "SYNTHETIC.AS", sizeof("SYNTHETIC.AS"));
  std::memcpy(fixture.base + archive + 4 + 268, "SYNTHETIC.INFO", sizeof("SYNTHETIC.INFO"));
  fixture.Store<uint32_t>(archive + 4 + 260, 0x300);
  fixture.Store<uint32_t>(archive + 4 + 264, 644);
  fixture.Store<uint32_t>(archive + 4 + 268 + 260, 0x600);
  fixture.Store<uint32_t>(archive + 4 + 268 + 264, 696);
  const auto as = archive + 0x300;
  fixture.Store<uint32_t>(as, 101);
  fixture.Store<uint32_t>(as + 4, 1);
  fixture.Store<uint32_t>(as + 520, 3);
  for (uint32_t i = 0; i < 3; ++i) {
    fixture.Store<uint32_t>(as + 524 + i * 8, i == 0 ? 24 : i == 1 ? 12 : 33);
    fixture.Store<uint32_t>(as + 528 + i * 8, 548 + i * 28);
    fixture.Store<uint32_t>(as + 548 + i * 28, i == 0 ? 2 : i == 1 ? UINT32_MAX : 3);
    fixture.Store<uint32_t>(as + 552 + i * 28, i == 0 ? 0 : 1);
    fixture.Store<uint32_t>(as + 556 + i * 28, 0);
  }
  const auto inf = archive + 0x600;
  fixture.Store<uint32_t>(inf, 100);
  fixture.Store<uint32_t>(inf + 8, 2);
  fixture.Store<uint32_t>(inf + 524, 7);
  fixture.Store<uint32_t>(inf + 528, 3);
  fixture.Store<uint32_t>(inf + 548, 5);
  fixture.Store<uint32_t>(inf + 610, 7);
  fixture.Store<uint32_t>(inf + 614, 0);
  fixture.Store<uint32_t>(inf + 634, 9);
  std::memcpy(fixture.base + request + 0x100, "SYNTHETIC.AS", sizeof("SYNTHETIC.AS"));
  std::memcpy(fixture.base + request + 0x200, "SYNTHETIC.INFO", sizeof("SYNTHETIC.INFO"));
  auto loaded = Context(0, outputs);
  loaded.r5.u32 = outputs + 4; loaded.lr = 0x82272ef0;
  sub_822733B8(loaded, fixture.base);
  auto mount = Context(file_manager, archive);
  sub_82272AF0(mount, fixture.base);
  signal_fake = true;
  signal_fake_offset = 0x300; signal_fake_size = 644;
  fixture.Store<uint32_t>(result_object + 8, as);
  fixture.Store<uint32_t>(result_object + 16, as + signal_fake_size);
  auto as_load = Context(signal, request + 0x100);
  sub_8210BF78(as_load, fixture.base);
  signal_fake_offset = 0x600; signal_fake_size = 696;
  fixture.Store<uint32_t>(result_object + 8, inf);
  fixture.Store<uint32_t>(result_object + 16, inf + signal_fake_size);
  auto info_load = Context(info, request + 0x200);
  sub_8210CB78(info_load, fixture.base);
}
}

int main(int argc, char** argv) {
  const auto saved_csr = _mm_getcsr();
  try {
    if (argc == 2 && std::strcmp(argv[1], "--emit-timeout-v1") == 0)
      Require(REX_LOGGER().level.Set("off").has_value(),
              "cannot silence timeout diagnostic transport");
    Fixture fixture;
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, Context(actor, setup), fixture.base);
    Require(setup_calls == 2, "disabled hook did not retain exactly one call");

    auto attachment_fixture = std::make_unique<Fixture>();
    ConfigureAnimationTraceForTest({0, -1}, false, false, true);
    TrackResources(*attachment_fixture);
    auto attachment_read = Context(request, outputs + 16);
    attachment_read.r5.u32 = outputs + 20;
    attachment_read.lr = 0x8224e8a8;
    const auto resolver_before = resolver_calls;
    CompareCall(__imp__sub_82273000, sub_82273000, attachment_read, attachment_fixture->base);
    Require(resolver_calls == resolver_before + 2, "attachment hook changed original calls");
    corrupt_loaded = true;
    auto bad_read = attachment_read;
    sub_82273000(bad_read, attachment_fixture->base);
    corrupt_loaded = false;
    mutate_attachment_request = true;
    auto changed_read = attachment_read;
    sub_82273000(changed_read, attachment_fixture->base);
    mutate_attachment_request = false;
    attachment_fixture->base[request] ^= 1;
    resolve_source = false;
    auto without_resolver = attachment_read;
    sub_82273000(without_resolver, attachment_fixture->base);
    resolve_source = true;
    for (unsigned i = 0; i < kAttachmentPerKindCapacity - 3; ++i) {
      auto extra = attachment_read;
      sub_82273000(extra, attachment_fixture->base);
    }
    const auto& attachment_snapshot = AnimationTraceSnapshotForTest();
    const auto animation_kind = size_t(AttachmentKind::animation);
    const auto& outcomes = attachment_snapshot.attachment.outcomes[animation_kind];
    Require(attachment_snapshot.stop == StopReason::none &&
        attachment_snapshot.attachment.seen[animation_kind] == kAttachmentPerKindCapacity + 2 &&
        outcomes[size_t(AttachmentOutcome::verified)] == kAttachmentPerKindCapacity - 3 &&
        outcomes[size_t(AttachmentOutcome::mismatch)] == 1 &&
        outcomes[size_t(AttachmentOutcome::changed)] == 1 &&
        outcomes[size_t(AttachmentOutcome::no_resolver)] == 1 &&
        outcomes[size_t(AttachmentOutcome::full)] == 2 &&
        attachment_snapshot.attachment.observation_count == 1 &&
        attachment_snapshot.attachment.observations[0].source.member_index == 1 &&
        attachment_snapshot.attachment.observations[0].count == kAttachmentPerKindCapacity - 3 &&
        attachment_snapshot.attachment.hash_bytes > 0 &&
        attachment_snapshot.attachment.hash_bytes <= kAttachmentHashBudgetBytes &&
        attachment_snapshot.attachment.hash_budget_full == 0,
        "attachment provenance, output validation or capacity accounting");
    std::array<char, 16384> attachment_json{};
    size_t attachment_size = 0;
    Require(SerializeAttachment(attachment_snapshot.attachment, StopReason::shutdown,
        attachment_json.data(), attachment_json.size(), attachment_size) &&
        std::string_view(attachment_json.data(), attachment_size).find("SYNTHETIC") ==
            std::string_view::npos,
        "attachment aggregate leaked request or failed serialization");

    ConfigureAnimationTraceForTest({0, -1}, false, false, true);
    TrackResources(*attachment_fixture);
    SetAttachmentHashBytesForTest(kAttachmentHashBudgetBytes);
    CompareCall(__imp__sub_82273000, sub_82273000, attachment_read, attachment_fixture->base);
    const auto& budget_snapshot = AnimationTraceSnapshotForTest();
    Require(budget_snapshot.attachment.hash_bytes == kAttachmentHashBudgetBytes &&
        budget_snapshot.attachment.hash_budget_full == 1 &&
        budget_snapshot.attachment.resolver_calls == 2 &&
        budget_snapshot.attachment.resolver_returns == 2 &&
        budget_snapshot.attachment.resolver_verified == 1 &&
        budget_snapshot.attachment.outcomes[animation_kind][size_t(AttachmentOutcome::full)] == 1,
        "attachment hash budget did not preserve the call and report exhaustion");

    ConfigureAnimationTraceForTest({0, -1}, false, false, true);
    TrackResources(*attachment_fixture);
    block_attachment_read = true;
    const auto verified_before_drain = AnimationTraceSnapshotForTest().attachment.outcomes
        [animation_kind][size_t(AttachmentOutcome::verified)];
    attachment_entered = release_attachment_read = false;
    std::thread attachment_worker([&] {
      auto input = attachment_read;
      sub_82273000(input, attachment_fixture->base);
    });
    for (unsigned i = 0; i < 2000 && !attachment_entered.load(); ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (!attachment_entered.load()) {
      release_attachment_read = true;
      attachment_worker.join();
      throw std::runtime_error("shutdown attachment read did not start");
    }
    StopAnimationTraceAdmissionForTest();
    release_attachment_read = true;
    const auto attachment_drained = DrainAnimationTraceForTest(2000);
    attachment_worker.join();
    block_attachment_read = false;
    const auto& drained_attachment = AnimationTraceSnapshotForTest();
    Require(attachment_drained && drained_attachment.stop == StopReason::none &&
        drained_attachment.counters.concurrent == 0 &&
        drained_attachment.attachment.read_inflight_at_flush == 0 &&
        drained_attachment.attachment.outcomes[animation_kind][size_t(AttachmentOutcome::verified)] ==
            verified_before_drain + 1,
        "attachment shutdown did not drain nested resolver work");

    ConfigureAnimationTraceForTest({0, -1});
    for (const auto& pair : {
             std::pair{__imp__sub_820A4648, sub_820A4648},
             std::pair{__imp__sub_820AF768, sub_820AF768},
             std::pair{__imp__sub_8208D878, sub_8208D878},
             std::pair{__imp__sub_820AAFB0, sub_820AAFB0},
             std::pair{__imp__sub_820A2968, sub_820A2968}}) {
      CompareCall(pair.first, pair.second, Context(actor), fixture.base);
    }
    fixture.base[actor + 112] = 0;
    CompareCall(__imp__sub_8217AD08, sub_8217AD08, Context(actor), fixture.base);
    fixture.base[actor + 112] = 1;
    fixture.Store<uint32_t>(actor + 28, UINT32_MAX);
    CompareCall(__imp__sub_8217AD08, sub_8217AD08, Context(actor), fixture.base);
    fixture.Store<uint32_t>(actor + 28, handle);
    CompareCall(__imp__sub_8217AD08, sub_8217AD08, Context(actor), fixture.base);
    CompareCall(__imp__sub_8217AD08, sub_8217AD08, Context(UINT32_MAX), fixture.base);
    const auto dispatch = AnimationTraceSnapshotForTest().dispatch;
    Require(upstream_original_calls == 18 && dispatch.resource_calls == 4 &&
        dispatch.flag_zero == 1 && dispatch.handle_minus_one == 1 &&
        dispatch.eligible == 1 && dispatch.unreadable == 1 &&
        dispatch.setup_wrapper_calls == std::array<uint64_t, 5>{1, 1, 1, 1, 1},
        "upstream counters or original-call preservation");
    fixture.base[actor + 112] = 0;

    ConfigureAnimationTraceForTest({0, -1});
    for (uint32_t i = 0; i < kUnsupportedVtableCapacity + 1; ++i) {
      const auto vtable = 0x82040200u + i * 0x80;
      fixture.Store<uint32_t>(actor + 0x200, vtable);
      fixture.Store<uint32_t>(vtable + 44, 0x82080068);
      auto rejected = Context(actor + 0x200, setup);
      sub_82093BE8(rejected, fixture.base);
    }
    for (uint32_t vtable : {0x100000u, 0u}) {
      fixture.Store<uint32_t>(actor + 0x200, vtable);
      auto rejected = Context(actor + 0x200, setup);
      sub_82093BE8(rejected, fixture.base);
    }
    const auto histogram = AnimationTraceSnapshotForTest().dispatch;
    uint64_t histogram_calls = 0;
    for (const auto& entry : histogram.unsupported_vtables) histogram_calls += entry.calls;
    Require(histogram.setup_rejections[3] == kUnsupportedVtableCapacity + 3 &&
        histogram_calls == kUnsupportedVtableCapacity && histogram.vtable_full == 2 &&
        histogram.vtable_zero == 1 && histogram.getter_unreadable == 1,
        "unsupported-vtable histogram bounds or loss accounting");

    ConfigureAnimationTraceForTest({0, -1}, true);
    TrackResources(fixture);
    auto quaternion_bind = Context(actor, setup);
    sub_82093BE8(quaternion_bind, fixture.base);
    exercise_quaternion = true;
    auto quaternion_evaluation = Context(ba, instance);
    quaternion_evaluation.lr = 0x8229ea94;
    CompareCall(__imp__sub_82298FF0, sub_82298FF0, quaternion_evaluation, fixture.base);
    exercise_quaternion = false;
    const auto probe = AnimationTraceSnapshotForTest();
    Require(probe.quaternion_count == 8 && probe.quaternion_counts.seen == 13 &&
        probe.quaternion_counts.invalid_context == 1 && probe.quaternion_counts.invalid_input == 1 &&
        probe.quaternion_counts.invalid_output == 1 && probe.quaternion_counts.per_evaluation_full == 2 &&
        quaternion_original_calls == 26 && probe.evaluation_count == 1 &&
        probe.quaternion[0].event.parent == probe.evaluation[0].event.id &&
        probe.quaternion[0].left[0] == std::bit_cast<uint32_t>(-1.0f) &&
        probe.quaternion[0].left[3] == std::bit_cast<uint32_t>(-4.0f) &&
        probe.quaternion[0].result[0] == std::bit_cast<uint32_t>(0.25f) &&
        probe.quaternion[0].result[3] == std::bit_cast<uint32_t>(1.0f),
        "quaternion correlation, signed VMX lane order, or bounded losses");
    auto serialized_probe = probe;
    serialized_probe.Stop(StopReason::shutdown);
    std::array<char, kSerializedCapacity> probe_output{};
    size_t probe_size = 0;
    Require(Serialize(serialized_probe, probe_output.data(), probe_output.size(), probe_size) &&
        std::string_view(probe_output.data(), probe_size).find(
            "\"left\":[-1,-2,-3,-4]") != std::string_view::npos,
        "private quaternion sample serialization");
    serialized_probe.quaternion[0].left[0] = 0x80000000u;
    Require(Serialize(serialized_probe, probe_output.data(), probe_output.size(), probe_size) &&
        std::string_view(probe_output.data(), probe_size).find(
            "\"left\":[-0.0,-2,-3,-4]") != std::string_view::npos,
        "quaternion signed zero was not preserved");
    setup_calls = 2;
    eval_calls = pose_calls = 0;

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, Context(actor, setup), fixture.base);
    auto snapshot = AnimationTraceSnapshotForTest();
    Require(setup_calls == 4 && snapshot.selected && snapshot.identity.actor == actor &&
        snapshot.identity.instance == instance && snapshot.identity.ba == ba &&
        snapshot.counters.setup_accepted == 1 && snapshot.identity.source.resolved &&
        snapshot.identity.source.archive_slot == 0 &&
        snapshot.identity.source.member_index == 1 && snapshot.identity.source.member_size == 4 &&
        snapshot.identity.actor_generation && snapshot.identity.instance_generation &&
        snapshot.identity.ba_generation, "synthetic actor binding and source");

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
    const auto source = snapshot.identity.source;
    const auto ba_generation = snapshot.identity.ba_generation;
    const auto decoded_before_cache = decode_calls;
    cache_load = true;
    auto cache = Context(manager);
    sub_8224E6F0(cache, fixture.base);
    cache_load = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.counters.cache_hits == 1 && decode_calls == decoded_before_cache &&
        snapshot.identity.ba_generation == ba_generation && snapshot.identity.source == source,
        "cache hit lost generation or provenance");
    const std::array<uint8_t, 32> expected_member{
        0xc9,0x7c,0x29,0xc7,0xa7,0x1b,0x39,0x2b,0x43,0x7e,0xe0,0x3f,0xd1,0x7f,0x09,0xbb,
        0x10,0xb7,0x5e,0x87,0x94,0x66,0xfc,0x0e,0xb7,0x57,0xb2,0xc4,0xa7,0x8a,0xc9,0x38};
    Require(source.member_digest == expected_member, "resolved member hash mismatch");
    auto release = Context(archive);
    sub_82272F58(release, fixture.base);
    auto reloaded = Context(0, outputs);
    reloaded.r5.u32 = outputs + 4; reloaded.lr = 0x82272ef0;
    sub_822733B8(reloaded, fixture.base);
    auto remount = Context(file_manager, archive);
    sub_82272AF0(remount, fixture.base);
    cache_load = true;
    auto cache_after_reuse = Context(manager);
    sub_8224E6F0(cache_after_reuse, fixture.base);
    cache_load = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::none && snapshot.identity.source == source &&
        snapshot.identity.ba_generation == ba_generation,
        "archive address reuse changed cached BA provenance");

    nested_controller = nested_queue_eval = true;
    auto nested_control = Context(actor);
    sub_82080158(nested_control, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.controller_count == 2 && snapshot.queue_count == 2 &&
        snapshot.evaluation_count == 2 &&
        snapshot.controller[1].event.id < snapshot.queue[1].event.id &&
        snapshot.queue[1].event.parent == snapshot.controller[1].event.id &&
        snapshot.evaluation[1].event.parent == snapshot.queue[1].event.id &&
        snapshot.controller[1].event.begin <= snapshot.queue[1].event.begin &&
        snapshot.queue[1].event.end <= snapshot.controller[1].event.end,
        "nested events lost identity, ordering, or parent timing");
    if (argc == 2 && std::strcmp(argv[1], "--emit-v3") == 0) {
      auto output = std::make_unique<char[]>(kSerializedCapacity);
      size_t size = 0;
      snapshot.Stop(StopReason::shutdown);
      Require(Serialize(snapshot, output.get(), kSerializedCapacity, size),
          "synthetic nested trace did not serialize");
      std::cout.write(output.get(), static_cast<std::streamsize>(size));
      _mm_setcsr(saved_csr);
      return 0;
    }

    uint32_t value = 0;
    Require(AnimationTraceReadForTest(fixture.base, actor, &value, 4), "mapped read rejected");
    uint64_t boundary_value = 0;
    Require(AnimationTraceReadForTest(fixture.base, 0xdffffffc, &boundary_value, 8) ==
                !n3::test::kPhysicalOffsetInCode,
            "physical shadow boundary policy differs");
    DWORD old = 0;
    Require(VirtualProtect(fixture.base + 0x18000, 4096, PAGE_NOACCESS, &old) != 0,
            "cannot protect fixture page");
    const bool inaccessible = AnimationTraceReadForTest(fixture.base, 0x18000, &value, 4);
    DWORD ignored = 0;
    VirtualProtect(fixture.base + 0x18000, 4096, old, &ignored);
    Require(!inaccessible, "unmapped read accepted");

    recursive = true;
    auto nested = Context(ba, instance);
    const auto before_recursive = eval_calls;
    sub_82298FF0(nested, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::reentrant && snapshot.counters.reentrant == 1 &&
        eval_calls == before_recursive + 2 && snapshot.counters.events_abandoned == 1,
        "reentrant original or stop");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    recursive_setup = true;
    const auto setup_before_recursion = setup_calls;
    {
      auto input = Context(actor, setup);
      sub_82093BE8(input, fixture.base);
    }
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::reentrant &&
        snapshot.counters.reentrant == 1 && setup_calls == setup_before_recursion + 2,
        "recursive setup did not retain both calls and fail closed");

    ConfigureAnimationTraceForTest({0, -1});
    mount_slot = 1;
    fixture.Store<uint32_t>(result_object + 20, mount_slot);
    TrackResources(fixture);
    {
      auto input = Context(actor, setup);
      sub_82093BE8(input, fixture.base);
    }
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.identity.source.resolved &&
        snapshot.identity.source.archive_slot == 1 &&
        snapshot.identity.source.member_index == 1, "winning archive slot was not retained");
    mount_slot = 0;
    fixture.Store<uint32_t>(file_manager + 24, 0);
    fixture.Store<uint32_t>(result_object + 20, 0);

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    fixture.Store<uint32_t>(actor + 0x200, 0x82040200);
    fixture.Store<uint32_t>(0x82040200 + 44, 0x82080068);
    auto unrelated_actor = Context(actor + 0x200, 0xdeadbeef);
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, unrelated_actor, fixture.base);
    auto valid_setup = Context(actor, setup);
    sub_82093BE8(valid_setup, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.stop == StopReason::none &&
        snapshot.counters.actor_filtered == 1 && snapshot.dispatch.setup_rejections[3] == 1 &&
        snapshot.dispatch.setup_rejections[5] == 1 &&
        snapshot.dispatch.unsupported_vtables[0].vtable == 0x82040200 &&
        snapshot.dispatch.unsupported_vtables[0].getter == 0x82080068 &&
        snapshot.dispatch.unsupported_vtables[0].calls == 1,
        "unrelated actor blocked selection or lost vtable evidence");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto invalid_setup = Context(actor, 0xdeadbeef);
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, invalid_setup, fixture.base);
    valid_setup = Context(actor, setup);
    sub_82093BE8(valid_setup, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::invalid_mapping &&
        snapshot.counters.invalid == 1 && snapshot.dispatch.setup_rejections[4] == 1,
        "invalid setup mapping did not fail closed");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    fixture.Store<uint32_t>(table + handle * 4, 0);
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, Context(actor, setup), fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    valid_setup = Context(actor, setup);
    sub_82093BE8(valid_setup, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::invalid_mapping &&
        snapshot.counters.invalid == 1, "invalid post-setup identity did not fail closed");

    ConfigureAnimationTraceForTest({actor + 0x200, -1});
    TrackResources(fixture);
    CompareCall(__imp__sub_82093BE8, sub_82093BE8, unrelated_actor, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::identity_changed &&
        snapshot.counters.invalid == 1, "invalid explicitly selected actor was filtered");

    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    TrackResources(fixture);
    auto invalid_queue = Context(manager + 4, handle);
    invalid_queue.r5.u32 = 2;
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, invalid_queue, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::none &&
        snapshot.counters.actor_filtered == 1, "unrelated manager was not filtered");
    fixture.Store<uint32_t>(table + handle * 4, 0);
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    auto after_invalid = queued;
    sub_82252BD8(after_invalid, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::invalid_mapping &&
        snapshot.counters.invalid == 1, "invalid resource mapping did not fail closed");

    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    TrackResources(fixture);
    fixture.Store<uint32_t>(ba, 0);
    CompareCall(__imp__sub_82252BD8, sub_82252BD8, queued, fixture.base);
    fixture.Store<uint32_t>(ba, 0x82051f14);
    after_invalid = queued;
    sub_82252BD8(after_invalid, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::invalid_mapping &&
        snapshot.counters.invalid == 1, "invalid resource vtable did not fail closed");
    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    TrackResources(fixture);
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
    if (snapshot.stop != StopReason::identity_changed || snapshot.counters.invalid != 1)
      std::cerr << "resource changed stop=" << unsigned(snapshot.stop)
                << " invalid=" << snapshot.counters.invalid << '\n';
    Require(snapshot.stop == StopReason::identity_changed && snapshot.counters.invalid == 1,
        "changed resource identity did not stop capture");
    fixture.Store<uint32_t>(table + handle * 4, instance);
    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    TrackResources(fixture);
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

    ConfigureAnimationTraceForTest({0, 2, Scope::resource});
    TrackResources(fixture);
    rebound = Context(manager, handle);
    rebound.r5.u32 = 2;
    sub_82252BD8(rebound, fixture.base);
    extra_pose = true;
    CompareCall(__imp__sub_82298FF0, sub_82298FF0, evaluation, fixture.base);
    extra_pose = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::invalid_value &&
        snapshot.counters.pose_outputs == 4 && snapshot.counters.events_abandoned == 1,
        "excess pose outputs did not fail closed");

    ConfigureAnimationTraceForTest({0, -1});
    cache_load = true;
    const auto before_untracked = ba_load_calls;
    auto untracked = Context(manager);
    sub_8224E6F0(untracked, fixture.base);
    cache_load = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(ba_load_calls == before_untracked + 1 &&
        snapshot.stop == StopReason::untracked_lifetime && snapshot.counters.cache_untracked == 1,
        "untracked cache was accepted or original call lost");

    ConfigureAnimationTraceForTest({0, -1});
    fixture.Store<uint32_t>(result_object + 16, archive + 0x305);
    TrackResources(fixture);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::invalid_mapping && !snapshot.selected,
        "mismatched resolver range was accepted");
    fixture.Store<uint32_t>(result_object + 16, archive + 0x304);

    ConfigureAnimationTraceForTest({0, -1});
    std::memset(fixture.base + archive + 4, 0, 256);
    std::memcpy(fixture.base + archive + 4, "synthetic.ba", sizeof("synthetic.ba"));
    TrackResources(fixture);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::invalid_mapping && !snapshot.selected,
        "resolver skipped an earlier case-insensitive member");
    std::memset(fixture.base + archive + 4, 0, 256);
    std::memcpy(fixture.base + archive + 4, "OTHER.BA", sizeof("OTHER.BA"));

    ConfigureAnimationTraceForTest({0, -1});
    corrupt_loaded = true;
    TrackResources(fixture);
    corrupt_loaded = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::identity_changed && !snapshot.selected,
        "decoded input did not match resolved member");

    ConfigureAnimationTraceForTest({0, -1});
    fixture.Store<uint32_t>(stream + 8, loaded_member + 4);
    TrackResources(fixture);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::untracked_lifetime && !snapshot.selected,
        "decoder stream did not match the observed read");
    fixture.Store<uint32_t>(stream + 8, loaded_member);

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    recursive_collect = true;
    const auto collect_before_recursion = collect_calls;
    {
      auto input = Context(manager);
      sub_8224E9B0(input, fixture.base);
    }
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::reentrant && snapshot.counters.reentrant == 1 &&
        collect_calls == collect_before_recursion + 2, "recursive BA collection was accepted");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    cache_load = true;
    load_during_collect = true;
    const auto ba_before_collect = ba_load_calls;
    {
      auto input = Context(manager);
      sub_8224E9B0(input, fixture.base);
    }
    cache_load = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::reentrant && snapshot.counters.reentrant == 1 &&
        ba_load_calls == ba_before_collect + 1, "BA load during collection was accepted");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    fixture.Store<uint32_t>(ba + 4, 0);
    CompareCall(__imp__sub_8224E9B0, sub_8224E9B0, Context(manager), fixture.base);
    fixture.Store<uint32_t>(ba + 4, 1);
    fixture.Store<uint32_t>(manager + 26168 + ba_handle * 4, ba);
    auto reload_ba = Context(manager);
    sub_8224E6F0(reload_ba, fixture.base);
    auto bind_reload = Context(actor, setup);
    sub_82093BE8(bind_reload, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.stop == StopReason::none &&
        snapshot.identity.ba_generation > snapshot.identity.instance_generation &&
        snapshot.identity.source.resolved, "same-address BA reload did not get a fresh generation");
    fixture.Store<uint32_t>(ba + 4, 0);
    CompareCall(__imp__sub_8224E9B0, sub_8224E9B0, Context(manager), fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::identity_changed && snapshot.counters.invalid == 1,
        "selected BA collection did not fail closed");
    fixture.Store<uint32_t>(ba + 4, 1);
    fixture.Store<uint32_t>(manager + 26168 + ba_handle * 4, ba);

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto remove_before_selection = Context(manager, handle);
    sub_82251D38(remove_before_selection, fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    auto recreate_instance = Context(instance);
    sub_8229CF30(recreate_instance, fixture.base);
    auto bind_recreated = Context(actor, setup);
    sub_82093BE8(bind_recreated, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.stop == StopReason::none &&
        snapshot.identity.instance_generation > snapshot.identity.ba_generation,
        "observed preselection instance reload lacked a new generation");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    recursive_reset = true;
    const auto reset_before_recursion = reset_calls;
    {
      auto input = Context(manager);
      sub_8224E0B8(input, fixture.base);
    }
    fixture.Store<uint32_t>(table + handle * 4, instance);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::reentrant && snapshot.counters.reentrant == 1 &&
        reset_calls == reset_before_recursion + 2, "recursive manager reset was accepted");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto other_instance = Context(instance + 0x800);
    sub_8229CF30(other_instance, fixture.base);
    auto reset_before_selection = Context(manager);
    sub_8224E0B8(reset_before_selection, fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    CompareCall(__imp__sub_8229CF30, sub_8229CF30, Context(instance + 0x800), fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::identity_changed,
        "reset discarded an unrelated live instance record");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    reset_before_selection = Context(manager);
    sub_8224E0B8(reset_before_selection, fixture.base);
    fixture.Store<uint32_t>(table + handle * 4, instance);
    recreate_instance = Context(instance);
    sub_8229CF30(recreate_instance, fixture.base);
    bind_recreated = Context(actor, setup);
    sub_82093BE8(bind_recreated, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.stop == StopReason::none &&
        snapshot.identity.instance_generation > snapshot.identity.ba_generation,
        "observed manager reset did not renew the instance generation");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    CompareCall(__imp__sub_8229CF30, sub_8229CF30, Context(instance), fixture.base);
    auto after_unobserved_reuse = Context(actor, setup);
    sub_82093BE8(after_unobserved_reuse, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.stop == StopReason::identity_changed,
        "unobserved preselection instance reuse was accepted");

    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto bind = Context(actor, setup);
    sub_82093BE8(bind, fixture.base);
    auto reused = Context(instance);
    CompareCall(__imp__sub_8229CF30, sub_8229CF30, reused, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::identity_changed && snapshot.counters.invalid == 1,
        "same-address instance reuse was accepted");
    for (const auto& pair : {
             std::pair{__imp__sub_82251D38, sub_82251D38},
             std::pair{__imp__sub_8224E0B8, sub_8224E0B8}}) {
      fixture.Store<uint32_t>(table + handle * 4, instance);
      ConfigureAnimationTraceForTest({0, -1});
      TrackResources(fixture);
      auto bind_actor = Context(actor, setup);
      sub_82093BE8(bind_actor, fixture.base);
      auto remove = Context(manager, handle);
      CompareCall(pair.first, pair.second, remove, fixture.base);
      snapshot = AnimationTraceSnapshotForTest();
      Require(snapshot.stop == StopReason::identity_changed,
          "instance destruction or reset was not observed");
    }
    constexpr uint32_t other_manager = 0x30000, other_table = 0x4f000;
    Require(VirtualAlloc(fixture.base + other_manager, 0x20000, MEM_COMMIT, PAGE_READWRITE) != nullptr,
        "cannot commit second synthetic manager");
    fixture.Store<uint32_t>(other_manager + 66268, 1);
    fixture.Store<uint32_t>(other_manager + 66272, other_table);
    fixture.Store<uint32_t>(other_table, instance);
    for (const auto& pair : {
             std::pair{__imp__sub_82251D38, sub_82251D38},
             std::pair{__imp__sub_8224E0B8, sub_8224E0B8}}) {
      fixture.Store<uint32_t>(table + handle * 4, instance);
      ConfigureAnimationTraceForTest({0, -1});
      TrackResources(fixture);
      auto bind_actor = Context(actor, setup);
      sub_82093BE8(bind_actor, fixture.base);
      CompareCall(pair.first, pair.second, Context(other_manager, 0), fixture.base);
      snapshot = AnimationTraceSnapshotForTest();
      Require(snapshot.stop == StopReason::identity_changed,
          "selected instance alias in another manager was ignored");
    }
    fixture.Store<uint32_t>(table + handle * 4, instance);
    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto submit_bind = Context(actor, setup);
    sub_82093BE8(submit_bind, fixture.base);
    const auto submissions_before = submit_calls;
    CompareCall(__imp__sub_8224AC98, sub_8224AC98, Context(manager, handle), fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(submit_calls == submissions_before + 2 && snapshot.stop == StopReason::none &&
        snapshot.selected && snapshot.identity.instance == instance,
        "non-destructive instance submission changed identity or original calls");
    destroy_during_submit = true;
    auto destructive_submit = Context(manager, handle);
    sub_8224AC98(destructive_submit, fixture.base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::identity_changed && snapshot.counters.invalid,
        "destruction nested in instance submission was not observed");
    fixture.Store<uint32_t>(table + handle * 4, instance);
    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    auto concurrent_bind = Context(actor, setup);
    sub_82093BE8(concurrent_bind, fixture.base);
    block_evaluation = true;
    evaluation_entered = release_evaluation = false;
    std::thread worker([&] {
      auto eval = Context(ba, instance);
      eval.lr = 0x8229ea94;
      sub_82298FF0(eval, fixture.base);
    });
    for (unsigned i = 0; i < 2000 && !evaluation_entered.load(); ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (!evaluation_entered.load()) {
      release_evaluation = true;
      worker.join();
      throw std::runtime_error("concurrent evaluation did not start");
    }
    auto concurrent_queue = Context(manager, handle);
    concurrent_queue.r5.u32 = 2;
    sub_82252BD8(concurrent_queue, fixture.base);
    release_evaluation = true;
    worker.join();
    block_evaluation = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.stop == StopReason::concurrent_actor && snapshot.counters.concurrent &&
        snapshot.counters.events_abandoned == 1, "concurrent association did not fail closed");

    fixture.Store<uint32_t>(table + handle * 4, instance);
    ConfigureAnimationTraceForTest({0, -1});
    TrackResources(fixture);
    concurrent_bind = Context(actor, setup);
    sub_82093BE8(concurrent_bind, fixture.base);
    block_evaluation = true;
    evaluation_entered = release_evaluation = false;
    std::thread draining_worker([&] {
      auto eval = Context(ba, instance);
      eval.lr = 0x8229ea94;
      sub_82298FF0(eval, fixture.base);
    });
    for (unsigned i = 0; i < 2000 && !evaluation_entered.load(); ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (!evaluation_entered.load()) {
      release_evaluation = true;
      draining_worker.join();
      throw std::runtime_error("shutdown evaluation did not start");
    }
    StopAnimationTraceAdmissionForTest();
    release_evaluation = true;
    const auto evaluation_drained = DrainAnimationTraceForTest(2000);
    draining_worker.join();
    block_evaluation = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(evaluation_drained && snapshot.stop == StopReason::none &&
        snapshot.counters.concurrent == 0 && snapshot.counters.events_abandoned == 0 &&
        snapshot.evaluation_count == 1 && snapshot.counters.inflight_at_flush == 0,
        "normal shutdown abandoned an in-flight evaluation");

    ConfigureAnimationTraceForTest({0, -1});
    const auto before_archives = archive_calls;
    archive_result_size = 4;
    for (uint32_t i = 0; i < 65; ++i) {
      archive_result = 0x28000 + i * 4;
      auto load_archive = Context(0, outputs);
      load_archive.r5.u32 = outputs + 4; load_archive.lr = 0x82272ef0;
      sub_822733B8(load_archive, fixture.base);
    }
    archive_result = archive;
    archive_result_size = archive_size;
    snapshot = AnimationTraceSnapshotForTest();
    Require(archive_calls == before_archives + 65 && snapshot.stop == StopReason::registry_full &&
        snapshot.counters.registry_full == 1, "archive registry exhaustion did not fail closed");

    auto signal_fixture = std::make_unique<Fixture>();
    ConfigureAnimationTraceForTest({0, -1}, false, true);
    TrackResources(*signal_fixture);
    TrackSignalAssets(*signal_fixture);
    signal_fixture->Store<uint32_t>(actor + 192, 0);
    constexpr uint32_t other_actor = actor + 0x200;
    signal_fixture->Store<uint32_t>(other_actor, 0xdeadbeef);
    const auto preselection_count = AnimationTraceSnapshotForTest().signal_count;
    signal_fake = false;
    for (auto hook : {sub_82097868, sub_82097958, sub_82097D00}) {
      auto input = Context(actor, 0);
      hook(input, signal_fixture->base);
    }
    auto orphan_selection = Context(info, 0);
    sub_8210CFE8(orphan_selection, signal_fixture->base);
    auto rejected_setup = Context(other_actor, setup);
    sub_82093BE8(rejected_setup, signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(!snapshot.selected && snapshot.signal_count == preselection_count &&
        snapshot.signal_counts.seen[size_t(SignalKind::setup)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::request)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::selection)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::install)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::group)] == 0,
        "preselection actor observations were not excluded");
    signal_fake = true;
    auto signal_setup = Context(actor, setup);
    sub_82093BE8(signal_setup, signal_fixture->base);
    const auto selected_count = AnimationTraceSnapshotForTest().signal_count;
    for (auto hook : {sub_82097868, sub_82097958, sub_82097D00}) {
      auto input = Context(other_actor, 0);
      hook(input, signal_fixture->base);
    }
    auto other_setup = Context(other_actor, setup);
    sub_82093BE8(other_setup, signal_fixture->base);
    auto detached_selection = Context(info, 0);
    sub_8210CFE8(detached_selection, signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.selected && snapshot.identity.actor == actor &&
        snapshot.signal_count == selected_count &&
        snapshot.signal_counts.seen[size_t(SignalKind::setup)] == 1 &&
        snapshot.signal_counts.seen[size_t(SignalKind::request)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::selection)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::install)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::group)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::dispatch)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::effect)] == 0,
        "nonprimary actor or unscoped selection was recorded");
    signal_fixture->base[effect_manager + 740] = 0;
    const auto signal_originals_before = signal_original_calls;
    auto signal_request = Context(actor, 7);
    signal_request.r5.u32 = 3; signal_request.r6.u32 = 5;
    sub_82097868(signal_request, signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    const SignalSample *as_sample = nullptr, *info_sample = nullptr, *setup_sample = nullptr;
    const SignalSample *request_sample = nullptr, *selection_sample = nullptr, *install_sample = nullptr;
    const SignalSample *group_sample = nullptr, *dispatch_sample = nullptr;
    size_t changed_effects = 0, wrong_effect_actors = 0;
    for (size_t i = 0; i < snapshot.signal_count; ++i) {
      const auto& item = snapshot.signal_samples[i];
      switch (item.kind) {
        case SignalKind::as_load: as_sample = &item; break;
        case SignalKind::info_load: info_sample = &item; break;
        case SignalKind::setup: setup_sample = &item; break;
        case SignalKind::request: request_sample = &item; break;
        case SignalKind::selection: selection_sample = &item; break;
        case SignalKind::install: install_sample = &item; break;
        case SignalKind::group: group_sample = &item; break;
        case SignalKind::dispatch: dispatch_sample = &item; break;
        case SignalKind::effect:
          changed_effects += item.changed_slots != 0;
          wrong_effect_actors += item.actor_generation != snapshot.identity.actor_generation;
          break;
        default: break;
      }
    }
    Require(as_sample && info_sample && as_sample->source.resolved && info_sample->source.resolved &&
        as_sample->source.member_index == 0 && info_sample->source.member_index == 1 &&
        as_sample->source.archive_digest == info_sample->source.archive_digest &&
        setup_sample && setup_sample->identity_bound && request_sample && selection_sample &&
        install_sample && group_sample && group_sample->identity_bound && dispatch_sample &&
        setup_sample->actor_generation == snapshot.identity.actor_generation &&
        request_sample->actor_generation == snapshot.identity.actor_generation &&
        install_sample->actor_generation == snapshot.identity.actor_generation &&
        group_sample->actor_generation == snapshot.identity.actor_generation &&
        dispatch_sample->actor_generation == snapshot.identity.actor_generation &&
        selection_sample->event.parent == request_sample->event.id &&
        install_sample->event.parent == request_sample->event.id &&
        group_sample->event.parent == install_sample->event.id &&
        dispatch_sample->event.parent == group_sample->event.id &&
        selection_sample->row_read && selection_sample->row_type == 7 &&
        selection_sample->row_index == 3 && selection_sample->row_attribute == 5 &&
        install_sample->selected_row == 0 && install_sample->installed_row == 0 &&
        dispatch_sample->source_offset && dispatch_sample->group_offset == 520 &&
        dispatch_sample->table_offset == 524 && dispatch_sample->record_offset == 548 &&
        dispatch_sample->record_kind == 24 && changed_effects == 2 && wrong_effect_actors == 0 &&
        snapshot.signal_recorded[size_t(SignalKind::dispatch)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::effect)] == 2 &&
        snapshot.signal_counts.record_map_invalid == 0 &&
        signal_original_calls == signal_originals_before + 7,
        "signal provenance, retained offsets, shared events or independent effects");
    snapshot.Stop(StopReason::shutdown);
    auto signal_json = std::make_unique<char[]>(kSerializedCapacity);
    size_t signal_size = 0;
    Require(Serialize(snapshot, signal_json.get(), kSerializedCapacity, signal_size) &&
        std::string_view(signal_json.get(), signal_size).find("SYNTHETIC") == std::string_view::npos,
        "signal trace serialization or private-name redaction");
    if (argc == 2 && std::strcmp(argv[1], "--emit-signal-v3") == 0) {
      std::cout.write(signal_json.get(), static_cast<std::streamsize>(signal_size));
      signal_fake = false;
      _mm_setcsr(saved_csr);
      return 0;
    }
    auto release_as = Context(signal);
    sub_8210BE98(release_as, signal_fixture->base);
    auto group_after_release = Context(actor);
    sub_82097D00(group_after_release, signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    bool invalidated = false;
    for (size_t i = 0; i < snapshot.signal_count; ++i)
      if (snapshot.signal_samples[i].kind == SignalKind::group &&
          !snapshot.signal_samples[i].identity_bound) invalidated = true;
    Require(invalidated, "released signal asset remained identity-bound");
    signal_fake = false;

    for (const auto mode : {NestedOtherRequest::normal, NestedOtherRequest::throwing}) {
      auto nested_fixture = std::make_unique<Fixture>();
      ConfigureAnimationTraceForTest({0, -1}, false, true);
      TrackResources(*nested_fixture);
      TrackSignalAssets(*nested_fixture);
      nested_fixture->Store<uint32_t>(actor + 192, 0);
      auto nested_setup = Context(actor, setup);
      sub_82093BE8(nested_setup, nested_fixture->base);
      const auto originals_before = signal_original_calls;
      nested_other_request = mode;
      nested_other_caught = false;
      auto nested_request = Context(actor, 7);
      nested_request.r5.u32 = 3; nested_request.r6.u32 = 5;
      sub_82097868(nested_request, nested_fixture->base);
      snapshot = AnimationTraceSnapshotForTest();
      const SignalSample *nested_request_sample = nullptr, *nested_dispatch_sample = nullptr;
      for (size_t i = 0; i < snapshot.signal_count; ++i) {
        const auto& item = snapshot.signal_samples[i];
        if (item.kind == SignalKind::request) nested_request_sample = &item;
        if (item.kind == SignalKind::dispatch) nested_dispatch_sample = &item;
      }
      size_t request_selections = 0, dispatch_selections = 0, dispatch_effects = 0;
      bool wrong_actor = false, wrong_selection = false;
      for (size_t i = 0; i < snapshot.signal_count; ++i) {
        const auto& item = snapshot.signal_samples[i];
        if (item.kind == SignalKind::selection) {
          wrong_selection |= item.requested_type != 7 || item.requested_index != 3 ||
              item.requested_attribute != 5;
          if (nested_request_sample && item.event.parent == nested_request_sample->event.id)
            ++request_selections;
          if (nested_dispatch_sample && item.event.parent == nested_dispatch_sample->event.id)
            ++dispatch_selections;
        }
        if (item.kind == SignalKind::request || item.kind == SignalKind::install ||
            item.kind == SignalKind::group || item.kind == SignalKind::dispatch ||
            item.kind == SignalKind::effect)
          wrong_actor |= item.actor != actor ||
              item.actor_generation != snapshot.identity.actor_generation;
        if (item.kind == SignalKind::effect && nested_dispatch_sample &&
            item.event.parent == nested_dispatch_sample->event.id) ++dispatch_effects;
      }
      Require(snapshot.stop == StopReason::none && nested_request_sample && nested_dispatch_sample &&
          nested_other_caught == (mode == NestedOtherRequest::throwing) &&
          active_other_request == NestedOtherRequest::none &&
          snapshot.controller_count == 1 && snapshot.controller[0].event.parent == 0 &&
          signal_original_calls == originals_before + 15 &&
          snapshot.signal_counts.seen[size_t(SignalKind::request)] == 1 &&
          snapshot.signal_counts.seen[size_t(SignalKind::selection)] == 2 &&
          snapshot.signal_counts.seen[size_t(SignalKind::install)] == 1 &&
          snapshot.signal_counts.seen[size_t(SignalKind::group)] == 1 &&
          snapshot.signal_counts.seen[size_t(SignalKind::dispatch)] == 2 &&
          snapshot.signal_counts.skipped[size_t(SignalKind::dispatch)] == 1 &&
          snapshot.signal_counts.seen[size_t(SignalKind::effect)] == 2 &&
          request_selections == 1 && dispatch_selections == 1 && dispatch_effects == 2 &&
          !wrong_actor && !wrong_selection,
          "nested excluded actor inherited signal context or prevented its restoration");
      signal_fake = false;
    }

    auto bounded_signal_fixture = std::make_unique<Fixture>();
    ConfigureAnimationTraceForTest({0, -1}, false, true);
    TrackResources(*bounded_signal_fixture);
    TrackSignalAssets(*bounded_signal_fixture);
    bounded_signal_fixture->Store<uint32_t>(actor + 192, 0);
    auto bounded_setup = Context(actor, setup);
    sub_82093BE8(bounded_setup, bounded_signal_fixture->base);
    signal_skip_dispatch = true;
    for (size_t i = 0; i < kSignalCapacities[size_t(SignalKind::group)]; ++i) {
      auto group = Context(actor);
      sub_82097D00(group, bounded_signal_fixture->base);
    }
    signal_skip_dispatch = false;
    auto group_at_capacity = Context(actor);
    sub_82097D00(group_at_capacity, bounded_signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    const SignalSample* retained_dispatch = nullptr;
    for (size_t i = 0; i < snapshot.signal_count; ++i)
      if (snapshot.signal_samples[i].kind == SignalKind::dispatch)
        retained_dispatch = &snapshot.signal_samples[i];
    Require(snapshot.signal_counts.full[size_t(SignalKind::group)] == 1 &&
        retained_dispatch && retained_dispatch->group_read &&
        retained_dispatch->group_index == 0 && retained_dispatch->record_read &&
        retained_dispatch->source_offset && retained_dispatch->record_offset == 548 &&
        retained_dispatch->actor_generation == snapshot.identity.actor_generation &&
        snapshot.signal_recorded[size_t(SignalKind::effect)] == 2,
        "group capacity discarded downstream context");

    const auto before_nested_dispatch = snapshot.signal_counts;
    signal_nested_path2 = true;
    auto nested_dispatch_group = Context(actor);
    sub_82097D00(nested_dispatch_group, bounded_signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    const auto dispatch_kind = size_t(SignalKind::dispatch);
    const auto effect_kind = size_t(SignalKind::effect);
    Require(snapshot.signal_counts.skipped[dispatch_kind] ==
            before_nested_dispatch.skipped[dispatch_kind] + 3 &&
        snapshot.signal_counts.skipped[effect_kind] ==
            before_nested_dispatch.skipped[effect_kind] + 2,
        "nested dispatch did not count its downstream effect losses");

    for (size_t i = snapshot.signal_recorded[size_t(SignalKind::dispatch)];
         i < kSignalCapacities[size_t(SignalKind::dispatch)]; ++i) {
      auto group = Context(actor);
      sub_82097D00(group, bounded_signal_fixture->base);
    }
    const auto before_dispatch_full = AnimationTraceSnapshotForTest().signal_counts;
    auto dispatch_at_capacity = Context(actor);
    sub_82097D00(dispatch_at_capacity, bounded_signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.signal_counts.full[dispatch_kind] == before_dispatch_full.full[dispatch_kind] + 1 &&
        snapshot.signal_counts.skipped[dispatch_kind] ==
            before_dispatch_full.skipped[dispatch_kind] + 1 &&
        snapshot.signal_counts.seen[effect_kind] == before_dispatch_full.seen[effect_kind] + 2 &&
        snapshot.signal_counts.skipped[effect_kind] == before_dispatch_full.skipped[effect_kind] + 2,
        "dropped dispatch or downstream effect was not explicitly counted");
    signal_fake = false;

    for (const auto& pair : {
             std::pair{__imp__sub_8210BF78, sub_8210BF78},
             std::pair{__imp__sub_8210CB78, sub_8210CB78},
             std::pair{__imp__sub_8210BE98, sub_8210BE98},
             std::pair{__imp__sub_8210CAB8, sub_8210CAB8},
             std::pair{__imp__sub_8210C728, sub_8210C728},
             std::pair{__imp__sub_8210CFE8, sub_8210CFE8},
             std::pair{__imp__sub_82097868, sub_82097868},
             std::pair{__imp__sub_82097958, sub_82097958},
             std::pair{__imp__sub_82097D00, sub_82097D00},
             std::pair{__imp__sub_820927C0, sub_820927C0},
             std::pair{__imp__sub_8209BE30, sub_8209BE30},
             std::pair{__imp__sub_82097D90, sub_82097D90},
             std::pair{__imp__sub_8212ACA8, sub_8212ACA8}}) {
      ConfigureAnimationTraceForTest({0, -1}, false, true);
      const auto before = signal_original_calls;
      CompareCall(pair.first, pair.second, Context(actor, info), signal_fixture->base);
      Require(signal_original_calls == before + 2, "signal hook did not preserve its original call");
    }

    auto drain_signal_fixture = std::make_unique<Fixture>();
    ConfigureAnimationTraceForTest({0, -1}, false, true);
    TrackResources(*drain_signal_fixture);
    TrackSignalAssets(*drain_signal_fixture);
    drain_signal_fixture->Store<uint32_t>(actor + 192, 0);
    auto drain_setup = Context(actor, setup);
    sub_82093BE8(drain_setup, drain_signal_fixture->base);
    block_signal_request = true;
    signal_entered = release_signal_request = false;
    std::thread signal_worker([&] {
      auto input = Context(actor, 7);
      input.r5.u32 = 3; input.r6.u32 = 5;
      sub_82097868(input, drain_signal_fixture->base);
    });
    for (unsigned i = 0; i < 2000 && !signal_entered.load(); ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (!signal_entered.load()) {
      release_signal_request = true;
      signal_worker.join();
      throw std::runtime_error("shutdown signal request did not start");
    }
    StopAnimationTraceAdmissionForTest();
    auto rejected_after_close = Context(actor);
    sub_82097D00(rejected_after_close, drain_signal_fixture->base);
    release_signal_request = true;
    const auto signal_drained = DrainAnimationTraceForTest(2000);
    signal_worker.join();
    block_signal_request = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(signal_drained && snapshot.stop == StopReason::none &&
        snapshot.counters.concurrent == 0 && snapshot.counters.events_abandoned == 0 &&
        snapshot.signal_recorded[size_t(SignalKind::request)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::selection)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::install)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::group)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::dispatch)] == 1 &&
        snapshot.signal_recorded[size_t(SignalKind::effect)] == 2 &&
        snapshot.signal_inflight[size_t(SignalKind::request)] == 0 &&
        snapshot.counters.inflight_at_flush == 0,
        "shutdown failed to drain nested hooks or admitted a new root");
    signal_fake = false;

    auto timeout_fixture = std::make_unique<Fixture>();
    ConfigureAnimationTraceForTest({0, -1}, true, true, true);
    TrackResources(*timeout_fixture);
    auto timeout_setup = Context(actor, setup);
    sub_82093BE8(timeout_setup, timeout_fixture->base);
    const std::filesystem::path prefix =
        "n3-animation-timeout-regression-" + std::to_string(GetCurrentProcessId());
    auto trace_path = prefix; trace_path += ".trace.json";
    auto attachment_path = prefix; attachment_path += ".attachment.json";
    auto timeout_path = prefix; timeout_path += ".timeout.json";
    Require(!std::filesystem::exists(trace_path) && !std::filesystem::exists(attachment_path) &&
        !std::filesystem::exists(timeout_path), "timeout test output already exists");
    SetAnimationTraceOutputsForTest(prefix);
    bad_pose_return = true;
    PauseAnimationTraceInvalidOutputForTest(true);
    std::thread timeout_worker([&] {
      auto input = Context(ba, instance);
      input.lr = 0x8229ea94;
      sub_82298FF0(input, timeout_fixture->base);
    });
    for (unsigned i = 0; i < 2000 && !AnimationTraceInvalidOutputPausedForTest(); ++i)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (!AnimationTraceInvalidOutputPausedForTest()) {
      PauseAnimationTraceInvalidOutputForTest(false);
      timeout_worker.join();
      bad_pose_return = false;
      throw std::runtime_error("invalid-output counter interleave did not start");
    }
    ShutdownAnimationTrace();
    std::error_code file_error;
    const bool trace_written = std::filesystem::exists(trace_path, file_error);
    const bool attachment_written = std::filesystem::exists(attachment_path, file_error);
    std::ifstream timeout_file(timeout_path, std::ios::binary);
    const std::string timeout_json{std::istreambuf_iterator<char>(timeout_file),
                                   std::istreambuf_iterator<char>()};
    timeout_file.close();
    const bool removed = std::filesystem::remove(timeout_path, file_error);
    if (trace_written) std::filesystem::remove(trace_path, file_error);
    if (attachment_written) std::filesystem::remove(attachment_path, file_error);
    PauseAnimationTraceInvalidOutputForTest(false);
    timeout_worker.join();
    bad_pose_return = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(!file_error && removed && !trace_written && !attachment_written &&
        snapshot.stop == StopReason::concurrent_probe && snapshot.counters.concurrent == 1 &&
        snapshot.counters.invalid_outputs == 2 &&
        snapshot.counters.invalid >= snapshot.counters.invalid_outputs &&
        timeout_json.find("\"aggregate\":\"omitted\"") != std::string::npos &&
        timeout_json.find("\"inflight_at_timeout\":1") != std::string::npos,
        "drain timeout read live counters or failed to write its incomplete diagnostic");
    if (argc == 2 && std::strcmp(argv[1], "--emit-timeout-v1") == 0) {
      std::cout << timeout_json;
      _mm_setcsr(saved_csr);
      return 0;
    }

    ConfigureAnimationTraceForTest({0, -1}, false, true);
    auto invalid_signal_load = Context(0);
    sub_8210BF78(invalid_signal_load, signal_fixture->base);
    snapshot = AnimationTraceSnapshotForTest();
    Require(snapshot.signal_recorded[size_t(SignalKind::as_load)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::as_load)] == 1 &&
        snapshot.signal_counts.unreadable[size_t(SignalKind::as_load)] == 1 &&
        snapshot.counters.events_abandoned == 1,
        "unbound successful load was not counted as unreadable and abandoned");

    ConfigureAnimationTraceForTest({0, -1}, false, true);
    cache_load = true;
    auto unknown_ba = Context(manager);
    const auto ba_before_untracked_signal = ba_load_calls;
    sub_8224E6F0(unknown_ba, signal_fixture->base);
    cache_load = false;
    snapshot = AnimationTraceSnapshotForTest();
    Require(ba_load_calls == ba_before_untracked_signal + 1 &&
        snapshot.stop == StopReason::untracked_lifetime &&
        snapshot.signal_recorded[size_t(SignalKind::ba_load)] == 0 &&
        snapshot.signal_counts.seen[size_t(SignalKind::ba_load)] == 1 &&
        snapshot.signal_counts.unreadable[size_t(SignalKind::ba_load)] == 1,
        "untracked BA load was not preserved and counted as unreadable");
    _mm_setcsr(saved_csr);
    std::cout << "animation trace hooks: retained calls, host state and guarded mappings passed\n";
    return 0;
  } catch (const std::exception& error) {
    _mm_setcsr(saved_csr);
    std::cerr << error.what() << '\n';
    return 1;
  }
}
