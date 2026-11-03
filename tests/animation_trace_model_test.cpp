#include "animation_trace_model.h"

#include <array>
#include <bit>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace {
using namespace n3::animation_trace;
void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
uint32_t Float(float value) { return std::bit_cast<uint32_t>(value); }
uint64_t Double(double value) { return std::bit_cast<uint64_t>(value); }
template<typename T>
bool Add(Trace& trace, T sample) {
  if (!trace.BeginEvent(sample.event, 0, trace.last_event + 1)) return false;
  sample.event.end = sample.event.begin + 1;
  bool added = false;
  if constexpr (std::is_same_v<T, ControllerSample>) added = trace.AddController(sample);
  else if constexpr (std::is_same_v<T, QueueSample>) added = trace.AddQueue(sample);
  else added = trace.AddEvaluation(sample);
  if (!added) trace.AbandonEvent();
  return added;
}

void CheckHashAndOverflow() {
  Sha256 hash;
  constexpr auto input = "abc";
  hash.Update(reinterpret_cast<const uint8_t*>(input), 1);
  hash.Update(reinterpret_cast<const uint8_t*>(input + 1), 2);
  const std::array<uint8_t, 32> expected{
      0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,
      0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad};
  Require(hash.Finish() == expected, "incremental SHA-256");
  Trace overflow;
  overflow.last_generation = UINT64_MAX;
  Require(!overflow.NextGeneration() && overflow.stop == StopReason::counter_overflow &&
      overflow.counters.counter_saturated == 1, "generation overflow");
  Trace count;
  count.counters.queue_full = UINT64_MAX;
  Require(!count.Count(count.counters.queue_full) && count.stop == StopReason::counter_overflow &&
      count.counters.queue_full == UINT64_MAX, "counter overflow");
  Trace event;
  event.last_event = UINT64_MAX;
  Event output{};
  Require(!event.BeginEvent(output, 0, 1) && event.stop == StopReason::counter_overflow &&
      event.last_event == UINT64_MAX && event.counters.counter_saturated == 1,
      "event sequence overflow");
}

void CheckTimeoutDiagnostic() {
  std::array<char, 256> output{};
  size_t size = 0;
  Require(SerializeDrainTimeout(1, output.data(), output.size(), size) &&
      std::string_view(output.data(), size).find("\"aggregate\":\"omitted\"") !=
          std::string_view::npos, "timeout diagnostic omitted its incomplete status");
  Require(!SerializeDrainTimeout(0, output.data(), output.size(), size) &&
      !SerializeDrainTimeout(0x80000000u, output.data(), output.size(), size) &&
      !SerializeDrainTimeout(1, nullptr, output.size(), size) &&
      !SerializeDrainTimeout(1, output.data(), 16, size),
      "invalid or truncated timeout diagnostic was accepted");
}

void CheckFilters() {
  uint32_t actor = 77;
  Require(ParseActor("first", actor) && actor == 0, "first actor");
  Require(ParseActor("0x82040170", actor) && actor == 0x82040170, "address actor");
  for (auto text : {"", "0x0", "0X123", "12", "0x100000000", "0x123junk"})
    Require(!ParseActor(text, actor), "invalid actor accepted");
  int32_t clip = 0;
  Require(ParseClip("all", clip) && clip == -1, "all clips");
  Require(ParseClip("4095", clip) && clip == 4095, "last clip");
  for (auto text : {"", "-1", "+1", "4096", "0x10", "1junk"})
    Require(!ParseClip(text, clip), "invalid clip accepted");
  Scope scope = Scope::actor;
  Require(ParseScope("resource", scope) && scope == Scope::resource &&
      ParseScope("actor", scope) && scope == Scope::actor &&
      !ParseScope("", scope) && !ParseScope("other", scope), "invalid scope parsing");
  Require(MatchesActor({0, -1}, 4) && !MatchesActor({0, -1}, 0) &&
      MatchesActor({4, -1}, 4) && !MatchesActor({4, -1}, 5), "actor predicate");
  Require(MatchesClip({0, -1}, 7) && MatchesClip({0, 7}, 7) &&
      !MatchesClip({0, 7}, 8), "clip predicate");
  Require(BasenameFingerprint("D:\\X\\HELLO", 10) == 0xa430d84680aabd0bull,
          "basename fingerprint");
  Require(FiniteFloatBits(Float(0.0f)) && !FiniteFloatBits(0x7f800000) &&
      !FiniteFloatBits(0x7fc00000) && FiniteDoubleBits(Double(-0.0)) &&
      !FiniteDoubleBits(0x7ff0000000000000ull), "finite classification");
}

