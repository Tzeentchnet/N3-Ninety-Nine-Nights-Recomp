"""Synthetic in-memory tests for the bounded signal/clip research helper."""

import io
import json
import struct
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

from tools import signal_clip_research as research


def make_ba(frames=(8,), bones=1, tail=b""):
    data = bytearray(struct.pack(">6I", 24, 0x244D, 12, len(frames), bones, 2))
    data.extend(struct.pack(f">{len(frames)}I", *frames))
    for _ in range(bones):
        data.extend(bytes(255 * 2 + 64 + 120))
        for _ in frames:
            data.extend(struct.pack(">4I", 2, 0, 0, 0))
    data.extend(tail)
    return bytes(data)


def make_signal(groups, *, list64=0, arrays=((), ())):
    data = bytearray(520)
    struct.pack_into(">II", data, 0, 101, len(groups))
    for group in groups:
        if isinstance(group, int):
            data.extend(struct.pack(">I", group))
            continue
        data.extend(struct.pack(">I", len(group)))
        table = len(data)
        data.extend(bytes(8 * len(group)))
        for index, (kind, time, channel, words) in enumerate(group):
            offset = len(data)
            struct.pack_into(">II", data, table + 8 * index, kind, offset)
            data.extend(struct.pack(">iiI", time, channel, len(words)))
            for word in words:
                data.extend(struct.pack(">I", word))
            data.extend(b"X" * 16)
    data.extend(struct.pack(">I", list64))
    data.extend(b"Y" * (64 * list64))
    for array in arrays:
        data.extend(struct.pack(">I", len(array)))
        data.extend(b"".join(struct.pack(">I", item) for item in array))
    return bytes(data)


def make_info(rows, *, suffix=b""):
    data = bytearray(524)
    struct.pack_into(">III", data, 0, 100, 0, len(rows))
    for type_id, index, attribute in rows:
        data.extend(struct.pack(">7i", type_id, index, 0, 0, 0, 0, attribute))
        data.extend(bytes(58))
    data.extend(suffix)
    return bytes(data)


class Table:
    def __init__(self, names, values):
        self.columns = tuple(SimpleNamespace(name=name) for name in names)
        self.rows = tuple(SimpleNamespace(values=row) for row in values)
        self.sha256 = "a" * 64

    def column_index(self, name):
        return next(index for index, column in enumerate(self.columns) if column.name == name)


class Archive:
    def __init__(self, members):
        self.members = tuple(
            SimpleNamespace(index=index, name=name, payload=payload)
            for index, (name, payload) in enumerate(members)
        )

    def read_member(self, member):
        return member.payload


def make_study(*, duplicate_signal=False, info_rows=1):
    study = research.Research(lambda _: "trailing")
    ba = make_ba(tail=b"private-synthetic-tail")
    signal = make_signal([[(3, 7, 0, (12345,)), (39, 8, 1, ()), (95, 9, 2, (88,))]])
    info = make_info([(9, 2, 1)] * info_rows, suffix=struct.pack(">I", 2) + b"uninterpreted")
    study.add_archive("character", "private-family", Archive([
        ("private-member.ba", ba),
    ]), "b" * 64)
    members = [("private-signal.as", signal), ("private-info.info", info)]
    if duplicate_signal:
        members.append(("private-signal.as", signal))
    study.add_archive("resource2", "private-family", Archive(members), "c" * 64)
    study.tables["chardata"] = Table(
        ("ani name", "AS file", "Parts file"),
        ((b"private-member", b"private-signal", b"private-info"),
         (b"private-member", b"private-signal", b"private-info")),
    )
    study.tables["itemtable"] = Table(("ItemName", "ParamType1"), ((b"private-item", 123),))
    study.add_script(".aib", b"private-script signal signal event")
    return study


