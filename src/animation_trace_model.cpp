#include "animation_trace_model.h"

#include <algorithm>
#include <bit>
#include <charconv>
#include <cstring>
#include <limits>

namespace n3::animation_trace {
namespace {
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
    case StopReason::untracked_lifetime: return "untracked_lifetime";
    case StopReason::registry_full: return "registry_full";
    case StopReason::counter_overflow: return "counter_overflow";
    case StopReason::clock_failure: return "clock_failure";
    case StopReason::concurrent_probe: return "concurrent_probe";
  }
  return "unknown";
}

constexpr std::array<std::string_view, kSignalKindCount> kSignalNames{
    "ba_load", "as_load", "info_load", "setup", "request", "selection",
    "install", "group", "dispatch", "effect"};

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
  void Digest(const std::array<uint8_t, 32>& value) {
    constexpr char hex[] = "0123456789abcdef";
    char buffer[66] = {'"'};
    for (size_t i = 0; i < value.size(); ++i) {
      buffer[1 + 2 * i] = hex[value[i] >> 4];
      buffer[2 + 2 * i] = hex[value[i] & 15];
    }
    buffer[65] = '"';
    Text({buffer, sizeof(buffer)});
  }
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

bool SerializeDrainTimeout(uint32_t inflight, char* output, size_t capacity, size_t& size) {
  size = 0;
  if (!inflight || inflight > 0x7fffffffu || !output || !capacity) return false;
  Writer w(output, capacity);
  w.Text("{\"schema\":\"n3.runtime-animation-drain-timeout\",\"version\":1,");
  w.Text("\"outcome\":\"incomplete\",\"reason\":\"drain_timeout\",");
  w.Text("\"aggregate\":\"omitted\",\"inflight_at_timeout\":");
  w.Number(inflight);
  w.Text("}\n");
  if (!w.ok()) return false;
  size = w.size();
  return true;
}

AttachmentKind ClassifyAttachmentRequest(std::string_view request) {
  const auto separator = request.find_last_of("\\/");
  if (separator != std::string_view::npos) request.remove_prefix(separator + 1);
  const auto equal = [](std::string_view left, std::string_view right) {
    if (left.size() != right.size()) return false;
    for (size_t i = 0; i < left.size(); ++i) {
      auto c = static_cast<unsigned char>(left[i]);
      if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
      if (c != static_cast<unsigned char>(right[i])) return false;
    }
    return true;
  };
  if (equal(request, "chardata.sox")) return AttachmentKind::character_table;
  if (equal(request, "itemtable.sox")) return AttachmentKind::item_table;
  if (equal(request, "herotable.sox")) return AttachmentKind::hero_table;
  const auto dot = request.find_last_of('.');
  if (dot == std::string_view::npos || dot == 0) return AttachmentKind::other;
  const auto suffix = request.substr(dot);
  if (equal(suffix, ".skin")) return AttachmentKind::descriptor;
  if (equal(suffix, ".bm")) return AttachmentKind::model;
  if (equal(suffix, ".ba")) return AttachmentKind::animation;
  return AttachmentKind::other;
}

bool AddAttachmentObservation(AttachmentTrace& trace, AttachmentKind kind, uint32_t read_caller,
                              uint64_t sequence, const SourceIdentity& source) {
  if (size_t(kind) >= kAttachmentKindCount || !read_caller || !sequence ||
      trace.observation_count > trace.observations.size() ||
      !source.resolved || !source.archive_generation || source.archive_slot >= kMaxArchiveSlots ||
      source.member_index >= kMaxArchiveMembers || source.archive_size < 4 ||
      source.archive_size > kMaxArchiveBytes || !source.member_size ||
      source.member_size > kMaxMemberBytes || source.member_size > source.archive_size)
    return false;
  for (size_t i = 0; i < trace.observation_count; ++i) {
    auto& observation = trace.observations[i];
    if (observation.kind != kind || observation.read_caller != read_caller ||
        !(observation.source == source)) continue;
    if (observation.count == UINT64_MAX) return false;
    observation.first_sequence = (std::min)(observation.first_sequence, sequence);
    observation.last_sequence = (std::max)(observation.last_sequence, sequence);
    ++observation.count;
    return true;
  }
  if (trace.observation_count >= trace.observations.size()) return false;
  trace.observations[trace.observation_count++] = {
      kind, read_caller, source, sequence, sequence, 1};
  return true;
}