void CheckBoundsAndSerialization(bool emit = false) {
  Trace trace;
  trace.selected = true;
  trace.identity.clips = 100;
  trace.identity.bones = 75;
  trace.identity.actor = 0x1234;
  trace.identity.actor_vtable = 0x82040170;
  trace.identity.manager = 0x2222;
  trace.identity.instance = 0x3333;
  trace.identity.ba = 0x4444;
  trace.identity.signal = 0x5555;
  trace.identity.info = 0x6666;
  trace.identity.signal_groups = 100;
  trace.identity.info_rows = 100;
  trace.identity.actor_generation = 3;
  trace.identity.instance_generation = 2;
  trace.identity.ba_generation = 1;
  trace.clock_frequency = 10000000;
  trace.identity.name_length = 5;
  trace.identity.name_fingerprint = 0xa430d84680aabd0bull;
  trace.counters.setup_calls = 1;
  trace.counters.setup_accepted = 1;
  trace.counters.controller_calls = kControllerCapacity + 1;
  trace.counters.queue_calls = kQueueCapacity + 1;
  trace.counters.evaluation_calls = kEvaluationCapacity + 1;
  const ControllerSample controller{0x82094b64, 4, 4, Float(2), Float(3), Float(1)};
  const QueueSample queue{0x820802d0, 4, Double(2)};
  const EvaluationSample evaluation{0x8229ea94, 4, Float(2), 1, 75, 0};
  for (size_t i = 0; i < kControllerCapacity; ++i)
    Require(Add(trace, controller), "controller prematurely full");
  for (size_t i = 0; i < kQueueCapacity; ++i)
    Require(Add(trace, queue), "queue prematurely full");
  for (size_t i = 0; i < kEvaluationCapacity; ++i)
    Require(Add(trace, evaluation), "evaluation prematurely full");
  Require(!Add(trace, controller) && !Add(trace, queue) &&
      !Add(trace, evaluation), "capacity did not stop additions");
  Require(trace.counters.controller_full == 1 && trace.counters.queue_full == 1 &&
      trace.counters.evaluation_full == 1 && trace.counters.pose_outputs == 4800,
      "bounded counters");
  trace.quaternion_enabled = true;
  for (size_t i = 0; i < kQuaternionCapacity; ++i) {
    auto& sample = trace.quaternion[trace.quaternion_count++];
    const auto& parent = trace.evaluation[i / kQuaternionPerEvaluationCapacity].event;
    sample.caller = 0x8229a214;
    sample.bone = 74;
    sample.factor = 0x7f7fffff;
    sample.left.fill(0x7f7fffff);
    sample.right.fill(0x7f7fffff);
    sample.result.fill(0x7f7fffff);
    Require(trace.BeginEvent(sample.event, parent.id, parent.begin), "quaternion event capacity");
  }
  trace.quaternion_counts.seen = kQuaternionCapacity;
  trace.signal_enabled = true;
  for (size_t kind = 0; kind < kSignalKindCount; ++kind) {
    for (size_t i = 0; i < kSignalCapacities[kind]; ++i) {
      auto& sample = trace.signal_samples[trace.signal_count++];
      sample.kind = static_cast<SignalKind>(kind);
      sample.caller = sample.actor = sample.instance = sample.ba = sample.signal = sample.info =
          UINT32_MAX;
      sample.actor_vtable = 0x82040170;
      sample.actor_generation = UINT64_MAX;
      sample.instance_generation = UINT64_MAX - 1;
      sample.ba_generation = UINT64_MAX - 2;
      sample.signal_generation = UINT64_MAX - 3;
      sample.info_generation = UINT64_MAX - 4;
      sample.instance_handle = sample.setup_key4 = sample.setup_key88 = UINT32_MAX;
      sample.ba_handle = 999;
      sample.signal_index = sample.info_index = 65535;
      sample.requested_type = sample.requested_index = sample.requested_attribute = INT32_MIN;
      sample.selected_row = sample.installed_row = 2047;
      sample.row_type = sample.row_index = sample.row_attribute = INT32_MIN;
      sample.identity_bound = sample.row_read = sample.group_read = sample.record_read = true;
      sample.group_index = 2047;
      sample.retained_index = 999999;
      sample.record_kind = sample.record_words = UINT32_MAX;
      sample.record_time = INT32_MAX;
      sample.record_bounded = 15;
      sample.group_offset = kMaxMemberBytes - 20;
      sample.table_offset = kMaxMemberBytes - 16;
      sample.record_offset = kMaxMemberBytes - 8;
      sample.source_offset = sample.kind == SignalKind::dispatch;
      sample.time_read = sample.kind == SignalKind::group;
      sample.actor_time = sample.actor_step_field = 0x7f7fffff;
      sample.dispatch_path = 3;
      sample.effect_kind = 2;
      sample.changed_slots = 180;
      if (sample.kind <= SignalKind::info_load) {
        sample.loaded = true;
        sample.source.resolved = true;
        sample.source.archive_slot = kMaxArchiveSlots - 1;
        sample.source.member_index = kMaxArchiveMembers - 1;
        sample.source.archive_size = kMaxArchiveBytes;
        sample.source.member_size = kMaxMemberBytes;
        sample.source.archive_generation = UINT64_MAX - 5;
        sample.source.archive_digest.fill(255);
        sample.source.member_digest.fill(255);
      }
      Require(trace.BeginEvent(sample.event, 0, UINT64_MAX - 1), "signal event capacity");
      ++trace.signal_recorded[kind];
      ++trace.signal_counts.seen[kind];
    }
  }
  Require(trace.signal_count == kSignalEventCapacity && trace.quaternion_count == kQuaternionCapacity,
      "combined probe capacities were not filled");
  trace.Stop(StopReason::shutdown);
  std::array<char, kSerializedCapacity> output{}, second{};
  size_t size = 0, size2 = 0;
  Require(Serialize(trace, output.data(), output.size(), size) && size > 100000 &&
      Serialize(trace, second.data(), second.size(), size2) && size == size2 &&
      std::string_view(output.data(), size) == std::string_view(second.data(), size2),
      "deterministic full serialization");
  const std::string_view json(output.data(), size);
  Require(json.find("\"schema\":\"n3.runtime-animation-trace\"") != json.npos &&
      json.find("\"scope\":\"actor\"") != json.npos &&
      json.find("\"pose_return\":\"0x8229ad64\"") != json.npos &&
      json.find("\"controller_full\":1") != json.npos &&
      json.find("\"pose_outputs\":4800") != json.npos &&
      json.find("\"signal_probe\":") != json.npos &&
      json.find("HELLO") == json.npos && json.find("\\\\") == json.npos,
      "sanitized schema");
  if (emit) std::cout.write(output.data(), static_cast<std::streamsize>(size));
  Trace resource;
  resource.selected = true;
  resource.filter.scope = Scope::resource;
  resource.clock_frequency = 10000000;
  resource.identity.manager = 0x2222;
  resource.identity.instance = 0x3333;
  resource.identity.ba = 0x4444;
  resource.identity.clips = 100;
  resource.identity.bones = 75;
  resource.identity.name_length = 5;
  resource.identity.instance_generation = 1;
  resource.identity.ba_generation = 2;
  resource.counters.resource_bindings = 1;
  resource.counters.queue_calls = 1;
  Require(Add(resource, queue), "resource queue");
  resource.Stop(StopReason::shutdown);
  Require(Serialize(resource, second.data(), second.size(), size2) &&
      std::string_view(second.data(), size2).find("\"scope\":\"resource\",\"actor\":\"unbound\"") !=
          std::string_view::npos, "resource scope schema");
  resource.stop = StopReason::none;
  Require(!Serialize(resource, second.data(), second.size(), size2), "incomplete trace accepted");
  resource.stop = StopReason::shutdown;
  resource.identity.source.resolved = true;
  resource.identity.source.archive_generation = 3;
  resource.identity.source.archive_slot = kMaxArchiveSlots;
  resource.identity.source.archive_size = 4;
  resource.identity.source.member_size = 1;
  Require(!Serialize(resource, second.data(), second.size(), size2), "invalid archive slot accepted");
  resource.identity.source.archive_slot = kMaxArchiveSlots - 1;
  Require(Serialize(resource, second.data(), second.size(), size2), "valid archive slot rejected");
  resource.identity.source = {};
  resource.queue[0].event = {2, 1, 2, 3};
  resource.last_event = 2;
  resource.counters.events_started = 2;
  resource.counters.events_abandoned = 1;
  Require(Serialize(resource, second.data(), second.size(), size2), "accounted missing parent");
  resource.queue[1] = resource.queue[0];
  resource.queue[1].event = {4, 3, 4, 5};
  resource.queue_count = resource.counters.queue_calls = 2;
  resource.last_event = resource.counters.events_started = 4;
  resource.counters.events_abandoned = 2;
  Require(Serialize(resource, second.data(), second.size(), size2), "two accounted missing parents");
  resource.last_event = resource.counters.events_started = 3;
  resource.counters.events_abandoned = 1;
  Require(!Serialize(resource, second.data(), second.size(), size2), "missing parent loss mismatch");
  resource.queue_count = resource.counters.queue_calls = 1;
  resource.last_event = resource.counters.events_started = 2;
  resource.counters.events_abandoned = 0;
  resource.counters.events_inflight_at_flush = 1;
  resource.counters.inflight_at_flush = 1;
  resource.queue[0].event.parent = 2;
  Require(!Serialize(resource, second.data(), second.size(), size2), "self parent accepted");
  resource.queue[0].event.parent = 1;
  resource.counters.events_inflight_at_flush = 0;
  resource.counters.inflight_at_flush = 0;
  Require(!Serialize(resource, second.data(), second.size(), size2), "unaccounted loss accepted");
  resource.counters.events_abandoned = 1;
  resource.counters.queue_full = 2;
  Require(!Serialize(resource, second.data(), second.size(), size2), "unaccounted capacity accepted");
  resource.counters.queue_full = 0;
  resource.identity.clips = 0;
  Require(!Serialize(resource, second.data(), second.size(), size2), "invalid identity accepted");
  resource.identity.clips = 100;
  std::array<char, 8> too_small{};
  size_t failed = 9;
  Require(!Serialize(resource, too_small.data(), too_small.size(), failed) &&
      failed == 0 && too_small[0] == '\0', "short output accepted");
  trace.controller_count = kControllerCapacity + 1;
  Require(!Serialize(trace, output.data(), output.size(), failed) && failed == 0,
      "invalid count accepted");
}