class BaLayoutTests(unittest.TestCase):
    def test_tail_is_only_an_offset_length_and_hash(self):
        data = make_ba((8, 12), bones=2, tail=b"uninterpreted")
        layout = research.ba_layout(data)
        self.assertEqual(layout.frame_counts, (8, 12))
        self.assertEqual(layout.bones, 2)
        self.assertEqual(layout.end, len(data) - len(b"uninterpreted"))
        self.assertEqual(research.ba_tail(data, layout), {
            "member_sha256": sha256(data).hexdigest(),
            "member_size": len(data),
            "offset": layout.end,
            "length": len(b"uninterpreted"),
            "tail_sha256": sha256(b"uninterpreted").hexdigest(),
        })
        self.assertIsNone(research.ba_tail(data[:layout.end], layout))

    def test_rejects_bad_headers_dimensions_tracks_and_truncations(self):
        valid = make_ba()
        cases = [b"", valid[:-1], struct.pack("<6I", 24, 0x244D, 12, 1, 1, 2) + valid[24:]]
        for offset, value in ((12, 0), (12, research.MAX_CLIPS + 1),
                              (16, 0), (20, 1), (24, 0)):
            data = bytearray(valid)
            struct.pack_into(">I", data, offset, value)
            cases.append(bytes(data))
        data = bytearray(valid)
        struct.pack_into(">I", data, 24 + 4 + 694, 1)
        cases.append(bytes(data))
        data = bytearray(valid)
        struct.pack_into(">I", data, 24 + 4 + 694 + 4, research.MAX_KEYS + 1)
        cases.append(bytes(data))
        for data in cases:
            with self.subTest(length=len(data)), self.assertRaises(research.ResearchError):
                research.ba_layout(data)

    def test_extent_validation_does_not_read_unknown_tail(self):
        data = make_ba(tail=b"synthetic-payload")
        layout = research.ba_layout(data)
        changed = data[:layout.end] + b"another-payload!!"
        self.assertEqual(research.ba_layout(changed), layout)
        self.assertNotEqual(research.ba_tail(changed, layout)["tail_sha256"],
                            research.ba_tail(data, layout)["tail_sha256"])
        with self.assertRaises(research.ResearchError):
            research.ba_tail(data, research.BaLayout((1,), 1, len(data) + 1))


class SignalLayoutTests(unittest.TestCase):
    def test_bounded_layout_and_runtime_filters(self):
        data = make_signal([
            [(3, 2, 1, (42, 43)), (39, -1, 0, (1,)), (95, 5, 16, ())],
            0, 0x10000,
        ], list64=2, arrays=((9, 10), (11,)))
        layout = research.signal_layout(data)
        self.assertEqual((len(layout.groups), layout.declared_records), (3, 3))
        self.assertEqual((layout.discarded_records, layout.empty_groups, layout.sentinel_groups),
                         (2, 2, 1))
        self.assertEqual((layout.list64_count, layout.array_counts, layout.end),
                         (2, (2, 1), len(data)))
        record = layout.groups[0][0]
        self.assertEqual((record.kind, record.time, record.bounded_value, record.words), (3, 2, 1, 2))
        self.assertNotIn("42", repr(record))
        self.assertNotIn("43", repr(record))

    def test_payload_and_unknown_footer_values_are_not_interpreted(self):
        left = make_signal([[(4, 7, 0, (0x12345678,))]])
        right = make_signal([[(4, 7, 0, (0x98765432,))]])
        self.assertEqual(research.signal_layout(left), research.signal_layout(right))
        self.assertNotIn("305419896", repr(research.signal_layout(left)))

    def test_rejects_unbounded_or_noncontiguous_extents(self):
        valid = make_signal([[(3, 5, 1, (42,)), (4, 8, 0, ())]])
        cases = [b"", valid[:-1], valid + b"X"]
        for offset, value in ((0, 0x65000000), (4, research.MAX_CLIPS + 1),
                              (520, research.MAX_RECORDS + 1),
                              (528, 0), (536, 0)):
            data = bytearray(valid)
            struct.pack_into(">I", data, offset, value)
            cases.append(bytes(data))
        offset = struct.unpack_from(">I", valid, 528)[0]
        data = bytearray(valid)
        struct.pack_into(">I", data, offset + 8, 0xFFFFFFFF)
        cases.append(bytes(data))
        layout = research.signal_layout(valid)
        for field in (layout.records_end, layout.records_end + 4):
            data = bytearray(valid)
            struct.pack_into(">I", data, field, 0xFFFFFFFF)
            cases.append(bytes(data))
        for data in cases:
            with self.subTest(length=len(data)), self.assertRaises(research.ResearchError):
                research.signal_layout(data)


