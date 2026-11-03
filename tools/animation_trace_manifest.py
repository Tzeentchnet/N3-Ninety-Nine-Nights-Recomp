#!/usr/bin/env python3
"""Validate a bounded private animation trace and write a sanitized aggregate."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "setup": "0x82093be8",
    "controller": "0x82080158",
    "queue": "0x82252bd8",
    "evaluation": "0x82298ff0",
    "pose_output": "0x82249628",
    "pose_return": "0x8229ad64",
}
COUNTERS = {
    "setup_calls", "setup_accepted", "resource_bindings", "controller_calls", "queue_calls",
    "evaluation_calls", "actor_filtered", "clip_filtered", "unselected",
    "invalid", "reentrant", "concurrent", "after_stop", "lock_dropped",
    "inflight_at_flush", "controller_full", "queue_full", "evaluation_full",
    "pose_outputs", "invalid_outputs", "transitions",
}
IDENTITY = {
    "actor", "actor_vtable", "manager", "instance_handle", "instance", "ba",
    "ba_handle", "signal", "info", "setup_signal_index", "setup_info_index",
    "clips", "bones", "signal_groups", "info_rows", "name_length",
    "name_fnv1a64",
}
ADDRESS = re.compile(r"0x[0-9a-f]{8}\Z")
FINGERPRINT = re.compile(r"0x[0-9a-f]{16}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value, keys: set[str], label: str) -> dict:
    _require(isinstance(value, dict) and set(value) == keys, f"invalid {label} fields")
    return value


def _uint(value, maximum: int, label: str) -> int:
    _require(type(value) is int and 0 <= value <= maximum, f"invalid {label}")
    return value


def _number(value, label: str) -> float:
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, f"invalid {label}")
    return value


def _address(value, label: str, *, nonzero: bool = True) -> str:
    _require(isinstance(value, str) and ADDRESS.fullmatch(value) is not None, f"invalid {label}")
    if nonzero:
        _require(value != "0x00000000", f"zero {label}")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def parse_trace(raw: bytes) -> dict:
    _require(0 < len(raw) <= 96 * 1024, "trace size exceeds bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid trace JSON") from error
    return validate_trace(value)


def validate_trace(value) -> dict:
    trace = _object(value, {"schema", "version", "sources", "filter", "selected",
                            "stop_reason", "identity", "counts", "controller",
                            "queue", "evaluation"}, "trace")
    _require(trace["schema"] == "n3.runtime-animation-trace" and
             type(trace["version"]) is int and trace["version"] == 2,
             "unsupported trace schema")
    _require(trace["sources"] == SOURCES, "unexpected hook identities")
    _require(trace["selected"] is True, "no validated actor binding was observed")
    _require(isinstance(trace["stop_reason"], str) and trace["stop_reason"] in {
        "shutdown", "invalid_mapping", "identity_changed", "invalid_value",
        "concurrent_actor", "concurrent_shared_ba", "reentrant", "two_transitions",
    }, "missing explicit shutdown or capture stop")
    filters = _object(trace["filter"], {"scope", "actor", "clip"}, "filter")
    _require(isinstance(filters["scope"], str) and filters["scope"] in {"actor", "resource"},
             "invalid trace scope")
    if filters["scope"] == "resource":
        _require(filters["actor"] == "unbound", "resource scope must not claim an actor")
    elif filters["actor"] != "first":
        _address(filters["actor"], "actor filter")
    if filters["clip"] != "all":
        _uint(filters["clip"], 4095, "clip filter")
    ident = _object(trace["identity"], IDENTITY, "identity")
    for name in ("manager", "instance", "ba"):
        _address(ident[name], name)
    if filters["scope"] == "actor":
        for name in ("actor", "actor_vtable", "signal", "info"):
            _address(ident[name], name)
        _require(ident["actor_vtable"] in {"0x82040170", "0x82041570"},
                 "unexpected actor vtable")
        if filters["actor"] != "first":
            _require(filters["actor"] == ident["actor"], "actor filter mismatch")
    else:
        for name in ("actor", "actor_vtable", "signal", "info"):
            _address(ident[name], name, nonzero=False)
            _require(ident[name] == "0x00000000", f"resource scope falsely identifies {name}")
    for name, maximum in (
        ("instance_handle", 65535), ("ba_handle", 999),
        ("setup_signal_index", 65535), ("setup_info_index", 65535),
        ("clips", 4096), ("bones", 2048), ("signal_groups", 4096),
        ("info_rows", 4096), ("name_length", 259),
    ):
        _uint(ident[name], maximum, name)
    for name in ("clips", "bones", "name_length"):
        _require(ident[name] > 0, f"empty {name}")
    if filters["scope"] == "actor":
        _require(ident["signal_groups"] > 0 and ident["info_rows"] > 0, "empty actor vectors")
        clip_limit = min(ident["clips"], ident["signal_groups"], ident["info_rows"])
    else:
        _require(all(ident[name] == 0 for name in (
            "signal_groups", "info_rows", "setup_signal_index", "setup_info_index")),
            "resource scope falsely identifies actor vectors")
        clip_limit = ident["clips"]
    _require(isinstance(ident["name_fnv1a64"], str) and
             FINGERPRINT.fullmatch(ident["name_fnv1a64"]) is not None, "invalid basename fingerprint")
    counts = _object(trace["counts"], COUNTERS, "counters")
    for name, number in counts.items():
        _uint(number, (1 << 64) - 1, name)
    _require(counts["inflight_at_flush"] == 0, "capture still had calls in flight at flush")
    _require(counts["invalid"] >= counts["invalid_outputs"], "invalid pose totals disagree")
    if filters["scope"] == "actor":
        _require(counts["setup_accepted"] == 1 and counts["setup_calls"] >= 1 and
                 counts["resource_bindings"] == 0, "actor binding counts disagree")
    else:
        _require(counts["resource_bindings"] == 1 and counts["setup_accepted"] == 0 and
                 counts["queue_calls"] >= 1 and not trace["controller"],
                 "resource binding counts disagree")
    for name, capacity in (("controller", 256), ("queue", 64), ("evaluation", 64)):
        _require(isinstance(trace[name], list) and len(trace[name]) <= capacity,
                 f"{name} sample capacity exceeded")
        _require(counts[f"{name}_calls"] >= len(trace[name]), f"{name} sample count disagrees")
    _require(sum(len(trace[name]) for name in ("controller", "queue", "evaluation")) > 0,
             "no runtime controller, queue or evaluation sample")

    def clip(value, label):
        result = _uint(value, clip_limit - 1, label)
        if filters["clip"] != "all":
            _require(result == filters["clip"], "sample violates clip filter")
        return result

    for sample in trace["controller"]:
        _object(sample, {"caller", "before_clip", "after_clip", "before_time",
                         "after_time", "step"}, "controller sample")
        _address(sample["caller"], "controller return")
        clip(sample["before_clip"], "controller clip")
        _uint(sample["after_clip"], clip_limit - 1, "controller after clip")
        for field in ("before_time", "after_time", "step"):
            _number(sample[field], field)
    for sample in trace["queue"]:
        _object(sample, {"caller", "clip", "frame"}, "queue sample")
        _address(sample["caller"], "queue return")
        clip(sample["clip"], "queue clip")
        _number(sample["frame"], "queue frame")
    for sample in trace["evaluation"]:
        _object(sample, {"caller", "clip", "time", "queue_count", "pose_outputs",
                         "invalid_outputs"}, "evaluation sample")
        _address(sample["caller"], "evaluation return")
        clip(sample["clip"], "evaluation clip")
        _number(sample["time"], "evaluation time")
        _require(1 <= _uint(sample["queue_count"], 5, "queue count") <= 5,
                 "empty evaluation queue")
        _uint(sample["pose_outputs"], ident["bones"], "pose count")
        _uint(sample["invalid_outputs"], ident["bones"], "invalid pose count")
    _require(counts["pose_outputs"] >= sum(s["pose_outputs"] for s in trace["evaluation"]) and
             counts["invalid_outputs"] >= sum(s["invalid_outputs"] for s in trace["evaluation"]),
             "pose totals disagree")
    return trace


def fingerprint(name: str) -> tuple[str, int]:
    basename = name.replace("\\", "/").rsplit("/", 1)[-1]
    raw = basename.encode("ascii").lower()
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"0x{value:016x}", len(raw)


def candidate_members(archive, archive_hash: str, identity: dict) -> list[dict]:
    _require(SHA256.fullmatch(archive_hash) is not None, "invalid archive hash")
    matches = []
    for member in archive.members:
        try:
            found = fingerprint(member.name)
        except UnicodeEncodeError:
            continue
        if found != (identity["name_fnv1a64"], identity["name_length"]):
            continue
        _require(0 <= member.size <= 32 * 1024 * 1024, "candidate member exceeds bound")
        payload = archive.read_member(member)
        _require(len(payload) == member.size, "candidate member size mismatch")
        matches.append({
            "archive_sha256": archive_hash,
            "member_index": member.index,
            "member_size": member.size,
            "member_sha256": hashlib.sha256(payload).hexdigest(),
            "evidence": "candidate_basename_fingerprint_only",
        })
    return matches


def aggregate(trace: dict, hashes: dict, candidates: list[dict], *,
              archives: list[str] | None = None,
              rate: int, seconds: int, audio: str = "default", route: dict | None = None) -> dict:
    validate_trace(trace)
    _require(rate in (30, 40, 60) and 1 <= seconds <= 300 and
             audio in {"default", "dummy", "directsound", "wasapi"},
             "invalid route bounds")
    for digest in hashes.values():
        _require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
                 "invalid build or asset hash")
    for digest in archives or []:
        _require(SHA256.fullmatch(digest) is not None, "invalid candidate archive hash")
    controller = trace["controller"]
    queue = trace["queue"]
    evaluation = trace["evaluation"]

    def histogram(samples, field):
        values = Counter(sample[field] for sample in samples)
        return [{"value": key, "count": values[key]} for key in sorted(values)]

    def extent(samples, *fields):
        values = [sample[field] for sample in samples for field in fields]
        return {"minimum": min(values), "maximum": max(values)} if values else None

    result = {
        "schema": "n3.runtime-animation-aggregate",
        "version": 2,
        "evidence": "observed_bounded_runtime_capture",
        "capture_sha256": hashes["capture"],
        "build": {key: value for key, value in hashes.items() if key not in {"capture", "route"}},
        "route": {"frame_rate_target": rate, "maximum_seconds": seconds,
                  "profile": "isolated", "input": "keyboard_controller_attempt",
                  "audio_backend": audio},
        "sources": SOURCES,
        "filter": trace["filter"],
        "identity": trace["identity"],
        "candidate_archive_sha256": sorted(archives or []),
        "asset_candidates": candidates,
        "asset_binding": "unverified_candidates_are_not_resolver_proof",
        "stop_reason": trace["stop_reason"],
        "counts": trace["counts"],
        "samples": {
            "controller": {"count": len(controller), "clips": histogram(controller, "before_clip"),
                           "times": extent(controller, "before_time", "after_time"),
                           "steps": histogram(controller, "step"),
                           "return_sites": histogram(controller, "caller")},
            "queue": {"count": len(queue), "clips": histogram(queue, "clip"),
                      "frames": extent(queue, "frame"), "return_sites": histogram(queue, "caller")},
            "evaluation": {"count": len(evaluation), "clips": histogram(evaluation, "clip"),
                           "times": extent(evaluation, "time"),
                           "pose_outputs": sum(s["pose_outputs"] for s in evaluation),
                           "return_sites": histogram(evaluation, "caller")},
        },
        "limitations": [
            "guest heap addresses identify only this capture and can be reused",
            "basename fingerprints and matching archive members do not prove the winning package",
            "samples do not establish source FPS, interpolation, signal payloads, axes or attachment semantics",
            "matrix contents and retail payload bytes are not recorded",
        ],
    }
    if audio == "dummy":
        result["limitations"].append(
            "dummy audio is a silent host sink and does not establish audio behavior or timing equivalence")
    if trace["filter"]["scope"] == "resource":
        result["limitations"].append(
            "resource scope does not bind an actor, signal table or INFO row")
    if route is not None:
        result["route_sha256"] = hashes["route"]
        result["route"].update({
            "elapsed_seconds": route["elapsed_seconds"],
            "trace_scope": route["trace_scope"],
            "input": "keyboard_controller_attempt" if route["input_pairs_posted"] else "no_keyboard_input_observed",
            "input_pairs_posted": route["input_pairs_posted"],
            "foreground_observed": route["foreground_observed"],
            "foreground_requests": route["foreground_requests"],
            "window_observed": route["window_observed"],
            "input_idle_observed": route["input_idle_observed"],
            "close_requested": route["close_requested"],
            "forced_stop": route["forced_stop"],
            "exit_code": route["exit_code"],
        })
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_provenance(audio: str, source: Path | None, library: Path | None,
                     sdk_bundle: Path | None) -> dict:
    if audio != "dummy":
        _require(source is None and library is None and sdk_bundle is None,
                 "audio build hashes are only accepted for the dummy backend")
        return {}
    _require(source is not None and library is not None and sdk_bundle is not None,
             "dummy audio requires its local SDL source, linked library and SDK source bundle")
    for path in (source, library, sdk_bundle):
        _require(path.resolve().is_relative_to(ROOT.resolve()) and path.is_file(),
                 "audio build inputs must be local project files")
    return {"audio_source_archive": sha256_file(source),
            "audio_linked_library": sha256_file(library),
            "audio_sdk_source_bundle": sha256_file(sdk_bundle)}


def validate_route(raw: bytes, *, rate: int, seconds: int, audio: str, scope: str = "actor") -> dict:
    _require(0 < len(raw) <= 16 * 1024, "route size exceeds bounds")
    try:
        route = json.loads(raw, object_pairs_hook=_unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid route JSON") from error
    _object(route, {"schema", "version", "process_id", "enabled", "trace_scope", "frame_rate_target",
                    "audio_backend", "maximum_seconds", "elapsed_seconds", "input_pairs_posted",
                    "foreground_observed", "foreground_requests",
                    "window_observed", "input_idle_observed", "close_requested", "forced_stop",
                    "exit_code", "capture_exists"}, "route")
    _require(route["schema"] == "n3.runtime-animation-route" and
             type(route["version"]) is int and route["version"] == 3,
             "unsupported route schema")
    _require(type(route["frame_rate_target"]) is int and type(route["maximum_seconds"]) is int and
             route["frame_rate_target"] == rate and route["maximum_seconds"] == seconds and
             route["audio_backend"] == audio and route["trace_scope"] == scope,
             "route parameters do not match")
    _require(_uint(route["process_id"], (1 << 32) - 1, "process id") > 0, "zero process id")
    _uint(route["input_pairs_posted"], 60, "posted input count")
    _uint(route["foreground_requests"], 60, "foreground request count")
    _require(type(route["foreground_observed"]) is bool and
             (not route["input_pairs_posted"] or route["foreground_observed"]),
             "input attempts lack foreground ownership evidence")
    elapsed = _number(route["elapsed_seconds"], "elapsed seconds")
    _require(0 < elapsed <= seconds + 2, "route exceeded its deadline")
    for name in ("enabled", "window_observed", "input_idle_observed",
                 "close_requested", "capture_exists"):
        _require(route[name] is True, f"route did not establish {name}")
    _require(route["forced_stop"] is False, "route required a hard kill")
    _require(type(route["exit_code"]) is int and route["exit_code"] == 0,
             "route did not exit normally")
    return route


def select_archives(game_root: Path, supplied: list[Path], directory: Path | None) -> list[Path]:
    result = list(supplied)
    if directory is not None:
        _require(directory.resolve().is_relative_to(game_root.resolve()) and directory.is_dir(),
                 "character archive directory must belong to the supplied game root")
        result.extend(path for path in directory.glob("*_char_res.pak") if path.is_file())
    _require(len(result) <= 64, "too many candidate archives")
    resolved = [path.resolve() for path in result]
    _require(len(set(resolved)) == len(resolved), "duplicate candidate archives")
    _require(all(path.is_relative_to(game_root.resolve()) for path in resolved),
             "candidate archive must belong to the supplied game root")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--route", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--archive", action="append", default=[], type=Path)
    parser.add_argument("--character-archive-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-rate", required=True, type=int, choices=(30, 40, 60))
    parser.add_argument("--seconds", required=True, type=int)
    parser.add_argument("--audio-backend",
                        choices=("default", "dummy", "directsound", "wasapi"), default="default")
    parser.add_argument("--audio-source-archive", type=Path)
    parser.add_argument("--audio-linked-library", type=Path)
    parser.add_argument("--audio-sdk-source-bundle", type=Path)
    args = parser.parse_args(argv)
    _require(args.trace.resolve().is_relative_to((ROOT / "private").resolve()),
             "trace must be inside the ignored private directory")
    _require(args.output.resolve().is_relative_to((ROOT / "private").resolve()),
             "aggregate must be inside the ignored private directory")
    _require(args.route.resolve().is_relative_to((ROOT / "private").resolve()) and
             args.trace.resolve() == (args.route.parent / "user" / "animation-trace-v2.json").resolve(),
             "route and trace must belong to the same private run")
    archives = select_archives(args.game_root, args.archive, args.character_archive_dir)
    _require(0 < args.trace.stat().st_size <= 96 * 1024, "trace size exceeds bounds")
    raw = args.trace.read_bytes()
    trace = parse_trace(raw)
    _require(0 < args.route.stat().st_size <= 16 * 1024, "route size exceeds bounds")
    route_raw = args.route.read_bytes()
    route = validate_route(route_raw, rate=args.frame_rate, seconds=args.seconds,
                           audio=args.audio_backend, scope=trace["filter"]["scope"])
    game_hash = sha256_file(args.game_root / "default.xex")
    expected = json.loads((ROOT / "docs" / "game-build.json").read_text(encoding="utf-8"))["xexSha256"]
    _require(game_hash == expected, "game executable hash does not match the pinned build")
    hashes = {
        "capture": hashlib.sha256(raw).hexdigest(),
        "route": hashlib.sha256(route_raw).hexdigest(),
        "host_executable": sha256_file(args.executable),
        "host_runtime_library": sha256_file(args.executable.parent / "rexruntimerd.dll"),
        "host_gpu_plugin": sha256_file(args.executable.parent / "rexgpu-xenosrd.dll"),
        "game_executable": game_hash,
        "hook_source": sha256_file(ROOT / "src" / "animation_trace_hooks.cpp"),
        "model_source": sha256_file(ROOT / "src" / "animation_trace_model.cpp"),
        "model_header": sha256_file(ROOT / "src" / "animation_trace_model.h"),
        "app_lifecycle_source": sha256_file(ROOT / "src" / "n3_app.h"),
        "build_wiring": sha256_file(ROOT / "CMakeLists.txt"),
        "toolchain_lock": sha256_file(ROOT / "tools" / "toolchain.lock.json"),
    }
    hashes.update(audio_provenance(args.audio_backend, args.audio_source_archive,
                                   args.audio_linked_library, args.audio_sdk_source_bundle))
    candidates = []
    archive_hashes = []
    if archives:
        try:
            from .n3_gameplay_data import GameplayDataError, read_pak
        except ImportError:
            from n3_gameplay_data import GameplayDataError, read_pak
        for path in archives:
            _require(path.stat().st_size <= 512 * 1024 * 1024, "archive exceeds bound")
            archive_hash = sha256_file(path)
            archive_hashes.append(archive_hash)
            try:
                archive = read_pak(path)
            except GameplayDataError as error:
                raise ValueError("candidate archive failed bounded structural validation") from error
            candidates.extend(candidate_members(archive, archive_hash, trace["identity"]))
            _require(len(candidates) <= 64, "too many candidate members")
    candidates.sort(key=lambda item: (item["archive_sha256"], item["member_index"]))
    result = aggregate(trace, hashes, candidates, archives=archive_hashes,
                       rate=args.frame_rate, seconds=args.seconds, audio=args.audio_backend,
                       route=route)
    result["build"]["git_head"] = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Validated {len(trace['controller'])} controller, {len(trace['queue'])} queue and "
          f"{len(trace['evaluation'])} evaluation samples; {len(candidates)} candidate members.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"Animation trace validation failed: {error}")