bool SerializeAttachment(const AttachmentTrace& trace, StopReason stop, char* output,
                         size_t capacity, size_t& size) {
  size = 0;
  if (!trace.enabled || !output || !capacity ||
      trace.observation_count > trace.observations.size() ||
      trace.hash_bytes > kAttachmentHashBudgetBytes ||
      trace.resolver_verified > trace.resolver_returns ||
      trace.resolver_returns > trace.resolver_calls)
    return false;
  constexpr std::array<std::string_view, kAttachmentKindCount> kinds{
      "character_table", "item_table", "hero_table", "descriptor", "model", "animation"};
  constexpr std::array<std::string_view, kAttachmentOutcomeCount> outcomes{
      "verified", "no_resolver", "read_failed", "unreadable", "mismatch",
      "changed", "unresolved", "skipped", "full"};
  std::array<uint64_t, kAttachmentKindCount> recorded{};
  std::array<uint64_t, kAttachmentKindCount> unfinished{};
  for (size_t i = 0; i < trace.observation_count; ++i) {
    const auto& item = trace.observations[i];
    const auto kind = size_t(item.kind);
    const auto& source = item.source;
    if (kind >= kinds.size() || !item.read_caller || !item.count || !item.first_sequence ||
        item.last_sequence < item.first_sequence || item.last_sequence > trace.sequence_count ||
        !source.resolved || !source.archive_generation || source.archive_slot >= kMaxArchiveSlots ||
        source.member_index >= kMaxArchiveMembers || source.archive_size < 4 ||
        source.archive_size > kMaxArchiveBytes || !source.member_size ||
        source.member_size > kMaxMemberBytes || source.member_size > source.archive_size ||
        UINT64_MAX - recorded[kind] < item.count)
      return false;
    recorded[kind] += item.count;
  }
  for (size_t kind = 0; kind < kinds.size(); ++kind) {
    uint64_t terminal = 0;
    for (const auto count : trace.outcomes[kind]) {
      if (UINT64_MAX - terminal < count) return false;
      terminal += count;
    }
    if (terminal > trace.seen[kind] ||
        recorded[kind] != trace.outcomes[kind][size_t(AttachmentOutcome::verified)])
      return false;
    unfinished[kind] = trace.seen[kind] - terminal;
  }
  Writer w(output, capacity);
  w.Text("{\"schema\":\"n3.runtime-attachment-probe\",\"version\":1,");
  w.Text("\"scope\":\"bounded-file-read-and-mounted-archive-resolver\",");
  w.Text("\"read_hook\":\"0x82273000\",\"resolver_hook\":\"0x82272c40\",");
  w.Text("\"stop_reason\":\""); w.Text(StopName(stop)); w.Text("\",");
  w.Text("\"classification\":\"request-basename-or-extension-only\",");
  w.Text("\"limits\":{\"per_kind\":"); w.Number(kAttachmentPerKindCapacity);
  w.Text(",\"observations\":"); w.Number(kAttachmentObservationCapacity);
  w.Text(",\"hash_bytes\":"); w.Number(kAttachmentHashBudgetBytes); w.Text("},");
  w.Text("\"sequence_count\":"); w.Number(trace.sequence_count);
  w.Text(",\"resolver\":{\"calls\":"); w.Number(trace.resolver_calls);
  w.Text(",\"returned_handles\":"); w.Number(trace.resolver_returns);
  w.Text(",\"verified_sources\":"); w.Number(trace.resolver_verified);
  w.Text(",\"hash_bytes\":"); w.Number(trace.hash_bytes); w.Text("},");
  w.Text("\"losses\":{\"request_unreadable\":"); w.Number(trace.request_unreadable);
  w.Text(",\"reentrant\":"); w.Number(trace.reentrant);
  w.Text(",\"concurrent\":"); w.Number(trace.concurrent);
  w.Text(",\"hash_budget_full\":"); w.Number(trace.hash_budget_full);
  w.Text(",\"read_inflight_at_flush\":"); w.Number(trace.read_inflight_at_flush);
  w.Text("},\"reads\":{");
  for (size_t kind = 0; kind < kinds.size(); ++kind) {
    if (kind) w.Text(",");
    w.Text("\""); w.Text(kinds[kind]); w.Text("\":{\"seen\":"); w.Number(trace.seen[kind]);
    for (size_t outcome = 0; outcome < outcomes.size(); ++outcome) {
      w.Text(",\""); w.Text(outcomes[outcome]); w.Text("\":");
      w.Number(trace.outcomes[kind][outcome]);
    }
    w.Text(",\"unfinished\":"); w.Number(unfinished[kind]); w.Text("}");
  }
  w.Text("},\"observations\":[");
  for (size_t i = 0; i < trace.observation_count; ++i) {
    if (i) w.Text(",");
    const auto& item = trace.observations[i];
    const auto& source = item.source;
    w.Text("{\"kind\":\""); w.Text(kinds[size_t(item.kind)]); w.Text("\",\"read_caller\":");
    w.Address(item.read_caller);
    w.Text(",\"archive_generation\":"); w.Number(source.archive_generation);
    w.Text(",\"archive_slot\":"); w.Number(source.archive_slot);
    w.Text(",\"archive_size\":"); w.Number(source.archive_size);
    w.Text(",\"archive_sha256\":"); w.Digest(source.archive_digest);
    w.Text(",\"member_index\":"); w.Number(source.member_index);
    w.Text(",\"member_size\":"); w.Number(source.member_size);
    w.Text(",\"member_sha256\":"); w.Digest(source.member_digest);
    w.Text(",\"first_sequence\":"); w.Number(item.first_sequence);
    w.Text(",\"last_sequence\":"); w.Number(item.last_sequence);
    w.Text(",\"count\":"); w.Number(item.count); w.Text("}");
  }
  w.Text("],\"actor_item_socket_lifecycle\":{\"instrumented\":false,\"verified_cases\":0},");
  w.Text("\"synchronized_transforms\":{\"instrumented\":false,\"samples\":0,");
  w.Text("\"residual\":null},\"binding_is_proven\":false}");
  if (!w.ok()) return false;
  size = w.size();
  return true;
}

