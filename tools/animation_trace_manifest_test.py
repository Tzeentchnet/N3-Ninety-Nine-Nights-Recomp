import copy
import hashlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import animation_trace_manifest as manifest


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


class TraceManifestTests(unittest.TestCase):
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
            manifest.parse_trace(b" " * (96 * 1024 + 1))
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


if __name__ == "__main__":
    unittest.main()