void CheckStops() {
  Trace trace;
  trace.selected = true;
  trace.identity.clips = 16;
  trace.filter.clip = 3;
  Require(!Add(trace, QueueSample{0, 2, Double(0)}) && trace.counters.clip_filtered == 1,
          "clip filter counter");
  Require(Add(trace, ControllerSample{0, 3, 4, Float(0), Float(1), Float(1)}),
          "first transition");
  Require(Add(trace, ControllerSample{0, 3, 3, Float(2), Float(3), Float(1)}) &&
      trace.stop == StopReason::two_transitions && trace.counters.transitions == 2,
      "two-transition stop");
  Require(!trace.AddQueue({0, 3, Double(0)}) && trace.counters.after_stop == 1,
          "post-stop accounting");
  Trace invalid;
  invalid.selected = true;
  invalid.identity.clips = 4;
  Require(!Add(invalid, QueueSample{0, 0, 0x7ff8000000000000ull}) &&
      invalid.counters.invalid == 1 && invalid.stop == StopReason::invalid_value,
      "nonfinite stop");
  Trace bad_output;
  bad_output.selected = true;
  bad_output.identity.clips = 4;
  Require(Add(bad_output, EvaluationSample{0, 0, Float(0), 1, 0, 1}) &&
      bad_output.stop == StopReason::invalid_mapping &&
      bad_output.counters.invalid_outputs == 1, "invalid pose stop");
}

