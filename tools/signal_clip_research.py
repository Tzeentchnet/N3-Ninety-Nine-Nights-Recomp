#!/usr/bin/env python3
"""Bounded, read-only signal/clip research over an owned local corpus.

Only structural counts, offsets and hashes are emitted. Package/member names,
paths, record payloads, and decoded game data remain in memory. Correlations
are candidates, not evidence that the runtime resolver selected those members.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True

try:
    from .n3_gameplay_data import GameplayDataError, parse_sox, read_pak
except ImportError:
    from n3_gameplay_data import GameplayDataError, parse_sox, read_pak


MAX_BA_SIZE = 16 * 1024 * 1024
MAX_SIGNAL_SIZE = 16 * 1024 * 1024
MAX_SCRIPT_SIZE = 16 * 1024 * 1024
MAX_CLIPS = 2048
MAX_BONES = 1024
MAX_FRAMES = 1_000_000
MAX_KEYS = 1_000_000
MAX_PACKAGES = 2048
MAX_LOOSE_SCRIPTS = 4096
MAX_RECORDS = 1_000_000
MAX_TOTAL_RECORDS = 2_000_000
MAX_UNIQUE_PAYLOADS = 65_536
_U32 = struct.Struct(">I")
_I32 = struct.Struct(">i")
_SUFFIXES = (".as", ".info", ".aib", ".ai_funcb", ".n3sb", ".bin")
_SCRIPT_TERMS = (b"signal", b"notify", b"event", b"anim")


class ResearchError(ValueError):
    """An input is outside this deliberately narrow research profile."""


def _uint(data: bytes, offset: int) -> int:
    if offset < 0 or offset > len(data) - 4:
        raise ResearchError("truncated integer")
    return _U32.unpack_from(data, offset)[0]


def _int(data: bytes, offset: int) -> int:
    if offset < 0 or offset > len(data) - 4:
        raise ResearchError("truncated integer")
    return _I32.unpack_from(data, offset)[0]


def _span(data: bytes, offset: int, length: int) -> int:
    if offset < 0 or length < 0 or offset > len(data) or length > len(data) - offset:
        raise ResearchError("out-of-bounds span")
    return offset + length


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fingerprint(values) -> str:
    digest = hashlib.sha256(b"n3.signal-clip-research.multiset-v1\0")
    encoded = sorted(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        for value in values
    )
    for record in encoded:
        digest.update(len(record).to_bytes(8, "big"))
        digest.update(record)
    return digest.hexdigest()


def _histogram(counter: Counter) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


@dataclass(frozen=True)
class BaLayout:
    frame_counts: tuple[int, ...]
    bones: int
    end: int


def ba_layout(data: bytes) -> BaLayout:
    """Walk only the established mode-2 BA extent, without interpreting a tail."""
    if not 24 <= len(data) <= MAX_BA_SIZE:
        raise ResearchError("unsupported BA size")
    header = struct.unpack_from(">6I", data)
    if header[:3] != (24, 0x244D, 12) or header[5] != 2:
        raise ResearchError("unsupported BA header")
    clips, bones = header[3:5]
    if not 1 <= clips <= MAX_CLIPS or not 1 <= bones <= MAX_BONES:
        raise ResearchError("unsupported BA dimensions")
    pos = _span(data, 24, 4 * clips)
    frames = struct.unpack_from(f">{clips}I", data, 24)
    if any(not 1 <= frame <= MAX_FRAMES for frame in frames):
        raise ResearchError("unsupported BA frame counts")

    for _ in range(bones):
        pos = _span(data, pos, 255 * 2 + 64 + 120)
        for _ in range(clips):
            if _uint(data, pos) != 2:
                raise ResearchError("unsupported BA track")
            pos += 4
            for key_size in (16, 20, 16):
                count = _uint(data, pos)
                pos += 4
                if count > MAX_KEYS:
                    raise ResearchError("unsupported BA key count")
                pos = _span(data, pos, count * key_size)
    return BaLayout(tuple(frames), bones, pos)


def ba_tail(data: bytes, layout: BaLayout) -> dict[str, int | str] | None:
    if not 0 <= layout.end <= len(data):
        raise ResearchError("invalid BA extent")
    if layout.end == len(data):
        return None
    return {
        "member_sha256": _hash(data),
        "member_size": len(data),
        "offset": layout.end,
        "length": len(data) - layout.end,
        "tail_sha256": _hash(data[layout.end:]),
    }


@dataclass(frozen=True)
class SignalRecord:
    time: int
    kind: int
    bounded_value: int
    words: int
    offset: int


@dataclass(frozen=True)
class SignalLayout:
    groups: tuple[tuple[SignalRecord, ...], ...]
    declared_records: int
    discarded_records: int
    empty_groups: int
    sentinel_groups: int
    records_end: int
    list64_count: int
    array_counts: tuple[int, int]
    end: int


def signal_layout(data: bytes) -> SignalLayout:
    """Read the observed AS-101 structure, never retaining parameter words."""
    if not 520 <= len(data) <= MAX_SIGNAL_SIZE or _uint(data, 0) != 101:
        raise ResearchError("unsupported AS header")
    count = _uint(data, 4)
    if count > MAX_CLIPS or count > (len(data) - 520) // 4:
        raise ResearchError("unsupported AS group count")
    pos = 520
    groups = []
    declared = discarded = empty = sentinel = 0
    for _ in range(count):
        record_count = _uint(data, pos)
        pos += 4
        if record_count in (0, 0x10000):
            empty += 1
            sentinel += record_count == 0x10000
            groups.append(())
            continue
        if record_count > MAX_RECORDS - declared:
            raise ResearchError("unsupported AS record count")
        declared += record_count
        table = pos
        pos = _span(data, pos, 8 * record_count)
        group = []
        for index in range(record_count):
            kind = _uint(data, table + 8 * index)
            offset = _uint(data, table + 8 * index + 4)
            # The bounded corpus profile has ordered, contiguous records.
            if offset != pos:
                raise ResearchError("unsupported AS record layout")
            time = _int(data, offset)
            bounded_value = _int(data, offset + 4)
            words = _uint(data, offset + 8)
            payload = _span(data, offset, 12)
            if words > (len(data) - payload) // 4:
                raise ResearchError("out-of-bounds AS payload")
            pos = _span(data, payload, 4 * words)
            pos = _span(data, pos, 16)
            if time < 0 or not 0 <= bounded_value < 16:
                discarded += 1
            else:
                group.append(SignalRecord(time, kind, bounded_value, words, offset))
        groups.append(tuple(group))

    records_end = pos
    list64_count = _uint(data, pos)
    pos = _span(data, pos + 4, list64_count * 64)
    arrays = []
    for _ in range(2):
        array_count = _uint(data, pos)
        pos = _span(data, pos + 4, array_count * 4)
        arrays.append(array_count)
    if pos != len(data):
        raise ResearchError("unsupported AS trailing layout")
    return SignalLayout(
        tuple(groups), declared, discarded, empty, sentinel, records_end,
        list64_count, (arrays[0], arrays[1]), pos,
    )


@dataclass(frozen=True)
class StateRow:
    type_id: int
    index: int
    attribute: int


@dataclass(frozen=True)
class StateLayout:
    rows: tuple[StateRow, ...]
    rows_end: int
    size: int
    suffix_count: int | None


def state_layout(data: bytes) -> StateLayout:
    if not 524 <= len(data) <= MAX_SIGNAL_SIZE or _uint(data, 0) != 100:
        raise ResearchError("unsupported INFO header")
    count = _uint(data, 8)
    if count > MAX_CLIPS:
        raise ResearchError("unsupported INFO row count")
    end = _span(data, 524, count * 86)
    rows = tuple(
        StateRow(_int(data, 524 + 86 * index),
                 _int(data, 528 + 86 * index),
                 _int(data, 548 + 86 * index))
        for index in range(count)
    )
    suffix_count = _int(data, end) if len(data) - end >= 4 else None
    return StateLayout(rows, end, len(data), suffix_count)


@dataclass(frozen=True)
class MemberIdentity:
    archive_sha256: str
    index: int
    member_sha256: str


def _member_stem(name: str, suffix: str) -> str | None:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if not base.endswith(suffix) or len(base) == len(suffix):
        return None
    return base[:-len(suffix)]


def _table_stem(value, suffix: str) -> str | None:
    if not isinstance(value, bytes):
        return None
    raw = value.split(b"\0", 1)[0].strip()
    try:
        name = raw.decode("ascii").replace("\\", "/").rsplit("/", 1)[-1].casefold()
    except UnicodeError:
        return None
    if not name:
        return None
    return name.removesuffix(suffix)


def _script_hits(data: bytes) -> dict[str, int]:
    if len(data) > MAX_SCRIPT_SIZE:
        raise ResearchError("unsupported script size")
    lower = data.lower()
    # These are byte-substring hits, not parsed records or semantic assertions.
    return {term.decode("ascii"): lower.count(term) for term in _SCRIPT_TERMS}


def _numeric_definitions(data: bytes) -> dict[bytes, int]:
    if len(data) > MAX_SCRIPT_SIZE:
        raise ResearchError("unsupported vocabulary size")
    result = {}
    pattern = rb"^[\t ]*#[\t ]*define[\t ]+([A-Za-z_]\w*)[\t ]+([+-]?(?:0x[0-9a-fA-F]+|\d+))\b"
    for line in data.splitlines():
        match = re.match(pattern, line)
        if match is None:
            continue
        name, value = match.groups()
        if name in result:
            raise ResearchError("duplicate vocabulary definition")
        result[name] = int(value, 16 if b"x" in value.lower() else 10)
    if not result:
        raise ResearchError("empty vocabulary definitions")
    return result


def _labeled_ids(data: bytes) -> set[int]:
    if len(data) > MAX_SCRIPT_SIZE:
        raise ResearchError("unsupported vocabulary size")
    pattern = rb'^[\t ]*"[^"\r\n]*"[\t ]+([+-]?\d+)[\t ]*$'
    return {int(match.group(1)) for line in data.splitlines()
            if (match := re.match(pattern, line)) is not None}


def _signal_schema_blocks(data: bytes, definitions: dict[bytes, int]) -> tuple[dict, dict[int, int]]:
    """Resolve authoring block symbols; standalone numbers are parameter counts."""
    if len(data) > MAX_SCRIPT_SIZE:
        raise ResearchError("unsupported vocabulary size")
    lines = data.splitlines()
    pattern = rb'^[\t ]*"[^"\r\n]*"[\t ]+([A-Za-z_]\w*)[\t ]*$'
    starts = [(index, match.group(1)) for index, line in enumerate(lines)
              if (match := re.match(pattern, line)) is not None]
    symbols = []
    counts = []
    for position, (index, symbol) in enumerate(starts):
        if index + 4 >= len(lines) or not re.fullmatch(rb"[\t ]*\d+[\t ]*", lines[index + 4]):
            raise ResearchError("unsupported signal schema block")
        count = int(lines[index + 4].strip())
        next_start = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        if count > MAX_RECORDS or count > next_start - index - 5:
            raise ResearchError("out-of-bounds signal schema block")
        symbols.append(symbol)
        counts.append(count)
    resolved = [definitions[name] for name in symbols if name in definitions]
    lengths: dict[int, set[int]] = defaultdict(set)
    for symbol, count in zip(symbols, counts, strict=True):
        if symbol in definitions:
            lengths[definitions[symbol]].add(count)
    expected = {kind: next(iter(values)) for kind, values in lengths.items() if len(values) == 1}
    summary = {
        "blocks": len(symbols),
        "resolved_header_symbols": len(resolved),
        "unresolved_header_symbols": len(symbols) - len(resolved),
        "unique_resolved_kind_ids": len(set(resolved)),
        "parameter_slots_declared": sum(counts),
        "kind_ids_with_ambiguous_slot_counts": len(lengths) - len(expected),
    }
    return summary, expected


def vocabulary_summary(animtype: bytes, signaltype: bytes, signalid: bytes, animid: bytes) -> tuple[dict, dict[int, int]]:
    animations = _numeric_definitions(animtype)
    signals = _numeric_definitions(signaltype)
    animation_values = set(animations.values())
    signal_values = set(signals.values())
    author_ids = _labeled_ids(animid)
    blocks, expected_word_counts = _signal_schema_blocks(signalid, signals)
    summary = {
        "animtype": {
            "numeric_definitions": len(animations),
            "unique_numeric_values": len(animation_values),
            "runtime_type_values_0_to_26": len(animation_values & set(range(27))),
        },
        "signaltype": {
            "numeric_definitions": len(signals),
            "unique_kind_ids": len(signal_values),
            "minimum": min(signal_values),
            "maximum": max(signal_values),
        },
        "signalid": blocks,
        "animid": {
            "unique_authoring_ids": len(author_ids),
            "minimum": min(author_ids, default=None),
            "maximum": max(author_ids, default=None),
        },
    }
    return summary, expected_word_counts


def _addon_classifier(root: Path) -> Callable[[bytes], str]:
    if not (root / "n3_blender" / "animation.py").is_file():
        raise ResearchError("missing add-on parser")
    original_path = sys.path[:]
    sys.path.insert(0, str(root))
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        animation = importlib.import_module("n3_blender.animation")
        errors = importlib.import_module("n3_blender.errors")
    finally:
        sys.dont_write_bytecode = previous
        sys.path[:] = original_path

    def classify(data: bytes) -> str:
        try:
            animation.parse_character_ba(data, label="candidate")
        except errors.N3FormatError as error:
            return "trailing" if error.code == errors.BA_TRAILING_DATA else "other"
        return "accepted"

    return classify


class Research:
    """Accumulate distinct payloads and private in-memory association candidates."""

    def __init__(self, classify_tail: Callable[[bytes], str] | None = None):
        self.classify_tail = classify_tail
        self.packages = Counter()
        self.failures = Counter()
        self.occurrences = Counter()
        self.ba: dict[str, BaLayout | None] = {}
        self.tails: dict[str, tuple[dict, str]] = {}
        self.ba_occurrences = Counter()
        self.signals: dict[str, SignalLayout | None] = {}
        self.total_signal_records = 0
        self.states: dict[str, StateLayout | None] = {}
        self.scripts: dict[tuple[str, str], dict[str, int]] = {}
        self.script_occurrences = Counter()
        self.index: dict[tuple[str, str, str], list[MemberIdentity]] = defaultdict(list)
        self.tables = {}

    def add_archive(self, role: str, family: str, archive, archive_sha256: str) -> None:
        self.packages[role] += 1
        for member in archive.members:
            lower = member.name.casefold()
            suffix = next((suffix for suffix in _SUFFIXES if lower.endswith(suffix)), None)
            if role == "character" and lower.endswith(".ba"):
                suffix = ".ba"
            is_table = role == "initial" and lower in ("chardata.sox", "itemtable.sox")
            if suffix is None and not is_table:
                continue
            data = archive.read_member(member)
            digest = _hash(data)
            if is_table:
                table_key = lower.removesuffix(".sox")
                if table_key in self.tables:
                    raise ResearchError("duplicate table")
                self.tables[table_key] = parse_sox(data, "table")
                continue
            self.occurrences[(role, suffix)] += 1
            if suffix == ".ba":
                self.ba_occurrences[digest] += 1
                if digest not in self.ba:
                    if len(self.ba) >= MAX_UNIQUE_PAYLOADS:
                        raise ResearchError("too many BA profiles")
                    try:
                        layout = ba_layout(data)
                        self.ba[digest] = layout
                        tail = ba_tail(data, layout)
                        if tail is not None:
                            classification = (
                                self.classify_tail(data) if self.classify_tail else "unverified"
                            )
                            self.tails[digest] = (tail, classification)
                    except (ResearchError, ValueError):
                        self.ba[digest] = None
                        self.failures["ba"] += 1
            elif suffix == ".as" and digest not in self.signals:
                if len(self.signals) >= MAX_UNIQUE_PAYLOADS:
                    raise ResearchError("too many AS profiles")
                try:
                    layout = signal_layout(data)
                    if layout.declared_records > MAX_TOTAL_RECORDS - self.total_signal_records:
                        raise ResearchError("too many total AS records")
                    self.total_signal_records += layout.declared_records
                    self.signals[digest] = layout
                except ResearchError:
                    self.signals[digest] = None
                    self.failures["as"] += 1
            elif suffix == ".info" and digest not in self.states:
                if len(self.states) >= MAX_UNIQUE_PAYLOADS:
                    raise ResearchError("too many INFO profiles")
                try:
                    self.states[digest] = state_layout(data)
                except ResearchError:
                    self.states[digest] = None
                    self.failures["info"] += 1
            elif suffix in (".aib", ".ai_funcb", ".n3sb", ".bin"):
                self.add_script(suffix, data)
            if ((role == "character" and suffix == ".ba")
                    or (role == "resource2" and suffix in (".as", ".info"))):
                stem = _member_stem(member.name, suffix)
                if stem is not None:
                    self.index[(family, suffix, stem)].append(
                        MemberIdentity(archive_sha256, member.index, digest)
                    )

    def add_script(self, kind: str, data: bytes) -> None:
        digest = _hash(data)
        self.script_occurrences[kind] += 1
        key = (kind, digest)
        if key not in self.scripts:
            if len(self.scripts) >= MAX_UNIQUE_PAYLOADS:
                raise ResearchError("too many script profiles")
            try:
                self.scripts[key] = _script_hits(data)
            except ResearchError:
                self.scripts[key] = {}
                self.failures["script"] += 1

    def _association(self, families: set[str]):
        if "chardata" not in self.tables or "itemtable" not in self.tables:
            raise ResearchError("missing required tables")
        table = self.tables["chardata"]
        fields = tuple(table.column_index(name) for name in ("ani name", "AS file", "Parts file"))
        global_stems = {
            suffix: {stem for _, kind, stem in self.index if kind == suffix}
            for suffix in (".ba", ".as", ".info")
        }
        name_matches = Counter()
        candidates = []
        unique_triples = set()
        rows_with_candidate = set()
        rows_with_matched_counts = set()
        matched_candidates = 0
        for row_number, row in enumerate(table.rows):
            names = tuple(
                _table_stem(row.values[index], suffix)
                for index, suffix in zip(fields, (".ba", ".as", ".info"), strict=True)
            )
            for name, suffix in zip(names, (".ba", ".as", ".info"), strict=True):
                if name is not None:
                    name_matches[suffix + "_nonempty"] += 1
                    name_matches[suffix + "_any_family_match"] += name in global_stems[suffix]
            if any(name is None for name in names):
                continue
            for family in families:
                matches = [
                    self.index.get((family, suffix, name), [])
                    for name, suffix in zip(names, (".ba", ".as", ".info"), strict=True)
                ]
                if not all(len(group) == 1 for group in matches):
                    continue
                ba, signal, state = (group[0] for group in matches)
                layout = self.ba.get(ba.member_sha256)
                slayout = self.signals.get(signal.member_sha256)
                ilayout = self.states.get(state.member_sha256)
                if layout is None or slayout is None or ilayout is None:
                    continue
                candidates.append((ba, signal, state))
                rows_with_candidate.add(row_number)
                if len(layout.frame_counts) == len(slayout.groups) == len(ilayout.rows):
                    matched_candidates += 1
                    rows_with_matched_counts.add(row_number)
                    unique_triples.add((ba.member_sha256, signal.member_sha256, state.member_sha256))

        candidates.sort(key=lambda triple: tuple(
            (item.archive_sha256, item.index, item.member_sha256) for item in triple
        ))
        fingerprint = _fingerprint([
            [[item.archive_sha256, item.index, item.member_sha256] for item in triple]
            for triple in candidates
        ])
        timing = Counter()
        out_of_bounds_kinds = Counter()
        matching_types = Counter()
        for ba_hash, signal_hash, state_hash in sorted(unique_triples):
            ba = self.ba[ba_hash]
            signal = self.signals[signal_hash]
            state = self.states[state_hash]
            assert ba is not None and signal is not None and state is not None
            timing["groups"] += len(signal.groups)
            for index, group in enumerate(signal.groups):
                matching_types[state.rows[index].type_id] += 1
                frame_count = ba.frame_counts[index]
                timing["groups_with_out_of_bounds_records"] += any(
                    record.time >= frame_count for record in group
                )
                for record in group:
                    timing["records"] += 1
                    timing["within_frame_count"] += record.time < frame_count
                    timing["equal_frame_count"] += record.time == frame_count
                    timing["beyond_frame_count"] += record.time > frame_count
                    timing["at_last_frame"] += record.time == frame_count - 1
                    timing["at_zero"] += record.time == 0
                    if record.time >= frame_count:
                        out_of_bounds_kinds[record.kind] += 1
        return {
            "table_reference_counts": dict(sorted(name_matches.items())),
            "same_family_unique_name_candidates": len(candidates),
            "chardata_rows_with_candidate": len(rows_with_candidate),
            "candidate_identity_fingerprint": fingerprint,
            "count_matched_candidates": matched_candidates,
            "chardata_rows_with_count_match": len(rows_with_matched_counts),
            "unique_count_matched_triples": len(unique_triples),
            "matched_ba_payloads": len({triple[0] for triple in unique_triples}),
            "matched_as_payloads": len({triple[1] for triple in unique_triples}),
            "matched_info_payloads": len({triple[2] for triple in unique_triples}),
            "matched_payload_triples_fingerprint": _fingerprint(unique_triples),
            "candidate_same_index_time_comparison": dict(sorted(timing.items())),
            "candidate_out_of_bounds_record_kinds": _histogram(out_of_bounds_kinds),
            "candidate_info_type_counts": _histogram(matching_types),
        }

    def report(self, families: set[str], vocabularies: dict,
               schema_word_counts: dict[int, int] | None = None) -> dict:
        signal_records = [record for signal in self.signals.values() if signal is not None
                          for group in signal.groups for record in group]
        valid_signals = [signal for signal in self.signals.values() if signal is not None]
        valid_states = [state for state in self.states.values() if state is not None]
        kinds = Counter(record.kind for record in signal_records)
        words = Counter(record.words for record in signal_records)
        bounded_values = Counter(record.bounded_value for record in signal_records)
        state_types = Counter(row.type_id for state in valid_states for row in state.rows)
        state_attributes = Counter(row.attribute for state in valid_states for row in state.rows)
        state_indices = Counter(
            "negative" if row.index < 0 else "zero" if row.index == 0 else "positive"
            for state in valid_states for row in state.rows
        )
        tails = []
        for digest, (tail, classification) in sorted(self.tails.items()):
            if classification == "trailing":
                tails.append({**tail, "occurrences": self.ba_occurrences[digest]})
        script_summary = {}
        for kind in sorted({kind for kind, _ in self.scripts}):
            hits = [value for (key, _), value in self.scripts.items() if key == kind]
            script_summary[kind] = {
                "occurrences": self.script_occurrences[kind],
                "unique_payloads": len(hits),
                "substring_hit_resources": {
                    term.decode("ascii"): sum(bool(item.get(term.decode("ascii"), 0)) for item in hits)
                    for term in _SCRIPT_TERMS
                },
                "substring_hits": {
                    term.decode("ascii"): sum(item.get(term.decode("ascii"), 0) for item in hits)
                    for term in _SCRIPT_TERMS
                },
            }
        tables = {}
        for key in ("chardata", "itemtable"):
            table = self.tables[key]
            tables[key] = {
                "sha256": table.sha256,
                "rows": len(table.rows),
                "columns": len(table.columns),
                "signal_clip_event_named_columns": sum(
                    bool(re.search(r"signal|clip|event", column.name, re.IGNORECASE))
                    for column in table.columns
                ),
            }
        result = {
            "schema": "n3.signal-clip-research",
            "version": 1,
            "packages": dict(sorted(self.packages.items())),
            "package_member_occurrences": {
                f"{role}:{suffix}": count
                for (role, suffix), count in sorted(self.occurrences.items())
            },
            "unique_parse_failures": dict(sorted(self.failures.items())),
            "ba": {
                "unique_payloads": len(self.ba),
                "unique_structural_tails": len(self.tails),
                "tail_classifications": _histogram(Counter(
                    classification for _, classification in self.tails.values()
                )),
                "confirmed_trailing_fingerprint": _fingerprint(tails),
                "confirmed_trailing_occurrences": sum(tail["occurrences"] for tail in tails),
                "confirmed_trailing_length_min": min((tail["length"] for tail in tails), default=None),
                "confirmed_trailing_length_max": max((tail["length"] for tail in tails), default=None),
                "confirmed_trailing_offset_min": min((tail["offset"] for tail in tails), default=None),
                "confirmed_trailing_offset_max": max((tail["offset"] for tail in tails), default=None),
                "confirmed_trailing_profiles": tails,
            },
            "as": {
                "unique_payloads": len(self.signals),
                "bounded_profiles": len(valid_signals),
                "groups": sum(len(signal.groups) for signal in valid_signals),
                "empty_groups": sum(signal.empty_groups for signal in valid_signals),
                "sentinel_groups": sum(signal.sentinel_groups for signal in valid_signals),
                "declared_records": sum(signal.declared_records for signal in valid_signals),
                "discarded_records": sum(signal.discarded_records for signal in valid_signals),
                "retained_records": len(signal_records),
                "record_kinds": _histogram(kinds),
                "payload_word_counts": _histogram(words),
                "bounded_value_counts": _histogram(bounded_values),
                "time_min": min((record.time for record in signal_records), default=None),
                "time_max": max((record.time for record in signal_records), default=None),
                "record_offset_min": min((record.offset for record in signal_records), default=None),
                "record_end_max": max((record.offset + 28 + 4 * record.words
                                       for record in signal_records), default=None),
                "following_64_byte_blocks": sum(signal.list64_count for signal in valid_signals),
                "following_first_array_words": sum(signal.array_counts[0] for signal in valid_signals),
                "following_second_array_words": sum(signal.array_counts[1] for signal in valid_signals),
            },
            "info": {
                "unique_payloads": len(self.states),
                "bounded_profiles": len(valid_states),
                "rows": sum(len(state.rows) for state in valid_states),
                "runtime_type_counts": _histogram(state_types),
                "attribute_counts": _histogram(state_attributes),
                "index_categories": _histogram(state_indices),
                "profiles_with_unparsed_suffix": sum(state.rows_end < state.size for state in valid_states),
                "suffix_length_min": min((state.size - state.rows_end for state in valid_states),
                                         default=None),
                "suffix_length_max": max((state.size - state.rows_end for state in valid_states),
                                         default=None),
                "suffix_count_histogram": _histogram(Counter(
                    state.suffix_count for state in valid_states if state.suffix_count is not None
                )),
                "profiles_without_suffix_count": sum(
                    state.suffix_count is None for state in valid_states
                ),
            },
            "tables": tables,
            "scripts": script_summary,
            "vocabularies": vocabularies,
            "correlation": self._association(families),
        }
        if schema_word_counts is not None:
            comparison = Counter()
            for record in signal_records:
                if record.kind not in schema_word_counts:
                    comparison["kind_without_unique_schema_count"] += 1
                elif record.words == schema_word_counts[record.kind]:
                    comparison["same_number_equal_word_count"] += 1
                else:
                    comparison["same_number_different_word_count"] += 1
            result["as"]["schema_numeric_length_comparison"] = {
                name: comparison[name] for name in (
                    "same_number_equal_word_count", "same_number_different_word_count",
                    "kind_without_unique_schema_count",
                )
            }
        return result


def _package_role(name: str) -> tuple[str, str]:
    lower = name.casefold()
    for suffix, role in (("_char_res.pak", "character"),
                         ("_res2_res.pak", "resource2"),
                         ("_res3_res.pak", "resource3")):
        if lower.endswith(suffix):
            return role, lower[:-len(suffix)]
    return ("initial", "") if lower == "res_init.pak" else ("other", "")


def _regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse = getattr(info, "st_file_attributes", 0) & 0x400
    return not path.is_symlink() and not reparse and path.is_file()


def _archive_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def summarize_runtime_trace(path: Path) -> dict:
    """Validate an existing trace and expose only its identity and counts."""
    try:
        from .animation_trace_manifest import read_trace
    except ImportError:
        from animation_trace_manifest import read_trace
    if not _regular_file(path):
        raise ResearchError("unsupported runtime trace")
    raw, trace = read_trace(path)
    identity = trace["identity"]
    return {
        "sha256": _hash(raw),
        "scope": trace["filter"]["scope"],
        "actor_bound": identity["actor"] != "0x00000000",
        "signal_bound": identity["signal"] != "0x00000000",
        "info_bound": identity["info"] != "0x00000000",
        "ba_identity": identity["ba"],
        "setup_calls": trace["counts"]["setup_calls"],
        "controller_calls": trace["counts"]["controller_calls"],
        "controller_samples": len(trace["controller"]),
        "queue_clip_counts": _histogram(Counter(sample["clip"] for sample in trace["queue"])),
        "evaluation_clip_counts": _histogram(
            Counter(sample["clip"] for sample in trace["evaluation"])
        ),
    }


def analyze_corpus(game_root: Path, addon_root: Path | None, *, all_packages: bool) -> dict:
    data_root = game_root / "data"
    packed = data_root / "PackedResources"
    if not packed.is_dir() or packed.is_symlink():
        raise ResearchError("missing corpus")
    files = sorted((path for path in packed.iterdir()
                    if path.suffix.casefold() == ".pak" and _regular_file(path)),
                   key=lambda path: path.name.casefold())
    if not files or len(files) > MAX_PACKAGES:
        raise ResearchError("unsupported package count")
    study = Research(_addon_classifier(addon_root) if addon_root is not None else None)
    families: dict[str, set[str]] = defaultdict(set)
    for path in files:
        role, family = _package_role(path.name)
        if role == "other" and not all_packages:
            continue
        try:
            archive = read_pak(path)
        except (GameplayDataError, OSError):
            if role != "other":
                raise ResearchError("required package unavailable")
            study.packages["other_unreadable"] += 1
            continue
        archive_hash = _archive_hash(path) if role in ("character", "resource2") else ""
        study.add_archive(role, family, archive, archive_hash)
        if family and role in ("character", "resource2"):
            families[family].add(role)
    for role in ("character", "resource2", "resource3", "initial"):
        if not study.packages[role]:
            raise ResearchError("missing required package category")

    ai_root = data_root / "AI"
    if ai_root.is_dir() and not ai_root.is_symlink():
        scripts = sorted((path for path in ai_root.rglob("*")
                          if path.suffix.casefold() in (".aib", ".ai_funcb", ".n3sb")
                          and _regular_file(path)), key=lambda path: str(path).casefold())
        if len(scripts) > MAX_LOOSE_SCRIPTS:
            raise ResearchError("unsupported loose script count")
        for path in scripts:
            if path.stat().st_size > MAX_SCRIPT_SIZE:
                study.failures["script"] += 1
                continue
            study.add_script("loose:" + path.suffix.casefold(), path.read_bytes())

    vocabulary_files = ("animtype.h", "signaltype.h", "signalid.txt", "animid.txt")
    vocabulary_data = []
    for name in vocabulary_files:
        path = data_root / name
        if not _regular_file(path) or path.stat().st_size > MAX_SCRIPT_SIZE:
            raise ResearchError("missing vocabulary")
        vocabulary_data.append(path.read_bytes())
    vocabularies, schema_word_counts = vocabulary_summary(*vocabulary_data)
    paired = {family for family, roles in families.items()
              if roles == {"character", "resource2"}}
    if not paired:
        raise ResearchError("missing package pairs")
    return study.report(paired, vocabularies, schema_word_counts)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ResearchError("invalid arguments")


def main(argv=None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--addon-root", type=Path)
    parser.add_argument("--all-packages", action="store_true")
    parser.add_argument("--trace", type=Path, help="optional existing bounded runtime trace")
    try:
        args = parser.parse_args(argv)
        result = analyze_corpus(args.game_root, args.addon_root, all_packages=args.all_packages)
        if args.trace is not None:
            result["runtime_trace"] = summarize_runtime_trace(args.trace)
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        return 0
    except Exception:  # noqa: BLE001 -- never expose private paths from unexpected parser errors
        print("signal/clip research: input missing, malformed, or unsupported", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
