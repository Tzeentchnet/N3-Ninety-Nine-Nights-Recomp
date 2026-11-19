#!/usr/bin/env python3
"""Validate a private animation trace or an incomplete drain-timeout diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "setup": "0x82093be8",
    "controller": "0x82080158",
    "queue": "0x82252bd8",
    "evaluation": "0x82298ff0",
    "pose_output": "0x82249628",
    "pose_return": "0x8229ad64",
}
SOURCES_V3 = {
    **SOURCES,
    "archive_load": "0x822733b8", "archive_raw_load": "0x82273000",
    "archive_mount": "0x82272af0", "archive_release": "0x82272f58",
    "resolver": "0x82272c40", "ba_load": "0x8224e6f0",
    "ba_decode": "0x82298e78", "ba_collect": "0x8224e9b0",
    "instance_create": "0x8229cf30", "instance_submit": "0x8224ac98",
    "instance_release_direct": "0x82251d38", "instance_reset": "0x8224e0b8",
    "manager_destroy": "0x82249fb0",
}
SOURCES_V3_LEGACY = {
    **{key: value for key, value in SOURCES_V3.items() if key != "instance_submit"},
    "instance_release": "0x8224ac98",
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
COUNTERS_V3 = COUNTERS | {
    "events_started", "events_abandoned", "events_inflight_at_flush",
    "cache_hits", "cache_untracked", "registry_full", "counter_saturated",
}
IDENTITY_V3 = IDENTITY | {"actor_generation", "instance_generation", "ba_generation", "source"}
EVENT_FIELDS = {"event_id", "parent_event_id", "begin_tick", "end_tick"}
DISPATCH_WRAPPERS = {"0x820a4648", "0x820af768", "0x8208d878", "0x820aafb0", "0x820a2968"}
QUATERNION_CALLERS = {"0x8229a214", "0x8229a5d0", "0x8229a6a4", "0x8229a868"}
ADDRESS = re.compile(r"0x[0-9a-f]{8}\Z")
FINGERPRINT = re.compile(r"0x[0-9a-f]{16}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TRACE_MAX_BYTES = 512 * 1024
TIMEOUT_DIAGNOSTIC_MAX_BYTES = 256
RUNTIME_PLUGINS = {
    "rexbase.dll": "rexgpu-xenos-d3d12.dll",
    "rexbased.dll": "rexgpu-xenos-d3d12d.dll",
    "rexbaserd.dll": "rexgpu-xenos-d3d12rd.dll",
}
SIGNAL_CAPACITIES = {
    "ba_load": 32, "as_load": 64, "info_load": 64, "setup": 64, "request": 32,
    "selection": 64, "install": 64, "group": 32, "dispatch": 96, "effect": 32,
}


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
    _require(0 < len(raw) <= TRACE_MAX_BYTES, "trace size exceeds bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid trace JSON") from error
    return validate_trace(value)


def parse_timeout_diagnostic(raw: bytes) -> dict:
    _require(0 < len(raw) <= TIMEOUT_DIAGNOSTIC_MAX_BYTES, "timeout diagnostic size exceeds bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid timeout diagnostic JSON") from error
    _object(value, {"schema", "version", "outcome", "reason", "aggregate", "inflight_at_timeout"},
            "timeout diagnostic")
    _require(value["schema"] == "n3.runtime-animation-drain-timeout" and
             type(value["version"]) is int and value["version"] == 1 and
             value["outcome"] == "incomplete" and value["reason"] == "drain_timeout" and
             value["aggregate"] == "omitted", "invalid timeout diagnostic identity")
    _uint(value["inflight_at_timeout"], 0x7fffffff, "timeout in-flight count")
    _require(value["inflight_at_timeout"] > 0, "timeout diagnostic requires in-flight work")
    return value


def read_trace(path: Path) -> tuple[bytes, dict]:
    _require(0 < path.stat().st_size <= TRACE_MAX_BYTES, "trace size exceeds bounds")
    raw = path.read_bytes()
    return raw, parse_trace(raw)


def _validate_signal_v3(trace: dict) -> list:
    probe = _object(trace["signal_probe"], {
        "version", "event_ids", "capacity", "counts", "losses", "samples",
    }, "signal probe")
    _require(type(probe["version"]) is int and probe["version"] == 1 and
             probe["event_ids"] == "shared_trace_v3" and
             type(probe["capacity"]) is int and probe["capacity"] == sum(SIGNAL_CAPACITIES.values()),
             "invalid signal probe version")
    counts = _object(probe["counts"], set(SIGNAL_CAPACITIES), "signal counts")
    losses = _object(probe["losses"], {
        "unresolved_sources", "record_map_full", "record_map_invalid",
        "actor_registry_full", "asset_registry_full",
    }, "signal losses")
    for key, value in losses.items():
        _uint(value, (1 << 64) - 1, key)
    samples = probe["samples"]
    _require(isinstance(samples, list) and len(samples) <= probe["capacity"], "invalid signal samples")
    actual = Counter()
    common = {"type", "caller"} | EVENT_FIELDS
    identity = {"identity_bound", "instance", "instance_generation", "ba", "ba_generation",
                "signal", "signal_generation", "info", "info_generation"}
    request = {"requested_type", "requested_index", "requested_attribute"}
    rows = {"row_read", "row_type", "row_index", "row_attribute"}
    source_fields = {"status", "archive_generation", "archive_slot", "archive_content_sha256",
                     "member_sha256", "member_index", "archive_size", "member_size"}
    for sample in samples:
        _require(isinstance(sample, dict) and isinstance(sample.get("type"), str) and
                 sample["type"] in SIGNAL_CAPACITIES, "invalid signal sample type")
        kind = sample["type"]
        actual[kind] += 1
        fields = set(common)
        if kind in {"ba_load", "as_load", "info_load"}:
            fields |= {"object", "generation", "loaded", "source"}
            if kind == "ba_load":
                fields.add("ba_handle")
        else:
            if kind != "selection":
                fields |= {"actor", "actor_generation"}
            if kind in {"setup", "group"}:
                fields |= identity
            if kind == "setup":
                fields |= {"actor_vtable", "instance_handle", "ba_handle", "signal_index",
                           "info_index", "setup_key4", "setup_key88"}
            if kind in {"request", "selection", "install"}:
                fields |= {"info", "info_generation"}
            if kind in {"selection", "install"}:
                fields |= {"selected_row"} | rows
            if kind in {"request", "selection"}:
                fields |= request
            if kind == "install":
                fields.add("installed_row")
            if kind in {"group", "dispatch"}:
                fields |= {"group_read", "group_index"}
            if kind == "group":
                fields |= {"time_read", "actor_time", "actor_step_field"}
            if kind == "dispatch":
                fields |= {"signal_generation", "dispatch_path", "record_read", "retained_index",
                           "record_kind", "record_time", "record_bounded", "record_word_count",
                           "source_offset", "group_offset", "table_offset", "record_offset"}
            if kind == "effect":
                fields |= {"observer", "changed_slots"}
        _object(sample, fields, "signal sample")
        _address(sample["caller"], "signal caller", nonzero=False)
        for field in EVENT_FIELDS:
            _uint(sample[field], (1 << 64) - 1, field)
        for field in fields & {"actor", "actor_vtable", "instance", "ba", "signal", "info", "object"}:
            _address(sample[field], field, nonzero=False)
        for field in fields & {"actor_generation", "instance_generation", "ba_generation",
                               "signal_generation", "info_generation", "generation"}:
            _uint(sample[field], (1 << 64) - 1, field)
        for field in fields & {"instance_handle", "ba_handle", "signal_index", "info_index",
                               "setup_key4", "setup_key88"}:
            _uint(sample[field], (1 << 32) - 1, field)
        for field in fields & (request | {"selected_row", "installed_row"}):
            _require(type(sample[field]) is int and -(1 << 31) <= sample[field] < (1 << 31),
                     f"invalid {field}")
        if kind in {"ba_load", "as_load", "info_load"}:
            _require(type(sample["loaded"]) is bool and
                     (not sample["loaded"] or sample["generation"] > 0 and
                      sample["object"] != "0x00000000"), "invalid signal load")
            source = _object(sample["source"], source_fields, "signal source")
            if source["status"] == "unavailable":
                _require(all(type(source[key]) is int and source[key] == 0 for key in
                             ("archive_generation", "archive_size", "member_size")) and
                         all(source[key] is None for key in ("archive_slot", "member_index",
                             "archive_content_sha256", "member_sha256")), "unavailable signal source")
            else:
                _require(source["status"] == "resolved" and
                         _uint(source["archive_generation"], (1 << 64) - 1, "archive generation") > 0,
                         "invalid signal source")
                _uint(source["archive_slot"], 63, "archive slot")
                _uint(source["member_index"], 4095, "member index")
                size = _uint(source["archive_size"], 128 * 1024 * 1024, "archive size")
                member = _uint(source["member_size"], 32 * 1024 * 1024, "member size")
                _require(size >= 4 and 0 < member <= size and all(
                    isinstance(source[key], str) and SHA256.fullmatch(source[key]) is not None
                    for key in ("archive_content_sha256", "member_sha256")), "invalid signal source bounds")
        if kind in {"setup", "group"}:
            _require(type(sample["identity_bound"]) is bool, "invalid signal identity")
            if sample["identity_bound"]:
                generations = [sample["actor_generation"]] + [
                    sample[f"{key}_generation"] for key in ("instance", "ba", "signal", "info")
                ]
                _require(all(sample[key] != "0x00000000" for key in
                             ("actor", "instance", "ba", "signal", "info")) and
                         all(generations) and len(set(generations)) == len(generations),
                         "invalid bound signal identity")
        if kind == "setup":
            _require((not sample["identity_bound"] or sample["actor_vtable"] != "0x00000000") and
                     sample["ba_handle"] < 1000 and sample["signal_index"] <= 65535 and
                     sample["info_index"] <= 65535, "invalid setup indices")
        if kind in {"selection", "install"}:
            _require(type(sample["row_read"]) is bool, "invalid row read")
            if sample["row_read"]:
                _require(0 <= sample["selected_row"] < 2048 and all(
                    type(sample[key]) is int and -(1 << 31) <= sample[key] < (1 << 31)
                    for key in ("row_type", "row_index", "row_attribute")), "invalid selected row")
            else:
                _require(all(sample[key] is None for key in ("row_type", "row_index", "row_attribute")),
                         "unreadable row claims values")
        if kind in {"group", "dispatch"}:
            _require(type(sample["group_read"]) is bool, "invalid group flag")
            if sample["group_read"]:
                _uint(sample["group_index"], (1 << 32) - 1, "group index")
            else:
                _require(sample["group_index"] is None, "unreadable group claims index")
        if kind == "group":
            _require(type(sample["time_read"]) is bool, "invalid time flag")
            for key in ("actor_time", "actor_step_field"):
                if sample["time_read"]:
                    _require(abs(_number(sample[key], key)) <= 3.4028236e38,
                             "signal time exceeds float32")
                else:
                    _require(sample[key] is None, "unreadable time claims value")
        if kind == "dispatch":
            _require(type(sample["dispatch_path"]) is int and sample["dispatch_path"] in (1, 2, 3) and
                     type(sample["record_read"]) is bool and type(sample["source_offset"]) is bool,
                     "invalid dispatch flags")
            fields = ("retained_index", "record_kind", "record_time", "record_bounded", "record_word_count")
            if sample["record_read"]:
                _require(sample["group_read"] and sample["group_index"] < 2048, "invalid record group")
                for key in ("retained_index", "record_kind", "record_word_count"):
                    _uint(sample[key], (1 << 32) - 1, key)
                _require(sample["retained_index"] <= 999999, "invalid retained index")
                for key in ("record_time", "record_bounded"):
                    _require(type(sample[key]) is int and -(1 << 31) <= sample[key] < (1 << 31),
                             "invalid record metadata")
            else:
                _require(all(sample[key] is None for key in fields), "unreadable record claims values")
            offsets = ("group_offset", "table_offset", "record_offset")
            if sample["source_offset"]:
                _require(sample["record_read"] and sample["signal_generation"] > 0 and
                         sample["record_time"] >= 0 and 0 <= sample["record_bounded"] < 16,
                         "unbound offset")
                for key in offsets:
                    _uint(sample[key], 32 * 1024 * 1024, key)
                _require(520 <= sample["group_offset"] <= sample["table_offset"] - 4 and
                         sample["table_offset"] + 8 <= sample["record_offset"], "invalid source offset")
            else:
                _require(all(sample[key] is None for key in offsets), "unmapped record claims offsets")
        if kind == "effect":
            _require(sample["observer"] in ("actor_byte_1056_comparison",
                                            "downstream_slot_occupancy_comparison"), "invalid observer")
            _uint(sample["changed_slots"], 1 if sample["observer"] ==
                  "actor_byte_1056_comparison" else 180, "changed slots")
    missing = 0
    for name, capacity in SIGNAL_CAPACITIES.items():
        count = _object(counts[name], {"seen", "recorded", "full", "unreadable", "skipped",
                                      "capacity"}, "signal kind counts")
        for field in ("seen", "recorded", "full", "unreadable", "skipped"):
            _uint(count[field], (1 << 64) - 1, field)
        _require(type(count["capacity"]) is int and count["capacity"] == capacity and
                 count["recorded"] == actual[name] <= capacity, "signal sample count")
        accounted = sum(count[key] for key in ("recorded", "full", "unreadable", "skipped"))
        _require(accounted <= count["seen"], "signal loss accounting")
        missing += count["seen"] - accounted
    _require(missing <= trace["counts"]["events_abandoned"] +
             trace["counts"]["events_inflight_at_flush"] +
             trace["counts"].get("inflight_at_flush", 0), "unfinished signal events")
    return samples


def _validate_v3(trace: dict) -> None:
    limit = (1 << 64) - 1
    if "dispatch" in trace:
        dispatch = _object(trace["dispatch"], {
            "version", "resource_hook", "setup_wrapper_calls", "resource_calls",
            "flag_zero", "handle_minus_one", "eligible", "unreadable",
        } | ({name for name in ("setup_rejections", "setup_vtables") if name in trace["dispatch"]}
             if isinstance(trace["dispatch"], dict) else set()), "dispatch")
        _require(type(dispatch["version"]) is int and dispatch["version"] == 1 and
                 dispatch["resource_hook"] == "0x8217ad08", "unsupported dispatch probe")
        wrappers = _object(dispatch["setup_wrapper_calls"], DISPATCH_WRAPPERS, "setup wrappers")
        for value in wrappers.values():
            _uint(value, limit, "setup wrapper calls")
        if "setup_rejections" in dispatch:
            setup = _object(dispatch["setup_rejections"], {
                "scope_skipped", "filter_mismatch", "vtable_unreadable", "vtable_unsupported",
                "input_invalid", "candidates", "post_identity_failed", "other_after_selection",
                "repeat_selected",
            }, "setup rejections")
            for name, value in setup.items():
                _uint(value, limit, name)
            if not trace["counts"]["inflight_at_flush"]:
                _require(setup["post_identity_failed"] <= setup["candidates"] and
                         sum(value for name, value in setup.items() if name != "post_identity_failed") <=
                         trace["counts"]["setup_calls"], "setup rejection accounting disagrees")
        if "setup_vtables" in dispatch:
            _require("setup_rejections" in dispatch, "vtable histogram lacks rejection counts")
            histogram = _object(dispatch["setup_vtables"], {
                "capacity", "full", "zero", "getter_unreadable", "entries",
            }, "setup vtables")
            _require(type(histogram["capacity"]) is int and histogram["capacity"] == 16 and
                     isinstance(histogram["entries"], list) and len(histogram["entries"]) <= 16,
                     "invalid vtable histogram capacity")
            for name in ("full", "zero", "getter_unreadable"):
                _uint(histogram[name], limit, name)
            keys = set()
            total = histogram["full"] + histogram["zero"]
            for entry in histogram["entries"]:
                _object(entry, {"vtable", "getter", "calls"}, "vtable entry")
                key = (_address(entry["vtable"], "vtable", nonzero=False),
                       _address(entry["getter"], "getter", nonzero=False))
                _require(key != ("0x00000000", "0x00000000") and key not in keys and
                         _uint(entry["calls"], limit, "vtable calls") > 0, "invalid vtable entry")
                keys.add(key)
                total += entry["calls"]
            if not trace["counts"]["inflight_at_flush"]:
                _require(total == setup["vtable_unsupported"] and
                         histogram["getter_unreadable"] <= total, "vtable accounting disagrees")
        for name in ("resource_calls", "flag_zero", "handle_minus_one", "eligible", "unreadable"):
            _uint(dispatch[name], limit, name)
        branches = sum(dispatch[name] for name in
                       ("flag_zero", "handle_minus_one", "eligible", "unreadable"))
        _require(abs(dispatch["resource_calls"] - branches) <= trace["counts"]["inflight_at_flush"],
                 "dispatch loss accounting disagrees")
    quaternion = []
    if "quaternion_probe" in trace:
        probe = _object(trace["quaternion_probe"], {
            "version", "helper", "component_order", "capacity", "per_evaluation_capacity",
            "counts", "samples",
        }, "quaternion probe")
        _require(type(probe["version"]) is int and probe["version"] == 1 and
                 probe["helper"] == "0x8229ca98" and
                 probe["component_order"] == "guest_vmx_lanes_0_to_3" and
                 type(probe["capacity"]) is int and probe["capacity"] == 128 and
                 type(probe["per_evaluation_capacity"]) is int and
                 probe["per_evaluation_capacity"] == 8, "unsupported quaternion probe")
        qc = _object(probe["counts"], {
            "seen", "invalid_context", "invalid_input", "invalid_output",
            "per_evaluation_full", "total_full", "parent_dropped",
        }, "quaternion counts")
        for name, value in qc.items():
            _uint(value, limit, name)
        quaternion = probe["samples"]
        _require(isinstance(quaternion, list) and len(quaternion) <= 128,
                 "invalid quaternion sample count")
        _require(abs(qc["seen"] - (len(quaternion) + sum(
            qc[name] for name in qc if name != "seen"))) <=
            9 * trace["counts"]["inflight_at_flush"], "quaternion loss accounting disagrees")
        evaluations = {sample["event_id"]: sample for sample in trace["evaluation"]}
        per_parent = Counter()
        for sample in quaternion:
            _object(sample, {"caller", "bone", "factor", "left", "right", "result"} |
                    EVENT_FIELDS, "quaternion sample")
            _require(isinstance(sample["caller"], str) and sample["caller"] in QUATERNION_CALLERS and
                     _uint(sample["parent_event_id"], limit, "quaternion parent") in evaluations,
                     "unbound quaternion sample")
            _uint(sample["bone"], trace["identity"]["bones"] - 1, "quaternion bone")
            _require(abs(_number(sample["factor"], "quaternion factor")) <= 3.4028236e38,
                     "quaternion factor exceeds float32")
            for name in ("left", "right", "result"):
                _require(isinstance(sample[name], list) and len(sample[name]) == 4,
                         "invalid quaternion vector")
                for component in sample[name]:
                    _require(abs(_number(component, "quaternion component")) <= 3.4028236e38,
                             "quaternion component exceeds float32")
            per_parent[sample["parent_event_id"]] += 1
        _require(all(count <= 8 for count in per_parent.values()), "per-evaluation capacity exceeded")
    signal = _validate_signal_v3(trace) if "signal_probe" in trace else []
    clock = _object(trace["clock"], {"kind", "frequency"}, "clock")
    _require(clock["kind"] == "performance_counter" and
             _uint(clock["frequency"], limit, "clock frequency") > 0, "invalid clock")
    identity, counts = trace["identity"], trace["counts"]
    generations = [_uint(identity[name], limit, name) for name in
                   ("actor_generation", "instance_generation", "ba_generation")]
    actor, instance, ba = generations
    if not trace["selected"]:
        _require(not any(generations), "unselected trace claims generations")
    else:
        _require(instance > 0 and ba > 0 and instance != ba, "invalid resource generations")
        if trace["filter"]["scope"] == "actor":
            _require(actor > 0 and actor not in (instance, ba), "invalid actor generation")
        else:
            _require(actor == 0, "resource scope claims actor generation")
    source = _object(identity["source"], {
        "status", "archive_generation", "archive_slot", "archive_content_sha256", "member_sha256",
        "member_index", "archive_size", "member_size",
    }, "source")
    _require(source["status"] in ("resolved", "unavailable"), "invalid source status")
    if source["status"] == "unavailable":
        _require(all(type(source[name]) is int and source[name] == 0 for name in
                     ("archive_generation", "archive_size", "member_size")) and
                 source["archive_content_sha256"] is None and
                 source["archive_slot"] is None and source["member_sha256"] is None and
                 source["member_index"] is None,
                 "unavailable source claims provenance")
    else:
        generation = _uint(source["archive_generation"], limit, "archive generation")
        _uint(source["archive_slot"], 63, "archive slot")
        archive_size = _uint(source["archive_size"], 128 * 1024 * 1024, "archive size")
        member_size = _uint(source["member_size"], 32 * 1024 * 1024, "member size")
        _uint(source["member_index"], 4095, "member index")
        _require(trace["selected"] and generation > 0 and generation not in generations and archive_size >= 4 and
                 0 < member_size <= archive_size, "invalid source bounds or generation")
        for name in ("archive_content_sha256", "member_sha256"):
            _require(isinstance(source[name], str) and SHA256.fullmatch(source[name]) is not None,
                     f"invalid {name}")
    _require(counts["counter_saturated"] <= 1, "invalid saturation flag")
    events = {}
    for samples in (trace["controller"], trace["queue"], trace["evaluation"], quaternion, signal):
        for sample in samples:
            event_id = _uint(sample["event_id"], limit, "event id")
            parent = _uint(sample["parent_event_id"], limit, "parent event id")
            begin = _uint(sample["begin_tick"], limit, "begin tick")
            end = _uint(sample["end_tick"], limit, "end tick")
            _require(0 < event_id <= counts["events_started"] and parent < event_id and
                     begin <= end and event_id not in events, "invalid or duplicate event")
            events[event_id] = (parent, begin, end)
    abandoned = counts["events_abandoned"]
    inflight = counts["events_inflight_at_flush"]
    _require(counts["events_started"] == len(events) + abandoned + inflight and
             inflight <= counts["inflight_at_flush"] and
             abandoned >= sum(counts[f"{name}_full"] for name in
                              ("controller", "queue", "evaluation")),
             "event loss accounting disagrees")
    missing_parents = set()
    for parent, begin, end in events.values():
        if not parent:
            continue
        if parent not in events:
            missing_parents.add(parent)
        else:
            _, parent_begin, parent_end = events[parent]
            _require(parent_begin <= begin <= end <= parent_end, "event outside parent interval")
    _require(len(missing_parents) <= abandoned + inflight, "missing event parents exceed loss")


def validate_trace(value) -> dict:
    _require(isinstance(value, dict) and type(value.get("version")) is int and
             value["version"] in (2, 3), "unsupported trace schema")
    version = value["version"]
    trace = _object(value, {"schema", "version", "sources", "filter", "selected",
                            "stop_reason", "identity", "counts", "controller",
                            "queue", "evaluation"} | ({"clock"} if version == 3 else set()) |
                    ({"dispatch"} if version == 3 and "dispatch" in value else set()) |
                    ({"quaternion_probe"} if version == 3 and "quaternion_probe" in value else set()) |
                    ({"signal_probe"} if version == 3 and "signal_probe" in value else set()), "trace")
    _require(trace["schema"] == "n3.runtime-animation-trace" and
             type(trace["version"]) is int and trace["version"] in (2, 3),
             "unsupported trace schema")
    _require((trace["sources"] in (SOURCES_V3, SOURCES_V3_LEGACY) if version == 3
              else trace["sources"] == SOURCES), "unexpected hook identities")
    _require(type(trace["selected"]) is bool, "invalid selection flag")
    _require(isinstance(trace["stop_reason"], str) and trace["stop_reason"] in {
        "shutdown", "invalid_mapping", "identity_changed", "invalid_value",
        "concurrent_actor", "concurrent_shared_ba", "reentrant", "two_transitions",
        *({"untracked_lifetime", "registry_full", "counter_overflow",
           "clock_failure", "concurrent_probe"} if version == 3 else set()),
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
    ident = _object(trace["identity"], IDENTITY_V3 if version == 3 else IDENTITY, "identity")
    if not trace["selected"]:
        for name in ("actor", "actor_vtable", "manager", "instance", "ba", "signal", "info"):
            _address(ident[name], name, nonzero=False)
            _require(ident[name] == "0x00000000", "unselected trace claims identity")
        for name in ("instance_handle", "ba_handle", "setup_signal_index", "setup_info_index",
                     "clips", "bones", "signal_groups", "info_rows", "name_length"):
            _require(type(ident[name]) is int and ident[name] == 0, "unselected trace claims identity")
        _require(ident["name_fnv1a64"] == "0x0000000000000000", "unselected name fingerprint")
        counts = _object(trace["counts"], COUNTERS_V3 if version == 3 else COUNTERS, "counters")
        for name, number in counts.items():
            _uint(number, (1 << 64) - 1, name)
        _require(counts["setup_accepted"] == counts["resource_bindings"] == 0 and
                 all(isinstance(trace[name], list) and not trace[name]
                     for name in ("controller", "queue", "evaluation")),
                 "unselected trace claims samples")
        if version == 3:
            _validate_v3(trace)
        return trace
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
    counts = _object(trace["counts"], COUNTERS_V3 if version == 3 else COUNTERS, "counters")
    for name, number in counts.items():
        _uint(number, (1 << 64) - 1, name)
    if version == 2:
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
    _require(sum(len(trace[name]) for name in ("controller", "queue", "evaluation")) > 0 or
             "signal_probe" in trace,
             "no runtime controller, queue or evaluation sample")

    def clip(value, label):
        result = _uint(value, clip_limit - 1, label)
        if filters["clip"] != "all":
            _require(result == filters["clip"], "sample violates clip filter")
        return result

    for sample in trace["controller"]:
        _object(sample, {"caller", "before_clip", "after_clip", "before_time",
                         "after_time", "step"} | (EVENT_FIELDS if version == 3 else set()), "controller sample")
        _address(sample["caller"], "controller return")
        clip(sample["before_clip"], "controller clip")
        _uint(sample["after_clip"], clip_limit - 1, "controller after clip")
        for field in ("before_time", "after_time", "step"):
            _number(sample[field], field)
    for sample in trace["queue"]:
        _object(sample, {"caller", "clip", "frame"} | (EVENT_FIELDS if version == 3 else set()), "queue sample")
        _address(sample["caller"], "queue return")
        clip(sample["clip"], "queue clip")
        _number(sample["frame"], "queue frame")
    for sample in trace["evaluation"]:
        _object(sample, {"caller", "clip", "time", "queue_count", "pose_outputs",
                         "invalid_outputs"} | (EVENT_FIELDS if version == 3 else set()), "evaluation sample")
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
    if version == 3:
        _validate_v3(trace)
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
    content_hash = hashlib.sha256(archive.payload).hexdigest() if "source" in identity else None
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
        candidate = {
            "archive_sha256": archive_hash,
            "member_index": member.index,
            "member_size": member.size,
            "member_sha256": hashlib.sha256(payload).hexdigest(),
            "evidence": "candidate_basename_fingerprint_only",
        }
        if content_hash is not None:
            candidate["archive_content_sha256"] = content_hash
        matches.append(candidate)
    if "source" in identity and identity["source"]["status"] == "resolved":
        source = identity["source"]
        if content_hash == source["archive_content_sha256"]:
            _require(len(archive.payload) == source["archive_size"] and any(
                item["member_index"] == source["member_index"] and
                item["member_size"] == source["member_size"] and
                item["member_sha256"] == source["member_sha256"] for item in matches),
                "resolver member identity mismatch")
            selected = [member for member in archive.members if member.index == source["member_index"]]
            _require(len(selected) == 1, "resolver member index is ambiguous")
            try:
                selected_name = selected[0].name.encode("ascii").lower()
                earlier = any(member.index < source["member_index"] and
                              member.name.encode("ascii").lower() == selected_name
                              for member in archive.members)
            except UnicodeEncodeError as error:
                raise ValueError("non-ASCII resolver member identity") from error
            _require(not earlier, "resolver did not select the first matching member")
    return matches


def aggregate(trace: dict, hashes: dict, candidates: list[dict], *,
              archives: list[str] | None = None,
              rate: int, seconds: int, audio: str = "default", route: dict | None = None) -> dict:
    validate_trace(trace)
    _require(rate in (0, 30, 40, 60) and 1 <= seconds <= 300 and
             audio in {"default", "dummy", "directsound", "wasapi"},
             "invalid route bounds")
    hash_fields = {
        "capture", "route", "host_executable", "host_runtime_library", "host_gpu_plugin",
        "game_executable", "hook_source", "trace_header", "model_source", "model_header",
        "runner_source", "manifest_source", "app_lifecycle_source", "build_wiring",
        "toolchain_lock", "audio_source_archive",
        "audio_linked_library", "audio_sdk_source_bundle",
    }
    _require(isinstance(hashes, dict) and "capture" in hashes and
             set(hashes) <= hash_fields and (route is None or "route" in hashes),
             "invalid provenance fields")
    _require(isinstance(candidates, list) and len(candidates) <= 64 and
             (archives is None or isinstance(archives, list) and len(archives) <= 64),
             "too many candidate sources")
    if route is not None:
        route = _validate_route(route, rate=rate, seconds=seconds, audio=audio,
                                scope=trace["filter"]["scope"])
        _require(route.get("quaternion_probe", False) == ("quaternion_probe" in trace),
                 "route and quaternion opt-in disagree")
        _require(route.get("signal_probe", False) == ("signal_probe" in trace),
                 "route and signal opt-in disagree")
        if "binary_provenance" in route:
            for name in ("host_executable", "host_runtime_library", "host_gpu_plugin"):
                _require(hashes.get(name) == route["binary_provenance"][name],
                         "route and binary provenance disagree")
    for digest in hashes.values():
        _require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
                 "invalid build or asset hash")
    for digest in archives or []:
        _require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
                 "invalid candidate archive hash")
    for candidate in candidates:
        fields = {"archive_sha256", "member_index", "member_size", "member_sha256", "evidence"}
        if trace["version"] == 3:
            fields.add("archive_content_sha256")
        _object(candidate, fields, "asset candidate")
        for field in ("archive_sha256", "member_sha256") + (
                ("archive_content_sha256",) if trace["version"] == 3 else ()):
            _require(isinstance(candidate[field], str) and SHA256.fullmatch(candidate[field]) is not None,
                     f"invalid candidate {field}")
        _uint(candidate["member_index"], 1_000_000, "candidate member index")
        _uint(candidate["member_size"], 512 * 1024 * 1024, "candidate member size")
        _require(candidate["evidence"] == "candidate_basename_fingerprint_only",
                 "invalid candidate evidence")
    controller = trace["controller"]
    queue = trace["queue"]
    evaluation = trace["evaluation"]

    def histogram(samples, field):
        values = Counter(sample[field] for sample in samples)
        return [{"value": key, "count": values[key]} for key in sorted(values)]

    def extent(samples, *fields):
        values = [sample[field] for sample in samples for field in fields]
        return {"minimum": min(values), "maximum": max(values)} if values else None

    source = trace["identity"].get("source")
    matched = bool(source and source["status"] == "resolved" and any(
        candidate.get("archive_content_sha256") == source["archive_content_sha256"] and
        candidate.get("member_index") == source["member_index"] and
        candidate.get("member_size") == source["member_size"] and
        candidate.get("member_sha256") == source["member_sha256"] for candidate in candidates))
    result = {
        "schema": "n3.runtime-animation-aggregate",
        "version": 3 if trace["version"] == 3 else 2,
        "evidence": "observed_bounded_runtime_capture",
        "capture_sha256": hashes["capture"],
        "build": {key: value for key, value in hashes.items() if key not in {"capture", "route"}},
        "route": {"frame_rate_target": rate, "maximum_seconds": seconds,
                  "profile": "isolated", "input": "keyboard_controller_attempt",
                  "audio_backend": audio},
        "sources": trace["sources"],
        "filter": trace["filter"],
        "identity": trace["identity"],
        "candidate_archive_sha256": sorted(archives or []),
        "asset_candidates": candidates,
        "asset_binding": ("resolver_observed_and_content_matched" if matched else
                          "resolver_observed_but_archive_not_matched"
                          if source and source["status"] == "resolved" else
                          "unverified_candidates_are_not_resolver_proof"),
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
    if "dispatch" in trace:
        dispatch = trace["dispatch"]
        result["dispatch"] = {key: value for key, value in dispatch.items() if key != "setup_vtables"}
        if "setup_vtables" in dispatch:
            vtable_summary = dispatch["setup_vtables"]
            result["dispatch"]["setup_vtables"] = {
                key: vtable_summary[key] for key in ("capacity", "full", "zero", "getter_unreadable")
            } | {"distinct": len(vtable_summary["entries"]),
                 "recorded_calls": sum(entry["calls"] for entry in vtable_summary["entries"])}
    if "quaternion_probe" in trace:
        probe = trace["quaternion_probe"]
        result["quaternion_probe"] = {
            "counts": probe["counts"], "sample_count": len(probe["samples"]),
            "return_sites": histogram(probe["samples"], "caller"),
            "component_order": probe["component_order"],
        }
    if "signal_probe" in trace:
        result["signal_probe"] = {
            "counts": trace["signal_probe"]["counts"],
            "losses": trace["signal_probe"]["losses"],
        }
    if trace["version"] == 3:
        counts = trace["counts"]
        events = []
        actor_identity = None
        if trace["selected"] and trace["filter"]["scope"] == "actor":
            actor_identity = (trace["identity"]["actor"], trace["identity"]["actor_generation"])
        for stream in ("controller", "queue", "evaluation"):
            for sample in trace[stream]:
                event = {
                    "stream": stream,
                    **{name: sample[name] for name in (
                        "event_id", "parent_event_id", "begin_tick", "end_tick", "caller")},
                }
                if stream == "controller":
                    event.update(before_clip=sample["before_clip"], after_clip=sample["after_clip"])
                else:
                    event["clip"] = sample["clip"]
                if actor_identity:
                    event["actor"], event["actor_generation"] = actor_identity
                events.append(event)
        if "quaternion_probe" in trace:
            for sample in trace["quaternion_probe"]["samples"]:
                event = {"stream": "quaternion", **{name: sample[name] for name in (
                    "event_id", "parent_event_id", "begin_tick", "end_tick", "caller", "bone")}}
                if actor_identity:
                    event["actor"], event["actor_generation"] = actor_identity
                events.append(event)
        signal_samples = trace.get("signal_probe", {}).get("samples", [])
        for sample in signal_samples:
            event = {"stream": "signal_" + sample["type"], **{name: sample[name] for name in (
                "event_id", "parent_event_id", "begin_tick", "end_tick", "caller")}}
            if "actor" in sample:
                event.update(actor=sample["actor"], actor_generation=sample["actor_generation"])
            events.append(event)
        events.sort(key=lambda event: event["event_id"])
        event_by_id = {event["event_id"]: event for event in events}
        signal_identity_complete = True
        for sample in signal_samples:
            kind = sample["type"]
            if kind in {"ba_load", "as_load", "info_load"}:
                continue
            event = event_by_id[sample["event_id"]]
            if kind == "selection":
                parent = event["parent_event_id"]
                while parent and parent in event_by_id:
                    ancestor = event_by_id[parent]
                    if ancestor["stream"] == "signal_request":
                        event.update(actor=ancestor["actor"],
                                     actor_generation=ancestor["actor_generation"])
                        break
                    parent = ancestor["parent_event_id"]
            signal_identity_complete &= (
                actor_identity is not None and
                (event.get("actor"), event.get("actor_generation")) == actor_identity
            )
            if kind in {"setup", "group"}:
                signal_identity_complete &= sample["identity_bound"] and all(
                    sample[field] == trace["identity"][field]
                    for field in ("instance", "instance_generation", "ba", "ba_generation",
                                  "signal", "info")
                )
            if kind in {"request", "selection", "install"}:
                signal_identity_complete &= (
                    sample["info"] == trace["identity"]["info"] and sample["info_generation"] > 0
                )
            if kind == "group":
                signal_identity_complete &= sample["group_read"] and sample["time_read"]
            if kind == "dispatch":
                signal_identity_complete &= sample["group_read"] and sample["record_read"]
        signal_probe = trace.get("signal_probe")
        signal_loss = bool(signal_probe and (
            any(signal_probe["losses"].values()) or
            any(count[field] for count in signal_probe["counts"].values()
                for field in ("full", "unreadable", "skipped"))
        ))
        quaternion_probe = trace.get("quaternion_probe")
        quaternion_loss = bool(quaternion_probe and any(
            value for name, value in quaternion_probe["counts"].items() if name != "seen"
        ))
        loss_fields = ("controller_full", "queue_full", "evaluation_full", "events_abandoned",
                       "events_inflight_at_flush", "inflight_at_flush", "lock_dropped",
                       "registry_full", "cache_untracked", "counter_saturated", "invalid",
                       "reentrant", "concurrent", "invalid_outputs")
        result["correlation"] = {
            "eligible": trace["selected"] and bool(controller or queue or evaluation)
                        and trace["stop_reason"] == "shutdown"
                        and not any(counts[field] for field in loss_fields)
                        and not signal_loss and not quaternion_loss and signal_identity_complete
                        and route is not None and route["version"] == 4,
            "clock": {"kind": "performance_counter", "frequency": trace["clock"]["frequency"],
                      "interpretation": "host_ticks_not_simulation_time"},
            "event_count": len(events),
            "events": events,
        }
        result["limitations"].append("event parentage records nested probe calls, not simulation causality")
        if signal_probe:
            result["limitations"].append(
                "actor signal observations exclude preselection activity; asset loads are global")
        if matched:
            result["limitations"][1] = (
                "resolver content matching identifies the observed source, not simulation semantics")
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
        if route["version"] == 4:
            result["route"]["clock_mode"] = route["clock_mode"]
        if "binary_provenance" not in route:
            result["build"]["binary_provenance_status"] = (
                "unverified_legacy_route" if route["version"] == 3
                else "unverified_historical_v4_route")
            result["limitations"].append(
                "route has no capture-time binary provenance; supplied host hashes "
                "describe files inspected during processing only")
        else:
            result["build"]["binary_provenance_status"] = "matched_route_hashes"
            result["route"]["binary_provenance"] = dict(route["binary_provenance"])
            result["limitations"].append(
                "matching route hashes do not independently prove which binaries were loaded at runtime")
        if route.get("attachment_probe", False):
            result["route"]["attachment_attempt"] = route["attachment_attempt"]
            result["route"]["directional_keys_posted"] = route["directional_keys_posted"]
            result["limitations"].append(
                "directional input is an unverified navigation attempt, not an equipped control or character identity")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_provenance_binary(path: Path) -> bytes:
    info = path.lstat()
    _require(path.is_file() and not path.is_symlink() and
             not getattr(info, "st_file_attributes", 0) & 0x400 and
             0 < info.st_size <= 128 * 1024 * 1024, "missing or invalid host binary")
    data = path.read_bytes()
    _require(len(data) == info.st_size, "host binary changed while reading")
    return data


def _pe_imports(data: bytes, *, expected_export: str | None = None) -> set[str]:
    def span(offset: int, size: int) -> None:
        _require(offset >= 0 and size >= 0 and offset <= len(data) - size, "invalid PE bounds")

    def u16(offset: int) -> int:
        span(offset, 2)
        return struct.unpack_from("<H", data, offset)[0]

    def u32(offset: int) -> int:
        span(offset, 4)
        return struct.unpack_from("<I", data, offset)[0]

    span(0, 64)
    _require(data[:2] == b"MZ", "invalid host executable")
    pe = u32(0x3C)
    span(pe, 24)
    _require(data[pe:pe + 4] == b"PE\0\0" and u16(pe + 4) == 0x8664,
             "unsupported host executable")
    section_count, optional_size = u16(pe + 6), u16(pe + 20)
    optional = pe + 24
    _require(0 < section_count <= 96 and optional_size >= 128, "invalid PE headers")
    span(optional, optional_size)
    _require(u16(optional) == 0x20B and u32(optional + 108) >= 2,
             "missing PE import directory")
    import_rva, import_size = u32(optional + 120), u32(optional + 124)
    _require(import_rva and 20 <= import_size <= 4096 * 20, "invalid PE import directory")
    section_table = optional + optional_size
    span(section_table, section_count * 40)
    sections = []
    for index in range(section_count):
        section = section_table + index * 40
        virtual = u32(section + 12)
        raw_size, raw_offset = u32(section + 16), u32(section + 20)
        span(raw_offset, raw_size)
        sections.append((virtual, raw_size, raw_offset))

    def resolve(rva: int, size: int) -> tuple[int, int]:
        matches = []
        for virtual, raw_size, raw_offset in sections:
            delta = rva - virtual
            if 0 <= delta <= raw_size and size <= raw_size - delta:
                matches.append((raw_offset + delta, raw_offset + raw_size))
        _require(len(matches) == 1, "invalid PE import address")
        return matches[0]

    if expected_export is not None:
        export_rva, export_size = u32(optional + 112), u32(optional + 116)
        _require(export_rva and export_size >= 40, "missing PE export directory")
        export_offset, _ = resolve(export_rva, 40)
        name_offset, section_end = resolve(u32(export_offset + 12), 1)
        end = data.find(b"\0", name_offset, min(name_offset + 256, section_end))
        _require(end > name_offset, "invalid PE export name")
        try:
            exported_name = data[name_offset:end].decode("ascii").lower()
        except UnicodeError as error:
            raise ValueError("invalid PE export name") from error
        _require(exported_name == expected_export, "runtime binary export name mismatch")

    offset, _ = resolve(import_rva, import_size)
    names = set()
    terminated = False
    for index in range(import_size // 20):
        descriptor = offset + index * 20
        fields = struct.unpack_from("<5I", data, descriptor)
        if not any(fields):
            terminated = True
            break
        name_offset, section_end = resolve(fields[3], 1)
        end = data.find(b"\0", name_offset, min(name_offset + 256, section_end))
        _require(end > name_offset, "invalid PE import name")
        try:
            name = data[name_offset:end].decode("ascii").lower()
        except UnicodeError as error:
            raise ValueError("invalid PE import name") from error
        _require(re.fullmatch(r"[a-z0-9_.-]+\.dll", name) is not None, "invalid PE import name")
        names.add(name)
    _require(terminated, "unterminated PE import directory")
    return names


def binary_provenance(executable: Path) -> dict:
    executable_bytes = _read_provenance_binary(executable)
    imports = _pe_imports(executable_bytes)
    runtimes = set(RUNTIME_PLUGINS) & imports
    _require(len(runtimes) == 1, "host executable has missing or ambiguous runtime imports")
    runtime = next(iter(runtimes))
    plugin = RUNTIME_PLUGINS[runtime]
    runtime_bytes = _read_provenance_binary(executable.parent / runtime)
    plugin_bytes = _read_provenance_binary(executable.parent / plugin)
    _pe_imports(runtime_bytes, expected_export=runtime)
    _require(set(RUNTIME_PLUGINS) & _pe_imports(plugin_bytes, expected_export=plugin) == {runtime},
             "GPU plugin and executable runtime imports disagree")
    return {
        "runtime_dll": runtime,
        "gpu_dll": plugin,
        "host_executable": hashlib.sha256(executable_bytes).hexdigest(),
        "host_runtime_library": hashlib.sha256(runtime_bytes).hexdigest(),
        "host_gpu_plugin": hashlib.sha256(plugin_bytes).hexdigest(),
    }


def _validate_binary_provenance(value) -> dict:
    provenance = _object(value, {
        "runtime_dll", "gpu_dll", "host_executable", "host_runtime_library", "host_gpu_plugin",
    }, "binary provenance")
    runtime = provenance["runtime_dll"]
    _require(isinstance(runtime, str) and runtime in RUNTIME_PLUGINS and
             provenance["gpu_dll"] == RUNTIME_PLUGINS[runtime], "invalid runtime/GPU pair")
    for field in ("host_executable", "host_runtime_library", "host_gpu_plugin"):
        _require(isinstance(provenance[field], str) and SHA256.fullmatch(provenance[field]),
                 "invalid binary provenance hash")
    return provenance


def require_binary_provenance(route: dict, actual: dict) -> None:
    _require("binary_provenance" in route, "route lacks binary provenance")
    _require(_validate_binary_provenance(route["binary_provenance"]) ==
             _validate_binary_provenance(actual), "runtime binary provenance mismatch")


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
    return _validate_route(route, rate=rate, seconds=seconds, audio=audio, scope=scope)


def _validate_route(route: dict, *, rate: int, seconds: int, audio: str, scope: str) -> dict:
    _require(isinstance(route, dict) and type(route.get("version")) is int and
             route["version"] in (3, 4), "unsupported route schema")
    _object(route, {"schema", "version", "process_id", "enabled", "trace_scope", "frame_rate_target",
                    "audio_backend", "maximum_seconds", "elapsed_seconds", "input_pairs_posted",
                    "foreground_observed", "foreground_requests",
                    "window_observed", "input_idle_observed", "close_requested", "forced_stop",
                    "exit_code", "capture_exists"} |
            ({"clock_mode"} if route["version"] == 4 else set()) |
            ({"binary_provenance"}
             if route["version"] == 4 and "binary_provenance" in route else set()) |
            ({"quaternion_probe"} if route["version"] == 4 and "quaternion_probe" in route else set()) |
            ({"signal_probe"} if route["version"] == 4 and "signal_probe" in route else set()) |
            ({"attachment_probe", "attachment_attempt", "directional_keys_posted",
              "attachment_capture_exists"}
             if route["version"] == 4 and "attachment_probe" in route else set()), "route")
    _require(route["schema"] == "n3.runtime-animation-route" and
             type(route["version"]) is int and route["version"] in (3, 4),
             "unsupported route schema")
    _require(rate in (0, 30, 40, 60), "invalid presentation target")
    _require(type(route["frame_rate_target"]) is int and type(route["maximum_seconds"]) is int and
             route["frame_rate_target"] == rate and route["maximum_seconds"] == seconds and
             route["audio_backend"] == audio and route["trace_scope"] == scope,
             "route parameters do not match")
    if route["version"] == 4:
        _require(route["clock_mode"] == ("original" if rate == 0 else "presentation_target"),
                 "invalid route clock mode")
        if "binary_provenance" in route:
            _validate_binary_provenance(route["binary_provenance"])
        if "quaternion_probe" in route:
            _require(route["quaternion_probe"] is True, "invalid quaternion opt-in")
        if "signal_probe" in route:
            _require(route["signal_probe"] is True, "invalid signal opt-in")
        if "attachment_probe" in route:
            _require(route["attachment_probe"] is True and route["attachment_capture_exists"] is True and
                     isinstance(route["attachment_attempt"], str) and
                     route["attachment_attempt"] in {"candidate", "alternate-weapon-control", "second-character"},
                     "invalid attachment attempt")
            _uint(route["directional_keys_posted"], 1, "directional input count")
            _require(not route["directional_keys_posted"] or
                     (route["foreground_observed"] is True and route["attachment_attempt"] != "candidate"),
                     "attachment input lacks foreground ownership")
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


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if any(arg == "--timeout-diagnostic" or arg.startswith("--timeout-diagnostic=") for arg in argv):
        parser = _Parser(description=__doc__)
        parser.add_argument("--timeout-diagnostic", required=True, type=Path)
        path = parser.parse_args(argv).timeout_diagnostic
        _require(path.resolve().is_relative_to((ROOT / "private").resolve()),
                 "timeout diagnostic must be inside the ignored private directory")
        _require(0 < path.stat().st_size <= TIMEOUT_DIAGNOSTIC_MAX_BYTES,
                 "timeout diagnostic size exceeds bounds")
        diagnostic = parse_timeout_diagnostic(path.read_bytes())
        print(json.dumps(diagnostic, sort_keys=True))
        return 0
    parser = _Parser(description=__doc__)
    parser.add_argument("--timeout-diagnostic", metavar="PATH",
                        help="validate an incomplete drain-timeout diagnostic instead of a trace")
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--route", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--archive", action="append", default=[], type=Path)
    parser.add_argument("--character-archive-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame-rate", required=True, type=int, choices=(0, 30, 40, 60))
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
    _require(args.route.resolve().is_relative_to((ROOT / "private").resolve()),
             "route must be inside the ignored private directory")
    archives = select_archives(args.game_root, args.archive, args.character_archive_dir)
    raw, trace = read_trace(args.trace)
    _require(args.trace.resolve() ==
             (args.route.parent / "user" / f"animation-trace-v{trace['version']}.json").resolve(),
             "route and trace must belong to the same private run")
    _require(0 < args.route.stat().st_size <= 16 * 1024, "route size exceeds bounds")
    route_raw = args.route.read_bytes()
    route = validate_route(route_raw, rate=args.frame_rate, seconds=args.seconds,
                           audio=args.audio_backend, scope=trace["filter"]["scope"])
    if "binary_provenance" not in route:
        binaries = {"host_executable": sha256_file(args.executable)}
    else:
        binaries = binary_provenance(args.executable)
        require_binary_provenance(route, binaries)
    game_hash = sha256_file(args.game_root / "default.xex")
    expected = json.loads((ROOT / "docs" / "game-build.json").read_text(encoding="utf-8"))["xexSha256"]
    _require(game_hash == expected, "game executable hash does not match the pinned build")
    hashes = {
        "capture": hashlib.sha256(raw).hexdigest(),
        "route": hashlib.sha256(route_raw).hexdigest(),
        **{name: value for name, value in binaries.items() if name in
           {"host_executable", "host_runtime_library", "host_gpu_plugin"}},
        "game_executable": game_hash,
        "hook_source": sha256_file(ROOT / "src" / "animation_trace_hooks.cpp"),
        "trace_header": sha256_file(ROOT / "src" / "animation_trace.h"),
        "model_source": sha256_file(ROOT / "src" / "animation_trace_model.cpp"),
        "model_header": sha256_file(ROOT / "src" / "animation_trace_model.h"),
        "runner_source": sha256_file(ROOT / "tools" / "animation_trace_run.ps1"),
        "manifest_source": sha256_file(ROOT / "tools" / "animation_trace_manifest.py"),
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
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("Animation trace validation failed: input or tool unavailable")
    except ValueError as error:
        raise SystemExit(f"Animation trace validation failed: {error}")
