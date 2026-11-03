#include "animation_trace_model.h"

#include <bit>
#include <charconv>
#include <cstring>
#include <limits>

namespace n3::animation_trace {
namespace {
void Increment(uint64_t& value) {
  if (value != std::numeric_limits<uint64_t>::max()) ++value;
}

bool ParseUnsigned(std::string_view text, int base, uint32_t& result) {
  if (text.empty()) return false;
  uint32_t value = 0;
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value, base);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size()) return false;
  result = value;
  return true;
}

const char* StopName(StopReason stop) {
  switch (stop) {
    case StopReason::none: return "none";
    case StopReason::invalid_mapping: return "invalid_mapping";
    case StopReason::identity_changed: return "identity_changed";
    case StopReason::invalid_value: return "invalid_value";
    case StopReason::concurrent_actor: return "concurrent_actor";
    case StopReason::concurrent_shared_ba: return "concurrent_shared_ba";
    case StopReason::reentrant: return "reentrant";
    case StopReason::two_transitions: return "two_transitions";
    case StopReason::shutdown: return "shutdown";
  }
  return "unknown";
}

class Writer {
 public:
  Writer(char* data, size_t capacity) : data_(data), capacity_(capacity) {}
  void Text(std::string_view text) {
    if (!ok_ || text.size() > capacity_ - size_) { ok_ = false; return; }
    std::memcpy(data_ + size_, text.data(), text.size());
    size_ += text.size();
  }
  template<typename T> void Number(T value) {
    if (!ok_) return;
    const auto converted = std::to_chars(data_ + size_, data_ + capacity_, value);
    if (converted.ec != std::errc{}) { ok_ = false; return; }
    size_ = size_t(converted.ptr - data_);
  }
  void Address(uint32_t value) { Hex(value, 8); }
  void Fingerprint(uint64_t value) { Hex(value, 16); }
  bool ok() const { return ok_; }
  size_t size() const { return size_; }
 private:
  void Hex(uint64_t value, unsigned digits) {
    constexpr char hex[] = "0123456789abcdef";
    char buffer[20] = {'"', '0', 'x'};
    for (unsigned i = 0; i < digits; ++i)
      buffer[3 + i] = hex[(value >> (4 * (digits - i - 1))) & 15];
    buffer[3 + digits] = '"';
    Text({buffer, size_t(digits + 4)});
  }
  char* data_;
  size_t capacity_;
  size_t size_ = 0;
  bool ok_ = true;
};
}  // namespace

bool ParseActor(std::string_view text, uint32_t& actor) {
  if (text == "first") { actor = 0; return true; }
  if (text.size() <= 2 || text.substr(0, 2) != "0x") return false;
  uint32_t value = 0;
  if (!ParseUnsigned(text.substr(2), 16, value) || !value) return false;
  actor = value;
  return true;
}

bool ParseClip(std::string_view text, int32_t& clip) {
  if (text == "all") { clip = -1; return true; }
  uint32_t value = 0;
  if (!ParseUnsigned(text, 10, value) || value >= kMaxClips) return false;
  clip = static_cast<int32_t>(value);
  return true;
}

bool ParseScope(std::string_view text, Scope& scope) {
  if (text == "actor") { scope = Scope::actor; return true; }
  if (text == "resource") { scope = Scope::resource; return true; }
  return false;
}

bool MatchesActor(Filter filter, uint32_t actor) {
  return actor != 0 && (!filter.actor || filter.actor == actor);
}
bool MatchesClip(Filter filter, uint32_t clip) {
  return filter.clip < 0 || uint32_t(filter.clip) == clip;
}
bool FiniteFloatBits(uint32_t bits) { return (bits & 0x7f800000u) != 0x7f800000u; }
bool FiniteDoubleBits(uint64_t bits) {
  return (bits & 0x7ff0000000000000ull) != 0x7ff0000000000000ull;
}

uint64_t BasenameFingerprint(const char* name, size_t length) {
  size_t start = 0;
  for (size_t i = 0; i < length; ++i)
    if (name[i] == '\\' || name[i] == '/') start = i + 1;
  uint64_t hash = 14695981039346656037ull;
  for (size_t i = start; i < length; ++i) {
    auto character = static_cast<unsigned char>(name[i]);
    if (character >= 'A' && character <= 'Z') character += 'a' - 'A';
    hash = (hash ^ character) * 1099511628211ull;
  }
  return hash;
}