void CheckAttachmentAggregate(bool emit = false) {
  Require(ClassifyAttachmentRequest("C:\\private\\ITEMTABLE.SOX") == AttachmentKind::item_table &&
      ClassifyAttachmentRequest("x/CHARDATA.SOX") == AttachmentKind::character_table &&
      ClassifyAttachmentRequest("herotable.sox") == AttachmentKind::hero_table &&
      ClassifyAttachmentRequest("x/PRIVATE.SKIN") == AttachmentKind::descriptor &&
      ClassifyAttachmentRequest("PRIVATE.Bm") == AttachmentKind::model &&
      ClassifyAttachmentRequest("PRIVATE.BA") == AttachmentKind::animation &&
      ClassifyAttachmentRequest(".ba") == AttachmentKind::other &&
      ClassifyAttachmentRequest("PRIVATE.BA.txt") == AttachmentKind::other,
      "bounded request classification");
  AttachmentTrace trace;
  trace.enabled = true;
  SourceIdentity source;
  source.resolved = true;
  source.archive_generation = 2;
  source.archive_size = 100;
  source.member_size = 4;
  source.member_index = 1;
  source.archive_digest.fill(0x12);
  source.member_digest.fill(0x34);
  Require(AddAttachmentObservation(trace, AttachmentKind::item_table, 0x82101234, 1, source) &&
      AddAttachmentObservation(trace, AttachmentKind::item_table, 0x82101234, 2, source) &&
      trace.observation_count == 1 && trace.observations[0].count == 2,
      "resolver aggregation");
  const auto item = size_t(AttachmentKind::item_table);
  trace.seen[item] = 3;
  trace.outcomes[item][size_t(AttachmentOutcome::verified)] = 2;
  trace.outcomes[item][size_t(AttachmentOutcome::full)] = 1;
  trace.sequence_count = 3;
  trace.resolver_calls = trace.resolver_returns = trace.resolver_verified = 2;
  trace.hash_bytes = 216;
  std::array<char, 16384> output{}, repeat{};
  size_t size = 0, repeated = 0;
  Require(SerializeAttachment(trace, StopReason::shutdown, output.data(), output.size(), size) &&
      SerializeAttachment(trace, StopReason::shutdown, repeat.data(), repeat.size(), repeated) &&
      size == repeated && std::string_view(output.data(), size) == std::string_view(repeat.data(), repeated),
      "deterministic attachment serialization");
  const std::string_view json(output.data(), size);
  Require(json.find("PRIVATE") == std::string_view::npos &&
      json.find("C:\\\\private") == std::string_view::npos &&
      json.find("\"residual\":null") != std::string_view::npos &&
      json.find("\"binding_is_proven\":false") != std::string_view::npos,
      "attachment aggregate privacy or proof gate");
  if (emit) std::cout.write(output.data(), size);
  trace.outcomes[item][size_t(AttachmentOutcome::verified)] = 3;
  Require(!SerializeAttachment(trace, StopReason::shutdown, output.data(), output.size(), size),
      "inconsistent attachment counts accepted");
  trace.outcomes[item][size_t(AttachmentOutcome::verified)] = 2;
  trace.hash_bytes = kAttachmentHashBudgetBytes + 1;
  Require(!SerializeAttachment(trace, StopReason::shutdown, output.data(), output.size(), size),
      "attachment hash budget ignored");
  trace.hash_bytes = 216;
  Require(!SerializeAttachment(trace, StopReason::shutdown, output.data(), 16, size) && !size,
      "attachment output bound ignored");
}

