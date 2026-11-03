"""Synthetic, in-memory checks for the read-only animation trace helper."""

import struct
import sys
import unittest

from tools import animation_static_trace as trace


def basic_xex(blocks, source, *, encrypted=False):
    data = bytearray(0x200)
    data[:4] = b"XEX2"
    struct.pack_into(">I", data, 8, 0x200)
    struct.pack_into(">II", data, 16, 0x80, 2)
    struct.pack_into(">IIII", data, 24, 0x3FF, 0x40, 0x10201, 0x82000000)
    struct.pack_into(">IHH", data, 0x40, 8 + 8 * len(blocks), int(encrypted), 1)
    for index, (length, zeros) in enumerate(blocks):
        struct.pack_into(">II", data, 0x48 + index * 8, length, zeros)
    data[0x1D0:0x1E0] = b"S" * 16
    data.extend(source)
    return bytes(data)


def synthetic_signal():
    data = bytearray(520)
    struct.pack_into(">II", data, 0, 71, 2)
    data.extend(struct.pack(">I", 2))
    table = len(data)
    data.extend(bytes(16))
    first = len(data)
    data.extend(struct.pack(">III", 3, 1, 2))
    data.extend(struct.pack(">II", 123, 456))
    data.extend(bytes(16))
    second = len(data)
    data.extend(struct.pack(">III", 0xFFFFFFFF, 0, 0))
    data.extend(bytes(16))
    struct.pack_into(">IIII", data, table, 3, first, 42, second)
    data.extend(struct.pack(">I", 0))
    return bytes(data)


def synthetic_info(types):
    data = bytearray(524)
    struct.pack_into(">III", data, 0, 100, 0, len(types))
    for type_id in types:
        data.extend(struct.pack(">7I", type_id, 0, 0, 0, 0, 0, 0))
        data.extend(bytes(58))
    return bytes(data)


class BasicXexTests(unittest.TestCase):
    def test_expands_basic_blocks_in_memory(self):
        base, image = trace.decode_basic_xex(basic_xex([(4, 3), (2, 1)], b"MZabXY"))
        self.assertEqual(base, 0x82000000)
        self.assertEqual(image, b"MZab\0\0\0XY\0")

    def test_rejects_malformed_headers_and_extents(self):
        valid = basic_xex([(4, 0)], b"MZab")
        for invalid in (
            b"XEX2",
            b"NOPE" + valid[4:],
            valid[:0x80],
            valid[:-1],
            basic_xex([(4, 0)], b"NOPE"),
        ):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                trace.decode_basic_xex(invalid)
        invalid = bytearray(valid)
        struct.pack_into(">I", invalid, 0x40, 9)
        with self.assertRaisesRegex(ValueError, "format block"):
            trace.decode_basic_xex(bytes(invalid))
        struct.pack_into(">I", invalid, 0x40, 16)
        struct.pack_into(">H", invalid, 0x46, 2)
        with self.assertRaisesRegex(ValueError, "basic-compressed"):
            trace.decode_basic_xex(bytes(invalid))

    def test_encrypted_path_uses_session_key_without_io(self):
        calls = []

        def decrypt(key, data):
            calls.append((key, data))
            if len(calls) == 1:
                return b"K" * 16
            return b"MZ" + b"x" * 14

        xex = basic_xex([(16, 2)], b"C" * 16, encrypted=True)
        base, image = trace.decode_basic_xex(xex, b"R" * 16, decrypt)
        self.assertEqual(base, 0x82000000)
        self.assertEqual(image, b"MZ" + b"x" * 14 + b"\0\0")
        self.assertEqual(calls, [(b"R" * 16, b"S" * 16), (b"K" * 16, b"C" * 16)])
        with self.assertRaisesRegex(ValueError, "key or security"):
            trace.decode_basic_xex(xex)

    @unittest.skipUnless(sys.platform == "win32", "Windows CNG is unavailable")
    def test_cng_public_aes_vector(self):
        ciphertext = bytes.fromhex("66e94bd4ef8a2c3b884cfa59ca342b2e")
        self.assertEqual(trace._aes_cbc_decrypt(bytes(16), ciphertext), bytes(16))
        with self.assertRaises(ValueError):
            trace._aes_cbc_decrypt(bytes(16), ciphertext[:-1])