void Trace::Stop(StopReason reason) {
  if (stop == StopReason::none) stop = reason;
}

bool Trace::AddController(const ControllerSample& sample) {
  if (stop != StopReason::none) { Increment(counters.after_stop); return false; }
  if (!selected || sample.before_clip >= identity.clips || sample.after_clip >= identity.clips ||
      !FiniteFloatBits(sample.before_time) || !FiniteFloatBits(sample.after_time) ||
      !FiniteFloatBits(sample.step)) {
    Increment(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.before_clip)) {
    Increment(counters.clip_filtered); return false;
  }
  if (controller_count == controller.size()) {
    Increment(counters.controller_full); return false;
  }
  if (have_last_clip && last_clip != sample.before_clip) Increment(counters.transitions);
  if (sample.before_clip != sample.after_clip) Increment(counters.transitions);
  last_clip = sample.after_clip;
  have_last_clip = true;
  controller[controller_count++] = sample;
  if (counters.transitions >= 2) Stop(StopReason::two_transitions);
  return true;
}

bool Trace::AddQueue(const QueueSample& sample) {
  if (stop != StopReason::none) { Increment(counters.after_stop); return false; }
  if (!selected || sample.clip >= identity.clips || !FiniteDoubleBits(sample.frame)) {
    Increment(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.clip)) { Increment(counters.clip_filtered); return false; }
  if (queue_count == queue.size()) { Increment(counters.queue_full); return false; }
  queue[queue_count++] = sample;
  return true;
}

bool Trace::AddEvaluation(const EvaluationSample& sample) {
  if (stop != StopReason::none) { Increment(counters.after_stop); return false; }
  if (!selected || sample.clip >= identity.clips || sample.queue_count > 5 ||
      !FiniteFloatBits(sample.time)) {
    Increment(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.clip)) { Increment(counters.clip_filtered); return false; }
  if (evaluation_count == evaluation.size()) {
    Increment(counters.evaluation_full); return false;
  }
  evaluation[evaluation_count++] = sample;
  counters.pose_outputs += sample.pose_outputs;
  counters.invalid_outputs += sample.invalid_outputs;
  if (sample.invalid_outputs) { Increment(counters.invalid); Stop(StopReason::invalid_mapping); }
  return true;
}