void Sha256::Transform(const uint8_t* block) {
  constexpr std::array<uint32_t, 64> constants{
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
      0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
      0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
      0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
      0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
      0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
      0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
      0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
      0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
  std::array<uint32_t, 64> words{};
  for (size_t i = 0; i < 16; ++i)
    words[i] = (uint32_t(block[i * 4]) << 24) | (uint32_t(block[i * 4 + 1]) << 16) |
               (uint32_t(block[i * 4 + 2]) << 8) | block[i * 4 + 3];
  for (size_t i = 16; i < words.size(); ++i) {
    const auto a = std::rotr(words[i - 15], 7) ^ std::rotr(words[i - 15], 18) ^
                   (words[i - 15] >> 3);
    const auto b = std::rotr(words[i - 2], 17) ^ std::rotr(words[i - 2], 19) ^
                   (words[i - 2] >> 10);
    words[i] = words[i - 16] + a + words[i - 7] + b;
  }
  auto [a, b, c, d, e, f, g, h] = state_;
  for (size_t i = 0; i < words.size(); ++i) {
    const auto upper = std::rotr(e, 6) ^ std::rotr(e, 11) ^ std::rotr(e, 25);
    const auto choose = (e & f) ^ (~e & g);
    const auto first = h + upper + choose + constants[i] + words[i];
    const auto lower = std::rotr(a, 2) ^ std::rotr(a, 13) ^ std::rotr(a, 22);
    const auto majority = (a & b) ^ (a & c) ^ (b & c);
    const auto second = lower + majority;
    h = g; g = f; f = e; e = d + first;
    d = c; c = b; b = a; a = first + second;
  }
  state_[0] += a; state_[1] += b; state_[2] += c; state_[3] += d;
  state_[4] += e; state_[5] += f; state_[6] += g; state_[7] += h;
}

void Sha256::Update(const uint8_t* data, size_t size) {
  bytes_ += size;
  while (size) {
    const auto count = (std::min)(size, buffer_.size() - used_);
    std::memcpy(buffer_.data() + used_, data, count);
    used_ += count;
    data += count;
    size -= count;
    if (used_ == buffer_.size()) { Transform(buffer_.data()); used_ = 0; }
  }
}

std::array<uint8_t, 32> Sha256::Finish() {
  const auto bits = bytes_ * 8;
  buffer_[used_++] = 0x80;
  if (used_ > 56) {
    while (used_ < 64) buffer_[used_++] = 0;
    Transform(buffer_.data());
    used_ = 0;
  }
  while (used_ < 56) buffer_[used_++] = 0;
  for (unsigned i = 0; i < 8; ++i) buffer_[56 + i] = uint8_t(bits >> (56 - i * 8));
  Transform(buffer_.data());
  std::array<uint8_t, 32> digest{};
  for (size_t i = 0; i < state_.size(); ++i)
    for (unsigned j = 0; j < 4; ++j) digest[i * 4 + j] = uint8_t(state_[i] >> (24 - j * 8));
  return digest;
}

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

bool Trace::Count(uint64_t& counter, uint64_t amount) {
  if (amount > std::numeric_limits<uint64_t>::max() - counter) {
    counter = std::numeric_limits<uint64_t>::max();
    counters.counter_saturated = 1;
    Stop(StopReason::counter_overflow);
    return false;
  }
  counter += amount;
  return true;
}

uint64_t Trace::NextGeneration() {
  if (stop != StopReason::none || !Count(last_generation)) return 0;
  return last_generation;
}

bool Trace::BeginEvent(Event& event, uint64_t parent, uint64_t tick) {
  if (stop != StopReason::none) { Count(counters.after_stop); return false; }
  if (parent > last_event) { Count(counters.invalid); Stop(StopReason::invalid_value); return false; }
  if (!Count(last_event) || !Count(counters.events_started)) return false;
  event = {last_event, parent, tick, tick};
  return true;
}

void Trace::AbandonEvent() { Count(counters.events_abandoned); }

namespace {
bool ValidEvent(const Event& event, uint64_t last_event) {
  return event.id && event.id <= last_event && event.parent < event.id &&
         event.begin <= event.end;
}
}

bool Trace::AddController(const ControllerSample& sample) {
  if (stop != StopReason::none) { Count(counters.after_stop); return false; }
  if (!selected || sample.before_clip >= identity.clips || sample.after_clip >= identity.clips ||
      !FiniteFloatBits(sample.before_time) || !FiniteFloatBits(sample.after_time) ||
      !FiniteFloatBits(sample.step) || !ValidEvent(sample.event, last_event)) {
    Count(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.before_clip)) {
    Count(counters.clip_filtered); return false;
  }
  if (controller_count == controller.size()) {
    Count(counters.controller_full); return false;
  }
  if (have_last_clip && last_clip != sample.before_clip) Count(counters.transitions);
  if (sample.before_clip != sample.after_clip) Count(counters.transitions);
  last_clip = sample.after_clip;
  have_last_clip = true;
  controller[controller_count++] = sample;
  if (counters.transitions >= 2) Stop(StopReason::two_transitions);
  return true;
}

bool Trace::AddQueue(const QueueSample& sample) {
  if (stop != StopReason::none) { Count(counters.after_stop); return false; }
  if (!selected || sample.clip >= identity.clips || !FiniteDoubleBits(sample.frame) ||
      !ValidEvent(sample.event, last_event)) {
    Count(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.clip)) { Count(counters.clip_filtered); return false; }
  if (queue_count == queue.size()) { Count(counters.queue_full); return false; }
  queue[queue_count++] = sample;
  return true;
}

bool Trace::AddEvaluation(const EvaluationSample& sample) {
  if (stop != StopReason::none) { Count(counters.after_stop); return false; }
  if (!selected || sample.clip >= identity.clips || sample.queue_count > 5 ||
      !FiniteFloatBits(sample.time) || !ValidEvent(sample.event, last_event)) {
    Count(counters.invalid); Stop(StopReason::invalid_value); return false;
  }
  if (!MatchesClip(filter, sample.clip)) { Count(counters.clip_filtered); return false; }
  if (evaluation_count == evaluation.size()) {
    Count(counters.evaluation_full); return false;
  }
  evaluation[evaluation_count++] = sample;
  Count(counters.pose_outputs, sample.pose_outputs);
  Count(counters.invalid_outputs, sample.invalid_outputs);
  if (sample.invalid_outputs) { Count(counters.invalid); Stop(StopReason::invalid_mapping); }
  return true;
}

bool Serialize(const Trace& t, char* output, size_t capacity, size_t& size) {
  size = 0;
  if (!output || !capacity || !t.clock_frequency || t.stop == StopReason::none ||
      t.stop > StopReason::concurrent_probe ||
      (t.filter.scope != Scope::actor && t.filter.scope != Scope::resource) ||
      t.filter.clip < -1 || t.filter.clip >= int32_t(kMaxClips) ||
      (t.filter.scope == Scope::resource && t.filter.actor) ||
      t.controller_count > t.controller.size() ||
      t.queue_count > t.queue.size() || t.evaluation_count > t.evaluation.size() ||
      t.quaternion_count > t.quaternion.size() ||
      t.signal_count > t.signal_samples.size()) return false;
  if (!t.selected) {
    if (!(t.identity == Identity{}) || t.controller_count || t.queue_count || t.evaluation_count ||
        t.quaternion_count || t.counters.setup_accepted || t.counters.resource_bindings) return false;
  } else {
    const auto& id = t.identity;
    if (!id.manager || !id.instance || !id.ba || id.instance_handle > 65535 ||
        id.setup_signal_index > 65535 || id.setup_info_index > 65535 ||
        id.ba_handle >= 1000 || !id.clips || id.clips > kMaxClips ||
        !id.bones || id.bones > kMaxBones || !id.name_length || id.name_length > 259) return false;
    if (t.filter.scope == Scope::actor) {
      if (!id.actor || (id.actor_vtable != 0x82040170 && id.actor_vtable != 0x82041570) ||
          !id.signal || !id.info || !id.signal_groups || id.signal_groups > kMaxClips ||
          !id.info_rows || id.info_rows > kMaxClips || t.counters.setup_accepted != 1 ||
          !t.counters.setup_calls || t.counters.resource_bindings ||
          (t.filter.actor && t.filter.actor != id.actor)) return false;
    } else if (id.actor || id.actor_vtable || id.signal || id.info ||
               id.setup_signal_index || id.setup_info_index || id.signal_groups || id.info_rows ||
               t.counters.setup_accepted || t.counters.resource_bindings != 1 ||
               !t.counters.queue_calls || t.controller_count) return false;
  }
  const auto& source = t.identity.source;
  if (!source.resolved && !(source == SourceIdentity{})) return false;
  if (t.selected && (!t.identity.instance_generation || !t.identity.ba_generation ||
      (t.filter.scope == Scope::actor && !t.identity.actor_generation) ||
      (t.filter.scope == Scope::resource && t.identity.actor_generation) ||
      t.identity.instance_generation == t.identity.ba_generation ||
      (t.identity.actor_generation &&
       (t.identity.actor_generation == t.identity.instance_generation ||
        t.identity.actor_generation == t.identity.ba_generation)))) return false;
  if (source.resolved && (!source.archive_generation || source.archive_size < 4 || !source.member_size ||
      source.archive_size > kMaxArchiveBytes || source.member_size > kMaxMemberBytes ||
      source.member_size > source.archive_size || source.archive_slot >= kMaxArchiveSlots ||
      source.member_index >= kMaxArchiveMembers ||
      source.archive_generation == t.identity.instance_generation ||
      source.archive_generation == t.identity.ba_generation ||
      source.archive_generation == t.identity.actor_generation))
    return false;
  const auto recorded = t.controller_count + t.queue_count + t.evaluation_count +
                        t.quaternion_count + t.signal_count;
  if (t.counters.events_started != t.last_event || recorded > t.counters.events_started ||
      t.counters.events_abandoned > t.counters.events_started - recorded ||
      t.counters.events_inflight_at_flush !=
          t.counters.events_started - recorded - t.counters.events_abandoned ||
      t.counters.events_inflight_at_flush > t.counters.inflight_at_flush ||
      t.counters.counter_saturated > 1 || t.counters.invalid < t.counters.invalid_outputs ||
      t.counters.controller_calls < t.controller_count || t.counters.queue_calls < t.queue_count ||
      t.counters.evaluation_calls < t.evaluation_count)
    return false;
  auto abandoned = t.counters.events_abandoned;
  for (auto dropped : {t.counters.controller_full, t.counters.queue_full, t.counters.evaluation_full}) {
    if (dropped > abandoned) return false;
    abandoned -= dropped;
  }
  const auto& qc = t.quaternion_counts;
  if (!t.quaternion_enabled && (t.quaternion_count || qc.seen || qc.invalid_context ||
      qc.invalid_input || qc.invalid_output || qc.per_evaluation_full || qc.total_full ||
      qc.parent_dropped)) return false;
  if (t.quaternion_enabled && !t.counters.inflight_at_flush) {
    auto remaining = qc.seen;
    for (auto count : {qc.invalid_context, qc.invalid_input, qc.invalid_output,
                       qc.per_evaluation_full, qc.total_full, qc.parent_dropped,
                       uint64_t(t.quaternion_count)}) {
      if (count > remaining) return false;
      remaining -= count;
    }
    if (remaining) return false;
  }
  constexpr auto event_capacity = kControllerCapacity + kQueueCapacity + kEvaluationCapacity +
                                  kQuaternionCapacity + kSignalEventCapacity;
  std::array<uint64_t, event_capacity> ids{};
  std::array<const Event*, event_capacity> events{};
  size_t id_count = 0;
  const auto valid_event = [&](const Event& event) {
    if (!ValidEvent(event, t.last_event)) return false;
    for (size_t i = 0; i < id_count; ++i) if (ids[i] == event.id) return false;
    ids[id_count] = event.id;
    events[id_count++] = &event;
    return true;
  };
  const auto clip_limit = t.filter.scope == Scope::actor ?
      (std::min)({t.identity.clips, t.identity.signal_groups, t.identity.info_rows}) : t.identity.clips;
  for (size_t i = 0; i < t.controller_count; ++i)
    if (!t.controller[i].caller || t.controller[i].before_clip >= clip_limit ||
        t.controller[i].after_clip >= clip_limit ||
        !MatchesClip(t.filter, t.controller[i].before_clip) ||
        !FiniteFloatBits(t.controller[i].before_time) ||
        !FiniteFloatBits(t.controller[i].after_time) || !FiniteFloatBits(t.controller[i].step) ||
        !valid_event(t.controller[i].event))
      return false;
  for (size_t i = 0; i < t.queue_count; ++i)
    if (!t.queue[i].caller || t.queue[i].clip >= clip_limit || !MatchesClip(t.filter, t.queue[i].clip) ||
        !FiniteDoubleBits(t.queue[i].frame) || !valid_event(t.queue[i].event)) return false;
  uint64_t pose_sum = 0, invalid_sum = 0;
  for (size_t i = 0; i < t.evaluation_count; ++i) {
    if (!t.evaluation[i].caller || t.evaluation[i].clip >= clip_limit ||
        !MatchesClip(t.filter, t.evaluation[i].clip) || !t.evaluation[i].queue_count ||
        t.evaluation[i].queue_count > 5 || t.evaluation[i].pose_outputs > t.identity.bones ||
        t.evaluation[i].invalid_outputs > t.identity.bones ||
        !FiniteFloatBits(t.evaluation[i].time) || !valid_event(t.evaluation[i].event))
      return false;
    pose_sum += t.evaluation[i].pose_outputs;
    invalid_sum += t.evaluation[i].invalid_outputs;
  }
  for (size_t i = 0; i < t.quaternion_count; ++i) {
    const auto& sample = t.quaternion[i];
    if ((sample.caller != 0x8229a214 && sample.caller != 0x8229a5d0 &&
         sample.caller != 0x8229a6a4 && sample.caller != 0x8229a868) ||
        sample.bone >= t.identity.bones || !FiniteFloatBits(sample.factor) ||
        !valid_event(sample.event)) return false;
    bool parent_found = false;
    for (size_t j = 0; j < t.evaluation_count; ++j)
      parent_found |= t.evaluation[j].event.id == sample.event.parent;
    if (!parent_found) return false;
    for (size_t lane = 0; lane < 4; ++lane)
      if (!FiniteFloatBits(sample.left[lane]) || !FiniteFloatBits(sample.right[lane]) ||
          !FiniteFloatBits(sample.result[lane])) return false;
  }
  std::array<size_t, kSignalKindCount> signal_recorded{};
  if (!t.signal_enabled && (t.signal_count || t.signal_counts.unresolved_sources ||
      t.signal_counts.record_map_full || t.signal_counts.record_map_invalid ||
      t.signal_counts.actor_registry_full || t.signal_counts.asset_registry_full)) return false;
  for (size_t i = 0; i < t.signal_count; ++i) {
    const auto& sample = t.signal_samples[i];
    const auto kind = size_t(sample.kind);
    if (!t.signal_enabled || kind >= kSignalKindCount || !valid_event(sample.event) ||
        ++signal_recorded[kind] > kSignalCapacities[kind]) return false;
    const bool load = kind <= size_t(SignalKind::info_load);
    if (!load && !(sample.source == SourceIdentity{})) return false;
    if (load && !sample.source.resolved && !(sample.source == SourceIdentity{})) return false;
    if (load && sample.source.resolved &&
        (!sample.source.archive_generation || sample.source.archive_slot >= kMaxArchiveSlots ||
         sample.source.member_index >= kMaxArchiveMembers || sample.source.archive_size < 4 ||
         sample.source.archive_size > kMaxArchiveBytes || !sample.source.member_size ||
         sample.source.member_size > kMaxMemberBytes ||
         sample.source.member_size > sample.source.archive_size)) return false;
    if (sample.source_offset && (sample.kind != SignalKind::dispatch || !sample.record_read ||
        sample.record_offset < sample.group_offset || sample.table_offset < sample.group_offset))
      return false;
    if (sample.time_read && (sample.kind != SignalKind::group ||
        !FiniteFloatBits(sample.actor_time) || !FiniteFloatBits(sample.actor_step_field))) return false;
  }
  for (size_t i = 0; i < kSignalKindCount; ++i) {
    if (signal_recorded[i] != t.signal_recorded[i] ||
        t.signal_counts.seen[i] < signal_recorded[i] ||
        t.signal_counts.full[i] > t.signal_counts.seen[i] ||
        t.signal_counts.unreadable[i] > t.signal_counts.seen[i] ||
        t.signal_counts.skipped[i] > t.signal_counts.seen[i]) return false;
    if (!t.signal_enabled && (t.signal_counts.seen[i] || t.signal_counts.full[i] ||
        t.signal_counts.unreadable[i] || t.signal_counts.skipped[i] ||
        t.signal_inflight[i])) return false;
  }
  if (pose_sum > t.counters.pose_outputs || invalid_sum > t.counters.invalid_outputs) return false;
  std::array<uint64_t, event_capacity> missing_parents{};
  size_t missing_count = 0;
  for (size_t i = 0; i < id_count; ++i) {
    const auto& event = *events[i];
    if (!event.parent) continue;
    const Event* parent = nullptr;
    for (size_t j = 0; j < id_count; ++j)
      if (events[j]->id == event.parent) { parent = events[j]; break; }
    if (!parent) {
      if (std::find(missing_parents.begin(), missing_parents.begin() + missing_count,
                    event.parent) == missing_parents.begin() + missing_count)
        missing_parents[missing_count++] = event.parent;
    } else if (parent->begin > event.begin || parent->end < event.end) return false;
  }
  if (missing_count > t.counters.events_abandoned + t.counters.events_inflight_at_flush) return false;
  Writer w(output, capacity);
  w.Text("{\"schema\":\"n3.runtime-animation-trace\",\"version\":3,");
  w.Text("\"sources\":{\"setup\":\"0x82093be8\",\"controller\":\"0x82080158\",");
  w.Text("\"queue\":\"0x82252bd8\",\"evaluation\":\"0x82298ff0\",");
  w.Text("\"pose_output\":\"0x82249628\",\"pose_return\":\"0x8229ad64\",");
  w.Text("\"archive_load\":\"0x822733b8\",\"archive_release\":\"0x82272f58\",");
  w.Text("\"archive_raw_load\":\"0x82273000\",\"archive_mount\":\"0x82272af0\",");
  w.Text("\"resolver\":\"0x82272c40\",\"ba_load\":\"0x8224e6f0\",");
  w.Text("\"ba_decode\":\"0x82298e78\",\"ba_collect\":\"0x8224e9b0\",");
  w.Text("\"instance_create\":\"0x8229cf30\",\"instance_submit\":\"0x8224ac98\",");
  w.Text("\"instance_release_direct\":\"0x82251d38\",\"instance_reset\":\"0x8224e0b8\",");
  w.Text("\"manager_destroy\":\"0x82249fb0\"},");
  w.Text("\"clock\":{\"kind\":\"performance_counter\",\"frequency\":");
  w.Number(t.clock_frequency); w.Text("},");
  w.Text("\"dispatch\":{\"version\":1,\"resource_hook\":\"0x8217ad08\",");
  w.Text("\"setup_wrapper_calls\":{");
  constexpr std::array<std::string_view, 5> wrapper_addresses{
      "0x820a4648", "0x820af768", "0x8208d878", "0x820aafb0", "0x820a2968"};
  for (size_t i = 0; i < wrapper_addresses.size(); ++i) {
    if (i) w.Text(",");
    w.Text("\""); w.Text(wrapper_addresses[i]); w.Text("\":");
    w.Number(t.dispatch.setup_wrapper_calls[i]);
  }
  w.Text("},\"setup_rejections\":{");
  constexpr std::array<std::string_view, 9> setup_names{
      "scope_skipped", "filter_mismatch", "vtable_unreadable", "vtable_unsupported",
      "input_invalid", "candidates", "post_identity_failed", "other_after_selection",
      "repeat_selected"};
  for (size_t i = 0; i < setup_names.size(); ++i) {
    if (i) w.Text(",");
    w.Text("\""); w.Text(setup_names[i]); w.Text("\":");
    w.Number(t.dispatch.setup_rejections[i]);
  }
  w.Text("},\"setup_vtables\":{\"capacity\":16,\"full\":"); w.Number(t.dispatch.vtable_full);
  w.Text(",\"zero\":"); w.Number(t.dispatch.vtable_zero);
  w.Text(",\"getter_unreadable\":"); w.Number(t.dispatch.getter_unreadable);
  w.Text(",\"entries\":[");
  bool first_vtable = true;
  for (const auto& entry : t.dispatch.unsupported_vtables) {
    if (!entry.calls) continue;
    if (!first_vtable) w.Text(",");
    first_vtable = false;
    w.Text("{\"vtable\":"); w.Address(entry.vtable);
    w.Text(",\"getter\":"); w.Address(entry.getter);
    w.Text(",\"calls\":"); w.Number(entry.calls); w.Text("}");
  }
  w.Text("]},\"resource_calls\":"); w.Number(t.dispatch.resource_calls);
  w.Text(",\"flag_zero\":"); w.Number(t.dispatch.flag_zero);
  w.Text(",\"handle_minus_one\":"); w.Number(t.dispatch.handle_minus_one);
  w.Text(",\"eligible\":"); w.Number(t.dispatch.eligible);
  w.Text(",\"unreadable\":"); w.Number(t.dispatch.unreadable);
  w.Text("},");
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
  w.Text("\"name_fnv1a64\":"); w.Fingerprint(t.identity.name_fingerprint); w.Text(",");
  NUMBER_FIELD("actor_generation", actor_generation);
  NUMBER_FIELD("instance_generation", instance_generation);
  NUMBER_FIELD("ba_generation", ba_generation);
  w.Text("\"source\":{\"status\":");
  w.Text(source.resolved ? "\"resolved\"" : "\"unavailable\"");
  w.Text(",\"archive_generation\":"); w.Number(source.resolved ? source.archive_generation : 0);
  w.Text(",\"archive_slot\":");
  if (source.resolved) w.Number(source.archive_slot); else w.Text("null");
  w.Text(",\"archive_content_sha256\":");
  if (source.resolved) w.Digest(source.archive_digest); else w.Text("null");
  w.Text(",\"member_sha256\":");
  if (source.resolved) w.Digest(source.member_digest); else w.Text("null");
  w.Text(",\"member_index\":");
  if (source.resolved) w.Number(source.member_index); else w.Text("null");
  w.Text(",\"archive_size\":"); w.Number(source.resolved ? source.archive_size : 0);
  w.Text(",\"member_size\":"); w.Number(source.resolved ? source.member_size : 0);
  w.Text("}},");
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
  COUNT_FIELD(transitions); COUNT_FIELD(events_started); COUNT_FIELD(events_abandoned);
  COUNT_FIELD(events_inflight_at_flush);
  COUNT_FIELD(cache_hits); COUNT_FIELD(cache_untracked); COUNT_FIELD(registry_full);
  w.Text("\"counter_saturated\":"); w.Number(t.counters.counter_saturated); w.Text("},");
#undef COUNT_FIELD
  const auto event_fields = [&](const Event& event) {
    w.Text(",\"event_id\":"); w.Number(event.id);
    w.Text(",\"parent_event_id\":"); w.Number(event.parent);
    w.Text(",\"begin_tick\":"); w.Number(event.begin);
    w.Text(",\"end_tick\":"); w.Number(event.end);
  };
  w.Text("\"controller\":[");
  for (size_t i = 0; i < t.controller_count; ++i) {
    const auto& s = t.controller[i];
    if (i) w.Text(",");
    w.Text("{\"caller\":"); w.Address(s.caller);
    w.Text(",\"before_clip\":"); w.Number(s.before_clip);
    w.Text(",\"after_clip\":"); w.Number(s.after_clip);
    w.Text(",\"before_time\":"); w.Number(std::bit_cast<float>(s.before_time));
    w.Text(",\"after_time\":"); w.Number(std::bit_cast<float>(s.after_time));
    w.Text(",\"step\":"); w.Number(std::bit_cast<float>(s.step));
    event_fields(s.event); w.Text("}");
  }
  w.Text("],\"queue\":[");
  for (size_t i = 0; i < t.queue_count; ++i) {
    const auto& s = t.queue[i];
    if (i) w.Text(",");
    w.Text("{\"caller\":"); w.Address(s.caller);
    w.Text(",\"clip\":"); w.Number(s.clip);
    w.Text(",\"frame\":"); w.Number(std::bit_cast<double>(s.frame));
    event_fields(s.event); w.Text("}");
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
    w.Text(",\"invalid_outputs\":"); w.Number(s.invalid_outputs);
    event_fields(s.event); w.Text("}");
  }
  w.Text("]");
  if (t.quaternion_enabled) {
    w.Text(",\"quaternion_probe\":{\"version\":1,\"helper\":\"0x8229ca98\",");
    w.Text("\"component_order\":\"guest_vmx_lanes_0_to_3\",");
    w.Text("\"capacity\":128,\"per_evaluation_capacity\":8,\"counts\":{");
#define QUAT_COUNT(member) w.Text("\"" #member "\":"); w.Number(qc.member); w.Text(",")
    QUAT_COUNT(seen); QUAT_COUNT(invalid_context); QUAT_COUNT(invalid_input);
    QUAT_COUNT(invalid_output); QUAT_COUNT(per_evaluation_full); QUAT_COUNT(total_full);
    w.Text("\"parent_dropped\":"); w.Number(qc.parent_dropped); w.Text("},\"samples\":[");
#undef QUAT_COUNT
    const auto signed_float = [&](uint32_t bits) {
      if (bits == 0x80000000u) w.Text("-0.0");
      else w.Number(std::bit_cast<float>(bits));
    };
    const auto vector = [&](const std::array<uint32_t, 4>& values) {
      w.Text("[");
      for (size_t lane = 0; lane < values.size(); ++lane) {
        if (lane) w.Text(",");
        signed_float(values[lane]);
      }
      w.Text("]");
    };
    for (size_t i = 0; i < t.quaternion_count; ++i) {
      const auto& sample = t.quaternion[i];
      if (i) w.Text(",");
      w.Text("{\"caller\":"); w.Address(sample.caller);
      w.Text(",\"bone\":"); w.Number(sample.bone);
      w.Text(",\"factor\":"); signed_float(sample.factor);
      w.Text(",\"left\":"); vector(sample.left);
      w.Text(",\"right\":"); vector(sample.right);
      w.Text(",\"result\":"); vector(sample.result);
      event_fields(sample.event); w.Text("}");
    }
    w.Text("]}");
  }
  if (t.signal_enabled) {
    w.Text(",\"signal_probe\":{\"version\":1,\"event_ids\":\"shared_trace_v3\",");
    w.Text("\"capacity\":544,\"counts\":{");
    for (size_t i = 0; i < kSignalKindCount; ++i) {
      if (i) w.Text(",");
      w.Text("\""); w.Text(kSignalNames[i]); w.Text("\":{\"seen\":");
      w.Number(t.signal_counts.seen[i]); w.Text(",\"recorded\":");
      w.Number(t.signal_recorded[i]); w.Text(",\"full\":");
      w.Number(t.signal_counts.full[i]); w.Text(",\"unreadable\":");
      w.Number(t.signal_counts.unreadable[i]); w.Text(",\"skipped\":");
      w.Number(t.signal_counts.skipped[i]); w.Text(",\"capacity\":");
      w.Number(kSignalCapacities[i]); w.Text("}");
    }
    w.Text("},\"losses\":{\"unresolved_sources\":"); w.Number(t.signal_counts.unresolved_sources);
    w.Text(",\"record_map_full\":"); w.Number(t.signal_counts.record_map_full);
    w.Text(",\"record_map_invalid\":"); w.Number(t.signal_counts.record_map_invalid);
    w.Text(",\"actor_registry_full\":"); w.Number(t.signal_counts.actor_registry_full);
    w.Text(",\"asset_registry_full\":"); w.Number(t.signal_counts.asset_registry_full);
    w.Text("},\"samples\":[");
    const auto signal_source = [&](const SourceIdentity& item) {
      w.Text("{\"status\":"); w.Text(item.resolved ? "\"resolved\"" : "\"unavailable\"");
      w.Text(",\"archive_generation\":"); w.Number(item.resolved ? item.archive_generation : 0);
      w.Text(",\"archive_slot\":"); if (item.resolved) w.Number(item.archive_slot); else w.Text("null");
      w.Text(",\"archive_content_sha256\":"); if (item.resolved) w.Digest(item.archive_digest); else w.Text("null");
      w.Text(",\"member_sha256\":"); if (item.resolved) w.Digest(item.member_digest); else w.Text("null");
      w.Text(",\"member_index\":"); if (item.resolved) w.Number(item.member_index); else w.Text("null");
      w.Text(",\"archive_size\":"); w.Number(item.resolved ? item.archive_size : 0);
      w.Text(",\"member_size\":"); w.Number(item.resolved ? item.member_size : 0);
      w.Text("}");
    };
    for (size_t i = 0; i < t.signal_count; ++i) {
      const auto& s = t.signal_samples[i];
      if (i) w.Text(",");
      w.Text("{\"type\":\""); w.Text(kSignalNames[size_t(s.kind)]); w.Text("\"");
      w.Text(",\"caller\":"); w.Address(s.caller);
      if (s.kind <= SignalKind::info_load) {
        const auto address = s.kind == SignalKind::ba_load ? s.ba :
            s.kind == SignalKind::as_load ? s.signal : s.info;
        const auto generation = s.kind == SignalKind::ba_load ? s.ba_generation :
            s.kind == SignalKind::as_load ? s.signal_generation : s.info_generation;
        w.Text(",\"object\":"); w.Address(address);
        w.Text(",\"generation\":"); w.Number(generation);
        w.Text(",\"loaded\":"); w.Text(s.loaded ? "true" : "false");
        if (s.kind == SignalKind::ba_load) {
          w.Text(",\"ba_handle\":"); w.Number(s.ba_handle);
        }
        w.Text(",\"source\":"); signal_source(s.source);
      } else {
        if (s.kind != SignalKind::selection) {
          w.Text(",\"actor\":"); w.Address(s.actor);
          w.Text(",\"actor_generation\":"); w.Number(s.actor_generation);
        }
        if (s.kind == SignalKind::setup || s.kind == SignalKind::group) {
          w.Text(",\"identity_bound\":"); w.Text(s.identity_bound ? "true" : "false");
          w.Text(",\"instance\":"); w.Address(s.instance);
          w.Text(",\"instance_generation\":"); w.Number(s.instance_generation);
          w.Text(",\"ba\":"); w.Address(s.ba);
          w.Text(",\"ba_generation\":"); w.Number(s.ba_generation);
          w.Text(",\"signal\":"); w.Address(s.signal);
          w.Text(",\"signal_generation\":"); w.Number(s.signal_generation);
          w.Text(",\"info\":"); w.Address(s.info);
          w.Text(",\"info_generation\":"); w.Number(s.info_generation);
        }
        if (s.kind == SignalKind::setup) {
          w.Text(",\"actor_vtable\":"); w.Address(s.actor_vtable);
          w.Text(",\"instance_handle\":"); w.Number(s.instance_handle);
          w.Text(",\"ba_handle\":"); w.Number(s.ba_handle);
          w.Text(",\"signal_index\":"); w.Number(s.signal_index);
          w.Text(",\"info_index\":"); w.Number(s.info_index);
          w.Text(",\"setup_key4\":"); w.Number(s.setup_key4);
          w.Text(",\"setup_key88\":"); w.Number(s.setup_key88);
        }
        if (s.kind == SignalKind::request || s.kind == SignalKind::selection ||
            s.kind == SignalKind::install) {
          w.Text(",\"info\":"); w.Address(s.info);
          w.Text(",\"info_generation\":"); w.Number(s.info_generation);
          if (s.kind != SignalKind::request) {
            w.Text(",\"selected_row\":"); w.Number(s.selected_row);
          }
        }
        if (s.kind == SignalKind::request || s.kind == SignalKind::selection) {
          w.Text(",\"requested_type\":"); w.Number(s.requested_type);
          w.Text(",\"requested_index\":"); w.Number(s.requested_index);
          w.Text(",\"requested_attribute\":"); w.Number(s.requested_attribute);
        }
        if (s.kind == SignalKind::install) {
          w.Text(",\"installed_row\":"); w.Number(s.installed_row);
        }
        if (s.kind == SignalKind::selection || s.kind == SignalKind::install) {
          w.Text(",\"row_read\":"); w.Text(s.row_read ? "true" : "false");
          w.Text(",\"row_type\":"); if (s.row_read) w.Number(s.row_type); else w.Text("null");
          w.Text(",\"row_index\":"); if (s.row_read) w.Number(s.row_index); else w.Text("null");
          w.Text(",\"row_attribute\":"); if (s.row_read) w.Number(s.row_attribute); else w.Text("null");
        }
        if (s.kind == SignalKind::group || s.kind == SignalKind::dispatch) {
          w.Text(",\"group_read\":"); w.Text(s.group_read ? "true" : "false");
          w.Text(",\"group_index\":"); if (s.group_read) w.Number(s.group_index); else w.Text("null");
        }
        if (s.kind == SignalKind::group) {
          w.Text(",\"time_read\":"); w.Text(s.time_read ? "true" : "false");
          w.Text(",\"actor_time\":");
          if (s.time_read) w.Number(std::bit_cast<float>(s.actor_time)); else w.Text("null");
          w.Text(",\"actor_step_field\":");
          if (s.time_read) w.Number(std::bit_cast<float>(s.actor_step_field)); else w.Text("null");
        }
        if (s.kind == SignalKind::dispatch) {
          w.Text(",\"signal_generation\":"); w.Number(s.signal_generation);
          w.Text(",\"dispatch_path\":"); w.Number(s.dispatch_path);
          w.Text(",\"record_read\":"); w.Text(s.record_read ? "true" : "false");
          w.Text(",\"retained_index\":"); if (s.record_read) w.Number(s.retained_index); else w.Text("null");
          w.Text(",\"record_kind\":"); if (s.record_read) w.Number(s.record_kind); else w.Text("null");
          w.Text(",\"record_time\":"); if (s.record_read) w.Number(s.record_time); else w.Text("null");
          w.Text(",\"record_bounded\":"); if (s.record_read) w.Number(s.record_bounded); else w.Text("null");
          w.Text(",\"record_word_count\":"); if (s.record_read) w.Number(s.record_words); else w.Text("null");
          w.Text(",\"source_offset\":"); w.Text(s.source_offset ? "true" : "false");
          w.Text(",\"group_offset\":"); if (s.source_offset) w.Number(s.group_offset); else w.Text("null");
          w.Text(",\"table_offset\":"); if (s.source_offset) w.Number(s.table_offset); else w.Text("null");
          w.Text(",\"record_offset\":"); if (s.source_offset) w.Number(s.record_offset); else w.Text("null");
        }
        if (s.kind == SignalKind::effect) {
          w.Text(",\"observer\":"); w.Text(s.effect_kind == 1 ?
              "\"actor_byte_1056_comparison\"" : "\"downstream_slot_occupancy_comparison\"");
          w.Text(",\"changed_slots\":"); w.Number(s.changed_slots);
        }
      }
      event_fields(s.event); w.Text("}");
    }
    w.Text("]}");
  }
  w.Text("}\n");
  if (!w.ok()) { output[0] = '\0'; return false; }
  size = w.size();
  return true;
}
}  // namespace n3::animation_trace
