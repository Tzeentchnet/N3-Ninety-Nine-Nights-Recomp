#include "animation_trace_model.h"

#include <array>
#include <bit>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace n3::animation_trace;
void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
uint32_t Float(float value) { return std::bit_cast<uint32_t>(value); }
uint64_t Double(double value) { return std::bit_cast<uint64_t>(value); }

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

void CheckBoundsAndSerialization() {
  Trace trace;
  trace.selected = true;
  trace.identity.clips = 100;
  trace.identity.bones = 75;
  trace.identity.actor = 0x1234;
  trace.identity.name_fingerprint = 0xa430d84680aabd0bull;
  const ControllerSample controller{0x82094b64, 4, 4, Float(2), Float(3), Float(1)};
  const QueueSample queue{0x820802d0, 4, Double(2)};
  const EvaluationSample evaluation{0x8229ea94, 4, Float(2), 1, 75, 0};
  for (size_t i = 0; i < kControllerCapacity; ++i)
    Require(trace.AddController(controller), "controller prematurely full");
  for (size_t i = 0; i < kQueueCapacity; ++i)
    Require(trace.AddQueue(queue), "queue prematurely full");
  for (size_t i = 0; i < kEvaluationCapacity; ++i)
    Require(trace.AddEvaluation(evaluation), "evaluation prematurely full");
  Require(!trace.AddController(controller) && !trace.AddQueue(queue) &&
      !trace.AddEvaluation(evaluation), "capacity did not stop additions");
  Require(trace.counters.controller_full == 1 && trace.counters.queue_full == 1 &&
      trace.counters.evaluation_full == 1 && trace.counters.pose_outputs == 4800,
      "bounded counters");
  std::array<char, kSerializedCapacity> output{}, second{};
  size_t size = 0, size2 = 0;
  Require(Serialize(trace, output.data(), output.size(), size) && size > 1000 &&
      Serialize(trace, second.data(), second.size(), size2) && size == size2 &&
      std::string_view(output.data(), size) == std::string_view(second.data(), size2),
      "deterministic full serialization");
  const std::string_view json(output.data(), size);
  Require(json.find("\"schema\":\"n3.runtime-animation-trace\"") != json.npos &&
      json.find("\"scope\":\"actor\"") != json.npos &&
      json.find("\"pose_return\":\"0x8229ad64\"") != json.npos &&
      json.find("\"controller_full\":1") != json.npos &&
      json.find("\"pose_outputs\":4800") != json.npos &&
      json.find("HELLO") == json.npos && json.find("\\\\") == json.npos,
      "sanitized schema");
  trace.filter.scope = Scope::resource;
  Require(Serialize(trace, second.data(), second.size(), size2) &&
      std::string_view(second.data(), size2).find("\"scope\":\"resource\",\"actor\":\"unbound\"") !=
          std::string_view::npos, "resource scope schema");
  std::array<char, 8> too_small{};
  size_t failed = 9;
  Require(!Serialize(trace, too_small.data(), too_small.size(), failed) &&
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
  Require(!trace.AddQueue({0, 2, Double(0)}) && trace.counters.clip_filtered == 1,
          "clip filter counter");
  Require(trace.AddController({0, 3, 4, Float(0), Float(1), Float(1)}),
          "first transition");
  Require(trace.AddController({0, 3, 3, Float(2), Float(3), Float(1)}) &&
      trace.stop == StopReason::two_transitions && trace.counters.transitions == 2,
      "two-transition stop");
  Require(!trace.AddQueue({0, 3, Double(0)}) && trace.counters.after_stop == 1,
          "post-stop accounting");
  Trace invalid;
  invalid.selected = true;
  invalid.identity.clips = 4;
  Require(!invalid.AddQueue({0, 0, 0x7ff8000000000000ull}) &&
      invalid.counters.invalid == 1 && invalid.stop == StopReason::invalid_value,
      "nonfinite stop");
  Trace bad_output;
  bad_output.selected = true;
  bad_output.identity.clips = 4;
  Require(bad_output.AddEvaluation({0, 0, Float(0), 1, 0, 1}) &&
      bad_output.stop == StopReason::invalid_mapping &&
      bad_output.counters.invalid_outputs == 1, "invalid pose stop");
}
}

int main() {
  try {
    CheckFilters();
    CheckBoundsAndSerialization();
    CheckStops();
    std::cout << "animation trace model: filters, bounds, stops and serialization passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