class GeneratedSearchTests(unittest.TestCase):
    def test_xrefs_track_register_clobbers_and_preserved_registers(self):
        text = """
DEFINE_REX_FUNC(sub_82000000) {
    // lis r11,-32252
    // addi r10,r11,2088
    // lwz r3,4(r10)
    // lis r31,-32252
    // addi r31,r31,2088
    // bl 0x82000100
    // addi r4,r10,8
    // lwz r4,8(r31)
}
"""
        refs = list(trace.iter_static_references(text))
        self.assertEqual(
            [ref.address for ref in refs],
            [0x82040828, 0x8204082C, 0x82040828, 0x82040830],
        )
        self.assertTrue(all(ref.function == "sub_82000000" for ref in refs))

    def test_calls_and_instruction_labels(self):
        text = """DEFINE_REX_FUNC(sub_82000100) {
    // li r3,1
    // bl 0x82000200
    ctx.lr = 0x82000108;
loc_82000120:
    // b 0x82000200
}
"""
        self.assertEqual(
            list(trace.iter_calls(text, 0x82000200)),
            [("sub_82000100", 3, "bl", 0x82000104),
             ("sub_82000100", 6, "b", None)],
        )
        self.assertEqual(
            [pc for _, pc, _, _ in trace.iter_instructions(text, 0x82000100)],
            [0x82000100, 0x82000104, 0x82000120],
        )

    def test_string_search_is_case_insensitive_and_bounded(self):
        self.assertEqual(
            list(trace.find_strings(b"\0Alpha.BA\0alpha.as\0", 0x82000000, b"ALPHA", 1)),
            [(0x82000001, 0x82000001, "Alpha.BA")],
        )
        with self.assertRaises(ValueError):
            list(trace.find_strings(b"", 0, b"", 1))


class CorrelationTests(unittest.TestCase):
    def test_reports_only_aggregate_signal_structure(self):
        result = trace.summarize_signal_structure(synthetic_signal())
        self.assertEqual(result["clips"], 2)
        self.assertEqual(result["nonempty_clips"], 1)
        self.assertEqual(result["retained_records"], 1)
        self.assertEqual(result["discarded_records"], 1)
        self.assertEqual(result["payload_records"], 1)
        self.assertEqual(result["payload_words"], 2)
        self.assertEqual(result["records_type_1_to_37"], 1)
        self.assertEqual(result["parsed_end"], result["member_size"])

    def test_header_count_matching_does_not_require_names(self):
        ba = struct.pack(">8I", 24, 17, 12, 2, 4, 2, 3, 5)
        info = synthetic_info([9, 23])
        result = trace.correlate_headers(ba, synthetic_signal(), info)
        self.assertTrue(result["counts_match"])
        self.assertEqual((result["ba_bones"], result["ba_mode_word"]), (4, 2))
        self.assertEqual(result["info_types_9_to_11"], 1)
        self.assertEqual(result["info_types_9_to_11_with_as_records"], 1)
        self.assertFalse(trace.correlate_headers(
            ba, synthetic_signal(), synthetic_info([9])
        )["counts_match"])

    def test_sentinel_and_invalid_member_bounds(self):
        sentinel = bytearray(524)
        struct.pack_into(">II", sentinel, 0, 71, 1)
        struct.pack_into(">I", sentinel, 520, 0x10000)
        self.assertEqual(trace.summarize_signal_structure(bytes(sentinel))["retained_records"], 0)
        for change in ("count", "offset", "payload", "footer"):
            invalid = bytearray(synthetic_signal())
            if change == "count":
                struct.pack_into(">I", invalid, 520, 100000)
            elif change == "offset":
                struct.pack_into(">I", invalid, 528, len(invalid) + 1)
            elif change == "payload":
                first_offset = struct.unpack_from(">I", invalid, 528)[0]
                struct.pack_into(">I", invalid, first_offset + 8, 100000)
            else:
                del invalid[-10:]
            with self.subTest(change=change), self.assertRaises(ValueError):
                trace.summarize_signal_structure(bytes(invalid))

    def test_rejects_unsupported_or_truncated_headers(self):
        signal = synthetic_signal()
        with self.assertRaises(ValueError):
            trace.correlate_headers(b"", signal, bytes(12))
        with self.assertRaisesRegex(ValueError, "BA header"):
            trace.correlate_headers(bytes(24), signal, struct.pack(">3I", 100, 0, 2))
        ba = struct.pack(">6I", 24, 17, 12, 2, 4, 2)
        with self.assertRaisesRegex(ValueError, "INFO version"):
            trace.correlate_headers(ba, signal, bytes(12))


if __name__ == "__main__":
    unittest.main()
