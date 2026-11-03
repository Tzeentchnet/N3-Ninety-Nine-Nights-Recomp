import copy
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

from tools import animation_trace_manifest as manifest
from tools import signal_clip_research as research


def fixture():
    counts = dict.fromkeys(manifest.COUNTERS, 0)
    counts.update(setup_calls=1, setup_accepted=1, controller_calls=1,
                  queue_calls=1, evaluation_calls=1, pose_outputs=2)
    name_hash, length = manifest.fingerprint("SYNTHETIC.BA")
    return {
        "schema": "n3.runtime-animation-trace", "version": 2,
        "sources": dict(manifest.SOURCES),
        "filter": {"scope": "actor", "actor": "first", "clip": "all"},
        "selected": True, "stop_reason": "shutdown",
        "identity": {
            "actor": "0x00004000", "actor_vtable": "0x82040170",
            "manager": "0x00010000", "instance_handle": 10,
            "instance": "0x00006000", "ba": "0x00007000", "ba_handle": 5,
            "signal": "0x00008000", "info": "0x00009000",
            "setup_signal_index": 0, "setup_info_index": 0,
            "clips": 4, "bones": 3, "signal_groups": 4, "info_rows": 4,
            "name_length": length, "name_fnv1a64": name_hash,
        },
        "counts": counts,
        "controller": [{"caller": "0x82094b60", "before_clip": 2, "after_clip": 2,
                        "before_time": 3, "after_time": 4, "step": 1}],
        "queue": [{"caller": "0x820802d0", "clip": 2, "frame": 3}],
        "evaluation": [{"caller": "0x8229ea94", "clip": 2, "time": 3,
                        "queue_count": 1, "pose_outputs": 2, "invalid_outputs": 0}],
    }


def fixture_v3():
    trace = fixture()
    trace.update(version=3, sources=dict(manifest.SOURCES_V3),
                 clock={"kind": "performance_counter", "frequency": 10_000_000})
    trace["identity"].update(
        actor_generation=4, instance_generation=3, ba_generation=2,
        source={"status": "unavailable", "archive_generation": 0, "archive_slot": None,
                "archive_content_sha256": None, "member_sha256": None,
                "member_index": None, "archive_size": 0, "member_size": 0},
    )
    trace["counts"].update(dict.fromkeys(manifest.COUNTERS_V3 - manifest.COUNTERS, 0))
    trace["counts"]["events_started"] = 3
    trace["controller"][0].update(event_id=1, parent_event_id=0, begin_tick=10, end_tick=100)
    trace["queue"][0].update(event_id=2, parent_event_id=1, begin_tick=20, end_tick=90)
    trace["evaluation"][0].update(event_id=3, parent_event_id=2, begin_tick=30, end_tick=80)
    return trace


TEST_PROVENANCE = {
    "runtime_dll": "rexruntime.dll", "gpu_dll": "rexgpu-xenos.dll",
    "host_executable": "c" * 64, "host_runtime_library": "d" * 64,
    "host_gpu_plugin": "e" * 64,
}


def route_v4(rate=0):
    return {
        "schema": "n3.runtime-animation-route", "version": 4, "process_id": 123,
        "enabled": True, "trace_scope": "actor", "frame_rate_target": rate,
        "clock_mode": "original" if rate == 0 else "presentation_target",
        "audio_backend": "default", "maximum_seconds": 100, "elapsed_seconds": 99.5,
        "input_pairs_posted": 0, "foreground_observed": False, "foreground_requests": 0,
        "window_observed": True, "input_idle_observed": True, "close_requested": True,
        "forced_stop": False, "exit_code": 0, "capture_exists": True,
        "binary_provenance": dict(TEST_PROVENANCE),
    }


def route_hashes(**extra):
    return {"capture": "a" * 64, "route": "b" * 64,
            **{name: TEST_PROVENANCE[name] for name in
               ("host_executable", "host_runtime_library", "host_gpu_plugin")}, **extra}


def signal_sample(kind, event_id, **fields):
    return {"type": kind, "caller": "0x82000000", "event_id": event_id,
            "parent_event_id": 0, "begin_tick": event_id, "end_tick": event_id,
            **fields}


def signal_probe_fixture():
    identity = {"actor": "0x00001000", "actor_generation": 1,
                "instance": "0x00002000", "instance_generation": 2,
                "ba": "0x00003000", "ba_generation": 3,
                "signal": "0x00004000", "signal_generation": 4,
                "info": "0x00005000", "info_generation": 5, "identity_bound": True}
    samples = [
        signal_sample("setup", 1, **identity, actor_vtable="0x82040170", instance_handle=1,
                      ba_handle=1, signal_index=1, info_index=1, setup_key4=0, setup_key88=0),
        signal_sample("group", 2, **identity, group_read=True, group_index=0,
                      time_read=True, actor_time=0.0, actor_step_field=1.0),
        signal_sample("dispatch", 3, actor=identity["actor"], actor_generation=1,
                      signal_generation=4, dispatch_path=1, group_read=True, group_index=0,
                      record_read=True, retained_index=0, record_kind=24, record_time=2,
                      record_bounded=0, record_word_count=1, source_offset=True,
                      group_offset=520, table_offset=524, record_offset=532),
        signal_sample("effect", 4, actor=identity["actor"], actor_generation=1,
                      observer="actor_byte_1056_comparison", changed_slots=1),
    ]
    counts = {kind: {"seen": 0, "recorded": 0, "full": 0, "unreadable": 0,
                     "skipped": 0, "capacity": capacity}
              for kind, capacity in manifest.SIGNAL_CAPACITIES.items()}
    for sample in samples:
        counts[sample["type"]]["seen"] += 1
        counts[sample["type"]]["recorded"] += 1
    return {"counts": {"events_abandoned": 0, "events_inflight_at_flush": 0},
            "signal_probe": {"version": 1, "event_ids": "shared_trace_v3",
                             "capacity": sum(manifest.SIGNAL_CAPACITIES.values()),
                             "counts": counts, "samples": samples,
                             "losses": dict.fromkeys(("unresolved_sources", "record_map_full",
                                 "record_map_invalid", "actor_registry_full", "asset_registry_full"), 0)}}