void CheckAttachmentCapacity() {
  AttachmentTrace trace;
  trace.enabled = true;
  SourceIdentity source;
  source.resolved = true;
  source.archive_generation = UINT64_MAX;
  source.archive_size = 1024 * 1024;
  source.member_size = 4;
  source.archive_digest.fill(0x56);
  source.member_digest.fill(0x78);
  uint64_t sequence = 0;
  for (size_t kind = 0; kind < kAttachmentKindCount; ++kind) {
    for (size_t index = 0; index < kAttachmentPerKindCapacity; ++index) {
      source.member_index = static_cast<uint32_t>(index);
      Require(AddAttachmentObservation(trace, static_cast<AttachmentKind>(kind),
                                      0x82101234, ++sequence, source),
              "attachment capacity rejected valid observation");
    }
    trace.seen[kind] = kAttachmentPerKindCapacity;
    trace.outcomes[kind][size_t(AttachmentOutcome::verified)] = kAttachmentPerKindCapacity;
  }
  trace.sequence_count = sequence;
  trace.resolver_calls = trace.resolver_returns = trace.resolver_verified = sequence;
  trace.hash_bytes = sequence * (source.archive_size + 2 * source.member_size);
  std::vector<char> output(512 * 1024);
  size_t size = 0;
  Require(trace.observation_count == kAttachmentObservationCapacity &&
      SerializeAttachment(trace, StopReason::shutdown, output.data(), output.size(), size) &&
      size < output.size(), "full attachment aggregate exceeded capture buffer");
  Require(!SerializeAttachment(trace, StopReason::shutdown, output.data(), size - 1, size),
      "truncated full attachment aggregate accepted");
}
}

int main(int argc, char** argv) {
  try {
    if (argc == 2 && std::string_view(argv[1]) == "--emit-full-probe-v3") {
      CheckBoundsAndSerialization(true);
      return 0;
    }
    if (argc == 2 && std::string_view(argv[1]) == "--emit-attachment-probe-v1") {
      CheckAttachmentAggregate(true);
      return 0;
    }
    CheckFilters();
    CheckHashAndOverflow();
    CheckTimeoutDiagnostic();
    CheckBoundsAndSerialization();
    CheckStops();
    CheckAttachmentAggregate();
    CheckAttachmentCapacity();
    std::cout << "animation trace model: filters, bounds, stops and serialization passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
