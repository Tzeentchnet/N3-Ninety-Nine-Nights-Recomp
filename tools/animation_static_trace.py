#!/usr/bin/env python3
"""Bounded, read-only animation tracing over a local XEX and ReXGlue output.

The image is decoded only in memory.  No game bytes or decoded image are written.
XEX support is deliberately limited to basic compression, as used by the pinned
executable.  Static xrefs are candidates, not a control-flow or alias analysis.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from pathlib import Path
import re
import struct
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "generated" / "default"
SDK_ARCHIVE = ROOT / ".tools" / "source-archives"
MAX_IMAGE = 64 * 1024 * 1024
MASK = 0xFFFFFFFF


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("truncated 32-bit read")
    return struct.unpack_from(">I", data, offset)[0]


def _sdk_retail_key(archive: Path) -> bytes:
    with tarfile.open(archive, "r:gz") as tar:
        names = [name for name in tar.getnames() if name.endswith("/src/system/xex_module.cpp")]
        if len(names) != 1:
            raise ValueError("SDK archive has no unique XEX implementation")
        stream = tar.extractfile(names[0])
        if stream is None:
            raise ValueError("SDK XEX implementation is unavailable")
        text = stream.read().decode("utf-8")
    declaration = text.partition("xe_xex2_retail_key")[2].partition("}")[0]
    key = bytes(int(value, 16) for value in re.findall(r"0x[0-9a-fA-F]+", declaration))
    if len(key) != 16:
        raise ValueError("SDK retail key declaration is unavailable")
    return key


def _aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("XEX decryption requires Windows CNG")
    if len(key) != 16 or len(data) % 16:
        raise ValueError("invalid AES-128-CBC input length")
    dll = ctypes.WinDLL("bcrypt")
    handle = ctypes.c_void_p
    byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
    u32 = ctypes.c_ulong
    functions = {
        "BCryptOpenAlgorithmProvider": ([ctypes.POINTER(handle), ctypes.c_wchar_p, ctypes.c_wchar_p, u32], ctypes.c_long),
        "BCryptSetProperty": ([handle, ctypes.c_wchar_p, byte_pointer, u32, u32], ctypes.c_long),
        "BCryptGetProperty": ([handle, ctypes.c_wchar_p, byte_pointer, u32, ctypes.POINTER(u32), u32], ctypes.c_long),
        "BCryptGenerateSymmetricKey": ([handle, ctypes.POINTER(handle), byte_pointer, u32, byte_pointer, u32, u32], ctypes.c_long),
        "BCryptDecrypt": ([handle, byte_pointer, u32, ctypes.c_void_p, byte_pointer, u32, byte_pointer, u32, ctypes.POINTER(u32), u32], ctypes.c_long),
        "BCryptDestroyKey": ([handle], ctypes.c_long),
        "BCryptCloseAlgorithmProvider": ([handle, u32], ctypes.c_long),
    }
    for name, (arguments, result) in functions.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = arguments, result

    def check(status: int) -> None:
        if status != 0:
            raise OSError(f"Windows CNG failed with status {status & MASK:08X}")

    algorithm, secret = handle(), handle()
    check(dll.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "AES", None, 0))
    try:
        chain = ctypes.create_unicode_buffer("ChainingModeCBC")
        check(dll.BCryptSetProperty(algorithm, "ChainingMode", ctypes.cast(chain, byte_pointer), ctypes.sizeof(chain), 0))
        object_size, received = u32(), u32()
        check(dll.BCryptGetProperty(algorithm, "ObjectLength", ctypes.cast(ctypes.byref(object_size), byte_pointer), ctypes.sizeof(object_size), ctypes.byref(received), 0))
        key_object = (ctypes.c_ubyte * object_size.value)()
        key_data = (ctypes.c_ubyte * len(key)).from_buffer_copy(key)
        check(dll.BCryptGenerateSymmetricKey(algorithm, ctypes.byref(secret), key_object, object_size, key_data, len(key), 0))
        ciphertext = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        plaintext = (ctypes.c_ubyte * len(data))()
        iv = (ctypes.c_ubyte * 16)()
        produced = u32()
        check(dll.BCryptDecrypt(secret, ciphertext, len(data), None, iv, 16, plaintext, len(data), ctypes.byref(produced), 0))
        if produced.value != len(data):
            raise ValueError("incomplete AES result")
        return bytes(plaintext)
    finally:
        if secret:
            dll.BCryptDestroyKey(secret)
        dll.BCryptCloseAlgorithmProvider(algorithm, 0)


def decode_basic_xex(data: bytes, key: bytes | None = None, decrypt=_aes_cbc_decrypt) -> tuple[int, bytes]:
    if len(data) < 24 or data[:4] != b"XEX2":
        raise ValueError("not a supported XEX2 image")
    header_end, security, option_count = _u32(data, 8), _u32(data, 16), _u32(data, 20)
    if option_count > 128 or 24 + 8 * option_count > len(data):
        raise ValueError("invalid XEX option count")
    options = {_u32(data, 24 + 8 * i): _u32(data, 28 + 8 * i) for i in range(option_count)}
    if 0x3FF not in options or 0x10201 not in options:
        raise ValueError("missing XEX format or image base")
    fmt, base = options[0x3FF], options[0x10201]
    size = _u32(data, fmt)
    if size < 8 or (size - 8) % 8 or size > 4096 or fmt + size > len(data):
        raise ValueError("invalid XEX format block")
    encryption, compression = struct.unpack_from(">HH", data, fmt + 4)
    if compression != 1 or encryption not in (0, 1):
        raise ValueError("only basic-compressed XEX images are supported")
    blocks = [(_u32(data, fmt + 8 + i), _u32(data, fmt + 12 + i)) for i in range(0, size - 8, 8)]
    packed = sum(n for n, _ in blocks)
    unpacked = sum(n + zero for n, zero in blocks)
    if not unpacked or unpacked > MAX_IMAGE or header_end + packed > len(data):
        raise ValueError("invalid XEX payload extent")
    source = data[header_end : header_end + packed]
    if encryption:
        if key is None or security + 0x160 > len(data):
            raise ValueError("XEX encryption key or security header is missing")
        session_key = decrypt(key, data[security + 0x150 : security + 0x160])
        source = decrypt(session_key, source)
    image = bytearray(unpacked)
    src = dst = 0
    for n, zero in blocks:
        image[dst : dst + n] = source[src : src + n]
        src += n
        dst += n + zero
    if image[:2] != b"MZ":
        raise ValueError("decoded XEX does not contain a PE image")
    return base, bytes(image)


@dataclass(frozen=True)
class Reference:
    function: str
    line: int
    address: int
    instruction: str


def iter_static_references(text: str):
    """Find straight-line lis/address references; branches can make these candidates false."""
    registers: dict[str, int] = {}
    function = ""
    for line, raw in enumerate(text.splitlines(), 1):
        match = re.match(r"DEFINE_REX_FUNC\((sub_[0-9A-Fa-f]+)\)", raw)
        if match:
            function, registers = match.group(1).upper().replace("SUB_", "sub_"), {}
            continue
        match = re.match(r"\s*// ([a-z0-9_.]+)\s*(.*)", raw)
        if not match or not function:
            continue
        op, args = match.groups()
        parts = [part.strip() for part in args.split(",")]
        address = None
        try:
            if op == "lis" and len(parts) == 2:
                registers[parts[0]] = (int(parts[1], 0) << 16) & MASK
            elif op == "li" and len(parts) == 2:
                registers[parts[0]] = int(parts[1], 0) & MASK
            elif op in ("addi", "addis", "ori", "oris") and len(parts) == 3:
                old = registers.get(parts[1])
                if old is None:
                    registers.pop(parts[0], None)
                else:
                    operand = int(parts[2], 0)
                    if op in ("addis", "oris"):
                        operand <<= 16
                    value = (old | operand) if op.startswith("or") else (old + operand)
                    address = registers[parts[0]] = value & MASK
            elif op == "mr" and len(parts) == 2:
                if parts[1] in registers:
                    registers[parts[0]] = registers[parts[1]]
                else:
                    registers.pop(parts[0], None)
            elif op.startswith(("lw", "lh", "lb", "lf", "st")) and len(parts) == 2:
                mem = re.fullmatch(r"(-?(?:0x[0-9a-fA-F]+|\d+))\((r\d+)\)", parts[1])
                if mem and mem.group(2) in registers:
                    address = (registers[mem.group(2)] + int(mem.group(1), 0)) & MASK
                if op.startswith(("lw", "lh", "lb")):
                    registers.pop(parts[0], None)
            elif op in ("bl", "bctrl"):
                for reg in ("r0", *(f"r{i}" for i in range(3, 13))):
                    registers.pop(reg, None)
            elif parts and re.fullmatch(r"r\d+", parts[0]) and not op.startswith(("cmp", "st", "b", "mt")):
                registers.pop(parts[0], None)
        except ValueError:
            if parts:
                registers.pop(parts[0], None)
        if address is not None and 0x82000000 <= address < 0x84000000:
            yield Reference(function, line, address, f"{op} {args}")


def iter_calls(text: str, target: int):
    function = ""
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        match = re.match(r"DEFINE_REX_FUNC\((sub_[0-9A-Fa-f]+)\)", raw)
        if match:
            function = match.group(1).upper().replace("SUB_", "sub_")
        match = re.match(r"\s*// (bl|b) 0x([0-9a-fA-F]+)\s*$", raw)
        if match and function and int(match.group(2), 16) == target:
            ret = re.search(r"ctx\.lr = 0x([0-9A-Fa-f]+)", "\n".join(lines[index + 1:index + 4]))
            site = int(ret.group(1), 16) - 4 if ret and match.group(1) == "bl" else None
            yield function, index + 1, match.group(1), site


def iter_instructions(text: str, target: int):
    """Report source lines and guest PCs, resynchronizing at generated labels."""
    active = False
    pc = target
    for line, raw in enumerate(text.splitlines(), 1):
        match = re.match(r"DEFINE_REX_FUNC\(sub_([0-9A-Fa-f]+)\)", raw)
        if match:
            active = int(match.group(1), 16) == target
            continue
        if not active:
            continue
        if raw == "}":
            return
        label = re.match(r"loc_([0-9A-Fa-f]+):", raw)
        if label:
            pc = int(label.group(1), 16)
        instruction = re.match(r"\s*// ([a-z0-9_.]+)(?:\s+(.*))?$", raw)
        if instruction:
            yield line, pc, instruction.group(1), instruction.group(2) or ""
            pc += 4


def find_strings(image: bytes, base: int, needle: bytes, limit: int):
    if not needle or len(needle) > 128:
        raise ValueError("string query must contain 1-128 ASCII bytes")
    lower, query = image.lower(), needle.lower()
    pos = count = 0
    while count < limit:
        pos = lower.find(query, pos)
        if pos < 0:
            break
        begin, end = pos, pos + len(needle)
        while begin > 0 and pos - begin < 120 and 32 <= image[begin - 1] <= 126:
            begin -= 1
        while end < len(image) and end - pos < 160 and 32 <= image[end] <= 126:
            end += 1
        yield base + pos, base + begin, image[begin:end].decode("ascii")
        count += 1
        pos += len(needle)


def _signal_structure(data: bytes) -> tuple[dict[str, int], list[bool]]:
    clip_count = _u32(data, 4)
    if clip_count > (len(data) - 520) // 4:
        raise ValueError("AS clip count exceeds member bounds")
    pos = 520
    nonempty = retained = discarded = payload_records = payload_words = 0
    dispatch_range = 0
    has_records = []
    for _ in range(clip_count):
        count = _u32(data, pos)
        pos += 4
        if count in (0, 0x10000):
            has_records.append(False)
            continue
        if count > (len(data) - pos) // 8:
            raise ValueError("AS record table exceeds member bounds")
        nonempty += 1
        retained_before = retained
        table = pos
        for index in range(count):
            event_type = _u32(data, table + index * 8)
            offset = _u32(data, table + index * 8 + 4)
            frame = _u32(data, offset)
            channel = _u32(data, offset + 4)
            words = _u32(data, offset + 8)
            if words > (len(data) - offset - 12) // 4:
                raise ValueError("AS record payload exceeds member bounds")
            end = offset + 12 + words * 4 + 16
            if end > len(data) or end < table + count * 8:
                raise ValueError("AS record footer exceeds member bounds")
            if frame < 0x80000000 and channel < 16:
                retained += 1
                payload_records += words != 0
                payload_words += words
                dispatch_range += 1 <= event_type <= 37
            else:
                discarded += 1
        pos = end
        has_records.append(retained > retained_before)
    return {
        "first_word": _u32(data, 0),
        "clips": clip_count,
        "nonempty_clips": nonempty,
        "retained_records": retained,
        "discarded_records": discarded,
        "payload_records": payload_records,
        "payload_words": payload_words,
        "records_type_1_to_37": dispatch_range,
        "parsed_end": pos,
        "member_size": len(data),
    }, has_records


def summarize_signal_structure(data: bytes) -> dict[str, int]:
    """Count bounded AS records without returning private payload values."""
    return _signal_structure(data)[0]


def correlate_headers(ba: bytes, signal: bytes, info: bytes) -> dict[str, int | bool]:
    """Report only structural metadata; matching counts do not prove identity."""
    if len(ba) < 24 or len(info) < 12:
        raise ValueError("truncated BA or INFO header")
    if _u32(ba, 8) != 12:
        raise ValueError("unsupported BA header")
    if _u32(info, 0) != 100:
        raise ValueError("unsupported INFO version")
    ba_clips = _u32(ba, 12)
    info_rows = _u32(info, 8)
    if ba_clips > (len(ba) - 24) // 4:
        raise ValueError("BA frame counts exceed member bounds")
    if info_rows > (len(info) - 524) // 86:
        raise ValueError("INFO rows exceed member bounds")
    result: dict[str, int | bool] = {
        "ba_clips": ba_clips,
        "ba_bones": _u32(ba, 16),
        "ba_mode_word": _u32(ba, 20),
        "info_version": _u32(info, 0),
        "info_rows": info_rows,
    }
    signal_summary, has_records = _signal_structure(signal)
    result.update(signal_summary)
    result["counts_match"] = ba_clips == result["clips"] == info_rows
    if result["counts_match"]:
        types_9_to_11 = 0
        types_9_to_11_with_records = 0
        for index in range(info_rows):
            if _u32(info, 524 + index * 86) in (9, 10, 11):
                types_9_to_11 += 1
                types_9_to_11_with_records += has_records[index]
        result["info_types_9_to_11"] = types_9_to_11
        result["info_types_9_to_11_with_as_records"] = types_9_to_11_with_records
    return result


def correlate_members(args) -> None:
    try:
        from .n3_gameplay_data import GameplayDataError, read_pak
    except ImportError:
        from n3_gameplay_data import GameplayDataError, read_pak

    try:
        char_archive, data_archive = read_pak(args.char_pak), read_pak(args.data_pak)
    except GameplayDataError as error:
        raise ValueError(str(error)) from error

    def member(archive, name: str) -> bytes:
        matches = archive.find(name)
        if len(matches) != 1:
            raise ValueError(f"{name!r} is not a unique archive member")
        return archive.read_member(matches[0])

    result = correlate_headers(
        member(char_archive, args.ba_member),
        member(data_archive, args.signal_member),
        member(data_archive, args.info_member),
    )
    for key, value in result.items():
        print(f"{key}={value}")
    print("Matching names and counts do not prove the runtime resource binding.")


def _image(args):
    archive = args.sdk_archive
    if archive is None:
        matches = sorted(SDK_ARCHIVE.glob("rexglue-rexglue-sdk-*.tar.gz"))
        if len(matches) != 1:
            raise ValueError("provide --sdk-archive for the matching SDK source archive")
        archive = matches[0]
    return decode_basic_xex(args.xex.read_bytes(), _sdk_retail_key(archive))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=GENERATED)
    parser.add_argument("--xex", type=Path, default=ROOT / "private" / "game" / "default.xex")
    parser.add_argument("--sdk-archive", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    strings = sub.add_parser("strings", help="find bounded printable XEX anchors")
    strings.add_argument("terms", nargs="+")
    strings.add_argument("--limit", type=int, default=12)
    words = sub.add_parser("words", help="read bounded big-endian image words")
    words.add_argument("address", type=lambda value: int(value, 0))
    words.add_argument("count", type=int)
    cstring = sub.add_parser("cstr", help="read one bounded printable image string")
    cstring.add_argument("address", type=lambda value: int(value, 0))
    wordrefs = sub.add_parser("wordrefs", help="find exact big-endian image words")
    wordrefs.add_argument("address", type=lambda value: int(value, 0))
    wordrefs.add_argument("--limit", type=int, default=50)
    refs = sub.add_parser("xrefs", help="find candidate generated static address references")
    refs.add_argument("address", type=lambda value: int(value, 0))
    refs.add_argument("--radius", type=lambda value: int(value, 0), default=0)
    callers = sub.add_parser("callers", help="find direct generated call/tail-branch sites")
    callers.add_argument("address", type=lambda value: int(value, 0))
    function = sub.add_parser("function", help="print one generated function's PPC instructions")
    function.add_argument("address", type=lambda value: int(value, 0))
    function.add_argument("--start", type=lambda value: int(value, 0), default=0)
    function.add_argument("--end", type=lambda value: int(value, 0), default=MASK)
    correlate = sub.add_parser("correlate", help="compare aggregate BA/AS/INFO metadata")
    correlate.add_argument("--char-pak", type=Path, required=True)
    correlate.add_argument("--data-pak", type=Path, required=True)
    correlate.add_argument("--ba-member", required=True)
    correlate.add_argument("--signal-member", required=True)
    correlate.add_argument("--info-member", required=True)
    args = parser.parse_args(argv)
    if args.command == "correlate":
        correlate_members(args)
    elif args.command in ("strings", "words", "wordrefs", "cstr"):
        base, image = _image(args)
        if args.command == "strings":
            if not 1 <= args.limit <= 100:
                raise ValueError("limit must be 1-100")
            for term in args.terms:
                for hit, start, text in find_strings(image, base, term.encode("ascii"), args.limit):
                    print(f"{term!r} hit=0x{hit:08X} start=0x{start:08X} {text}")
        elif args.command == "words":
            if not 1 <= args.count <= 64 or args.address < base or args.address + 4 * args.count > base + len(image):
                raise ValueError("word range is outside the mapped image or count exceeds 64")
            for i in range(args.count):
                address = args.address + 4 * i
                print(f"0x{address:08X}: 0x{_u32(image, address - base):08X}")
        elif args.command == "cstr":
            offset = args.address - base
            if not 0 <= offset < len(image):
                raise ValueError("string address is outside the mapped image")
            end = image.find(b"\0", offset, min(offset + 256, len(image)))
            if end < 0:
                raise ValueError("unterminated or oversized string")
            value = image[offset:end]
            if not value or any(char < 32 or char > 126 for char in value):
                raise ValueError("address does not contain a printable ASCII string")
            print(f"0x{args.address:08X}: {value.decode('ascii')}")
        else:
            if not 1 <= args.limit <= 1000:
                raise ValueError("limit must be 1-1000")
            encoded = struct.pack(">I", args.address)
            pos = count = 0
            while count < args.limit:
                pos = image.find(encoded, pos)
                if pos < 0:
                    break
                print(f"0x{base + pos:08X}")
                count += 1
                pos += 4
    else:
        if args.command == "xrefs" and not 0 <= args.radius <= 4096:
            raise ValueError("xref radius must be 0-4096")
        for path in sorted(args.generated.glob("n3_recomp.*.cpp")):
            text = path.read_text(encoding="utf-8")
            if args.command == "xrefs":
                for ref in iter_static_references(text):
                    if abs(ref.address - args.address) <= args.radius:
                        print(f"{path.name}:{ref.line} {ref.function} 0x{ref.address:08X} {ref.instruction}")
            elif args.command == "callers":
                for function, line, op, site in iter_calls(text, args.address):
                    location = f"0x{site:08X}" if site is not None else "unknown"
                    print(f"{path.name}:{line} {function} {op} site={location}")
            else:
                for line, pc, op, operands in iter_instructions(text, args.address):
                    if args.start <= pc <= args.end:
                        print(f"{path.name}:{line} 0x{pc:08X} {op} {operands}".rstrip())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, UnicodeError) as error:
        print(f"animation static trace: {error}", file=sys.stderr)
        raise SystemExit(2)