bool Serialize(const Trace& t, char* output, size_t capacity, size_t& size) {
  size = 0;
  if (!output || !capacity || t.controller_count > t.controller.size() ||
      t.queue_count > t.queue.size() || t.evaluation_count > t.evaluation.size()) return false;
  for (size_t i = 0; i < t.controller_count; ++i)
    if (!FiniteFloatBits(t.controller[i].before_time) ||
        !FiniteFloatBits(t.controller[i].after_time) || !FiniteFloatBits(t.controller[i].step))
      return false;
  for (size_t i = 0; i < t.queue_count; ++i)
    if (!FiniteDoubleBits(t.queue[i].frame)) return false;
  for (size_t i = 0; i < t.evaluation_count; ++i)
    if (!FiniteFloatBits(t.evaluation[i].time)) return false;
  Writer w(output, capacity);
  w.Text("{\"schema\":\"n3.runtime-animation-trace\",\"version\":2,");
  w.Text("\"sources\":{\"setup\":\"0x82093be8\",\"controller\":\"0x82080158\",");
  w.Text("\"queue\":\"0x82252bd8\",\"evaluation\":\"0x82298ff0\",");
  w.Text("\"pose_output\":\"0x82249628\",\"pose_return\":\"0x8229ad64\"},");
  w.Text("\"filter\":{\"scope\":");
  w.Text(t.filter.scope == Scope::resource ? "\"resource\"" : "\"actor\"");
  w.Text(",\"actor\":");
  if (t.filter.scope == Scope::resource) w.Text("\"unbound\"");
  else if (t.filter.actor) w.Address(t.filter.actor); else w.Text("\"first\"");
  w.Text(",\"clip\":");
  if (t.filter.clip < 0) w.Text("\"all\""); else w.Number(t.filter.clip);
  w.Text("},\"selected\":"); w.Text(t.selected ? "true" : "false");
  w.Text(",\"stop_reason\":\""); w.Text(StopName(t.stop)); w.Text("\",\"identity\":{");
#define ADDRESS_FIELD(label, member) w.Text("\"" label "\":"); w.Address(t.identity.member); w.Text(",")
#define NUMBER_FIELD(label, member) w.Text("\"" label "\":"); w.Number(t.identity.member); w.Text(",")
  ADDRESS_FIELD("actor", actor); ADDRESS_FIELD("actor_vtable", actor_vtable);
  ADDRESS_FIELD("manager", manager); NUMBER_FIELD("instance_handle", instance_handle);
  ADDRESS_FIELD("instance", instance); ADDRESS_FIELD("ba", ba);
  NUMBER_FIELD("ba_handle", ba_handle); ADDRESS_FIELD("signal", signal);
  ADDRESS_FIELD("info", info); NUMBER_FIELD("setup_signal_index", setup_signal_index);
  NUMBER_FIELD("setup_info_index", setup_info_index); NUMBER_FIELD("clips", clips);
  NUMBER_FIELD("bones", bones); NUMBER_FIELD("signal_groups", signal_groups);
  NUMBER_FIELD("info_rows", info_rows); NUMBER_FIELD("name_length", name_length);
  w.Text("\"name_fnv1a64\":"); w.Fingerprint(t.identity.name_fingerprint); w.Text("},");
#undef ADDRESS_FIELD
#undef NUMBER_FIELD
  w.Text("\"counts\":{");
#define COUNT_FIELD(member) w.Text("\"" #member "\":"); w.Number(t.counters.member); w.Text(",")
  COUNT_FIELD(setup_calls); COUNT_FIELD(setup_accepted); COUNT_FIELD(resource_bindings);
  COUNT_FIELD(controller_calls);
  COUNT_FIELD(queue_calls); COUNT_FIELD(evaluation_calls); COUNT_FIELD(actor_filtered);
  COUNT_FIELD(clip_filtered); COUNT_FIELD(unselected); COUNT_FIELD(invalid);
  COUNT_FIELD(reentrant); COUNT_FIELD(concurrent); COUNT_FIELD(after_stop);
  COUNT_FIELD(lock_dropped); COUNT_FIELD(inflight_at_flush);
  COUNT_FIELD(controller_full); COUNT_FIELD(queue_full); COUNT_FIELD(evaluation_full);
  COUNT_FIELD(pose_outputs); COUNT_FIELD(invalid_outputs);
  w.Text("\"transitions\":"); w.Number(t.counters.transitions); w.Text("},");
#undef COUNT_FIELD
  w.Text("\"controller\":[");
  for (size_t i = 0; i < t.controller_count; ++i) {
    const auto& s = t.controller[i];
    if (i) w.Text(",");
    w.Text("{\"caller\":"); w.Address(s.caller);
    w.Text(",\"before_clip\":"); w.Number(s.before_clip);
    w.Text(",\"after_clip\":"); w.Number(s.after_clip);
    w.Text(",\"before_time\":"); w.Number(std::bit_cast<float>(s.before_time));
    w.Text(",\"after_time\":"); w.Number(std::bit_cast<float>(s.after_time));
    w.Text(",\"step\":"); w.Number(std::bit_cast<float>(s.step)); w.Text("}");
  }
  w.Text("],\"queue\":[");
  for (size_t i = 0; i < t.queue_count; ++i) {
    const auto& s = t.queue[i];
    if (i) w.Text(",");
    w.Text("{\"caller\":"); w.Address(s.caller);
    w.Text(",\"clip\":"); w.Number(s.clip);
    w.Text(",\"frame\":"); w.Number(std::bit_cast<double>(s.frame)); w.Text("}");
  }
  w.Text("],\"evaluation\":[");
  for (size_t i = 0; i < t.evaluation_count; ++i) {
    const auto& s = t.evaluation[i];
    if (i) w.Text(",");
    w.Text("{\"caller\":"); w.Address(s.caller);
    w.Text(",\"clip\":"); w.Number(s.clip);
    w.Text(",\"time\":"); w.Number(std::bit_cast<float>(s.time));
    w.Text(",\"queue_count\":"); w.Number(s.queue_count);
    w.Text(",\"pose_outputs\":"); w.Number(s.pose_outputs);
    w.Text(",\"invalid_outputs\":"); w.Number(s.invalid_outputs); w.Text("}");
  }
  w.Text("]}\n");
  if (!w.ok()) { output[0] = '\0'; return false; }
  size = w.size();
  return true;
}
}  // namespace n3::animation_trace