def signal_trace_v3():
    trace = fixture_v3()
    probe = signal_probe_fixture()["signal_probe"]
    identity = {"actor": trace["identity"]["actor"], "actor_generation": 4,
                "instance": trace["identity"]["instance"], "instance_generation": 3,
                "ba": trace["identity"]["ba"], "ba_generation": 2,
                "signal": trace["identity"]["signal"], "signal_generation": 5,
                "info": trace["identity"]["info"], "info_generation": 6}
    for sample in probe["samples"]:
        sample["event_id"] += 3
        sample["begin_tick"] = sample["end_tick"] = sample["event_id"] * 100
        for field in identity.keys() & sample.keys():
            sample[field] = identity[field]
    request = signal_sample("request", 8, actor=identity["actor"], actor_generation=4,
                            info=identity["info"], info_generation=6, requested_type=7,
                            requested_index=3, requested_attribute=5)
    request.update(begin_tick=800, end_tick=850)
    selection = signal_sample("selection", 9, info=identity["info"], info_generation=6,
                              requested_type=7, requested_index=3, requested_attribute=5,
                              selected_row=0, row_read=True, row_type=7, row_index=3,
                              row_attribute=5)
    selection.update(parent_event_id=8, begin_tick=810, end_tick=820)
    for sample in (request, selection):
        probe["samples"].append(sample)
        probe["counts"][sample["type"]].update(seen=1, recorded=1)
    trace["signal_probe"] = probe
    trace["counts"]["events_started"] = 9
    return trace


def synthetic_pe(*imports, export_name=None):
    data = bytearray(0x800)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 240)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 108, 16)
    struct.pack_into("<II", data, optional + 120, 0x1000, (len(imports) + 1) * 20)
    section = optional + 240
    struct.pack_into("<IIII", data, section + 8, 0x400, 0x1000, 0x400, 0x400)
    cursor = 0x500
    for index, name in enumerate(imports):
        encoded = name.encode("ascii") + b"\0"
        data[cursor:cursor + len(encoded)] = encoded
        struct.pack_into("<I", data, 0x400 + index * 20 + 12, 0x1000 + cursor - 0x400)
        cursor += len(encoded)
    if export_name:
        struct.pack_into("<II", data, optional + 112, 0x1200, 0x80)
        struct.pack_into("<I", data, 0x600 + 12, 0x1250)
        encoded = export_name.encode("ascii") + b"\0"
        data[0x650:0x650 + len(encoded)] = encoded
    return bytes(data)