class StateLayoutTests(unittest.TestCase):
    def test_reads_type_index_attribute_and_suffix_count_without_suffix_records(self):
        data = make_info([(9, 2, 7), (26, -1, -3)], suffix=struct.pack(">I", 2) + b"opaque")
        layout = research.state_layout(data)
        self.assertEqual(layout.rows, (research.StateRow(9, 2, 7), research.StateRow(26, -1, -3)))
        self.assertEqual((layout.rows_end, layout.size), (len(data) - 10, len(data)))
        self.assertEqual(layout.suffix_count, 2)
        self.assertIsNone(research.state_layout(make_info([])).suffix_count)

    def test_rejects_wrong_byte_order_and_invalid_rows(self):
        valid = make_info([(1, 0, 0)])
        cases = [b"", valid[:-1]]
        for offset, value in ((0, 0x64000000), (8, research.MAX_CLIPS + 1)):
            data = bytearray(valid)
            struct.pack_into(">I", data, offset, value)
            cases.append(bytes(data))
        for data in cases:
            with self.subTest(length=len(data)), self.assertRaises(research.ResearchError):
                research.state_layout(data)


class AggregateTests(unittest.TestCase):
    def test_addon_import_is_bytecode_silent_and_restores_the_caller_setting(self):
        seen = []

        def fake_import(name):
            seen.append(sys.dont_write_bytecode)
            if name.endswith(".animation"):
                return SimpleNamespace(parse_character_ba=lambda *args, **kwargs: None)
            return SimpleNamespace(N3FormatError=ValueError, BA_TRAILING_DATA="trailing")

        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(research.importlib, "import_module", side_effect=fake_import), \
             mock.patch.object(sys, "path", list(sys.path)), \
             mock.patch.object(sys, "dont_write_bytecode", False):
            original_path = sys.path[:]
            classify = research._addon_classifier(Path("synthetic-add-on"))
            self.assertEqual(classify(b"synthetic"), "accepted")
            self.assertFalse(sys.dont_write_bytecode)
            self.assertEqual(sys.path, original_path)
        self.assertEqual(seen, [True, True])
        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(research.importlib, "import_module", side_effect=RuntimeError), \
             mock.patch.object(sys, "path", list(sys.path)), \
             mock.patch.object(sys, "dont_write_bytecode", False):
            original_path = sys.path[:]
            with self.assertRaises(RuntimeError):
                research._addon_classifier(Path("synthetic-add-on"))
            self.assertFalse(sys.dont_write_bytecode)
            self.assertEqual(sys.path, original_path)

    def test_same_family_candidates_and_time_comparison_are_not_proven_linkage(self):
        study = make_study()
        report = study.report({"private-family"}, {}, {3: 1, 39: 2})
        self.assertEqual(report["ba"]["tail_classifications"], {"trailing": 1})
        self.assertEqual(report["ba"]["confirmed_trailing_profiles"][0]["occurrences"], 1)
        correlation = report["correlation"]
        self.assertEqual(correlation["same_family_unique_name_candidates"], 2)
        self.assertEqual(correlation["chardata_rows_with_candidate"], 2)
        self.assertEqual(correlation["unique_count_matched_triples"], 1)
        self.assertEqual(correlation["candidate_same_index_time_comparison"], {
            "at_last_frame": 1, "at_zero": 0, "beyond_frame_count": 1,
            "equal_frame_count": 1, "groups": 1, "groups_with_out_of_bounds_records": 1,
            "records": 3,
            "within_frame_count": 1,
        })
        self.assertEqual(correlation["candidate_out_of_bounds_record_kinds"], {"39": 1, "95": 1})
        self.assertEqual(report["as"]["record_kinds"], {"3": 1, "39": 1, "95": 1})
        self.assertEqual(report["as"]["record_offset_min"], 548)
        self.assertEqual(report["as"]["record_end_max"], 640)
        self.assertEqual(report["as"]["schema_numeric_length_comparison"], {
            "same_number_equal_word_count": 1,
            "same_number_different_word_count": 1,
            "kind_without_unique_schema_count": 1,
        })
        self.assertEqual(report["info"]["runtime_type_counts"], {"9": 1})
        self.assertEqual(report["info"]["attribute_counts"], {"1": 1})
        self.assertEqual(report["info"]["index_categories"], {"positive": 1})
        self.assertEqual(report["info"]["suffix_count_histogram"], {"2": 1})
        self.assertEqual(report["info"]["profiles_without_suffix_count"], 0)
        self.assertEqual(correlation["count_matched_candidates"], 2)
        self.assertEqual(correlation["matched_ba_payloads"], 1)
        self.assertEqual(report["scripts"][".aib"]["substring_hit_resources"]["signal"], 1)
        self.assertEqual(report["scripts"][".aib"]["substring_hits"]["signal"], 2)
        output = json.dumps(report)
        for secret in ("private-family", "private-member", "private-signal",
                       "private-info", "private-script", "private-item", "12345"):
            self.assertNotIn(secret, output)

    def test_ambiguous_names_and_mismatched_counts_never_become_matched_triples(self):
        ambiguous = make_study(duplicate_signal=True).report({"private-family"}, {})
        self.assertEqual(ambiguous["correlation"]["same_family_unique_name_candidates"], 0)
        self.assertEqual(ambiguous["correlation"]["unique_count_matched_triples"], 0)
        mismatched = make_study(info_rows=2).report({"private-family"}, {})
        self.assertEqual(mismatched["correlation"]["same_family_unique_name_candidates"], 2)
        self.assertEqual(mismatched["correlation"]["unique_count_matched_triples"], 0)

    def test_unconfirmed_tails_are_never_reported_as_confirmed(self):
        study = make_study()
        digest = next(iter(study.tails))
        tail, _ = study.tails[digest]
        study.tails[digest] = tail, "unverified"
        report = study.report({"private-family"}, {})
        self.assertEqual(report["ba"]["tail_classifications"], {"unverified": 1})
        self.assertEqual(report["ba"]["confirmed_trailing_profiles"], [])

    def test_fingerprint_is_deterministic_and_preserves_multiplicity(self):
        self.assertEqual(research._fingerprint([1, 2]), research._fingerprint([2, 1]))
        self.assertNotEqual(research._fingerprint([1, 2]), research._fingerprint([1, 2, 2]))

    def test_scans_archived_script_and_generic_binary_without_retaining_bytes(self):
        study = research.Research()
        study.add_archive("other", "", Archive([
            ("secret.n3sb", b"secret signal"),
            ("secret.bin", b"secret event"),
        ]), "")
        self.assertEqual(study.script_occurrences[".n3sb"], 1)
        self.assertEqual(study.script_occurrences[".bin"], 1)
        self.assertEqual(sum(hits["signal"] for hits in study.scripts.values()), 1)
        self.assertEqual(sum(hits["event"] for hits in study.scripts.values()), 1)
        self.assertNotIn("secret", repr(study.scripts))

    def test_synthetic_schema_numeric_domains_stay_separate(self):
        animations = b"#define A 0\n#define B 26\n#define LAST 27\n#define FLAG 0x100 // flag\n"
        signals = b"#define TYPE_ZERO 0\n#define TYPE_LAST 41\n"
        blocks = (b'"name" TYPE_ZERO\n"label"\n0 0 0\n0 0 0\n2\none\ntwo\n'
                  b'"other" TYPE_LAST\n"label"\n0 0 0\n0 0 0\n0\n')
        author_ids = b'"none" -1\n"stand" 0\n'
        summary, expected = research.vocabulary_summary(animations, signals, blocks, author_ids)
        self.assertEqual(summary["animtype"]["unique_numeric_values"], 4)
        self.assertEqual(summary["animtype"]["runtime_type_values_0_to_26"], 2)
        self.assertEqual(summary["signaltype"]["unique_kind_ids"], 2)
        self.assertEqual(summary["signalid"], {
            "blocks": 2, "resolved_header_symbols": 2, "unresolved_header_symbols": 0,
            "unique_resolved_kind_ids": 2, "parameter_slots_declared": 2,
            "kind_ids_with_ambiguous_slot_counts": 0,
        })
        self.assertEqual(expected, {0: 2, 41: 0})
        self.assertEqual(summary["animid"], {
            "unique_authoring_ids": 2, "minimum": -1, "maximum": 0,
        })
        # A standalone "2" above is a parameter count, not a kind ID.
        self.assertNotEqual(summary["signalid"]["parameter_slots_declared"],
                            summary["signaltype"]["maximum"])
        with self.assertRaises(research.ResearchError):
            research.vocabulary_summary(animations, signals,
                                        blocks.replace(b"\n2\none", b"\n999\none"), author_ids)
        unresolved, unresolved_expected = research.vocabulary_summary(
            animations, signals, blocks.replace(b"TYPE_LAST", b"TYPE_UNKNOWN"), author_ids,
        )
        self.assertEqual(unresolved["signalid"]["unresolved_header_symbols"], 1)
        self.assertEqual(unresolved_expected, {0: 2})
        duplicate_id = b"#define TYPE_ZERO 0\n#define TYPE_LAST 0\n"
        ambiguous, ambiguous_expected = research.vocabulary_summary(
            animations, duplicate_id, blocks, author_ids,
        )
        self.assertEqual(ambiguous["signalid"]["kind_ids_with_ambiguous_slot_counts"], 1)
        self.assertEqual(ambiguous_expected, {})

    def test_cli_errors_do_not_disclose_paths_or_exception_text(self):
        for argv in (["--game-root", "PRIVATE_PATH"], ["--bad-PRIVATE_PATH"]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(research, "analyze_corpus",
                                   side_effect=ValueError("PRIVATE_EXCEPTION")), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(research.main(argv), 2)
            self.assertNotIn("PRIVATE", stdout.getvalue() + stderr.getvalue())

    def test_existing_trace_is_validated_and_only_counts_are_returned(self):
        source = {
            "filter": {"scope": "resource"},
            "identity": {
                "actor": "0x00000000", "signal": "0x00000000",
                "info": "0x00000000", "ba": "0x00007000",
            },
            "counts": {"setup_calls": 0, "controller_calls": 0},
            "controller": [], "queue": [{"clip": 2}, {"clip": 2}],
            "evaluation": [{"clip": 2}],
        }
        path = mock.Mock()
        path.stat.return_value.st_size = 24
        path.read_bytes.return_value = b"private synthetic trace"
        manifest = ModuleType("tools.animation_trace_manifest")
        manifest.read_trace = mock.Mock(return_value=(b"private synthetic trace", source))
        with mock.patch.object(research, "_regular_file", return_value=True), \
             mock.patch.dict(sys.modules, {"tools.animation_trace_manifest": manifest}):
            result = research.summarize_runtime_trace(path)
        manifest.read_trace.assert_called_once_with(path)
        self.assertFalse(result["actor_bound"])
        self.assertFalse(result["signal_bound"])
        self.assertFalse(result["info_bound"])
        self.assertEqual(result["queue_clip_counts"], {"2": 2})
        self.assertEqual(result["evaluation_clip_counts"], {"2": 1})
        self.assertNotIn("private synthetic", json.dumps(result))

    def test_invalid_runtime_trace_is_not_silently_accepted(self):
        path = mock.Mock()
        path.stat.return_value.st_size = 24
        path.read_bytes.return_value = b"invalid"
        manifest = ModuleType("tools.animation_trace_manifest")
        manifest.read_trace = mock.Mock(side_effect=ValueError("private data"))
        with mock.patch.object(research, "_regular_file", return_value=True), \
             mock.patch.dict(sys.modules, {"tools.animation_trace_manifest": manifest}), \
             self.assertRaises(ValueError):
            research.summarize_runtime_trace(path)


if __name__ == "__main__":
    unittest.main()