class TraceManifestTests(unittest.TestCase):
    def test_optional_private_probe_and_dispatch_are_sanitized(self):
        trace = fixture_v3()
        trace["counts"]["events_started"] = 4
        trace["counts"]["setup_calls"] = 3
        trace["dispatch"] = {
            "version": 1, "resource_hook": "0x8217ad08",
            "setup_wrapper_calls": dict.fromkeys(manifest.DISPATCH_WRAPPERS, 0),
            "resource_calls": 3, "flag_zero": 1, "handle_minus_one": 1,
            "eligible": 1, "unreadable": 0,
            "setup_rejections": {
                "scope_skipped": 0, "filter_mismatch": 0, "vtable_unreadable": 0,
                "vtable_unsupported": 2, "input_invalid": 0, "candidates": 1,
                "post_identity_failed": 0, "other_after_selection": 0, "repeat_selected": 0,
            },
            "setup_vtables": {
                "capacity": 16, "full": 0, "zero": 0, "getter_unreadable": 0,
                "entries": [{"vtable": "0xdeadbeef", "getter": "0xcafef00d", "calls": 2}],
            },
        }
        trace["quaternion_probe"] = {
            "version": 1, "helper": "0x8229ca98",
            "component_order": "guest_vmx_lanes_0_to_3",
            "capacity": 128, "per_evaluation_capacity": 8,
            "counts": {"seen": 1, "invalid_context": 0, "invalid_input": 0,
                       "invalid_output": 0, "per_evaluation_full": 0,
                       "total_full": 0, "parent_dropped": 0},
            "samples": [{
                "caller": "0x8229a214", "bone": 1, "factor": 0.25,
                "left": [1, 0, 0, 0], "right": [0, 1, 0, 0],
                "result": [0.75, 0.25, 0, 0], "event_id": 4,
                "parent_event_id": 3, "begin_tick": 40, "end_tick": 50,
            }],
        }
        route = route_v4()
        route["quaternion_probe"] = True
        report = manifest.aggregate(trace, route_hashes(),
                                    [], rate=0, seconds=100, route=route)
        self.assertEqual(report["quaternion_probe"]["sample_count"], 1)
        self.assertEqual(report["correlation"]["event_count"], 4)
        self.assertEqual(report["dispatch"]["setup_vtables"]["recorded_calls"], 2)
        self.assertNotIn("0xdeadbeef", json.dumps(report))
        self.assertNotIn('"left"', json.dumps(report))
        self.assertNotIn('"result"', json.dumps(report))
        legacy = fixture_v3()
        legacy["sources"] = dict(manifest.SOURCES_V3_LEGACY)
        self.assertEqual(manifest.validate_trace(legacy), legacy)
        for mutate in (
            lambda t: t["dispatch"].update(eligible=2),
            lambda t: t["dispatch"]["setup_vtables"].update(zero=1),
            lambda t: t["dispatch"]["setup_vtables"]["entries"].append(
                dict(t["dispatch"]["setup_vtables"]["entries"][0])),
            lambda t: t["quaternion_probe"]["counts"].update(seen=2),
            lambda t: t["quaternion_probe"]["samples"][0].update(parent_event_id=2),
            lambda t: t["quaternion_probe"]["samples"][0].update(end_tick=81),
        ):
            broken = copy.deepcopy(trace)
            mutate(broken)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                manifest.validate_trace(broken)
        with self.assertRaisesRegex(ValueError, "opt-in"):
            manifest.aggregate(trace, route_hashes(),
                               [], rate=0, seconds=100, route=route_v4())

    def test_v3_shared_events_source_and_original_route(self):
        trace = fixture_v3()
        member = SimpleNamespace(name="synthetic.ba", index=0, size=4)
        payload = b"synthetic-table-abcd"
        archive = SimpleNamespace(members=(member,), payload=payload,
                                  read_member=lambda _: payload[-4:])
        trace["identity"]["source"] = {
            "status": "resolved", "archive_generation": 1, "archive_slot": 2,
            "archive_content_sha256": hashlib.sha256(payload).hexdigest(),
            "member_sha256": hashlib.sha256(b"abcd").hexdigest(),
            "member_index": 0, "archive_size": len(payload), "member_size": 4,
        }
        raw = json.dumps(trace).encode()
        self.assertEqual(manifest.parse_trace(raw), trace)
        candidates = manifest.candidate_members(archive, "d" * 64, trace["identity"])
        self.assertEqual(candidates[0]["archive_content_sha256"], hashlib.sha256(payload).hexdigest())
        route = manifest.validate_route(json.dumps(route_v4()).encode(),
                                        rate=0, seconds=100, audio="default")
        report = manifest.aggregate(trace, route_hashes(),
                                    candidates, rate=0, seconds=100, route=route)
        self.assertEqual(report["asset_binding"], "resolver_observed_and_content_matched")
        self.assertEqual(report["identity"]["source"]["archive_slot"], 2)
        self.assertTrue(report["correlation"]["eligible"])
        self.assertEqual(report["correlation"]["clock"]["interpretation"],
                         "host_ticks_not_simulation_time")
        events = report["correlation"]["events"]
        self.assertEqual([event["event_id"] for event in events], [1, 2, 3])
        self.assertEqual((events[1]["stream"], events[1]["parent_event_id"],
                          events[1]["begin_tick"], events[1]["end_tick"]),
                         ("queue", 1, 20, 90))
        self.assertEqual(report["route"]["clock_mode"], "original")
        self.assertNotIn("synthetic.ba", json.dumps(report).lower())
        invalid_slot = copy.deepcopy(trace)
        invalid_slot["identity"]["source"]["archive_slot"] = 64
        with self.assertRaises(ValueError):
            manifest.validate_trace(invalid_slot)
        malformed = copy.deepcopy(candidates)
        malformed[0]["private_path"] = "synthetic-confidential-path"
        with self.assertRaises(ValueError):
            manifest.aggregate(trace, route_hashes(),
                               malformed, rate=0, seconds=100, route=route)
        with self.assertRaises(ValueError):
            manifest.aggregate(trace, route_hashes(private_path="c" * 64), candidates,
                               rate=0, seconds=100, route=route)
        failed_route = dict(route, forced_stop=True)
        with self.assertRaises(ValueError):
            manifest.aggregate(trace, route_hashes(),
                               candidates, rate=0, seconds=100, route=failed_route)
        empty = fixture_v3()
        empty["controller"], empty["queue"], empty["evaluation"] = [], [], []
        empty["counts"].update(events_started=0, pose_outputs=0)
        with self.assertRaisesRegex(ValueError, "no runtime"):
            manifest.aggregate(empty, route_hashes(),
                               [], rate=0, seconds=100, route=route)
        mismatch = copy.deepcopy(trace["identity"])
        mismatch["source"]["member_index"] = 1
        with self.assertRaisesRegex(ValueError, "resolver member"):
            manifest.candidate_members(archive, "d" * 64, mismatch)
        duplicate = SimpleNamespace(name="SYNTHETIC.BA", index=1, size=4)
        duplicate_archive = SimpleNamespace(members=(member, duplicate), payload=payload,
                                            read_member=lambda _: payload[-4:])
        mismatch["source"]["member_index"] = 1
        with self.assertRaisesRegex(ValueError, "first matching"):
            manifest.candidate_members(duplicate_archive, "d" * 64, mismatch)

    def test_cli_errors_do_not_expose_input_paths(self):
        private_name = "synthetic-confidential-path"
        missing = manifest.ROOT / "private" / private_name
        command = [
            sys.executable, str(manifest.ROOT / "tools" / "animation_trace_manifest.py"),
            "--trace", str(missing), "--route", str(missing), "--executable", str(missing),
            "--game-root", str(missing), "--output", str(missing), "--seconds", "100",
            "--frame-rate",
        ]
        for rate in ("0", str(missing)):
            result = subprocess.run(command + [rate], capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(private_name, result.stdout + result.stderr)

    def test_v3_malformed_identity_events_and_bounded_loss(self):
        mutations = (
            lambda t: t["identity"].update(actor_generation=2),
            lambda t: t["identity"]["source"].update(archive_size=1),
            lambda t: t["identity"]["source"].update(archive_slot=0),
            lambda t: t["clock"].update(frequency=0),
            lambda t: t["queue"][0].update(event_id=1),
            lambda t: t["evaluation"][0].update(begin_tick=19),
            lambda t: t["counts"].update(events_started=4),
            lambda t: t["counts"].update(queue_full=1),
            lambda t: t["counts"].update(counter_saturated=2),
            lambda t: t["counts"].update(events_started=1 << 64),
        )
        for mutate in mutations:
            trace = fixture_v3()
            mutate(trace)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                manifest.validate_trace(trace)
        trace = fixture_v3()
        trace["queue"] = []
        trace["counts"].update(events_abandoned=1, queue_full=1)
        manifest.validate_trace(trace)
        route = route_v4()
        report = manifest.aggregate(trace, route_hashes(),
                                    [], rate=0, seconds=100, route=route)
        self.assertFalse(report["correlation"]["eligible"])
        trace = fixture_v3()
        trace["controller"] = []
        trace["queue"][0].update(event_id=3, parent_event_id=1)
        trace["evaluation"][0].update(event_id=4, parent_event_id=2)
        trace["counts"].update(events_started=4, events_abandoned=2)
        manifest.validate_trace(trace)
        trace["counts"].update(events_started=3, events_abandoned=1)
        with self.assertRaises(ValueError):
            manifest.validate_trace(trace)
        route["clock_mode"] = "presentation_target"
        with self.assertRaisesRegex(ValueError, "clock mode"):
            manifest.validate_route(json.dumps(route).encode(), rate=0, seconds=100, audio="default")

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "PowerShell 7 required")
    def test_runner_validation_only_never_starts_or_creates_run(self):
        run_id = f"validateonly{os.getpid()}"
        run_dir = manifest.ROOT / "private" / "traces" / "runtime-instrumentation" / run_id
        self.assertFalse(run_dir.exists())
        command = [shutil.which("pwsh"), "-NoProfile", "-File",
                   str(manifest.ROOT / "tools" / "animation_trace_run.ps1"),
                   "-RunId", run_id, "-ValidateOnly"]
        for rate, expected in (("Original", 0), ("0", 0), ("30", 30), ("40", 40), ("60", 60)):
            result = subprocess.run(command + ["-FrameRate", rate], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            validated = json.loads(result.stdout)
            self.assertEqual(validated["frame_rate_target"], expected)
            self.assertEqual(validated["clock_mode"], "original" if expected == 0 else "presentation_target")
            self.assertFalse(run_dir.exists())
        result = subprocess.run(command + ["-Clip", "4096"], capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(run_dir.exists())

    def test_valid_deterministic_sanitized_aggregate(self):
        self.assertEqual(manifest.SOURCES["pose_return"], "0x8229ad64")
        source = fixture()
        raw = json.dumps(source, separators=(",", ":")).encode()
        validated = manifest.parse_trace(raw)
        hashes = {"capture": hashlib.sha256(raw).hexdigest(),
                  "host_executable": "a" * 64, "game_executable": "b" * 64}
        first = manifest.aggregate(validated, hashes, [], archives=["c" * 64],
                                   rate=30, seconds=100)
        second = manifest.aggregate(validated, hashes, [], archives=["c" * 64],
                                    rate=30, seconds=100)
        self.assertEqual(first, second)
        self.assertEqual(first["samples"]["evaluation"]["pose_outputs"], 2)
        self.assertEqual(first["samples"]["controller"]["times"],
                         {"minimum": 3, "maximum": 4})
        encoded = json.dumps(first)
        self.assertNotIn("SYNTHETIC.BA", encoded)
        self.assertNotIn("\\\\", encoded)
        self.assertEqual(first["asset_binding"], "unverified_candidates_are_not_resolver_proof")

    def test_name_fingerprint_and_candidate_are_structural_only(self):
        self.assertEqual(manifest.fingerprint("D:\\X\\HELLO"),
                         ("0xa430d84680aabd0b", 5))
        first = SimpleNamespace(name="folder\\synthetic.ba", index=2, size=4)
        second = SimpleNamespace(name="other.ba", index=3, size=3)
        archive = SimpleNamespace(members=(first, second),
                                  read_member=lambda member: b"abcd" if member is first else b"xxx")
        candidates = manifest.candidate_members(archive, "d" * 64, fixture()["identity"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["member_index"], 2)
        self.assertEqual(candidates[0]["member_sha256"], hashlib.sha256(b"abcd").hexdigest())
        self.assertNotIn("synthetic", json.dumps(candidates))

    def test_rejects_untrusted_schema_and_paths(self):
        for mutate in (
            lambda t: t.update(version=True),
            lambda t: t.update(host_path="C:\\private"),
            lambda t: t["sources"].update(controller="0xdeadbeef"),
            lambda t: t["controller"][0].update(caller="C:\\private"),
            lambda t: t["identity"].update(actor_vtable="0x12345678"),
            lambda t: t["counts"].update(invalid=-1),
            lambda t: t["counts"].update(pose_outputs=1),
            lambda t: t["counts"].update(inflight_at_flush=1),
            lambda t: t["counts"].update(invalid_outputs=1),
            lambda t: t["filter"].update(clip=3),
            lambda t: t["evaluation"][0].update(queue_count=6),
            lambda t: t["controller"][0].update(before_time=float("nan")),
            lambda t: t["controller"][0].update(before_time=10 ** 400),
            lambda t: t.update(selected=False),
        ):
            trace = copy.deepcopy(fixture())
            mutate(trace)
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                manifest.validate_trace(trace)

    def test_size_duplicate_and_sample_bounds(self):
        with self.assertRaises(ValueError):
            manifest.parse_trace(b" " * (192 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            manifest.parse_trace(b'{"schema":"x","schema":"y"}')
        trace = fixture()
        trace["controller"] *= 257
        trace["counts"]["controller_calls"] = 257
        with self.assertRaisesRegex(ValueError, "capacity"):
            manifest.validate_trace(trace)
        trace = fixture()
        trace["controller"] = []
        trace["queue"] = []
        trace["evaluation"] = []
        with self.assertRaisesRegex(ValueError, "no runtime"):
            manifest.validate_trace(trace)

    def test_candidate_member_size_limit(self):
        member = SimpleNamespace(name="synthetic.ba", index=1, size=32 * 1024 * 1024 + 1)
        archive = SimpleNamespace(members=(member,), read_member=lambda _: b"")
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            manifest.candidate_members(archive, "e" * 64, fixture()["identity"])

    def test_dummy_audio_requires_local_build_provenance(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            manifest.audio_provenance("dummy", None, None, None)
        with self.assertRaisesRegex(ValueError, "only accepted"):
            manifest.audio_provenance("default", Path("source"), Path("library"), None)
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(manifest, "sha256_file", side_effect=["a" * 64, "b" * 64, "c" * 64]):
            hashes = manifest.audio_provenance(
                "dummy", manifest.ROOT / "source", manifest.ROOT / "library", manifest.ROOT / "bundle")
        self.assertEqual(hashes, {"audio_source_archive": "a" * 64,
                                  "audio_linked_library": "b" * 64,
                                  "audio_sdk_source_bundle": "c" * 64})
        trace = fixture()
        hashes["capture"] = "c" * 64
        aggregate = manifest.aggregate(trace, hashes, [], rate=30, seconds=100, audio="dummy")
        self.assertIn("silent host sink", aggregate["limitations"][-1])

    def test_route_requires_bounded_graceful_observation(self):
        route = {
            "schema": "n3.runtime-animation-route", "version": 3, "process_id": 123,
            "enabled": True, "trace_scope": "actor", "frame_rate_target": 30, "audio_backend": "dummy",
            "maximum_seconds": 100, "elapsed_seconds": 99.5, "input_pairs_posted": 4,
            "foreground_observed": True, "foreground_requests": 1,
            "window_observed": True, "input_idle_observed": True, "close_requested": True,
            "forced_stop": False, "exit_code": 0, "capture_exists": True,
        }
        raw = json.dumps(route).encode()
        self.assertEqual(manifest.validate_route(raw, rate=30, seconds=100, audio="dummy"), route)
        for field, value in (("version", True), ("forced_stop", True), ("capture_exists", False),
                             ("input_idle_observed", False), ("elapsed_seconds", 103),
                             ("exit_code", 1), ("audio_backend", "default"), ("trace_scope", "resource"),
                             ("foreground_observed", False)):
            changed = dict(route)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                manifest.validate_route(json.dumps(changed).encode(), rate=30, seconds=100, audio="dummy")

    def test_attachment_route_is_an_unverified_bounded_attempt(self):
        route = route_v4()
        route.update(attachment_probe=True, attachment_attempt="second-character",
                     directional_keys_posted=1, attachment_capture_exists=True,
                     audio_backend="dummy", foreground_observed=True)
        validated = manifest.validate_route(json.dumps(route).encode(),
                                            rate=0, seconds=100, audio="dummy")
        self.assertEqual(validated["attachment_attempt"], "second-character")
        for field, value in (("attachment_probe", False), ("attachment_capture_exists", False),
                             ("attachment_attempt", []), ("directional_keys_posted", 2),
                             ("foreground_observed", False),
                             ("attachment_attempt", "candidate")):
            changed = dict(route)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                manifest.validate_route(json.dumps(changed).encode(),
                                        rate=0, seconds=100, audio="dummy")

    def test_resource_scope_never_claims_an_actor_or_signal_binding(self):
        trace = fixture()
        trace["filter"] = {"scope": "resource", "actor": "unbound", "clip": "all"}
        for field in ("actor", "actor_vtable", "signal", "info"):
            trace["identity"][field] = "0x00000000"
        trace["identity"]["signal_groups"] = trace["identity"]["info_rows"] = 0
        trace["controller"] = []
        trace["counts"].update(setup_calls=0, setup_accepted=0, resource_bindings=1)
        manifest.validate_trace(trace)
        aggregate = manifest.aggregate(trace, {"capture": "a" * 64}, [],
                                       rate=30, seconds=100)
        self.assertIn("does not bind an actor", aggregate["limitations"][-1])
        trace["identity"]["signal"] = "0x00008000"
        with self.assertRaisesRegex(ValueError, "falsely identifies"):
            manifest.validate_trace(trace)

    def test_candidate_archive_selection_is_bounded_and_private(self):
        root = manifest.ROOT / "private" / "game"
        one = root / "data" / "one.pak"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            manifest.select_archives(root, [one, one], None)
        with self.assertRaisesRegex(ValueError, "too many"):
            manifest.select_archives(root, [root / f"{n}.pak" for n in range(65)], None)
        with self.assertRaisesRegex(ValueError, "game root"):
            manifest.select_archives(root, [manifest.ROOT / "other.pak"], None)
        self.assertEqual(manifest.select_archives(root, [one], None), [one])


class SignalManifestTests(unittest.TestCase):
    def test_valid_bounded_structural_samples(self):
        trace = signal_probe_fixture()
        self.assertEqual(len(manifest._validate_signal_v3(trace)), 4)

    def test_malformed_identity_offsets_and_unknown_payload_are_rejected(self):
        mutations = (
            lambda t: t["signal_probe"]["samples"][0].update(instance_generation=1),
            lambda t: t["signal_probe"]["samples"][0].update(actor_vtable="0x00000000"),
            lambda t: t["signal_probe"]["samples"][0].update(signal_index=65536),
            lambda t: t["signal_probe"]["samples"][1].update(actor_time=10 ** 400),
            lambda t: t["signal_probe"]["samples"][2].update(record_bounded=16),
            lambda t: t["signal_probe"]["samples"][2].update(retained_index=1000000),
            lambda t: t["signal_probe"]["samples"][2].update(parameter_words=[123]),
            lambda t: t["signal_probe"]["samples"][3].update(observer=[]),
        )
        for mutate in mutations:
            trace = copy.deepcopy(signal_probe_fixture())
            mutate(trace)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                manifest._validate_signal_v3(trace)

    def test_signal_losses_and_actor_attribution_gate_combined_correlation(self):
        route = route_v4()
        route["signal_probe"] = True
        hashes = route_hashes()

        def report(trace):
            return manifest.aggregate(trace, hashes, [], rate=0, seconds=100, route=route)

        trace = signal_trace_v3()
        correlation = report(trace)["correlation"]
        self.assertTrue(correlation["eligible"])
        events = {event["event_id"]: event for event in correlation["events"]}
        self.assertEqual((events[9]["actor"], events[9]["actor_generation"]),
                         (trace["identity"]["actor"], trace["identity"]["actor_generation"]))
        self.assertEqual(events[1]["actor"], trace["identity"]["actor"])
        for kind in manifest.SIGNAL_CAPACITIES:
            for loss in ("full", "unreadable", "skipped"):
                damaged = copy.deepcopy(trace)
                count = damaged["signal_probe"]["counts"][kind]
                count["seen"] += 1
                count[loss] += 1
                with self.subTest(kind=kind, loss=loss):
                    self.assertFalse(report(damaged)["correlation"]["eligible"])
        for loss in trace["signal_probe"]["losses"]:
            damaged = copy.deepcopy(trace)
            damaged["signal_probe"]["losses"][loss] = 1
            with self.subTest(loss=loss):
                self.assertFalse(report(damaged)["correlation"]["eligible"])
        for mutate in (
            lambda t: t["signal_probe"]["samples"][0].update(actor="0x00002000"),
            lambda t: t["signal_probe"]["samples"][0].update(actor_generation=99),
            lambda t: t["signal_probe"]["samples"][0].update(instance_generation=99),
            lambda t: t["signal_probe"]["samples"][1].update(ba_generation=99),
            lambda t: t["signal_probe"]["samples"][-2].update(info_generation=0),
            lambda t: t["signal_probe"]["samples"][-1].update(info="0x0000a000"),
            lambda t: t["signal_probe"]["samples"][-1].update(parent_event_id=0),
        ):
            damaged = copy.deepcopy(trace)
            mutate(damaged)
            with self.subTest(mutate=mutate):
                self.assertFalse(report(damaged)["correlation"]["eligible"])

    def test_quaternion_losses_gate_combined_correlation(self):
        route = route_v4()
        route["quaternion_probe"] = True
        hashes = route_hashes()
        trace = fixture_v3()
        trace["quaternion_probe"] = {
            "version": 1, "helper": "0x8229ca98",
            "component_order": "guest_vmx_lanes_0_to_3",
            "capacity": 128, "per_evaluation_capacity": 8,
            "counts": dict.fromkeys(("seen", "invalid_context", "invalid_input", "invalid_output",
                                     "per_evaluation_full", "total_full", "parent_dropped"), 0),
            "samples": [],
        }
        self.assertTrue(manifest.aggregate(trace, hashes, [], rate=0, seconds=100,
                                           route=route)["correlation"]["eligible"])
        for loss in trace["quaternion_probe"]["counts"]:
            if loss == "seen":
                continue
            damaged = copy.deepcopy(trace)
            damaged["quaternion_probe"]["counts"].update(seen=1, **{loss: 1})
            with self.subTest(loss=loss):
                self.assertFalse(manifest.aggregate(damaged, hashes, [], rate=0, seconds=100,
                                                    route=route)["correlation"]["eligible"])


class BinaryProvenanceTests(unittest.TestCase):
    def test_binary_size_bounds_link_rejection_and_changed_reads(self):
        path = Mock()
        path.lstat.return_value = SimpleNamespace(st_size=3, st_file_attributes=0)
        path.is_file.return_value = True
        path.is_symlink.return_value = False
        path.read_bytes.return_value = b"abc"
        self.assertEqual(manifest._read_provenance_binary(path), b"abc")

        for size in (0, 128 * 1024 * 1024 + 1):
            path.lstat.return_value.st_size = size
            path.read_bytes.reset_mock()
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "invalid host binary"):
                manifest._read_provenance_binary(path)
            path.read_bytes.assert_not_called()
        path.lstat.return_value.st_size = 3
        for field in ("symlink", "reparse", "not_file"):
            path.is_symlink.return_value = field == "symlink"
            path.lstat.return_value.st_file_attributes = 0x400 if field == "reparse" else 0
            path.is_file.return_value = field != "not_file"
            path.read_bytes.reset_mock()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "invalid host binary"):
                manifest._read_provenance_binary(path)
            path.read_bytes.assert_not_called()
        path.is_symlink.return_value = False
        path.lstat.return_value.st_file_attributes = 0
        path.is_file.return_value = True
        for size in (2, 128 * 1024 * 1024):
            path.lstat.return_value.st_size = size
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "changed while reading"):
                manifest._read_provenance_binary(path)

    def test_release_and_debug_imports_select_matching_runtime_and_plugin(self):
        executable = Path("synthetic") / "n3.exe"
        for runtime, plugin in manifest.RUNTIME_PLUGINS.items():
            contents = {
                "n3.exe": synthetic_pe(runtime, "kernel32.dll"),
                runtime: synthetic_pe("kernel32.dll", export_name=runtime),
                plugin: synthetic_pe(runtime, export_name=plugin),
            }
            with self.subTest(runtime=runtime), patch.object(
                    manifest, "_read_provenance_binary",
                    side_effect=lambda path, contents=contents: contents[path.name]):
                actual = manifest.binary_provenance(executable)
                self.assertEqual((actual["runtime_dll"], actual["gpu_dll"]), (runtime, plugin))
                self.assertEqual(actual["host_executable"], hashlib.sha256(contents["n3.exe"]).hexdigest())
                self.assertEqual(actual["host_runtime_library"], hashlib.sha256(contents[runtime]).hexdigest())
                self.assertEqual(actual["host_gpu_plugin"], hashlib.sha256(contents[plugin]).hexdigest())
                route = route_v4()
                route["binary_provenance"] = actual
                manifest.require_binary_provenance(route, actual)
                manifest.validate_route(json.dumps(route).encode(), rate=0, seconds=100, audio="default")
                for field in ("host_executable", "host_runtime_library", "host_gpu_plugin"):
                    changed = dict(actual, **{field: "0" * 64})
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, "mismatch"):
                        manifest.require_binary_provenance(route, changed)
                missing = route_v4()
                missing.pop("binary_provenance")
                with self.assertRaisesRegex(ValueError, "lacks"):
                    manifest.require_binary_provenance(missing, actual)

    def test_missing_ambiguous_or_mismatched_runtime_provenance_is_rejected(self):
        executable = Path("synthetic") / "n3.exe"
        for imports in ((), ("rexruntime.dll", "rexruntimerd.dll")):
            with self.subTest(imports=imports), patch.object(
                    manifest, "_read_provenance_binary", return_value=synthetic_pe(*imports)), \
                    self.assertRaisesRegex(ValueError, "runtime imports"):
                manifest.binary_provenance(executable)
        contents = {
            "n3.exe": synthetic_pe("rexruntime.dll"),
            "rexruntime.dll": synthetic_pe("kernel32.dll", export_name="rexruntime.dll"),
            "rexgpu-xenos.dll": synthetic_pe("rexruntimerd.dll", export_name="rexgpu-xenos.dll"),
        }
        with patch.object(manifest, "_read_provenance_binary",
                          side_effect=lambda path: contents[path.name]), \
                self.assertRaisesRegex(ValueError, "disagree"):
            manifest.binary_provenance(executable)
        contents["rexruntime.dll"] = synthetic_pe("kernel32.dll", export_name="rexruntimed.dll")
        with patch.object(manifest, "_read_provenance_binary",
                          side_effect=lambda path: contents[path.name]), \
                self.assertRaisesRegex(ValueError, "export name mismatch"):
            manifest.binary_provenance(executable)
        contents["rexruntime.dll"] = synthetic_pe("kernel32.dll", export_name="rexruntime.dll")
        contents["rexgpu-xenos.dll"] = synthetic_pe(
            "rexruntime.dll", export_name="rexgpu-xenosrd.dll")
        with patch.object(manifest, "_read_provenance_binary",
                          side_effect=lambda path: contents[path.name]), \
                self.assertRaisesRegex(ValueError, "export name mismatch"):
            manifest.binary_provenance(executable)
        contents["rexgpu-xenos.dll"] = synthetic_pe("rexruntime.dll", export_name="rexgpu-xenos.dll")

        def read_present(path):
            if path.name not in contents:
                raise FileNotFoundError
            return contents[path.name]
        for missing in ("rexruntime.dll", "rexgpu-xenos.dll"):
            binary = contents.pop(missing)
            with self.subTest(missing=missing), patch.object(manifest, "_read_provenance_binary",
                    side_effect=read_present), self.assertRaises(FileNotFoundError):
                manifest.binary_provenance(executable)
            contents[missing] = binary
        for malformed in (b"MZ", synthetic_pe("rexruntime.dll")[:0x400]):
            with self.subTest(malformed=len(malformed)), self.assertRaises(ValueError):
                manifest._pe_imports(malformed)


class RouteCliTests(unittest.TestCase):
    def setUp(self):
        self.provenance = {
            "runtime_dll": "rexruntime.dll", "gpu_dll": "rexgpu-xenos.dll",
            "host_executable": "a" * 64, "host_runtime_library": "b" * 64,
            "host_gpu_plugin": "c" * 64,
        }

    def run_cli(self, route, expected_error=None, trace_version=3, binary_error=None):
        run = manifest.ROOT / "private" / "_synthetic_route_cli"
        trace_path = run / "user" / f"animation-trace-v{trace_version}.json"
        route_path = run / "route.json"
        executable = run / "n3.exe"
        raw = json.dumps(fixture_v3() if trace_version == 3 else fixture()).encode()
        route_raw = json.dumps(route).encode()
        output = mock_open()
        command = ["--trace", str(trace_path), "--route", str(route_path),
                   "--executable", str(executable), "--game-root", str(run / "game"),
                   "--output", str(run / "aggregate.json"),
                   "--frame-rate", str(route["frame_rate_target"]), "--seconds", "100"]

        def fake_stat(path):
            return SimpleNamespace(st_size=len({trace_path: raw, route_path: route_raw}[path]))

        def fake_bytes(path):
            return {trace_path: raw, route_path: route_raw}[path]

        def fake_hash(path):
            return "e" * 64 if path == executable else "d" * 64

        with (patch.object(Path, "resolve", autospec=True, side_effect=lambda path: path.absolute()),
              patch.object(Path, "stat", autospec=True, side_effect=fake_stat),
              patch.object(Path, "read_bytes", autospec=True, side_effect=fake_bytes),
              patch.object(Path, "read_text", return_value=json.dumps({"xexSha256": "d" * 64})),
              patch.object(Path, "mkdir"), patch.object(Path, "open", output),
              patch.object(manifest, "select_archives", return_value=[]),
              patch.object(manifest, "binary_provenance", return_value=self.provenance,
                           side_effect=binary_error) as inspect,
              patch.object(manifest, "sha256_file", side_effect=fake_hash),
              patch.object(manifest.subprocess, "check_output", return_value="f" * 40),
              redirect_stdout(io.StringIO())):
            if expected_error:
                error_type = FileNotFoundError if binary_error else ValueError
                with self.assertRaisesRegex(error_type, expected_error):
                    manifest.main(command)
                output.assert_not_called()
                return None, inspect.call_count
            self.assertEqual(manifest.main(command), 0)
            return json.loads(output().write.call_args.args[0]), inspect.call_count

    def test_legacy_route_uses_explicitly_unverified_processing_time_executable_hash(self):
        for trace_version in (2, 3):
            route = route_v4(rate=30)
            route["version"] = 3
            route.pop("clock_mode")
            route.pop("binary_provenance")
            with self.subTest(trace_version=trace_version):
                report, inspections = self.run_cli(route, trace_version=trace_version)
                self.assertEqual(inspections, 0)
                self.assertEqual(report["build"]["binary_provenance_status"], "unverified_legacy_route")
                self.assertEqual(report["build"]["host_executable"], "e" * 64)
                self.assertNotIn("host_runtime_library", report["build"])
                self.assertNotIn("host_gpu_plugin", report["build"])
                if trace_version == 3:
                    self.assertFalse(report["correlation"]["eligible"])
                self.assertTrue(any("no capture-time binary provenance" in item and
                                    "processing only" in item for item in report["limitations"]))

    def test_historical_v4_route_uses_an_explicitly_unverified_path(self):
        route = route_v4()
        route.pop("binary_provenance")
        for trace_version in (2, 3):
            with self.subTest(trace_version=trace_version):
                report, inspections = self.run_cli(route, trace_version=trace_version)
                self.assertEqual(inspections, 0)
                self.assertEqual(report["build"]["binary_provenance_status"],
                                 "unverified_historical_v4_route")
                self.assertEqual(report["build"]["host_executable"], "e" * 64)
                self.assertNotIn("host_runtime_library", report["build"])
                self.assertNotIn("host_gpu_plugin", report["build"])
                self.assertNotIn("binary_provenance", report["route"])
                self.assertTrue(any("no capture-time binary provenance" in item and
                                    "processing only" in item for item in report["limitations"]))
                if trace_version == 3:
                    self.assertTrue(report["correlation"]["eligible"])

    def test_current_route_matches_capture_binary_provenance(self):
        route = route_v4()
        route["binary_provenance"] = dict(self.provenance)
        report, inspections = self.run_cli(route)
        self.assertEqual(inspections, 1)
        self.assertEqual(report["build"]["binary_provenance_status"], "matched_route_hashes")
        self.assertEqual(report["route"]["binary_provenance"], self.provenance)
        for field in ("host_executable", "host_runtime_library", "host_gpu_plugin"):
            self.assertEqual(report["build"][field], self.provenance[field])
            changed = copy.deepcopy(route)
            changed["binary_provenance"][field] = "0" * 64
            with self.subTest(field=field):
                self.run_cli(changed, "provenance mismatch")
        self.run_cli(route, "missing runtime or GPU", binary_error=FileNotFoundError(
            "missing runtime or GPU"))

    def test_current_route_is_also_strict_through_validation_and_aggregation_apis(self):
        missing = route_v4()
        missing.pop("binary_provenance")
        self.assertEqual(manifest.validate_route(json.dumps(missing).encode(), rate=0,
                                                 seconds=100, audio="default"), missing)
        report = manifest.aggregate(fixture_v3(), route_hashes(), [], rate=0,
                                    seconds=100, route=missing)
        self.assertEqual(report["build"]["binary_provenance_status"],
                         "unverified_historical_v4_route")
        self.assertTrue(report["correlation"]["eligible"])
        for value in (None, {}, {"runtime_dll": "rexruntime.dll"}):
            malformed = route_v4()
            malformed["binary_provenance"] = value
            with self.subTest(provenance=value), self.assertRaises(ValueError):
                manifest.validate_route(json.dumps(malformed).encode(), rate=0,
                                        seconds=100, audio="default")
        for field in ("host_executable", "host_runtime_library", "host_gpu_plugin"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "provenance disagree"):
                manifest.aggregate(fixture_v3(), route_hashes(**{field: "0" * 64}), [],
                                   rate=0, seconds=100, route=route_v4())


class LargeTraceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("N3_ANIMATION_TRACE_MODEL_TEST"), "native model test is unavailable")
    def test_maximum_synthetic_trace_reaches_cli_and_research_reader(self):
        binary = os.environ["N3_ANIMATION_TRACE_MODEL_TEST"]
        raw = subprocess.run([binary, "--emit-full-probe-v3"], capture_output=True, check=True).stdout
        self.assertGreater(len(raw), 350_000)
        self.assertLess(len(raw), manifest.TRACE_MAX_BYTES)
        trace = manifest.parse_trace(raw)
        self.assertEqual(len(trace["signal_probe"]["samples"]), sum(manifest.SIGNAL_CAPACITIES.values()))

        fake_path = Mock()
        fake_path.stat.return_value.st_size = len(raw)
        fake_path.read_bytes.return_value = raw
        with patch.object(research, "_regular_file", return_value=True):
            summary = research.summarize_runtime_trace(fake_path)
        self.assertEqual(summary["sha256"], hashlib.sha256(raw).hexdigest())
        fake_path.stat.return_value.st_size = manifest.TRACE_MAX_BYTES + 1
        fake_path.read_bytes.reset_mock()
        with self.assertRaisesRegex(ValueError, "size"):
            manifest.read_trace(fake_path)
        fake_path.read_bytes.assert_not_called()

        run = manifest.ROOT / "private" / "synthetic-trace-validation"
        trace_path, route_path = run / "user" / "animation-trace-v3.json", run / "route.json"
        provenance = {
            "runtime_dll": "rexruntime.dll", "gpu_dll": "rexgpu-xenos.dll",
            "host_executable": "a" * 64, "host_runtime_library": "b" * 64,
            "host_gpu_plugin": "c" * 64,
        }
        route = route_v4()
        route.update(quaternion_probe=True, signal_probe=True, binary_provenance=provenance)
        route_raw = json.dumps(route).encode()

        def fake_stat(path, *args, **kwargs):
            if path == trace_path:
                return SimpleNamespace(st_size=len(raw))
            if path == route_path:
                return SimpleNamespace(st_size=len(route_raw))
            raise AssertionError(f"unexpected stat: {path.name}")

        def fake_bytes(path):
            return {trace_path: raw, route_path: route_raw}[path]

        command = ["--trace", str(trace_path), "--route", str(route_path),
                   "--executable", str(run / "n3.exe"), "--game-root", str(run / "game"),
                   "--output", str(run / "aggregate.json"), "--frame-rate", "0", "--seconds", "100"]
        output = mock_open()
        with (patch.object(Path, "resolve", autospec=True, side_effect=lambda path: path.absolute()),
              patch.object(Path, "stat", autospec=True, side_effect=fake_stat),
              patch.object(Path, "read_bytes", autospec=True, side_effect=fake_bytes),
              patch.object(Path, "read_text", return_value=json.dumps({"xexSha256": "d" * 64})),
              patch.object(Path, "mkdir"), patch.object(Path, "open", output),
              patch.object(manifest, "select_archives", return_value=[]),
              patch.object(manifest, "binary_provenance", return_value=provenance),
              patch.object(manifest, "sha256_file", return_value="d" * 64),
              patch.object(manifest.subprocess, "check_output", return_value="e" * 40),
              redirect_stdout(io.StringIO())):
            self.assertEqual(manifest.main(command), 0)
        result = json.loads(output().write.call_args.args[0])
        self.assertEqual(result["capture_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(result["correlation"]["eligible"])


class TimeoutDiagnosticTests(unittest.TestCase):
    def test_timeout_diagnostic_rejects_complete_or_inconsistent_claims(self):
        diagnostic = {
            "schema": "n3.runtime-animation-drain-timeout", "version": 1,
            "outcome": "incomplete", "reason": "drain_timeout", "aggregate": "omitted",
            "inflight_at_timeout": 1,
        }
        raw = json.dumps(diagnostic).encode()
        self.assertEqual(manifest.parse_timeout_diagnostic(raw), diagnostic)
        with self.assertRaises(ValueError):
            manifest.parse_trace(raw)
        for update in ({"outcome": "complete"}, {"aggregate": "included"},
                       {"inflight_at_timeout": 0}, {"inflight_at_timeout": True},
                       {"inflight_at_timeout": 0x80000000}, {"version": True},
                       {"counts": {"seen": 1, "skipped": 2}}):
            broken = dict(diagnostic, **update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                manifest.parse_timeout_diagnostic(json.dumps(broken).encode())
        with self.assertRaises(ValueError):
            manifest.parse_timeout_diagnostic(raw + b" " * manifest.TIMEOUT_DIAGNOSTIC_MAX_BYTES)

    def test_timeout_diagnostic_cli_validates_only_private_incomplete_output(self):
        path = manifest.ROOT / "private" / "_synthetic_run" / "animation-trace-timeout-v1.json"
        diagnostic = {
            "schema": "n3.runtime-animation-drain-timeout", "version": 1,
            "outcome": "incomplete", "reason": "drain_timeout", "aggregate": "omitted",
            "inflight_at_timeout": 1,
        }
        raw = json.dumps(diagnostic).encode()
        with (patch.object(Path, "resolve", autospec=True, side_effect=lambda item: item.absolute()),
              patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(raw))),
              patch.object(Path, "read_bytes", return_value=raw)):
            for command in (["--timeout-diagnostic", str(path)], [f"--timeout-diagnostic={path}"]):
                with self.subTest(command=command), redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(manifest.main(command), 0)
                    self.assertEqual(json.loads(stdout.getvalue()), diagnostic)
            with self.assertRaisesRegex(ValueError, "invalid arguments"):
                manifest.main(["--timeout-diagnostic", str(path), "--trace", str(path)])
            with self.assertRaisesRegex(ValueError, "inside the ignored private"):
                manifest.main(["--timeout-diagnostic", str(manifest.ROOT / "outside.json")])

    @unittest.skipUnless(os.environ.get("N3_ANIMATION_TRACE_HOOKS_TEST"),
                         "native hook test is unavailable")
    def test_interleaved_timeout_writes_valid_separate_diagnostic(self):
        binary = os.environ["N3_ANIMATION_TRACE_HOOKS_TEST"]
        raw = subprocess.run([binary, "--emit-timeout-v1"], capture_output=True, check=True).stdout
        diagnostic = manifest.parse_timeout_diagnostic(raw)
        self.assertEqual(diagnostic["outcome"], "incomplete")
        self.assertEqual(diagnostic["aggregate"], "omitted")
        self.assertEqual(diagnostic["inflight_at_timeout"], 1)
        with self.assertRaises(ValueError):
            manifest.parse_trace(raw)


if __name__ == "__main__":
    unittest.main()
